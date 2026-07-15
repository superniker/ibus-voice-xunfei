#!/usr/bin/env python3
# IBus语音引擎 - 海峰五笔式完整状态栏
#
# 关键设计（参考 ibus-table 实现）：
#   1. 状态栏主属性 "InputMode"（IBus 命名规范）
#      - symbol: 状态文字（"讯"/"录"/"识"）
#      - icon: 三态图标
#      - 点击切换（录音 toggle）
#   2. "LetterWidth" 等可选菜单（占位）
#   3. "Setup" 属性启动独立的设置程序
#   4. "About" 属性显示关于
#
# 状态机:
#   idle       -> symbol="讯" icon=blue
#   recording  -> symbol="录" icon=red
#   processing -> symbol="识" icon=orange
import gi
gi.require_version('IBus', '1.0')
from gi.repository import IBus, GLib
import socket, os, json, threading, time, subprocess

SOCK = '/tmp/ibus-voice.sock'
CFG_PATH = os.path.expanduser('~/.config/ibus-voice/config.json')
SETUP_SCRIPT = os.path.expanduser('~/.hermes/scripts/voice-setup.py')


def _load_config():
    try:
        with open(CFG_PATH) as f:
            cfg = json.load(f)
        return cfg.get('engine', {})
    except Exception:
        return {}


ENGINE_CFG = _load_config()
OUTPUT_MODE = ENGINE_CFG.get('output', 'preview_paste')
PREVIEW_MODE = ENGINE_CFG.get('preview', 'zenity_center')
SHORTCUT = ENGINE_CFG.get('shortcut', '<Primary><Shift>v')

# 状态定义（参考海峰五笔结构）
STATES = {
    'idle': {
        'number': 0,
        'symbol': '讯',
        'icon': '/home/niker/.local/share/icons/hicolor/256x256/apps/ibus-voice-input.png',
        'label': '空闲',
        'tooltip': '点击开始录音\n快捷键: ' + SHORTCUT,
    },
    'recording': {
        'number': 1,
        'symbol': '录',
        'icon': '/home/niker/.local/share/icons/hicolor/256x256/apps/ibus-voice-input-recording.png',
        'label': '录音中',
        'tooltip': '点击停止录音',
    },
    'processing': {
        'number': 2,
        'symbol': '识',
        'icon': '/home/niker/.local/share/icons/hicolor/256x256/apps/ibus-voice-input-processing.png',
        'label': '识别中',
        'tooltip': '正在识别...',
    },
}


def log(msg):
    try:
        with open('/tmp/ibus-voice.log', 'a') as f:
            f.write(f'{time.strftime("%H:%M:%S")} {msg}\n')
    except Exception:
        pass


