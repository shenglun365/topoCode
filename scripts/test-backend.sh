#!/bin/bash
# 测试 Python 后端
# 用法: ./scripts/test-backend.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "=== TopoOne Backend - 测试 ==="
echo ""

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装"
    exit 1
fi

echo "🐍 Python: $(python3 --version)"
echo ""

# 检查依赖
echo "📦 检查依赖..."
cd "$BACKEND_DIR"

if python3 -c "import zmq" 2>/dev/null; then
    echo "  ✅ pyzmq"
else
    echo "  ⚠️  pyzmq 未安装，安装中..."
    pip3 install pyzmq 2>/dev/null || pip install pyzmq 2>/dev/null
fi

if python3 -c "import tree_sitter" 2>/dev/null; then
    echo "  ✅ tree-sitter"
else
    echo "  ⚠️  tree-sitter 未安装 (可选)"
fi

echo ""

# 测试导入
echo "🧪 测试模块导入..."
cd "$BACKEND_DIR"

if python3 -c "from sqlite_ctx import SQLiteContext; print('  ✅ sqlite_ctx')" 2>/dev/null; then
    :
else
    echo "  ❌ sqlite_ctx 导入失败"
    python3 -c "from sqlite_ctx import SQLiteContext" 2>&1 | head -5
fi

if python3 -c "from zmq_server import ZMQServer; print('  ✅ zmq_server')" 2>/dev/null; then
    :
else
    echo "  ❌ zmq_server 导入失败"
    python3 -c "from zmq_server import ZMQServer" 2>&1 | head -5
fi

if python3 -c "from core_service import register_project_methods; print('  ✅ core_service')" 2>/dev/null; then
    :
else
    echo "  ❌ core_service 导入失败"
    python3 -c "from core_service import register_project_methods" 2>&1 | head -5
fi

echo ""

# 测试数据库初始化
echo "🗄️  测试数据库初始化..."
TEMP_DB=$(mktemp)

if python3 -c "
import sys
sys.path.insert(0, '$BACKEND_DIR')
from sqlite_ctx import SQLiteContext
db = SQLiteContext('$TEMP_DB')
print('  ✅ 数据库初始化成功')
tables = db.fetchall(\"SELECT name FROM sqlite_master WHERE type='table'\")
print(f'  📊 创建了 {len(tables)} 张表')
for t in tables:
    print(f'    - {t[\"name\"]}')
db.close()
" 2>/dev/null; then
    rm -f "$TEMP_DB"
else
    echo "  ❌ 数据库初始化失败"
    rm -f "$TEMP_DB"
fi

echo ""

# 启动后端 (后台)
echo "🚀 启动后端 (5 秒后自动停止)..."
cd "$BACKEND_DIR"

# 使用临时数据库
TEST_DB=$(mktemp)
timeout 5 python3 main.py "$TEST_DB" 2>&1 | head -20 || true
rm -f "$TEST_DB"

echo ""
echo "✅ 后端测试完成!"
echo ""
echo "💡 手动启动后端:"
echo "  cd $BACKEND_DIR"
echo "  python3 main.py"
