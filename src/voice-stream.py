#!/usr/bin/env python3
# 语音输入 - dwa=wpgs + 终态打字（clipboard-paste方案）
#
# Wayland下打字方案优先级（按可靠性）：
#   1. --mode ibus    通过ibus-voice-engine.py的commit_text（待引擎稳定后启用）
#   2. --mode paste   clipboard粘贴（wl-copy + Ctrl+V），当前最可靠
#   3. --mode ydotool ydotool type（常因FGK_BYPASS失效）
#   4. --mode none    仅打印+写文件
#
# 流式策略：
#   - 实时模式 (--mode ibus)：每收到一段新结果就 commit 新字符
#   - 终态模式 (--mode paste/ydotool/none)：只在结束时打字一次
import json, base64, hmac, hashlib, time, subprocess, os, sys
from urllib.parse import quote
import threading, queue, argparse
import sounddevice as sd

CONFIG = os.path.expanduser('~/.config/ibus-voice/config.json')
LOG = open('/tmp/iat-stream.log', 'a')
def log(msg):
    LOG.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
    LOG.flush()


def xf_thread(cfg, audio_q, result_q, duration):
    import websocket, ssl
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
    url = (
        f"wss://{HOST}{PATH}"
        f"?host={HOST}&date={quote(DATE)}&authorization={quote(auth)}"
    )

    results = []

    def on_message(ws_conn, message):
        msg = json.loads(message)
        code = msg.get('code', 0)
        if code != 0:
            log(f"ERR {msg.get('message')}")
            return

        d = msg.get('data', {}); r = d.get('result', {})
        pgs, rg = r.get('pgs', ''), r.get('rg', [])
        text = ''.join(c.get('w', '')
                       for w in r.get('ws', [])
                       for c in w.get('cw', []))

        log(f"RECV pgs={pgs} rg={rg} text=[{text[:60]}] len={len(results)}")

        if pgs == 'rpl' and len(rg) == 2:
            start = rg[0] - 1
            end = rg[1]
            while len(results) < end:
                results.append('')
            results[start:end] = [text] if text else ['']
            del results[end:]
            log(f"  rpl[{start}:{end}] -> {len(results)} elems")
        elif pgs == 'apd' and text:
            results.append(text)
            log(f"  apd +[{text[:30]}] -> {len(results)}")

        full = ''.join(results)
        result_q.put(('text', full))
        log(f"  full [{len(full)}] {full[:120]}")

        if d.get('status') == 2:
            log(f"=== DONE: {full} ===")
            result_q.put(('done', None))

    def on_error(ws_conn, error):
        result_q.put(('error', str(error)))

    def on_close(ws_conn, a, b):
        pass

    def on_open(ws_conn):
        def send_audio():
            first = True
            deadline = time.time() + duration
            log(f"=== START {duration}s ===")
            while time.time() < deadline:
                try:
                    chunk = audio_q.get(timeout=0.5)
                except queue.Empty:
                    continue
                status = 0 if first else 1
                payload = {
                    "data": {
                        "status": status,
                        "format": "audio/L16;rate=16000",
                        "audio": str(base64.b64encode(chunk), 'utf-8'),
                        "encoding": "raw",
                    }
                }
                if first:
                    payload["common"] = {"app_id": cfg['appid']}
                    payload["business"] = {
                        "language": "zh_cn",
                        "domain": "iat",
                        "accent": "mandarin",
                        "dwa": "wpgs",
                        "vad_eos": 10000,
                    }
                    first = False
                try:
                    ws_conn.send(json.dumps(payload))
                except Exception:
                    break
            try:
                ws_conn.send(json.dumps({"data": {"status": 2}}))
            except Exception:
                pass
            time.sleep(1)
            ws_conn.close()
        thread.start_new_thread(send_audio, ())

    ws_app = websocket.WebSocketApp(
        url,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws_app.on_open = on_open
    ws_app.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})


# ---------- 打字后端 ----------

class Typer:
    """终态打字：根据模式选择后端。一次性输出完整文本。"""

    def __init__(self, mode):
        self.mode = mode

    def type_final(self, text):
        if not text:
            return False
        if self.mode == 'paste':
            return self._type_paste(text)
        elif self.mode == 'ydotool':
            return self._type_ydotool(text)
        # 'none' / 'ibus' (ibus引擎自己处理) -> 不在此输出
        return False

    def _type_paste(self, text):
        """clipboard + Ctrl+V - Wayland下最可靠"""
        try:
            p = subprocess.Popen(
                ['wl-copy'],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            p.stdin.write(text.encode('utf-8'))
            p.stdin.close()
            p.wait(timeout=2)
        except FileNotFoundError:
            log('wl-copy not found - is wl-clipboard installed?')
            return False
        except Exception as e:
            log(f'wl-copy fail: {e}')
            return False
        # Ctrl down, V down/up, Ctrl up
        try:
            subprocess.run(
                ['ydotool', 'key', '29:1', '47:1', '47:0', '29:0'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            return True
        except Exception as e:
            log(f'ydotool paste key fail: {e}')
            return False

    def _type_ydotool(self, text):
        try:
            subprocess.run(
                ['ydotool', 'type', '--', text],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=10,
            )
            return True
        except Exception as e:
            log(f'ydotool type fail: {e}')
            return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--max', type=int, default=30, help='录音秒数')
    p.add_argument('--mode', choices=['paste', 'ydotool', 'ibus', 'none'],
                   default='paste', help='打字后端（默认 paste=clipboard）')
    args = p.parse_args()

    with open(CONFIG) as f:
        cfg = json.load(f)

    print(f"mic {args.max}s | mode={args.mode}", file=sys.stderr, flush=True)
    for i in [3, 2, 1]:
        sys.stderr.write(f'\r  {i}...')
        sys.stderr.flush()
        time.sleep(1)
    sys.stderr.write('\r  RED\n')
    sys.stderr.flush()

    audio_q = queue.Queue()
    result_q = queue.Queue()

    t = threading.Thread(
        target=xf_thread,
        args=(cfg, audio_q, result_q, args.max),
        daemon=True,
    )
    t.start()

    def callback(indata, frames, ti, st):
        audio_q.put(indata.flatten().tobytes())

    stream = sd.InputStream(
        samplerate=16000, channels=1, dtype='int16',
        callback=callback, blocksize=1280,
    )
    stream.start()

    typer = Typer(args.mode)
    last = ''
    try:
        while t.is_alive() or not result_q.empty():
            try:
                typ, val = result_q.get(timeout=0.3)
                if typ == 'text' and val != last:
                    last = val
                    print(f"  >> {val}", flush=True)
                elif typ == 'done':
                    break
            except queue.Empty:
                pass
    except KeyboardInterrupt:
        pass

    stream.stop()
    stream.close()

    with open('/tmp/voice-output.txt', 'w') as f:
        f.write(last)

    if last.strip():
        if args.mode == 'ibus':
            print(f"  ibus引擎应已逐字 commit - 共 {len(last)}字", file=sys.stderr)
        elif args.mode == 'paste':
            ok = typer.type_final(last)
            print(f"  clipboard-paste: {'OK' if ok else 'FAIL'} ({len(last)}字)", file=sys.stderr)
        elif args.mode == 'ydotool':
            ok = typer.type_final(last)
            print(f"  ydotool type: {'OK' if ok else 'FAIL'} ({len(last)}字)", file=sys.stderr)
        else:
            print(f"  {len(last)}字 已写入 /tmp/voice-output.txt", file=sys.stderr)
    else:
        print("  no text recognized", file=sys.stderr)


if __name__ == '__main__':
    main()