class VoiceEngine(IBus.Engine):
    __gtype_name__ = 'EngineVoice'

    def __init__(self, *args, **kwargs):
        # GObject 工厂创建时不调 Python __init__!
        # 改用 __gobject_init__ (GObject 3.x 钩子)
        super().__init__(*args, **kwargs)

    def __gobject_init__(self):
        """GObject 工厂创建时实际调用的方法"""
        import os as _os
        # 立即写一个临时文件证明 __gobject_init__ 被调用
        try:
            with open('/tmp/voice-init-marker.txt', 'w') as f:
                f.write(f'__gobject_init__ called at {_os.environ.get("IBUS_ADDRESS", "?")}\n')
        except Exception:
            pass
        log('__gobject_init__ start')
        # 延迟到 do_enable 做主要 init
        self._initialized = False

    def _setup_properties(self):
        """注册ibus属性菜单（海峰五笔风格）"""
        # 1. InputMode - 状态栏主显示
        # 使用标准 InputMode.Direct 子属性（IBus 状态栏识别）
        self._input_mode_properties = {
            'InputMode.Direct': {
                'number': 0,
                'symbol': STATES['idle']['symbol'],      # 状态栏主显示
                'icon': STATES['idle']['icon'],
                'label': '空闲（点击录音）',
                'tooltip': STATES['idle']['tooltip'],
            },
            'InputMode.Recording': {
                'number': 1,
                'symbol': STATES['recording']['symbol'],
                'icon': STATES['recording']['icon'],
                'label': '录音中（点击停止）',
                'tooltip': STATES['recording']['tooltip'],
            },
            'InputMode.Processing': {
                'number': 2,
                'symbol': STATES['processing']['symbol'],
                'icon': STATES['processing']['icon'],
                'label': '识别中...',
                'tooltip': STATES['processing']['tooltip'],
            },
        }
        # InputMode 主属性
        self._prop_dict['InputMode'] = IBus.Property(
            key='InputMode',
            prop_type=IBus.PropType.MENU,
            label=IBus.Text.new_from_string(f'讯飞语音 ({STATES[self._status]["symbol"]})'),
            symbol=IBus.Text.new_from_string(STATES[self._status]['symbol']),
            icon=STATES[self._status]['icon'],
            tooltip=IBus.Text.new_from_string(f'状态: {STATES[self._status]["label"]}\\n快捷键: {SHORTCUT}'),
            sensitive=True,
            visible=True,
            state=IBus.PropState.UNCHECKED,
        )
        # 子属性
        sub_input = IBus.PropList()
        for key, prop in self._input_mode_properties.items():
            self._prop_dict[key] = IBus.Property(
                key=key,
                prop_type=IBus.PropType.RADIO,
                label=IBus.Text.new_from_string(prop['label']),
                symbol=IBus.Text.new_from_string(prop['symbol']),
                icon=prop['icon'],
                tooltip=IBus.Text.new_from_string(prop['tooltip']),
                sensitive=True,
                visible=True,
                state=IBus.PropState.UNCHECKED,
            )
            sub_input.append(self._prop_dict[key])
        self._prop_dict['InputMode'].set_sub_props(sub_input)
        self._sub_props_dict['InputMode'] = sub_input

        # 2. OutputMode - 输出方式
        self._output_mode_properties = {
            'OutputMode.Paste': {
                'number': 0,
                'symbol': 'P',
                'icon': 'edit-paste',
                'label': '终态粘贴',
            },
            'OutputMode.Preview': {
                'number': 1,
                'symbol': 'V',
                'icon': 'view-refresh',
                'label': '预览+粘贴',
            },
            'OutputMode.Stream': {
                'number': 2,
                'symbol': 'S',
                'icon': 'media-playback-start',
                'label': '实时（实验）',
            },
        }
        self._prop_dict['OutputMode'] = IBus.Property(
            key='OutputMode',
            prop_type=IBus.PropType.MENU,
            label=IBus.Text.new_from_string(f'输出'),
            symbol=IBus.Text.new_from_string(self._get_output_symbol()),
            icon=self._get_output_icon(),
            tooltip=IBus.Text.new_from_string('选择输出方式'),
            sensitive=True,
            visible=True,
        )
        sub_out = IBus.PropList()
        for key, prop in self._output_mode_properties.items():
            self._prop_dict[key] = IBus.Property(
                key=key,
                prop_type=IBus.PropType.RADIO,
                label=IBus.Text.new_from_string(prop['label']),
                icon=prop['icon'],
                tooltip=IBus.Text.new_from_string(prop['label']),
                sensitive=True,
                visible=True,
                state=IBus.PropState.CHECKED if key == f'OutputMode.{self._output_mode.capitalize().replace("_","")}' or key == self._get_output_key() else IBus.PropState.UNCHECKED,
            )
            sub_out.append(self._prop_dict[key])
        self._prop_dict['OutputMode'].set_sub_props(sub_out)
        self._sub_props_dict['OutputMode'] = sub_out

        # 3. Setup - 启动设置程序（key 小写 - IBus 标准）
        self._prop_dict['setup'] = IBus.Property(
            key='setup',
            prop_type=IBus.PropType.NORMAL,
            label=IBus.Text.new_from_string('设置...'),
            icon='gtk-preferences',
            tooltip=IBus.Text.new_from_string('打开讯飞语音设置'),
            sensitive=True,
            visible=True,
        )

        # 4. About - 关于
        self._prop_dict['About'] = IBus.Property(
            key='About',
            prop_type=IBus.PropType.NORMAL,
            label=IBus.Text.new_from_string('关于'),
            icon='help-about',
            tooltip=IBus.Text.new_from_string('关于讯飞语音输入法'),
            sensitive=True,
            visible=True,
        )

        # 注册所有属性
        main_props = IBus.PropList()
        for key in ['InputMode', 'OutputMode', 'setup', 'About']:
            main_props.append(self._prop_dict[key])
        self.register_properties(main_props)

    def _get_output_symbol(self):
        symbols = {'paste': 'P', 'preview_paste': 'V', 'stream': 'S'}
        return symbols.get(self._output_mode, '?')

    def _get_output_icon(self):
        icons = {'paste': 'edit-paste', 'preview_paste': 'view-refresh', 'stream': 'media-playback-start'}
        return icons.get(self._output_mode, 'edit-paste')

    def _get_output_key(self):
        return f'OutputMode.{self._output_mode.capitalize()}'

    def _update_status(self, status, force=False):
        """更新状态栏（force=True 强制更新，即使状态相同）"""
        log(f'update_status called: {status} force={force} current={self._status}')
        if not force and status == self._status:
            log('  early return (no change)')
            return
        self._status = status
        st = STATES[status]
        log(f'  setting icon={st["icon"]} symbol={st["symbol"]}')
        try:
            self._prop_dict['InputMode'].set_label(
                IBus.Text.new_from_string(f'讯飞语音 ({st["symbol"]})'))
            self._prop_dict['InputMode'].set_symbol(
                IBus.Text.new_from_string(st['symbol']))
            self._prop_dict['InputMode'].set_icon(st['icon'])
            self._prop_dict['InputMode'].set_tooltip(
                IBus.Text.new_from_string(f'状态: {st["label"]}\\n快捷键: {SHORTCUT}'))
            self.update_property(self._prop_dict['InputMode'])
            log('  update_property called')
        except Exception as e:
            log(f'  update_property failed: {e}')

    def do_property_activate(self, prop_name, prop_state):
        log(f'property_activate: {prop_name} state={prop_state}')
        if prop_state != IBus.PropState.CHECKED and not prop_name.startswith('InputMode.'):
            # 没勾选直接返回（hover 不算点击）
            return

        # InputMode 点击 - toggle 录音
        if prop_name.startswith('InputMode.'):
            if self._status == 'idle':
                self._start_recording()
            elif self._status == 'recording':
                self._stop_recording()
            return

        # OutputMode
        if prop_name.startswith('OutputMode.'):
            mode_name = prop_name[len('OutputMode.'):].lower()
            self._output_mode = mode_name
            self._prop_dict['OutputMode'].set_symbol(
                IBus.Text.new_from_string(self._get_output_symbol()))
            self._prop_dict['OutputMode'].set_icon(self._get_output_icon())
            try:
                self.update_property(self._prop_dict['OutputMode'])
            except Exception:
                pass
            return

        if prop_name == 'setup':
            self._start_setup()
            return

        if prop_name == 'About':
            # 用 zenity 弹窗显示（notify-send 可能不显示）
            import subprocess
            about_text = (
                '讯飞语音输入法 v1.3\n\n'
                '功能:\n'
                '  • 流式语音识别（边说边显示）\n'
                '  • IBus commit_text 上屏\n'
                '  • 屏幕底部状态条\n'
                '  • 设置菜单\n\n'
                '快捷键: F8\n'
                f'状态: {self._status}\n\n'
                '文件: ~/.hermes/scripts/\n'
                '配置: ~/.config/ibus-voice/config.json'
            )
            subprocess.Popen(
                ['zenity', '--info',
                 '--title=关于讯飞语音',
                 '--text=' + about_text,
                 '--width=400', '--height=300',
                 '--timeout=10'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return

    def _start_setup(self):
        """启动独立的设置程序"""
        if self._setup_proc and self._setup_proc.poll() is None:
            return  # 已在运行
        if not os.path.exists(SETUP_SCRIPT):
            self._notify('设置', f'设置脚本不存在: {SETUP_SCRIPT}\n请创建')
            return
        try:
            self._setup_proc = subprocess.Popen(
                ['python3', '-B', SETUP_SCRIPT],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except Exception as e:
            self._notify('设置', f'启动失败: {e}')

    # ---- IBus 事件（不自动录音） ----

    def _lazy_init(self):
        """延迟初始化 - 因为 GObject 工厂不调 Python __init__"""
        if getattr(self, '_initialized', False):
            return
        self._initialized = True
        log('_lazy_init start')
        self._sock = None
        self._latest_text = ''
        self._committed_text = ''
        self._lock = threading.Lock()
        self._recv_thread = None
        self._enabled = False
        self._recording = False
        self._active_focus = False
        self._status = 'idle'
        self._output_mode = OUTPUT_MODE
        self._preview_mode = PREVIEW_MODE
        self._preview_last_time = 0.0
        self._prop_dict = {}
        self._sub_props_dict = {}
        self._setup_properties()
        # 启动 commit_text 监听
        t = threading.Thread(target=self._commit_listener_safe, daemon=True)
        t.start()
        # 启动 partial_text 监听（流式预编辑）
        t2 = threading.Thread(target=self._partial_listener_safe, daemon=True)
        t2.start()
        log('_lazy_init done')

    def do_enable(self):
        self._lazy_init()
        log('enable')
        self._enabled = True
        self._update_status('idle', force=True)

    def do_disable(self):
        log('disable')
        self._enabled = False
        if self._recording:
            self._stop_recording()
        self._update_status('idle', force=True)

    def do_focus_in(self):
        self._lazy_init()
        log(f'focus_in (rec={self._recording}, status={self._status})')
        self._active_focus = True

    def do_focus_out(self):
        self._lazy_init()
        log('focus_out')
        self._active_focus = False

    def do_reset(self):
        self._lazy_init()
        log('reset')

    def do_cursor_down(self):
        return False

    def do_cursor_up(self):
        return False

    def do_process_key_event(self, keyval, keycode, state):
        # 调试: 记录所有 key event
        log(f'key event: keyval={keyval} keycode={keycode} state={state} status={self._status} latest={self._latest_text[:20] if self._latest_text else ""!r}')
        # Space/Tab 键 - 在录音中 commit 当前 preedit
        # 模仿海峰五笔按 space commit
        if keyval in (32, 65289):  # Space, Tab
            with self._lock:
                current = self._latest_text
            # 只有真的有 preedit 内容才 commit + 拦截
            if current and self._status in ('recording', 'processing'):
                log(f'commit key pressed: keyval={keyval} text={current[:20]!r}')
                GLib.idle_add(self._commit_and_continue_preedit)
                return True
        return False

    def _commit_and_continue_preedit(self):
        """录音中按 Space: commit 当前 preedit 到焦点, 然后 preedit 从空开始"""
        try:
            with self._lock:
                current = self._latest_text
            if current:
                self.commit_text(IBus.Text.new_from_string(current))
                log(f'partial committed: {current[:30]}')
            # 强制清 preedit - 双保险
            try:
                self.hide_preedit_text()
            except Exception:
                pass
            try:
                IBus.Engine.update_preedit_text_with_mode(
                    self, IBus.Text.new_from_string(''), 0, False,
                    IBus.PreeditFocusMode.COMMIT)
            except Exception:
                pass
            # 清 _latest_text
            with self._lock:
                self._latest_text = ''
        except Exception as e:
            log(f'commit_and_continue err: {e}')
        return False

    # ---- 录音控制 ----

    def _start_recording(self):
        if self._recording:
            return
        log('start_recording')
        with self._lock:
            self._latest_text = ''
            self._committed_text = ''
            self._preview_last_text = ''
            self._auto_committed = ''
            self._recording = True
        self._update_status('recording')
        self._start_session()
        if self._preview_mode != 'none':
            self._show_preview('🎤 录音中...')
        self._notify('讯飞语音', '🔴 开始录音')

    def _stop_recording(self):
        if not self._recording:
            return
        log('stop_recording')
        self._update_status('processing')
        with self._lock:
            text = self._latest_text
            self._latest_text = ''
            self._recording = False
        self._stop_session()
        if self._preview_mode != 'none':
            self._hide_preview()
        if not text:
            self._update_status('idle')
            self._notify('讯飞语音', '⚠ 未识别到内容')
            return
        # 用 IBus commit_text（IBus 标准方式，不依赖剪贴板/焦点）
        self._commit_text_to_focus(text)
        self._update_status('idle')
        self._notify('讯飞语音', f'✓ 已识别 {len(text)} 字')

    def _commit_text_to_focus(self, text):
        """通过 IBus commit_text 提交到当前焦点应用 - IBus 标准方式"""
        try:
            self.commit_text(IBus.Text.new_from_string(text))
            log(f'commit_text OK: {text[:30]}')
        except Exception as e:
            log(f'commit_text fail: {e}')

    def _commit_listener(self):
        """监听外部 commit_text 请求 + status 更新"""
        import socket as sk, json as js, _thread as thread
        SOCK = '/tmp/voice-commit.sock'
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        try:
            srv = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
            srv.bind(SOCK)
            srv.listen(8)
            srv.settimeout(1)
            log(f'commit listener on {SOCK}')
        except Exception as e:
            log(f'commit listener bind fail: {e}')
            return

        def handle_client(client):
            try:
                data = client.recv(4096).decode().strip()
                if data:
                    try:
                        msg = js.loads(data)
                        if 'status' in msg:
                            status = msg['status']
                            log(f'status update: {status}')
                            GLib.idle_add(self._update_status, status)
                        text = msg.get('text', '')
                        if text:
                            log(f'commit request: {text[:30]}')
                            GLib.idle_add(self._do_commit, text)
                    except Exception as e:
                        log(f'commit parse err: {e}')
                client.close()
            except Exception as e:
                log(f'handle err: {e}')

        while True:
            try:
                client, _ = srv.accept()
                # 每个连接独立线程处理
                thread.start_new_thread(handle_client, (client,))
            except sk.timeout:
                continue
            except Exception as e:
                log(f'commit listener err: {e}')
                break

    def _commit_listener_safe(self):
        """commit_listener 包装 - 捕获所有异常"""
        try:
            self._commit_listener()
        except Exception as e:
            log(f'commit listener thread crash: {e}')

    def _partial_listener_safe(self):
        try:
            self._partial_listener()
        except Exception as e:
            log(f'partial listener thread crash: {e}')

    def _partial_listener(self):
        """监听 partial result - 显示预编辑（流式）"""
        import socket as sk, json as js, _thread as thread
        SOCK = '/tmp/voice-partial.sock'
        try:
            os.unlink(SOCK)
        except FileNotFoundError:
            pass
        try:
            srv = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
            srv.bind(SOCK)
            srv.listen(8)
            srv.settimeout(1)
            log(f'partial listener on {SOCK}')
        except Exception as e:
            log(f'partial listener bind fail: {e}')
            return

        def handle(client):
            try:
                data = client.recv(4096).decode().strip()
                if data:
                    try:
                        msg = js.loads(data)
                        text = msg.get('text', '')
                        if text:
                            # 在 GLib 主线程调 update_preedit + 更新 _latest_text
                            GLib.idle_add(self._do_partial_with_text, text)
                    except Exception as e:
                        log(f'partial parse err: {e}')
                client.close()
            except Exception as e:
                log(f'partial handle err: {e}')

        while True:
            try:
                client, _ = srv.accept()
                thread.start_new_thread(handle, (client,))
            except sk.timeout:
                continue
            except Exception as e:
                log(f'partial listener err: {e}')
                break

    def _do_partial(self, text):
        """在焦点应用上显示预编辑文本 - 流式"""
        try:
            # IBus.Engine.update_preedit_text_with_mode
            IBus.Engine.update_preedit_text_with_mode(
                self,
                IBus.Text.new_from_string(text),
                len(text),  # 光标在末尾
                True,        # visible
                IBus.PreeditFocusMode.COMMIT)
        except Exception as e:
            log(f'do_partial err: {e}')
        return False

    def _do_partial_with_text(self, text):
        """partial 同时更新 _latest_text - 让 Space commit 找到内容

        长文本策略：遇到句号/问号/感叹号，把已确认的前半段先 commit，
        preedit 只保留最后一句。这样不会超出屏幕宽度。
        """
        with self._lock:
            self._latest_text = text
        # 检测句子边界，自动 commit 已确认的前半段
        import re
        # 找最后一个句子边界（。！？!?）
        m = None
        for m in re.finditer(r'[。！？!?]', text):
            pass  # 找最后一个
        if m and m.end() < len(text):
            # 有句子边界，且后面还有文字
            commit_part = text[:m.end()]
            remain_part = text[m.end():]
            # 只 commit 比上次多出来的部分
            already_committed = getattr(self, '_auto_committed', '')
            if commit_part != already_committed and commit_part.startswith(already_committed):
                new_part = commit_part[len(already_committed):]
                if new_part:
                    try:
                        self.commit_text(IBus.Text.new_from_string(new_part))
                        log(f'auto-commit sentence: {new_part[:30]}')
                    except Exception as e:
                        log(f'auto-commit err: {e}')
                self._auto_committed = commit_part
            # preedit 只显示最后一句
            self._do_partial(remain_part)
            with self._lock:
                self._latest_text = remain_part
            return False
        return self._do_partial(text)

    def _do_commit(self, text):
        # 先 commit_text 到焦点应用
        try:
            self.commit_text(IBus.Text.new_from_string(text))
            log(f'do_commit OK: {text[:30]}')
        except Exception as e:
            log(f'do_commit err: {e}')
        # 强制清空 preedit - wayland 下需要多种方法
        # 方法 1: hide_preedit_text
        try:
            self.hide_preedit_text()
            log('hide_preedit_text called')
        except Exception as e:
            log(f'hide_preedit err: {e}')
        # 方法 2: update_preedit_text_with_mode
        try:
            IBus.Engine.update_preedit_text_with_mode(
                self, IBus.Text.new_from_string(''), 0, False,
                IBus.PreeditFocusMode.COMMIT)
            log('update_preedit_text called')
        except Exception as e:
            log(f'update_preedit err: {e}')
        # 同时清 _latest_text
        with self._lock:
            self._latest_text = ''
        self._update_status('idle')
        return False

    def _commit_final_then_idle(self, text):
        self._commit_final(text)
        self._update_status('idle')
        return False

    def _commit_final(self, text):
        try:
            self.commit_text(IBus.Text.new_from_string(text))
        except Exception:
            pass
        return False

    # ---- socket session ----

    def _start_session(self):
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(2)
            s.connect(SOCK)
            self._sock = s
            s.sendall(json.dumps({'cmd': 'start'}).encode() + b'\n')
            log('start sent')
            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
        except Exception as e:
            log(f'start_session fail: {e}')
            self._sock = None

    def _stop_session(self):
        sock = self._sock
        self._sock = None
        if sock:
            try:
                sock.sendall(json.dumps({'cmd': 'stop'}).encode() + b'\n')
            except Exception:
                pass
            try:
                sock.close()
            except Exception:
                pass

    def _recv_loop(self):
        sock = self._sock
        if not sock:
            return
        buf = b''
        try:
            while True:
                with self._lock:
                    if not self._recording or self._sock is None:
                        break
                try:
                    chunk = sock.recv(4096)
                except socket.timeout:
                    continue
                except Exception:
                    break
                if not chunk:
                    break
                buf += chunk
                while b'\n' in buf:
                    line, buf = buf.split(b'\n', 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line.decode())
                    except Exception:
                        continue
                    if 'text' in msg and self._recording:
                        text = msg['text']
                        with self._lock:
                            self._latest_text = text
                            preview_changed = (text != self._preview_last_text)
                            now = time.time()
                            time_ok = (now - self._preview_last_time) > 0.3
                            if preview_changed and time_ok:
                                self._preview_last_text = text
                                self._preview_last_time = now
                                should_preview = True
                            else:
                                should_preview = False
                        if should_preview and self._preview_mode != 'none':
                            GLib.idle_add(self._show_preview_async, text[-100:])
        except Exception as e:
            log(f'recv err: {e}')
        log('recv loop exit')

    def _notify(self, title, body):
        try:
            subprocess.Popen(['notify-send', '-t', '3000', title, body],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception:
            pass

    def _show_preview(self, text):
        """发送文本到 GTK 预览窗口（紧贴焦点）"""
        try:
            import socket as sk, json as js
            s = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect('/tmp/voice-preview.sock')
            s.sendall(js.dumps({'text': text}).encode() + b'\n')
            s.close()
        except Exception:
            # 降级到 notify-send
            try:
                subprocess.Popen(['notify-send', '-t', '5000', '语音输入', text],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass

    def _show_preview_async(self, text):
        self._show_preview(text)
        return False

    def _hide_preview(self):
        """隐藏预览窗口（发送空文本或隐藏指令）"""
        try:
            import socket as sk, json as js
            s = sk.socket(sk.AF_UNIX, sk.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect('/tmp/voice-preview.sock')
            s.sendall(js.dumps({'text': '', 'hide': True}).encode() + b'\n')
            s.close()
        except Exception:
            pass

    def _paste_to_focused_app(self, text, replace_all=False):
        try:
            p = subprocess.Popen(['wl-copy'], stdin=subprocess.PIPE,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            p.stdin.write(text.encode('utf-8'))
            p.stdin.close()
            p.wait(timeout=2)
        except Exception as e:
            log(f'wl-copy fail: {e}')
            return
        try:
            args = ['ydotool', 'key']
            if replace_all:
                args += ['29:1', '6:1', '6:0', '29:0']
            args += ['29:1', '47:1', '47:0', '29:0']
            subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
        except Exception as e:
            log(f'ydotool paste fail: {e}')


def main():
    IBus.main()


if __name__ == '__main__':
    component = IBus.Component(
        name='org.freedesktop.IBus.VoiceInput',
        description='讯飞语音输入法',
        version='1.2.0', license='MIT', author='Hermes',
        homepage='https://github.com/superniker',
    )
    engine_desc = IBus.EngineDesc(
        name='voice-input',
        longname='讯飞语音',
        description='Ctrl+Shift+V 录音',
        language='zh_CN', license='MIT', author='Hermes',
        icon='ibus-voice-input', rank=1,
    )
    component.add_engine(engine_desc)
    IBus.Bus().register_component(component)
    IBus.Factory.new(IBus.Bus().get_connection()).add_engine('voice-input', VoiceEngine)
    main()
