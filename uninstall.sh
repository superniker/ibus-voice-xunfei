#!/bin/bash
# ibus-voice-xunfei 卸载脚本
set -e

echo "=== 讯飞语音输入法 卸载 ==="

# 1. 停止 daemon
systemctl --user stop ibus-voice-daemon.service 2>/dev/null || true
systemctl --user disable ibus-voice-daemon.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/ibus-voice-daemon.service"
systemctl --user daemon-reload 2>/dev/null || true

# 2. 删除 IBus 组件注册
rm -f "$HOME/.local/share/ibus/component/voice-input.xml"

# 3. 删除安装文件
rm -rf "$HOME/.local/share/ibus-voice-xunfei"

# 4. 删除图标
rm -f "$HOME/.local/share/icons/hicolor/256x256/apps/ibus-voice-input*.png"
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

# 5. 重启 IBus
ibus restart 2>/dev/null || true

echo ""
echo "=== 卸载完成 ==="
echo ""
echo "配置文件保留在 ~/.config/ibus-voice/（如需删除请手动操作）"
