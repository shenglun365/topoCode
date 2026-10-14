#!/bin/bash
# topo serve — 后端服务集统一启动（supervisor 唯一 owner，P0）
# 用法: ./scripts/serve.sh [--data-dir DIR] [--http-port PORT] [--http-host HOST] [background|foreground]
#
# 默认前台运行；传 background 则后台运行并输出日志到 ~/.topocode/logs/serve.log
# 关闭: 传 background 后可用 ./scripts/serve.sh stop（读 PID 文件 SIGTERM）

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

DATA_DIR="${TOPO_DATA_DIR:-$HOME/.topocode}"
HTTP_PORT="${TOPO_HTTP_PORT:-3456}"
HTTP_HOST="${TOPO_HTTP_HOST:-0.0.0.0}"
MODE="${1:-foreground}"

if [ "$MODE" = "stop" ]; then
    PIDFILE="$DATA_DIR/topo-serve.pid"
    if [ -f "$PIDFILE" ]; then
        PID="$(cat "$PIDFILE")"
        echo "Stopping topo serve (pid=$PID)..."
        kill -TERM "$PID" 2>/dev/null || true
        for i in $(seq 1 10); do
            [ -f "$PIDFILE" ] || break
            sleep 1
        done
        [ -f "$PIDFILE" ] && echo "pidfile still present (process may need more time)" || echo "Stopped."
    else
        echo "topo serve not running (no pidfile at $PIDFILE)"
    fi
    exit 0
fi

PYTHON="${TOPO_PYTHON:-python3}"
cd "$PROJECT_DIR"

case "$MODE" in
    background)
        mkdir -p "$DATA_DIR/logs"
        nohup "$PYTHON" -m topoone.supervisor.cli serve \
            --data-dir "$DATA_DIR" \
            --http-port "$HTTP_PORT" \
            --http-host "$HTTP_HOST" \
            >> "$DATA_DIR/logs/serve.log" 2>&1 &
        echo "topo serve started in background (pid=$!)"
        echo "  data-dir: $DATA_DIR"
        echo "  http:     http://$HTTP_HOST:$HTTP_PORT"
        echo "  log:      $DATA_DIR/logs/serve.log"
        echo "stop:      $0 stop"
        ;;
    *)
        exec "$PYTHON" -m topoone.supervisor.cli serve \
            --data-dir "$DATA_DIR" \
            --http-port "$HTTP_PORT" \
            --http-host "$HTTP_HOST"
        ;;
esac
