# ibus-voice-xunfei

讯飞语音输入法 — IBus 引擎 + 讯飞 IAT 流式识别

在 Linux 桌面（Wayland/X11）上实现语音转文字，通过 IBus 标准 `commit_text` 上屏，兼容所有支持 IBus 的应用。

## 功能

- 🎤 **F8 一键录音** — 按一次开始，再按一次停止并上屏
- 📝 **流式预编辑** — 边说边显示，按 Space 可提前上屏
- 🔲 **屏幕底部状态条** — 讯(空闲)/录(录音)/识(识别) 三态
- ⚙️ **GTK 设置界面** — 配置讯飞 API、输出模式、快捷键
- 🖥️ **IBus 状态栏图标** — 三态图标 + 属性菜单
- 🔧 **多种输出模式** — 终态粘贴、预览+粘贴、实时（实验）

## 架构

```
┌─────────────┐    Unix Socket    ┌──────────────┐    WebSocket    ┌───────────┐
│ IBus Engine  │ ◀──────────────▶ │ voice-daemon │ ◀─────────────▶ │ 讯飞 IAT  │
│ (commit_text)│  partial/commit  │ (录音+识别)   │   流式音频     │ 云端 API  │
└─────────────┘                   └──────────────┘                 └───────────┘
       ▲
       │ IBus 协议
       ▼
  ┌──────────┐
  │ 焦点应用  │  (微信/GNOME编辑器/终端/任何 IBus 应用)
  └──────────┘
```

## 依赖

```bash
# Python 依赖
pip install sounddevice websocket-client numpy

# 系统依赖 (GNOME/Wayland)
sudo apt install ibus python3-gi gir1.2-ibus-1.0

# 可选（用于其他输出模式）
sudo apt install wl-clipboard ydotool zenity
```

## 安装

```bash
git clone https://github.com/superniker/ibus-voice-xunfei.git
cd ibus-voice-xunfei

# 配置讯飞 API 密钥
cp config/config.json.example ~/.config/ibus-voice/config.json
# 编辑 ~/.config/ibus-voice/config.json，填入你的 appid/api_key/api_secret

# 运行安装脚本
bash install.sh
```

安装脚本会：
1. 复制源文件到 `~/.local/share/ibus-voice-xunfei/`
2. 复制图标到 XDG 图标目录
3. 注册 IBus 组件
4. 重启 IBus

## 使用

1. 在 GNOME 设置 → 键盘 → 输入源中添加「讯飞语音」
2. 按 **F8** 开始录音
3. 说话
4. 按 **F8** 停止 → 文字自动上屏

### 状态栏

屏幕底部会显示一个状态条：
- **讯** (蓝色) — 空闲
- **录** (红色) — 录音中
- **识** (橙色) — 识别中

### IBus 状态栏

系统状态栏显示「讯」图标，点击可切换录音状态。右键可访问：
- 输出模式切换
- 设置
- 关于

### 快捷键

| 快捷键 | 功能 |
|--------|------|
| F8 | 开始/停止录音 |
| Space (录音中) | 提交当前预编辑文本 |

## 配置

配置文件：`~/.config/ibus-voice/config.json`

```json
{
    "appid": "你的讯飞APPID",
    "api_key": "你的讯飞API Key",
    "api_secret": "你的讯飞API Secret",
    "engine": {
        "output": "preview_paste",
        "preview": "none",
        "shortcut": "F8"
    }
}
```

### 输出模式

| 模式 | 说明 |
|------|------|
| `preview_paste` | 预览文本后粘贴（默认） |
| `paste` | 直接剪贴板粘贴 |
| `stream` | 实时上屏（实验性） |

## 讯飞 API 申请

1. 注册 [讯飞开放平台](https://www.xfyun.cn/)
2. 创建应用，获取 APPID、API Key、API Secret
3. 开通「语音听写」服务

## 文件说明

| 文件 | 说明 |
|------|------|
| `src/ibus-voice-engine.py` | IBus socket 包装脚本（自动找 IBus 地址） |
| `src/ibus-voice-engine-inner.py` | IBus 引擎核心（状态机、commit_text、属性菜单） |
| `src/voice-daemon.py` | 讯飞语音守护进程（录音、WebSocket 识别） |
| `src/voice-trigger.py` | F8 触发脚本 |
| `src/voice-statusbar-gtk.py` | 屏幕底部状态条 |
| `src/voice-popup.py` | 弹窗通知 |
| `src/voice-setup.py` | GTK 设置界面 |
| `src/voice-stream.py` | 独立流式识别工具（CLI） |

## 卸载

```bash
bash uninstall.sh
```

## 已测试环境

- GNOME Wayland (Fedora/Ubuntu)
- 微信 (XWayland)
- gnome-text-editor、gedit、终端
- IBus 1.5.x

## License

MIT
