#!/usr/bin/env python3
"""讯飞语音输入法 - 设置程序 (类似 ibus-setup-table)

由 ibus-setup 或系统键盘首选项调用
"""
import sys
import os
import gi

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk
import json

CONFIG = os.path.expanduser('~/.config/ibus-voice/config.json')


class SetupWindow(Gtk.Window):
    def __init__(self):
        super().__init__(title='讯飞语音输入法 - 设置')
        self.set_default_size(540, 380)
        self.set_border_width(10)
        self.set_position(Gtk.WindowPosition.CENTER)

        # 加载配置
        self.cfg = {}
        try:
            with open(CONFIG) as f:
                self.cfg = json.load(f)
        except Exception:
            pass

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        self.add(vbox)

        # === 标签页 ===
        notebook = Gtk.Notebook()
        vbox.pack_start(notebook, True, True, 0)

        # --- 基本设置 ---
        page1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page1.set_border_width(12)

        # 讯飞 API 配置
        frame_api = Gtk.Frame(label='讯飞 API 凭证')
        page1.pack_start(frame_api, False, False, 0)
        api_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        api_box.set_border_width(8)
        frame_api.add(api_box)

        self.entry_appid = Gtk.Entry()
        self.entry_appid.set_text(self.cfg.get('appid', ''))
        self.entry_appid.set_placeholder_text('AppID')
        api_box.pack_start(self._labeled('AppID:', self.entry_appid), False, False, 0)

        self.entry_api_key = Gtk.Entry()
        self.entry_api_key.set_text(self.cfg.get('api_key', ''))
        self.entry_api_key.set_placeholder_text('API Key')
        api_box.pack_start(self._labeled('API Key:', self.entry_api_key), False, False, 0)

        self.entry_api_secret = Gtk.Entry()
        self.entry_api_secret.set_text(self.cfg.get('api_secret', ''))
        self.entry_api_secret.set_placeholder_text('API Secret')
        api_box.pack_start(self._labeled('API Secret:', self.entry_api_secret), False, False, 0)

        # 快捷键
        frame_shortcut = Gtk.Frame(label='快捷键')
        page1.pack_start(frame_shortcut, False, False, 0)
        sc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        sc_box.set_border_width(8)
        frame_shortcut.add(sc_box)
        self.entry_shortcut = Gtk.Entry()
        self.entry_shortcut.set_text(self.cfg.get('engine', {}).get('shortcut', 'F8'))
        sc_box.pack_start(self._labeled('录音快捷键:', self.entry_shortcut), False, False, 0)
        lbl_hint = Gtk.Label(label='提示：在 GNOME 设置→键盘→自定义快捷键中修改实际绑定')
        lbl_hint.set_xalign(0)
        sc_box.pack_start(lbl_hint, False, False, 0)

        notebook.append_page(page1, Gtk.Label(label='基本设置'))

        # --- 关于 ---
        page2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        page2.set_border_width(12)
        about_text = (
            '讯飞语音输入法 - Linux 版\n\n'
            '基于 IBus 框架 + 讯飞流式识别 API\n\n'
            '用法：\n'
            '  1. 按快捷键开始录音\n'
            '  2. 说话\n'
            '  3. 再按快捷键停止，文字自动到焦点应用\n\n'
            '技术架构：\n'
            '  - IBus commit_text 提交（不是 wl-copy/ydotool）\n'
            '  - 兼容 Wayland GTK 应用\n'
            '  - 全局快捷键由 GNOME 自定义快捷键处理'
        )
        lbl_about = Gtk.Label(label=about_text)
        lbl_about.set_xalign(0)
        lbl_about.set_line_wrap(True)
        page2.pack_start(lbl_about, False, False, 0)
        notebook.append_page(page2, Gtk.Label(label='关于'))

        # === 底部按钮 ===
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        btn_box.set_homogeneous(True)
        vbox.pack_start(btn_box, False, False, 0)

        btn_ok = Gtk.Button(label='保存')
        btn_ok.connect('clicked', self.on_save)
        btn_box.pack_start(btn_ok, True, True, 0)

        btn_cancel = Gtk.Button(label='取消')
        btn_cancel.connect('clicked', lambda w: Gtk.main_quit())
        btn_box.pack_start(btn_cancel, True, True, 0)

    def _labeled(self, text, widget):
        """包装 widget 带标签"""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lbl = Gtk.Label(label=text)
        lbl.set_xalign(0)
        lbl.set_size_request(120, -1)
        box.pack_start(lbl, False, False, 0)
        box.pack_start(widget, True, True, 0)
        return box

    def on_save(self, widget):
        self.cfg['appid'] = self.entry_appid.get_text()
        self.cfg['api_key'] = self.entry_api_key.get_text()
        self.cfg['api_secret'] = self.entry_api_secret.get_text()
        if 'engine' not in self.cfg:
            self.cfg['engine'] = {}
        self.cfg['engine']['shortcut'] = self.entry_shortcut.get_text()
        try:
            with open(CONFIG, 'w') as f:
                json.dump(self.cfg, f, indent=4)
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.INFO,
                buttons=Gtk.ButtonsType.OK, text='配置已保存')
            dialog.run()
            dialog.destroy()
            Gtk.main_quit()
        except Exception as e:
            dialog = Gtk.MessageDialog(
                transient_for=self, modal=True, message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK, text=f'保存失败: {e}')
            dialog.run()
            dialog.destroy()


def main():
    win = SetupWindow()
    win.connect('destroy', Gtk.main_quit)
    win.show_all()
    Gtk.main()


if __name__ == '__main__':
    main()
