#!/usr/bin/env bash
# 前端 dev 分支守护环(3470/5176 韧性裁决): vite 瞬时死亡(任意来源
# SIGTERM/崩溃)自动复活——concurrently 不具备分支重启能力, 半死树
# (壳存活+分支残缺)曾致前端 5176 不可访问且无自愈路径。
#
# 语义组合(与 concurrently --kill-others 配套):
# - 瞬时死亡 → 1s 后重启(环进程存活, 不触发 kill-others);
# - 守护环自身被杀/致命故障 → 分支退出 → kill-others 全树干净退出;
# - 全树收尾(Ctrl+C/kill-others TERM) → trap 完整收尸(杀当前 npm 子进程,
#   不留孤儿)。
#
# 用法: dev-watch.sh <app>(workspace 名 @topo/app-<app>) [额外 npm 参数...]
set -um
app="$1"; shift
pid=""

term() {
  # 杀进程组(set -m: npm 独立成组, vite 是其孙进程)——只杀 npm 包装会留
  # vite 孤儿继续占端口(实测), 整组收尸才是完整退出
  [ -n "$pid" ] && kill -- -"$pid" 2>/dev/null
  wait "$pid" 2>/dev/null
  exit 0
}
trap term TERM INT

while true; do
  npm run dev -w "@topo/app-$app" "$@" &
  pid=$!
  wait "$pid"
  code=$?
  echo "[dev-watch] app-$app exited code=$code $(date '+%F %T') — restart in 1s"
  sleep 1
done
