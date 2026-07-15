#!/usr/bin/env python3
"""通过 daemon socket 触发语音输入 - toggle 模式
   第一次按: 开始录音
   第二次按: 停止 + paste
"""
import subprocess
import os
import sys
import time
import glob
import json
import socket

SOCK = '/tmp/ibus-voice.sock'

# 找最新ibus socket
sockets = sorted(glob.glob('/home/niker/.cache/ibus/dbus-*'),
                 key=os.path.getmtime, reverse=True)
IBUS_SOCK = sockets[0] if sockets else None


_last_popup_pid = [None]


def notify(title, body, mode='auto'):
    """弹窗
       mode: 'recording' | 'result' | 'status' | 'permanent'
       - recording: 不自动消失（保持显示直到录音结束）
       - result: 4秒后自动消失
       - status: 2.5秒后自动消失
       - permanent: 不自动消失

       注意: 弹窗抢焦点 - 录音中弹窗导致焦点丢失, paste/type 到错地方
       解决: 用 'nonblocking' 模式只用 notify-send (不抢焦点)
    """
    import subprocess
    if mode == 'recording':
        bg = '#3a1e2a'  # 红
        timeout = 0  # 不自动消失
    elif mode == 'result':
        bg = '#1e2e1e'  # 绿
        timeout = 4000
    elif mode == 'permanent':
        bg = '#1e1e28'
        timeout = 0
    else:  # status
        bg = '#1e1e28'
        timeout = 2500

    # 关掉之前的弹窗（杀进程组确保子进程一起死）
    if _last_popup_pid[0]:
        try:
            # 用负数 PID = 进程组
            subprocess.Popen(['kill', '-9', f'-{_last_popup_pid[0]}'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass
    # 短暂等旧进程退出
    import time as _t
    _t.sleep(0.1)

    # 录音中只用 notify-send (不抢焦点), 保证 ydotool type 能输入到原窗口
    if mode == 'recording':
        # notify-send 不抢焦点
        subprocess.Popen(
            ['notify-send', '-t', '3000', '-h', 'string:x-canonical-private-synchronous:voice',
             title, body],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return

    p = subprocess.Popen(
        ['python3', '-B',
         os.path.expanduser('~/.hermes/scripts/voice-popup.py'),
         title, body, str(timeout), bg],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,  # 新进程组，kill 时连带子进程
    )
    _last_popup_pid[0] = p.pid


def trigger_toggle():
    """toggle: 第一次=开始录音, 第二次=停止+paste"""
    # 检查 daemon
    r = subprocess.run(['pgrep', '-f', 'voice-daemon.py'], capture_output=True)
    if r.returncode != 0:
        subprocess.Popen(
            ['python3', '-B', '-u', os.path.expanduser('~/.hermes/scripts/voice-daemon.py')],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(1.5)

    # 检查 daemon 是否在 toggle session
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(10)  # daemon join 录音需要等 mic 流释放
        s.connect(SOCK)
        # 发 toggle 命令
        s.sendall(json.dumps({'cmd': 'toggle'}).encode() + b'\n')
        # 收到 started/stopped 表示开始
        data = s.recv(4096).decode()
        s.close()
        msg = json.loads(data.split('\n')[0])
        if msg.get('event') == 'started':
            notify('讯飞语音', '🔴 开始录音（再次按 F8 停止）', mode='recording')
            print('started')
            return 'started'
        elif msg.get('event') == 'stopped':
            # 不弹窗，不显示字数（用户要求）
            text = msg.get('text', '')
            if text:
                print(f'stopped, text: {text}')
            else:
                print('stopped, no text')
            return f'stopped: {text}'
    except Exception as e:
        print(f"err: {e}", file=sys.stderr)
        return None


def main():
    # 检查当前输入法是否是讯飞语音
    try:
        r = subprocess.run(['ibus', 'engine'], capture_output=True, text=True, timeout=2)
        current_engine = r.stdout.strip() if r.returncode == 0 else ''
    except Exception:
        current_engine = ''

    if 'voice' not in current_engine.lower():
        # 当前不是讯飞语音，自动切换
        try:
            subprocess.run(['ibus', 'engine', 'voice-input'],
                          capture_output=True, timeout=2)
            import time as _t
            _t.sleep(0.3)  # 等 IBus 切换
        except Exception:
            pass

    ensure_status_bar()
    # 录音前保存当前窗口
    win_id = save_active_window()
    trigger_toggle()
    # 录音后激活窗口
    if win_id:
        restore_window(win_id)


def save_active_window():
    """保存当前活动窗口 id（录音后用）"""
    try:
        r = subprocess.run(['xdotool', 'getactivewindow'],
                           capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and r.stdout.strip():
            wid = r.stdout.strip()
            print(f'saved window: {wid}', file=sys.stderr)
            return wid
    except Exception:
        pass
    return None


def restore_window(wid):
    """录音结束后激活之前保存的窗口"""
    try:
        subprocess.run(['xdotool', 'windowactivate', '--sync', wid],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=2)
        time.sleep(0.1)  # 等窗口切换
        print(f'restored window: {wid}', file=sys.stderr)
    except Exception as e:
        print(f'restore failed: {e}', file=sys.stderr)


def ensure_status_bar():
    """确保状态条窗口在跑"""
    r = subprocess.run(['pgrep', '-f', 'voice-statusbar-gtk.py'],
                       capture_output=True)
    if r.returncode != 0:
        try:
            subprocess.Popen(
                ['python3', '-B',
                 os.path.expanduser('~/.hermes/scripts/voice-statusbar-gtk.py')],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            time.sleep(0.5)
        except Exception as e:
            print(f"status bar start failed: {e}", file=sys.stderr)


if __name__ == '__main__':
    main()
