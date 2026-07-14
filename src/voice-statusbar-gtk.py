#!/usr/bin/env python3
"""讯飞语音 - 紧贴屏幕底部的状态条（GTK Window 替代品）

不受 IBus/GNOME 状态栏控制 - 自己显示状态：
  讯 (空闲) | 录 (录音中) | 识 (识别中)

通过 socket 接收状态更新
"""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
import socket
import threading
import os
import sys
import json

STATUS_SOCK = '/tmp/voice-status.sock'

# 状态颜色
COLORS = {
    'idle':      ('讯', '#4a90e2'),     # 蓝色
    'recording': ('录', '#ff5252'),     # 红色
    'processing':('识', '#ff9800'),     # 橙色
    'paused':    ('休', '#9e9e9e'),     # 灰色
}


class StatusBar(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_title('讯飞语音')
        self.set_default_size(120, 50)
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_above(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_app_paintable(True)

        # 半透明
        screen = Gdk.Screen.get_default()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)

        # CSS
        css = b"""
        window { background-color: rgba(0,0,0,0); }
        .bar {
            background-color: rgba(30,30,40,0.92);
            border-radius: 8px;
            border: 1px solid rgba(255,255,255,0.15);
            padding: 6px 16px;
        }
        .icon {
            color: white;
            font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", sans-serif;
            font-size: 22px;
            font-weight: bold;
            min-width: 32px;
        }
        .text {
            color: rgba(255,255,255,0.6);
            font-size: 10px;
        }
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css)
        context = self.get_style_context()
        context.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        # 内容
        hbox = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        hbox.get_style_context().add_class('bar')

        self.label_icon = Gtk.Label()
        self.label_icon.get_style_context().add_class('icon')
        hbox.pack_start(self.label_icon, False, False, 0)

        self.label_text = Gtk.Label()
        self.label_text.get_style_context().add_class('text')
        hbox.pack_start(self.label_text, False, False, 0)

        self.add(hbox)
        hbox.show_all()

        self._status = 'idle'
        self._update_display()

        # 屏幕底部居中
        GLib.timeout_add(500, self._position)

    def set_status(self, status):
        if status == self._status:
            return
        self._status = status
        GLib.idle_add(self._update_display)

    def _update_display(self):
        icon, color = COLORS.get(self._status, COLORS['idle'])
        self.label_icon.set_markup(
            f'<span foreground="{color}">{icon}</span>')
        text_map = {
            'idle': '空闲 - Ctrl+Alt+V 录音',
            'recording': '🔴 录音中...',
            'processing': '识别中...',
            'paused': '已暂停',
        }
        self.label_text.set_text(text_map.get(self._status, ''))
        return False

    def _position(self):
        # 屏幕底部居中
        screen = Gdk.Screen.get_default()
        sw = screen.get_width()
        sh = screen.get_height()
        # 假设大小
        win_w = 180
        win_h = 50
        x = (sw - win_w) // 2
        y = sh - win_h - 50  # dock 上方 50px
        # 避免 dock 重叠 - 简化
        self.move(x, y)
        return True


def socket_server(window):
    if os.path.exists(STATUS_SOCK):
        os.unlink(STATUS_SOCK)
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(STATUS_SOCK)
    srv.listen(2)
    srv.settimeout(1)
    while True:
        try:
            client, _ = srv.accept()
            data = client.recv(4096).decode().strip()
            if data:
                try:
                    msg = json.loads(data)
                    status = msg.get('status', 'idle')
                    GLib.idle_add(window.set_status, status)
                except Exception:
                    pass
            client.close()
        except socket.timeout:
            continue
        except Exception:
            break


def main():
    window = StatusBar()
    window.show_all()
    t = threading.Thread(target=socket_server, args=(window,), daemon=True)
    t.start()
    Gtk.main()


if __name__ == '__main__':
    main()
