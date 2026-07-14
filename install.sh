#!/bin/bash
# ibus-voice-xunfei 安装脚本
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$HOME/.local/share/ibus-voice-xunfei"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
CONFIG_DIR="$HOME/.config/ibus-voice"

echo "=== 讯飞语音输入法 安装 ==="

# 1. 创建目录
mkdir -p "$INSTALL_DIR" "$ICON_DIR" "$CONFIG_DIR"

# 2. 复制源文件
echo "复制源文件..."
cp "$SCRIPT_DIR"/src/*.py "$INSTALL_DIR/"
chmod +x "$INSTALL_DIR"/ibus-voice-engine.py
chmod +x "$INSTALL_DIR"/voice-daemon.py
chmod +x "$INSTALL_DIR"/voice-trigger.py
chmod +x "$INSTALL_DIR"/voice-statusbar-gtk.py
chmod +x "$INSTALL_DIR"/voice-popup.py
chmod +x "$INSTALL_DIR"/voice-setup.py
chmod +x "$INSTALL_DIR"/voice-stream.py

# 3. 复制图标
echo "复制图标..."
cp "$SCRIPT_DIR"/icons/*.png "$ICON_DIR/"

# 4. 更新 icon cache
if command -v gtk-update-icon-cache &>/dev/null; then
    gtk-update-icon-cache "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
fi

# 5. 创建配置文件（如果不存在）
if [ ! -f "$CONFIG_DIR/config.json" ]; then
    echo "创建配置文件..."
    cp "$SCRIPT_DIR/config/config.json.example" "$CONFIG_DIR/config.json"
    echo ""
    echo "⚠  请编辑配置文件，填入你的讯飞 API 密钥："
    echo "   $CONFIG_DIR/config.json"
    echo ""
else
    echo "配置文件已存在，跳过"
fi

# 6. 修改 engine wrapper 的路径指向安装目录
echo "配置 IBus 引擎..."
ENGINE_WRAPPER="$INSTALL_DIR/ibus-voice-engine.py"
sed -i "s|import os, sys, glob|import os, sys, glob, subprocess|" "$ENGINE_WRAPPER"

# 7. 注册 IBus 组件
echo "注册 IBus 组件..."
export PYTHONPATH="$INSTALL_DIR:${PYTHONPATH:-}"

# 8. 写 IBus 注册 XML
XML_DIR="$HOME/.local/share/ibus/component"
mkdir -p "$XML_DIR"
cat > "$XML_DIR/voice-input.xml" << XMLEOF
<?xml version="1.0" encoding="UTF-8"?>
<component>
  <name>org.freedesktop.IBus.VoiceInput</name>
  <description>讯飞语音输入法</description>
  <exec>$INSTALL_DIR/ibus-voice-engine.py</exec>
  <version>0.1.0</version>
  <author>superniker</author>
  <license>MIT</license>
  <homepage>https://github.com/superniker/ibus-voice-xunfei</homepage>
  <engines>
    <engine>
      <name>voice-input</name>
      <longname>讯飞语音</longname>
      <description>F8 语音输入</description>
      <language>zh_CN</language>
      <license>MIT</license>
      <author>superniker</author>
      <icon>ibus-voice-input</icon>
      <rank>1</rank>
    </engine>
  </engines>
</component>
XMLEOF

# 9. 设置 systemd 用户服务（自动启动 daemon）
SERVICE_DIR="$HOME/.config/systemd/user"
mkdir -p "$SERVICE_DIR"
cat > "$SERVICE_DIR/ibus-voice-daemon.service" << SVCEOF
[Unit]
Description=讯飞语音守护进程
After=graphical-session.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 $INSTALL_DIR/voice-daemon.py
Restart=on-failure
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
SVCEOF

systemctl --user daemon-reload
systemctl --user enable ibus-voice-daemon.service
systemctl --user start ibus-voice-daemon.service

# 10. 重启 IBus
echo "重启 IBus..."
ibus restart 2>/dev/null || ibus-daemon -drx 2>/dev/null || true

echo ""
echo "=== 安装完成 ==="
echo ""
echo "1. 在 GNOME 设置 → 键盘 → 输入源中添加「讯飞语音」"
echo "2. 按 F8 开始录音"
echo "3. 确保已编辑 $CONFIG_DIR/config.json"
echo ""
echo "状态条会自动显示在屏幕底部"
