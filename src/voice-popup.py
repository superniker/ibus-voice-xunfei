#!/usr/bin/env python3
"""讯飞语音 - 弹窗（不阻塞，无按钮，自动消失）"""
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GLib, Pango
import sys
import os

# 解析参数
# voice-popup.py "title" "body" [timeout_ms] [bg_color]
if len(sys.argv) < 3:
    print("usage: voice-popup.py title body [timeout_ms] [bg_color]")
    sys.exit(1)

title = sys.argv[1]
body = sys.argv[2]
timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 3000
bg = sys.argv[4] if len(sys.argv) > 4 else '#1e1e28'


class Popup(Gtk.Window):
    def __init__(self):
        super().__init__(type=Gtk.WindowType.POPUP)
        self.set_title(title)
        self.set_default_size(420, 110)
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

        css = f"""
        window {{ background-color: rgba(0,0,0,0); }}
        .frame {{
            background-color: {bg};
            border-radius: 14px;
            border: 1px solid rgba(255,255,255,0.18);
            padding: 14px 22px;
        }}
        .title {{
            color: white;
            font-size: 12px;
            opacity: 0.7;
        }}
        .body {{
            color: white;
            font-size: 17px;
            font-weight: 500;
            margin-top: 4px;
        }}
        """
        provider = Gtk.CssProvider()
        provider.load_from_data(css.encode())
        context = self.get_style_context()
        context.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        vbox.get_style_context().add_class('frame')

        lbl_title = Gtk.Label(label=title)
        lbl_title.set_xalign(0)
        lbl_title.get_style_context().add_class('title')
        vbox.pack_start(lbl_title, False, False, 0)

        lbl_body = Gtk.Label()
        lbl_body.set_xalign(0)
        lbl_body.set_line_wrap(True)
        lbl_body.set_max_width_chars(45)
        lbl_body.set_ellipsize(Pango.EllipsizeMode.END)
        lbl_body.get_style_context().add_class('body')
        lbl_body.set_text(body)
        vbox.pack_start(lbl_body, False, False, 0)

        self.add(vbox)
        vbox.show_all()

        # 屏幕中央偏上
        sw = screen.get_width()
        sh = screen.get_height()
        win_w = 420
        win_h = 110
        self.move((sw - win_w) // 2, sh // 3)
        # 自动关闭（timeout=0 表示不自动关闭）
        if timeout > 0:
            GLib.timeout_add(timeout, self._close)

    def _close(self):
        Gtk.main_quit()
        return False


def main():
    popup = Popup()
    popup.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
