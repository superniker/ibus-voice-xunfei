#!/usr/bin/env python3
# 讯飞语音守护进程 - 单连接版（已验证）
# 不分段, 单连接识别到自然结束
import json, base64, hmac, hashlib, time, os, sys, socket, threading, queue
import sounddevice as sd

CONFIG = os.path.expanduser('~/.config/ibus-voice/config.json')
SOCK = '/tmp/ibus-voice.sock'
STATE_FILE = '/tmp/voice-state.json'
DURATION = 120  # 2 分钟


def log(msg):
    with open('/tmp/voice-daemon.log', 'a') as f:
        f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')


def read_state():
    try:
        return json.load(open(STATE_FILE))
    except Exception:
        return {'recording': False, 'started': 0}


def write_state(state):
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f)


def notify_engine_partial(text):
    import socket as sk, json as js
    try:
        s = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
        s.settimeout(0.1)
        s.connect('/tmp/voice-partial.sock')
        s.sendall(js.dumps({'text': text, 'type': 'partial'}).encode() + b'\n')
        s.close()
    except Exception as e:
        # 只在第一次失败时 log，避免刷屏
        if not hasattr(notify_engine_partial, '_logged_fail'):
            log(f'partial send fail: {e}')
            notify_engine_partial._logged_fail = True


def notify_engine_commit(text):
    import socket as sk, json as js
    try:
        s = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
        s.settimeout(0.5)
        s.connect('/tmp/voice-commit.sock')
        payload = js.dumps({'text': text, 'type': 'commit'}).encode() + b'\n'
        s.sendall(payload)
        log(f'commit sent ({len(text)} chars, {len(payload)} bytes)')
        s.close()
    except Exception as e:
        log(f'notify commit fail: {e}')


def notify_status_bar(status):
    import socket as sk, json as js
    try:
        s = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect('/tmp/voice-status.sock')
        s.sendall(js.dumps({'status': status}).encode() + b'\n')
        s.close()
    except Exception:
        pass


def notify_engine_status(status):
    """通知 engine 状态变化 (recording/processing/idle)"""
    import socket as sk, json as js
    try:
        s = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
        s.settimeout(0.3)
        s.connect('/tmp/voice-commit.sock')  # 用 commit socket
        s.sendall(js.dumps({'status': status}).encode() + b'\n')
        s.close()
    except Exception:
        pass


def run_session(cfg, stop_event, results_holder):
    """单连接录音识别 - 完整保存到 stop"""
    import websocket, ssl
    from urllib.parse import quote
    from wsgiref.handlers import format_date_time
    from datetime import datetime
    from time import mktime
    import _thread as thread

    HOST = 'iat-api.xfyun.cn'; PATH = '/v2/iat'
    DATE = format_date_time(mktime(datetime.now().timetuple()))
    sig_src = f"host: {HOST}\ndate: {DATE}\nGET {PATH} HTTP/1.1"
    sig = base64.b64encode(hmac.new(cfg['api_secret'].encode(),
        sig_src.encode(), hashlib.sha256).digest()).decode()
    auth_src = (
        f'api_key="{cfg["api_key"]}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{sig}"'
    )
    auth = base64.b64encode(auth_src.encode()).decode()
    url = f"wss://{HOST}{PATH}?host={HOST}&date={quote(DATE)}&authorization={quote(auth)}"

    audio_q = queue.Queue()
    results = results_holder['results']
    results_dict = {}  # 用字典存储结果，key=序号(1-indexed)
    # 同步写入 results_holder，stop_session 可随时读到最新状态
    results_holder['results_dict'] = results_dict

    def on_message(ws, message):
        try:
            msg = json.loads(message)
        except Exception:
            return
        if msg.get('code') != 0:
            log(f'WS error: {msg.get("message")}')
            return
        d = msg.get('data', {}); r = d.get('result', {})
        pgs = r.get('pgs', ''); rg = r.get('rg', [])
        text = ''.join(c.get('w', '') for w in r.get('ws', []) for c in w.get('cw', []))
        # 调试: log 讯飞返回
        log(f'iat: pgs={pgs} rg={rg} text={text!r} dict_len={len(results_dict)}')
        # 讯飞协议: rg 是结果序号(1-indexed)，不是数组索引
        # 用字典存储结果，key=序号
        if pgs == 'rpl' and len(rg) == 2:
            start_num, end_num = rg[0], rg[1]
            max_key = max(results_dict.keys()) if results_dict else 0
            if start_num > max_key:
                # rg 超出范围，替换最后一个（刚追加的）
                if max_key > 0:
                    results_dict[max_key] = text
            else:
                # 替换序号 start_num 到 min(end_num, max_key) 的结果
                for num in range(start_num, min(end_num, max_key) + 1):
                    results_dict[num] = text if num == start_num else ''
        elif pgs == 'apd' and text:
            # 追加新结果，序号 = 当前最大序号 + 1
            max_num = max(results_dict.keys()) if results_dict else 0
            results_dict[max_num + 1] = text
        # 拼接所有结果(按序号排序，跳过空串)
        sorted_results = [results_dict[k] for k in sorted(results_dict.keys()) if results_dict[k]]
        partial = ''.join(sorted_results)
        if partial:
            notify_engine_partial(partial)
        # 检测是否为最终结果
        if d.get('status') == 2:
            log(f'final result received, {len(partial)} chars')

    def on_open(ws):
        def send_audio():
            first = True
            deadline = time.time() + DURATION
            while not stop_event.is_set() and time.time() < deadline:
                try:
                    chunk = audio_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                payload = {'data': {
                    'status': 0 if first else 1,
                    'format': 'audio/L16;rate=16000',
                    'audio': str(base64.b64encode(chunk), 'utf-8'),
                    'encoding': 'raw',
                }}
                if first:
                    payload['common'] = {'app_id': cfg['appid']}
                    payload['business'] = {
                        'language': 'zh_cn', 'domain': 'iat',
                        'accent': 'mandarin', 'dwa': 'wpgs',
                        'vad_eos': 10000,
                    }
                    first = False
                try:
                    ws.send(json.dumps(payload))
                except Exception:
                    break
            try:
                ws.send(json.dumps({'data': {'status': 2}}))
                log('sent status:2 to iat')
            except Exception:
                pass
            # 等待最终结果到达（最多 3 秒）
            for _ in range(6):
                time.sleep(0.5)
                if stop_event.is_set():
                    break
            try:
                ws.close()
            except Exception:
                pass
        thread.start_new_thread(send_audio, ())

    ws_app = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=lambda *a: None,
        on_close=lambda *a: None,
    )
    ws_app.on_open = on_open
    try:
        stream = sd.InputStream(
            samplerate=16000, channels=1, dtype='int16',
            callback=lambda i, f, t, s: audio_q.put(i.flatten().tobytes()),
            blocksize=1280,
        )
        stream.start()
        log('mic started')
        ws_app.run_forever(sslopt={'cert_reqs': ssl.CERT_NONE})
    except Exception as e:
        log(f'session error: {e}')
    finally:
        try:
            stream.stop(); stream.close()
        except Exception:
            pass
    # 额外等一下确保 on_message 最后一次调用完成
    time.sleep(0.5)
    final = ''.join(results)
    # 用字典版本（更准确）
    if results_dict:
        final = ''.join(results_dict[k] for k in sorted(results_dict.keys()))
    results_holder['results_dict'] = results_dict
    log(f'session ended: {len(final)} chars')
    # 通知 engine commit（在线程结束前，确保结果完整）
    if final.strip():
        notify_engine_commit(final)
    # 通知状态
    notify_status_bar('idle')
    notify_engine_status('idle')
    # 标记完成
    results_holder['done'] = True


