#!/usr/bin/env python3
# 包装脚本：自动找到当前 ibus socket 路径再启动真实引擎
# 这样用户每次不需要重新指定 IBUS_ADDRESS 环境变量
import os, sys, glob

HOME = os.path.expanduser('~')

def find_ibus_socket():
    """扫描 ~/.cache/ibus/dbus-* 找当前活跃的socket"""
    pattern = os.path.join(HOME, '.cache/ibus/dbus-*')
    sockets = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
    import socket as sock_mod
    for path in sockets:
        try:
            s = sock_mod.socket(sock_mod.AF_UNIX, sock_mod.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(path)
            s.close()
            return path
        except Exception:
            continue
    return None

sock = find_ibus_socket()
if not sock:
    print("ERROR: 找不到可用的 ibus socket（~/.cache/ibus/dbus-*）", file=sys.stderr)
    print("提示：ibus-daemon 没在跑？执行 'ibus-daemon -drx' 启动", file=sys.stderr)
    sys.exit(1)

env = os.environ.copy()
env['IBUS_ADDRESS'] = f'unix:path={sock}'
print(f"voice-engine: using IBUS_ADDRESS={sock}", file=sys.stderr)

real_script = os.path.join(os.path.dirname(__file__), 'ibus-voice-engine-inner.py')
os.execvpe('python3', ['python3', '-B', '-u', real_script], env)
