"""Architect 独立服务入口（M13，chat/docs 同款独立进程 :3470）。

用法: python -m topoone_app_architect --port 3470 --data-dir /path/to/data
      [--kb-url http://127.0.0.1:3459] [--mcp-url http://127.0.0.1:3460]
"""

import argparse
import logging
import os
import signal

# M13: 包已 editable 安装，topoone.* 全局可见，无需 sys.path 引导。
# 保留 _project_dir 仅用于加载项目根 .env（env 变量）。
_project_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger(__name__)


def _load_env():
    """加载项目根 .env（env 变量默认值，setdefault 不覆盖已有）。"""
    env_path = os.path.join(_project_dir, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                    key, val = line.split('=', 1)
                    os.environ.setdefault(key.strip(), val.strip())


_load_env()


def _pidfile_path(data_dir: str) -> str:
    return os.path.join(data_dir or os.path.expanduser("~/.topocode"),
                        "architect.pid")


def _cmdline_of(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return f.read().decode("utf-8", "replace").replace("\0", " ")
    except (OSError, ValueError):
        return ""


def _ensure_single_instance(data_dir: str) -> None:
    """实例互斥 pidfile（3470 端口冲突事故根治, 通用逻辑非特判）。

    启动前检测既有实例并按其监管形态处置:
    - 孤儿(ppid=1, 无监管者) → 自动接管: SIGTERM 等退(超时 SIGKILL)——
      supervisor 死亡后的遗留实例不应阻塞监管树恢复;
    - 被监管实例(ppid 存活) → 拒绝双开并报明 pid——手动实例不得越权
      顶掉监管树的正主(防端口竞争复发);
    - 无实例 → 直接放行。启动后写自己的 pid 供下轮判定。
    """
    pf = _pidfile_path(data_dir)
    try:
        old = int(open(pf).read().strip())
    except (OSError, ValueError):
        old = 0
    if old and old != os.getpid() and os.path.exists(f"/proc/{old}"):
        ppid = 0
        try:
            with open(f"/proc/{old}/stat") as f:
                ppid = int(f.read().split(") ", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            pass
        if "topoone_app_architect" not in _cmdline_of(old):
            logger.warning("[architect] pidfile %s 指向非 architect 进程 "
                           "(pid=%s), 覆盖登记", pf, old)
        elif ppid == 1:
            import time as _t
            logger.warning("[architect] 检测到孤儿实例 pid=%s, 自动接管"
                           "(SIGTERM)", old)
            os.kill(old, signal.SIGTERM)
            for _ in range(100):
                if not os.path.exists(f"/proc/{old}"):
                    break
                _t.sleep(0.1)
            else:
                logger.warning("[architect] 孤儿 pid=%s 未退, SIGKILL", old)
                try:
                    os.kill(old, signal.SIGKILL)
                except OSError:
                    pass
        else:
            raise SystemExit(
                f"[architect] 实例已在运行且受监管: pid={old} "
                f"(pidfile={pf})——如需重启请先停监管者(supervisor/终端), "
                "勿手动双开(3470 端口竞争事故见运维记录)")
    os.makedirs(os.path.dirname(pf), exist_ok=True)
    with open(pf, "w") as f:
        f.write(str(os.getpid()))
    logger.info("[architect] pidfile 登记 pid=%s → %s", os.getpid(), pf)


def main():
    parser = argparse.ArgumentParser(description="TopoOne Architect Service")
    parser.add_argument("--port", type=int, default=3470, help="HTTP port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="HTTP host")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory")
    parser.add_argument("--kb-url", type=str, default=None, help="KB data_api base URL")
    parser.add_argument("--mcp-url", type=str, default=None, help="MCP server base URL")
    args = parser.parse_args()

    _ensure_single_instance(args.data_dir or "")

    if args.kb_url:
        os.environ.setdefault("KB_BASE_URL", args.kb_url)
    if args.mcp_url:
        os.environ.setdefault("MCP_BASE_URL", args.mcp_url)

    import uvicorn
    from topoone_app_architect.server import build_app, default_cors
    # 让 architect 应用模块的 INFO 级日志可见(默认根 logger 只输出 WARNING+，
    # 会吞掉语义资产提取等关键诊断的 collect_context/extract_scope 明细)。
    _log_level = os.environ.get("ARCH_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, _log_level, logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    for _name in ("arch_routes", "arch_routes.semantic_assets", "agent.tools.req_agent",
                  "kb_gateway", "arch_routes.project", "common", "agent.execution.exec_bridge"):
        logging.getLogger(_name).setLevel(getattr(logging, _log_level, logging.INFO))
    logger.info("Architect 日志级别: %s (可用 ARCH_LOG_LEVEL 覆盖)", _log_level)
    # cross-origin: dev/web via vite, and reports 3456 (if any reverse proxy kept)
    app = build_app(data_dir=args.data_dir, cors_origins=default_cors())

    logger.info(f"Architect server starting on http://{args.host}:{args.port}")

    should_exit = False

    def handle_sigterm(signum, frame):
        nonlocal should_exit
        logger.info("Received SIGTERM, shutting down architect...")
        should_exit = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    from topoone.http_logging import install_heartbeat_filter
    install_heartbeat_filter()

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
