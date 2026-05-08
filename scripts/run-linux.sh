#!/bin/bash
# TopoOne UI - Linux 运行脚本
# 用法: ./scripts/run-linux.sh [x11|vnc|xvfb]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RELEASE_DIR="$PROJECT_DIR/release/linux-unpacked"

if [ ! -f "$RELEASE_DIR/topoone-ui" ]; then
    echo "❌ 未找到打包文件，请先运行: npm run package"
    exit 1
fi

MODE="${1:-auto}"

case "$MODE" in
    x11)
        echo "🖥️  X11 模式 - 需要 X Server"
        if [ -z "$DISPLAY" ]; then
            echo "❌ DISPLAY 未设置，请启用 X11 转发或使用 MobaXterm"
            echo ""
            echo "SecureCRT 配置:"
            echo "  Session Options → X11 → Enable X11 forwarding"
            echo ""
            echo "或使用 MobaXterm (默认开启 X11)"
            exit 1
        fi
        echo "  DISPLAY=$DISPLAY"
        exec "$RELEASE_DIR/topoone-ui" --no-sandbox --disable-gpu
        ;;
    
    vnc)
        echo "🖥️  VNC 模式"
        VNC_DISPLAY="${VNC_DISPLAY:-:1}"
        export DISPLAY="$VNC_DISPLAY"
        echo "  DISPLAY=$DISPLAY"
        
        if ! pgrep -f "vnc" > /dev/null; then
            echo "⚠️  VNC 未运行，启动中..."
            vncserver $VNC_DISPLAY -geometry 1920x1080 2>/dev/null || {
                echo "❌ VNC 启动失败，请先安装: sudo apt install tightvncserver"
                exit 1
            }
        fi
        
        exec "$RELEASE_DIR/topoone-ui" --no-sandbox --disable-gpu
        ;;
    
    xvfb)
        echo "🖥️  虚拟帧缓冲模式 (无头测试)"
        sudo apt install -y xvfb 2>/dev/null || {
            echo "❌ xvfb 未安装，请运行: sudo apt install xvfb"
            exit 1
        }
        exec xvfb-run --auto-servernum "$RELEASE_DIR/topoone-ui" --no-sandbox --disable-gpu
        ;;
    
    auto)
        echo "🔍 自动检测显示模式..."
        
        if [ -n "$DISPLAY" ]; then
            echo "  ✅ 检测到 DISPLAY=$DISPLAY"
            echo "  运行: $RELEASE_DIR/topoone-ui"
            exec "$RELEASE_DIR/topoone-ui" --no-sandbox --disable-gpu
        elif command -v xvfb-run > /dev/null; then
            echo "  ✅ 使用 xvfb-run (虚拟帧缓冲)"
            exec xvfb-run --auto-servernum "$RELEASE_DIR/topoone-ui" --no-sandbox --disable-gpu
        else
            echo "❌ 无显示环境"
            echo ""
            echo "可用方案:"
            echo "  1. X11 转发:  ./scripts/run-linux.sh x11"
            echo "     (SecureCRT: Session Options → X11 → Enable)"
            echo ""
            echo "  2. VNC 远程:  ./scripts/run-linux.sh vnc"
            echo "     (需安装: sudo apt install tightvncserver)"
            echo ""
            echo "  3. 虚拟帧缓冲: ./scripts/run-linux.sh xvfb"
            echo "     (需安装: sudo apt install xvfb)"
            exit 1
        fi
        ;;
    
    *)
        echo "用法: $0 [x11|vnc|xvfb|auto]"
        exit 1
        ;;
esac
