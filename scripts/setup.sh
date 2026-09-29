#!/bin/bash
# setup.sh — 一键环境安装（Monorepo 终态，M14）
# 步骤：创建/复用 .venv → pip install -e 核心 + 4 子项目后端 → npm install（workspaces）→ 输出后续指引
# 用法: ./scripts/setup.sh  （或 npm run setup）
# 依赖: python >= 3.10（建议 pyenv/venv）、node >= 20、npm

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "==> TopoCode 环境安装"
echo "    项目根: $PROJECT_DIR"

# ── 1. Python 虚拟环境（创建/复用 .venv）──────────────────────────────
if [ ! -d ".venv" ]; then
    echo "==> 创建 .venv（python3 -m venv）..."
    python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "    使用 Python: $(python --version 2>&1)"
pip install --upgrade pip >/dev/null

# ── 2. Python 包（editable：核心 + 4 子项目后端）─────────────────────
echo "==> pip install -e（核心 + 子项目后端）..."
pip install -e packages/core \
            -e apps/workbench \
            -e apps/docs \
            -e apps/workbench/chat_service \
            -e apps/architect

# ── 3. 前端 workspaces（npm install）──────────────────────────────────
echo "==> npm install（workspaces）..."
npm install

# ── 4. 后续指引 ───────────────────────────────────────────────────────
echo ""
echo "==> 安装完成！后续命令："
echo "    激活环境:      source .venv/bin/activate"
echo "    开发（全栈）:  npm run dev          # core + workbench + docs + chat + architect"
echo "    仅后端服务:    npm run serve        # supervisor 拉起 9 进程（:3456）"
echo "    构建:          npm run build        # core bundle + portal + 4 app"
echo "    测试:          npm run test         # pytest(core+apps) + vitest(workbench+web-core)"
echo "    状态:          npm run status"
echo ""
echo "    浏览器访问:    http://localhost:3456/  （首次运行会生成 token，见终端输出）"
