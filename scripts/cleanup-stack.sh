#!/bin/bash
# topo cleanup — 清理 topoOne 开发栈的残留进程。
#
# 适用场景：npm run dev 退出后，backend 子服务进程残留（可能 defunct/孤儿），
# 端口（3456/3459/3482/5671/5684 等）被占，导致下次 npm run dev 时
# vite 一直报 connect ECONNREFUSED 127.0.0.1:3456，后端起不来。
#
# 用法:
#   ./scripts/cleanup-stack.sh          # SIGTERM 优雅终止
#   ./scripts/cleanup-stack.sh --force  # 直接 SIGKILL（进程不响应 TERM 时用）
#
# 说明: 脚本会终止本项目相关的 supervisor / backend 子服务 / vite / npm run dev 进程，
#       不影响 codegraph 等无关进程。

set -u

DATA_DIR="${TOPO_DATA_DIR:-$HOME/.topocode}"
PIDFILE="$DATA_DIR/topo-serve.pid"
SCRIPT_PATH="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"

FORCE=""
if [ "${1:-}" = "--force" ]; then
    FORCE=1
fi

echo "== topo 残留进程清理 ($(date '+%H:%M:%S')) =="

# 1. 按 pidfile 停 supervisor（优雅），并删除残留 pidfile
if [ -f "$PIDFILE" ]; then
    PID="$(cat "$PIDFILE" 2>/dev/null || true)"
    if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
        echo "  pidfile supervisor pid=$PID → SIGTERM"
        kill -TERM "$PID" 2>/dev/null || true
    else
        echo "  pidfile 存在但进程已不在 → 删除残留 pidfile"
    fi
    rm -f "$PIDFILE"
fi

# 2. 收集项目相关进程
#    - cmdline 含本项目路径 topoCodeProj/topoOne-ui
#    - 或孤儿 supervisor（cmdline 为 topoone.supervisor.cli serve，路径可能不完整）
pids="$(pgrep -f "topoCodeProj/topoOne-ui" 2>/dev/null || true)"
pids="$pids $(pgrep -f "topoone.supervisor.cli serve" 2>/dev/null || true)"
pids="$(echo "$pids" | tr ' ' '\n' | grep -E '^[0-9]+$' | sort -u)"

found=0
for pid in $pids; do
    [ "$pid" = "$$" ] && continue
    cmd="$(ps -o cmd= -p "$pid" 2>/dev/null)" || continue
    case "$cmd" in
        *codegraph*) continue ;;      # codegraph MCP 索引器，不动
        *"$SCRIPT_PATH"*) continue ;; # 脚本自身
    esac
    found=1
    if [ -n "$FORCE" ]; then
        kill -9 "$pid" 2>/dev/null && echo "  SIGKILL $pid  $(echo "$cmd" | cut -c1-90)"
    else
        kill -TERM "$pid" 2>/dev/null && echo "  SIGTERM $pid  $(echo "$cmd" | cut -c1-90)"
    fi
done
[ "$found" = "0" ] && echo "  未发现残留进程"

echo "  等待 2s..."
sleep 2

# 3. --force 模式补杀仍存活的
if [ -n "$FORCE" ]; then
    for pid in $pids; do
        [ "$pid" = "$$" ] && continue
        if kill -0 "$pid" 2>/dev/null; then
            cmd="$(ps -o cmd= -p "$pid" 2>/dev/null)"
            case "$cmd" in
                *codegraph*) continue ;;
                *"$SCRIPT_PATH"*) continue ;;
            esac
            kill -9 "$pid" 2>/dev/null && echo "  补杀 $pid"
        fi
    done
fi

# 4. 端口检查
echo "== 端口检查 =="
PORTS="3456 3458 3459 3470 3481 3482 3483 3484 5173 5174 5671 5681 5682 5683 5684"
blocked=0
for p in $PORTS; do
    line="$(ss -tlnp 2>/dev/null | grep -E "[:.]$p " | head -1)"
    if [ -n "$line" ]; then
        blocked=1
        echo "  端口 $p 仍被占用: $(echo "$line" | sed 's/.*users:((//; s/)).*//' | cut -c1-80)"
    fi
done
[ "$blocked" = "0" ] && echo "  目标端口全部空闲 ✔"

echo "== 清理完成 =="