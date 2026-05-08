#!/bin/bash
# 测试打包后的 Electron 应用
# 用法: ./scripts/test-pack.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
RELEASE_DIR="$PROJECT_DIR/release/linux-unpacked"

echo "=== TopoOne UI - 打包测试 ==="
echo ""

# 检查打包输出
if [ ! -d "$RELEASE_DIR" ]; then
    echo "❌ release/linux-unpacked 不存在，请先运行 npm run package"
    exit 1
fi

echo "📦 打包内容:"
echo "  主程序: $(ls -lh $RELEASE_DIR/topoone-ui | awk '{print $5}')"
echo "  app.asar: $(ls -lh $RELEASE_DIR/resources/app.asar | awk '{print $5}')"
echo ""

# 检查文件结构
echo "📁 目录结构:"
find $RELEASE_DIR -maxdepth 2 -type f -name "*.js" -o -name "*.json" -o -name "*.pak" | head -20 | sed 's/^/  /'
echo ""

# 检查 package.json
echo "📋 应用元数据:"
node -e "const p = require('$RELEASE_DIR/resources/app.asar/package.json'); console.log('  name:', p.name); console.log('  version:', p.version); console.log('  main:', p.main);" 2>/dev/null || echo "  (无法读取 asar 中的 package.json)"
echo ""

# 尝试启动 (无头模式)
echo "🚀 尝试启动 (无头模式)..."
if [ -z "$DISPLAY" ]; then
    echo "  ⚠️  没有显示服务器，使用 xvfb-run 或设置 DISPLAY"
    echo ""
    echo "💡 在有显示器的 Linux 上测试:"
    echo "  cd $RELEASE_DIR"
    echo "  ./topoone-ui --no-sandbox"
else
    timeout 3 $RELEASE_DIR/topoone-ui --no-sandbox --disable-gpu 2>&1 || true
fi

echo ""
echo "✅ 打包测试完成!"
echo ""
echo "📊 打包统计:"
du -sh $RELEASE_DIR/
echo ""
echo "🎯 下一步:"
echo "  - Linux: 运行 ./scripts/test-pack.sh"
echo "  - Windows: npm run dist:win (需要 Windows 环境或 Wine)"
echo "  - macOS: npm run dist:mac (需要 macOS 环境)"