session_lock = threading.Lock()
session_state = {
    'stop_event': None,
    'thread': None,
    'results': None,
}


def start_session(cfg):
    with session_lock:
        if session_state['thread'] and session_state['thread'].is_alive():
            return False
        stop_event = threading.Event()
        results_holder = {'results': []}
        t = threading.Thread(
            target=run_session,
            args=(cfg, stop_event, results_holder),
            daemon=True,
        )
        t.start()
        session_state['stop_event'] = stop_event
        session_state['thread'] = t
        session_state['results'] = results_holder
    write_state({'recording': True, 'started': time.time()})
    notify_status_bar('recording')
    notify_engine_status('recording')
    return True


def stop_session():
    with session_lock:
        stop_event = session_state['stop_event']
        t = session_state['thread']
        results_holder = session_state['results']
        if not stop_event or not t:
            return None
        session_state['stop_event'] = None
        session_state['thread'] = None
        session_state['results'] = None
    state = read_state()
    elapsed = time.time() - state.get('started', 0)
    if elapsed < 1.5:
        log(f'stop too early ({elapsed:.1f}s), waiting')
        time.sleep(1.5 - elapsed)
    stop_event.set()
    # 等待 run_session 完成（包括 commit 通知）
    t.join(timeout=15)
    # 读取最终结果
    rd = results_holder.get('results_dict', {})
    final = ''.join(rd[k] for k in sorted(rd.keys())) if rd else ''
    write_state({'recording': False, 'started': 0, 'last_text': final})
    log(f'stopped, text: {final[:80]}')
    return final


def handle_toggle(client_sock, cfg):
    state = read_state()
    if not state.get('recording'):
        if start_session(cfg):
            try:
                client_sock.sendall(json.dumps({'event': 'started'}).encode() + b'\n')
            except Exception:
                pass
        else:
            try:
                client_sock.sendall(json.dumps({'event': 'error', 'reason': 'already_running'}).encode() + b'\n')
            except Exception:
                pass
    else:
        final = stop_session()
        try:
            client_sock.sendall(json.dumps({
                'event': 'stopped',
                'text': final or ''
            }).encode() + b'\n')
        except Exception:
            pass
    try:
        client_sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    client_sock.close()


def main():
    cfg = json.load(open(CONFIG))
    try: os.unlink(SOCK)
    except FileNotFoundError: pass
    write_state({'recording': False, 'started': 0})
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(SOCK)
    server.listen(8)
    log(f'daemon listening on {SOCK}')
    while True:
        client, _ = server.accept()
        try:
            client.settimeout(3)
            data = client.recv(4096).decode().strip()
            if not data:
                client.close()
                continue
            try:
                msg = json.loads(data.split('\n')[0])
            except Exception:
                client.close()
                continue
            cmd = msg.get('cmd', '')
            log(f'cmd: {cmd}')
            if cmd == 'toggle':
                handle_toggle(client, cfg)
            elif cmd == 'status':
                state = read_state()
                try:
                    client.sendall(json.dumps(state).encode() + b'\n')
                except Exception:
                    pass
                client.close()
            else:
                try:
                    client.sendall(json.dumps({'status': 'ok'}).encode() + b'\n')
                except Exception:
                    pass
                client.close()
        except Exception as e:
            log(f'client err: {e}')
            try: client.close()
            except Exception: pass


if __name__ == '__main__':
    main()
