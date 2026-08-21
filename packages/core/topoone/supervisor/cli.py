"""topo CLI 入口（`topo` 命令）。

入口: python -m topoone.supervisor.cli  （或 python -m topoone.supervisor）

命令结构:
  topo init/uninit/status            — 项目初始化
  topo community/arch/diff/quality   — 架构查询
  topo serve                         — 启动后端服务集（supervisor 唯一 owner，manifest 驱动）
  topo status/doctor                 — 服务健康 / 进程拓扑诊断
  topo import/analyze/tasks/export/verify/settings — 经 daemon /api/rpc
  topo session                       — AI 会话追踪 (待实现)
  topo install/uninstall/detect      — Agent Installer
  topo tui                           — 终端界面（Textual）
"""

import argparse
import os
import sys
from pathlib import Path

# 仓库根（topoone/supervisor/cli.py → parents[4]）
_REPO_ROOT = Path(__file__).resolve().parents[4]
_PARENT = _REPO_ROOT  # 别名：后续路径拼接以仓库根为基准
# M14: topoone/plugins 均经 editable 安装全局可导入，无需 sys.path 引导


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topocode",
        description="topocode — 代码架构认知工具。提升人的架构认知水平。",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # === 项目 ===
    sub.add_parser("init", help="初始化项目分析")
    sub.add_parser("uninit", help="清除分析数据")

    # === 架构查询 ===
    p_comm = sub.add_parser("community", help="查看社区结构")
    p_comm.add_argument("--type", choices=["INCLUDE", "CALL"], default="INCLUDE")
    p_comm.add_argument("--level", type=int, default=0)
    p_comm.add_argument("--json", action="store_true")

    p_arch = sub.add_parser("arch", help="架构操作")
    p_arch_subs = p_arch.add_subparsers(dest="arch_action")

    p_arch_analyze = p_arch_subs.add_parser("analyze", help="批量 LLM 分析社区")
    p_arch_analyze.add_argument("--all", action="store_true", help="分析全部社区")
    p_arch_analyze.add_argument("--level", default="L0")
    p_arch_analyze.add_argument("--edge-type", default="INCLUDE", choices=["INCLUDE", "CALL"])
    p_arch_analyze.add_argument("--output", default="", help="输出目录")
    p_arch_analyze.add_argument("--model", default="", help="LLM 模型 ID")

    p_arch_overview = p_arch_subs.add_parser("overview", help="生成架构概览")
    p_arch_overview.add_argument("--output", default="")

    p_arch_export = p_arch_subs.add_parser("export", help="导出架构文档")
    p_arch_export.add_argument("--format", default="md", choices=["md", "json", "html"])
    p_arch_export.add_argument("--output", default="")

    p_arch_list = p_arch_subs.add_parser("list", help="列出社区结构")
    p_arch_list.add_argument("--level", default="L0")
    p_arch_list.add_argument("--json", action="store_true")

    p_diff = sub.add_parser("diff", help="版本差异")
    p_diff_subs = p_diff.add_subparsers(dest="diff_action")
    p_diff_snapshots = p_diff_subs.add_parser("snapshots", help="列出可用快照")
    p_diff_compare = p_diff_subs.add_parser("compare", help="对比两个版本")
    p_diff_compare.add_argument("from_version", nargs="?", default="")
    p_diff_compare.add_argument("to_version", nargs="?", default="")
    p_diff_compare.add_argument("--output", default="")

    p_track = sub.add_parser("track", help="架构变更追踪")
    p_track_subs = p_track.add_subparsers(dest="track_action")
    p_track_start = p_track_subs.add_parser("start", help="开始追踪")
    p_track_start.add_argument("--tag", default="", help="版本标签")
    p_track_stop = p_track_subs.add_parser("stop", help="结束追踪")
    p_track_stop.add_argument("--output", default="")
    p_track_list = p_track_subs.add_parser("list", help="历史追踪记录")
    p_track_list.add_argument("--limit", type=int, default=10)
    p_track_status = p_track_subs.add_parser("status", help="当前追踪状态")

    p_qual = sub.add_parser("quality", help="质量检查")
    p_qual.add_argument("--focus", default="all")
    p_qual.add_argument("--json", action="store_true")

    # === Agent Installer ===
    p_install = sub.add_parser("install", help="安装到 AI Coding Agent 配置")
    p_install.add_argument("agents", nargs="*", help="Agent ID (claude/opencode/codex/cursor/copilot/gemini/windsurf)")
    p_install.add_argument("--global", dest="global_", action="store_true", help="全局安装")

    p_uninstall = sub.add_parser("uninstall", help="移除 Agent 配置")
    p_uninstall.add_argument("agents", nargs="*", help="Agent ID")
    p_uninstall.add_argument("--global", dest="global_", action="store_true")

    sub.add_parser("detect", help="检测已安装的 AI Agents")

    # === Session ===
    p_session = sub.add_parser("session", help="AI 会话追踪")
    p_session.add_argument("action", nargs="?", default="list", choices=["list", "summary"])

    # === 进程治理 (P0) ===
    p_serve = sub.add_parser("serve", help="启动后端服务集（supervisor 唯一 owner）")
    p_serve.add_argument("--http-port", type=int, default=3456, help="HTTP 端口 (gateway)")
    p_serve.add_argument("--http-host", type=str, default="0.0.0.0", help="HTTP 绑定地址（默认 0.0.0.0 允许局域网访问）")
    p_serve.add_argument("--data-dir", type=str, default=None, help="数据目录")

    p_status = sub.add_parser("status", help="服务健康状态")
    p_status.add_argument("--data-dir", type=str, default=None, help="数据目录")

    p_doctor = sub.add_parser("doctor", help="诊断进程拓扑/端口/数据目录")
    p_doctor.add_argument("--data-dir", type=str, default=None, help="数据目录")

    # === P5 新增命令（经 /api/rpc 连 daemon） ===
    p_import = sub.add_parser("import", help="导入项目（经 daemon /api/rpc）")
    p_import.add_argument("path", help="项目路径")
    p_import.add_argument("--http-port", type=int, default=3456)
    p_import.add_argument("--data-dir", type=str, default=None)
    p_import.add_argument("--json", action="store_true")

    p_analyze = sub.add_parser("analyze", help="运行分析任务（经 daemon /api/rpc）")
    p_analyze.add_argument("path", help="项目路径")
    p_analyze.add_argument("--task", default="", help="任务名（默认取最近任务）")
    p_analyze.add_argument("--http-port", type=int, default=3456)
    p_analyze.add_argument("--data-dir", type=str, default=None)
    p_analyze.add_argument("--json", action="store_true")

    p_tasks = sub.add_parser("tasks", help="列出项目任务（经 daemon /api/rpc）")
    p_tasks.add_argument("path", help="项目路径")
    p_tasks.add_argument("--http-port", type=int, default=3456)
    p_tasks.add_argument("--data-dir", type=str, default=None)
    p_tasks.add_argument("--json", action="store_true")

    p_export = sub.add_parser("export", help="导出项目分析数据（经 daemon /api/rpc）")
    p_export.add_argument("path", help="项目路径")
    p_export.add_argument("--task", default="", help="任务名（默认取最近任务）")
    p_export.add_argument("--http-port", type=int, default=3456)
    p_export.add_argument("--data-dir", type=str, default=None)
    p_export.add_argument("--json", action="store_true")

    p_verify = sub.add_parser("verify", help="校验项目文件（经 daemon /api/rpc）")
    p_verify.add_argument("path", help="项目路径")
    p_verify.add_argument("--http-port", type=int, default=3456)
    p_verify.add_argument("--data-dir", type=str, default=None)
    p_verify.add_argument("--json", action="store_true")

    p_settings = sub.add_parser("settings", help="读取/设置配置（经 daemon /api/rpc）")
    p_settings.add_argument("--http-port", type=int, default=3456)
    p_settings.add_argument("--data-dir", type=str, default=None)
    p_settings.add_argument("--json", action="store_true")
    p_settings.add_argument("--get-models", action="store_true", help="列出模型")
    p_settings.add_argument("--get-agents", action="store_true", help="列出 agent")
    p_settings.add_argument("--get-skills", action="store_true", help="列出技能")

    # === P6 TUI ===
    p_tui = sub.add_parser("tui", help="启动终端界面（Python Textual）")
    p_tui.add_argument("--http-port", type=int, default=3456)
    p_tui.add_argument("--data-dir", type=str, default=None)

    parser.add_argument("--project-root", default=".", help="项目根目录")
    parser.add_argument("--data-dir", default=None, help="数据目录（默认 ~/.topocode）")
    parser.add_argument("--log-level", default="INFO", help="日志级别")

    return parser


def main():
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return

    import logging
    logging.basicConfig(level=getattr(logging, args.log_level.upper(), logging.INFO))

    cmd = args.command

    if cmd == "serve":
        _cmd_serve(args)

    elif cmd == "status":
        _cmd_status(args)

    elif cmd == "doctor":
        _cmd_doctor(args)

    elif cmd == "tui":
        _cmd_tui(args)

    elif cmd in ("import", "analyze", "tasks", "export", "verify", "settings"):
        _cmd_daemon(args)

    elif cmd in ("install", "uninstall", "detect"):
        _cmd_installer(args)

    elif cmd in ("community", "arch", "diff", "quality", "track"):
        _cmd_query(args)
        if cmd == "track":
            _cmd_track(args)
        elif cmd == "arch":
            _cmd_arch(args)
        elif cmd == "diff" and hasattr(args, "diff_action") and args.diff_action:
            _cmd_diff(args)

    elif cmd in ("init", "uninit"):
        _cmd_project(args)

    elif cmd == "session":
        _cmd_session(args)


def _cmd_tui(args):
    """`topo tui` — 启动 Python Textual 终端界面（P6）。"""
    try:
        import textual  # noqa: F401
    except ImportError:
        print("textual not installed. Run: pip install textual", file=sys.stderr)
        sys.exit(1)
    from topoone.supervisor.tui import main as _tui_main
    # 复用 serve 的 data-dir 默认值
    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    sys.argv = ["tui", "--data-dir", data_dir, "--http-port", str(args.http_port)]
    _tui_main()


def _cmd_installer(args):
    """Agent Installer 命令。"""
    import importlib.util
    # Load installer plugin directly（M07: installer 迁至 topoone/plugins/installer）
    installer_path = os.path.join(_PARENT, "packages", "core", "topoone", "plugins", "installer", "plugin_entry.py")
    try:
        spec = importlib.util.spec_from_file_location("installer", installer_path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
    except Exception as e:
        print(f"Failed to load installer plugin: {e}")

    if args.command == "detect":
        installer._cmd_detect()
    elif args.command == "install":
        installer._cmd_install(args.agents, args.global_)
    elif args.command == "uninstall":
        installer._cmd_uninstall(args.agents, args.global_)


# ═══════════════════════════════════════════════════════════════
# 进程治理（P0）— `topo serve` 唯一 owner
# ═══════════════════════════════════════════════════════════════

# 固定核心 + 生态进程（非 manifest 驱动）。
# M07: doc/chat/architect 改由 apps/*/manifest.toml（kind=service）动态注册（见 _manifest_apps）。
# M08: mcp/runner 迁入 topoone.plugins，入口 `python -m topoone.plugins.{mcp,runner}`（仍固定表）。
_FIXED_SERVICES = {
    "kb":     {"health": "/health", "port_env": "DATA_API_PORT", "default_port": 3459},
    "gateway": {"health": "/health", "port_env": None, "default_port": 3456},
    "llm":    {"health": "/health", "port_env": "LLM_SERVICE_PORT", "default_port": 3484, "pub_env": "LLM_PUB_PORT", "pub_port": 5682},
    "agent":  {"health": "/health", "port_env": "AGENT_SERVICE_PORT", "default_port": 3482, "pub_env": "AGENT_PUB_PORT", "pub_port": 5684},
    "mcp":    {"health": "/health", "port_env": "MCP_SERVER_PORT", "default_port": 3460},
    "runner": {"health": "/health", "port_env": "CODING_AGENT_RUNNER_PORT", "default_port": 3458},
}


def _manifest_apps() -> dict:
    """kind=service 的 app manifest（doc/chat/architect 等）→ {name: AppManifest}。"""
    from topoone.manifest import discover_apps
    try:
        apps = discover_apps(str(_REPO_ROOT))
    except Exception as e:
        print(f"[serve] WARNING: manifest discovery failed: {e}", file=sys.stderr)
        return {}
    return {n: m for n, m in sorted(apps.items()) if m.kind == "service" and m.port}


def _all_service_names() -> list:
    """统一进程注册表：固定核心/生态 + manifest service app（保持 kb→gateway→…→runner 顺序）。"""
    manifest = _manifest_apps()
    ordered = []
    for name in ("kb", "gateway", "llm", "agent", "docs", "chat", "architect", "mcp", "runner"):
        if name in _FIXED_SERVICES or name in manifest:
            ordered.append(name)
    # 兜底：manifest 中新增的 service app（未在固定顺序内）
    for name in manifest:
        if name not in ordered:
            ordered.append(name)
    return ordered


def _service_meta(name: str):
    """取服务的元数据（固定表或 manifest）。manifest app 返回其 AppManifest。"""
    if name in _FIXED_SERVICES:
        return _FIXED_SERVICES[name]
    return _manifest_apps().get(name)


def _service_port(name: str) -> int:
    """取服务端口：固定表（env 覆盖优先）/ manifest app（manifest port）。"""
    meta = _service_meta(name)
    if meta is None:
        raise KeyError(f"unknown service: {name}")
    if isinstance(meta, dict):  # 固定核心/生态
        env = meta.get("port_env")
        if env and os.environ.get(env):
            return int(os.environ[env])
        return meta["default_port"]
    return meta.port  # manifest app


def _health_url(name: str) -> str:
    return f"http://127.0.0.1:{_service_port(name)}/health"


def _make_cmd(name: str, data_dir: str, http_port: int, http_host: str) -> list[str]:
    """构造固定核心/生态进程启动命令（doc/chat/architect 改由 _make_manifest_cmd）"""
    meta = _FIXED_SERVICES[name]
    if name == "kb":
        # core 进程：ZMQ + data-api(3459) + ingest；不自行 spawn reports/architect/mcp
        # M03: 入口迁至核心包（python -m topoone.engine）
        return [sys.executable, "-m", "topoone.engine", data_dir,
                "--http-port", str(http_port), "--http-host", http_host, "--no-spawn"]
    if name == "llm":
        # M04: llm 服务入口迁至核心包（python -m topoone.llm）
        return [sys.executable, "-m", "topoone.llm", "--data-dir", data_dir,
                "--port", str(_service_port(name)),
                "--pub-port", str(int(os.environ.get(meta.get("pub_env"), str(meta.get("pub_port", 5682)))))]
    if name == "agent":
        # M05: agent 服务入口迁至核心包（python -m topoone.agent）
        return [sys.executable, "-m", "topoone.agent", "--data-dir", data_dir,
                "--port", str(_service_port(name)),
                "--pub-port", str(int(os.environ.get(meta.get("pub_env"), str(meta.get("pub_port", 5682)))))]
    if name == "gateway":
        # M06: gateway 入口迁至核心包（python -m topoone.gateway）
        return [sys.executable, "-m", "topoone.gateway",
                "--port", str(http_port), "--host", http_host,
                "--data-dir", data_dir, "--data-api-port", str(_service_port("kb"))]
    if name == "mcp":
        # M08: MCP Server 入口迁至核心包（python -m topoone.plugins.mcp），端口经 env 传递
        return [sys.executable, "-m", "topoone.plugins.mcp"]
    if name == "runner":
        # M08: Coding Agent Runner 入口迁至核心包（python -m topoone.plugins.runner）
        return [sys.executable, "-m", "topoone.plugins.runner"]
    raise KeyError(f"Unknown fixed service: {name}")


def _make_manifest_cmd(m, data_dir: str) -> list[str]:
    """构造 kind=service manifest app 启动命令（M07 manifest 驱动）。

    entry: `module:func` → `-m module`；脚本路径（仓库根相对）→ 直接路径。
    端口取自 manifest；统一追加 --host 127.0.0.1（doc/chat 默认即此，architect 需要）。
    architect 的 kb/mcp 核心 URL 经 env（KB_BASE_URL/MCP_BASE_URL）注入（见 _cmd_serve）。
    """
    if m.python_entry_is_module():
        mod = m.python_entry.split(":")[0]
        return [sys.executable, "-m", mod, "--data-dir", data_dir, "--port", str(m.port)]
    entry = os.path.join(str(_REPO_ROOT), m.python_entry)
    return [sys.executable, entry, "--data-dir", data_dir,
            "--port", str(m.port), "--host", "127.0.0.1"]


def _write_pidfile(data_dir: str) -> str:
    """写 PID 文件；若已存在且进程存活则拒绝启动。返回 pidfile 路径。"""
    pidfile = os.path.join(data_dir, "topo-serve.pid")
    if os.path.exists(pidfile):
        try:
            with open(pidfile) as f:
                old_pid = int(f.read().strip())
            os.kill(old_pid, 0)  # 存活则抛 ProcessLookupError
            print(f"[serve] already running (pid={old_pid}, pidfile={pidfile})")
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass
    with open(pidfile, "w") as f:
        f.write(str(os.getpid()))
    return pidfile


def _ensure_token(data_dir: str):
    """生成/复用 `~/.topocode/token`（D7：鉴权 token 默认自动生成）。"""
    token_path = os.path.join(data_dir, "token")
    if os.path.exists(token_path):
        with open(token_path) as f:
            existing = f.read().strip()
        if existing:
            return existing
    import secrets
    token = secrets.token_hex(32)
    with open(token_path, "w") as f:
        f.write(token)
    os.chmod(token_path, 0o600)
    print(f"[serve] token generated: {token_path}")
    return token


def _cmd_serve(args):
    """`topo serve` — supervisor 唯一 owner，拉起 5 进程服务集"""
    import signal as _sig

    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    os.makedirs(data_dir, exist_ok=True)
    pidfile = _write_pidfile(data_dir)
    token = _ensure_token(data_dir)

    from topoone.supervisor.supervisor import Supervisor
    sv = Supervisor()

    manifest = _manifest_apps()
    for name in _all_service_names():
        if name in manifest:
            # manifest 驱动的 service app（doc/chat/architect 等）
            env = {"TOPOCODE_DB_DIR": data_dir,
                   "KB_BASE_URL": f"http://127.0.0.1:{_service_port('kb')}",
                   "MCP_BASE_URL": f"http://127.0.0.1:{_service_port('mcp')}"}
            cmd = _make_manifest_cmd(manifest[name], data_dir)
        else:
            # 固定核心/生态进程
            if name == "kb":
                env = {"TOPO_MODE": "monolith",
                       "ZMQ_PUB_PORT": "5681",
                       "AGENT_API_URL": f"http://127.0.0.1:{_service_port('agent')}"}
            elif name == "llm":
                env = {"LLM_SERVICE_PORT": str(_service_port("llm")),
                       "LLM_PUB_PORT": str(int(os.environ.get("LLM_PUB_PORT", "5682")))}
            elif name == "agent":
                env = {"AGENT_SERVICE_PORT": str(_service_port("agent")),
                       "AGENT_PUB_PORT": str(int(os.environ.get("AGENT_PUB_PORT", "5684")))}
            elif name == "gateway":
                env = {"TOPOCODE_DB_DIR": data_dir}
            else:
                env = None
            cmd = _make_cmd(name, data_dir, args.http_port, args.http_host)
        sv.register(
            name,
            cmd,
            restart_limit=5,
            health_url=_health_url(name),
            env=env,
        )

    async def _run():
        await sv.start_all()
        print(f"[serve] started: {', '.join(_all_service_names())} (data_dir={data_dir}, http={args.http_host}:{args.http_port})", flush=True)
        host_hint = "0.0.0.0" if args.http_host in ("0.0.0.0", "") else args.http_host
        print(f"[serve] token: {token}", flush=True)
        print(f"[serve] 浏览器访问: http://<本机IP>:{args.http_port}/#token={token}", flush=True)
        print(f"[serve] (token 亦存于 {os.path.join(data_dir, 'token')}；绑定 {host_hint}，局域网可用本机 LAN IP 访问)", flush=True)

        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (_sig.SIGINT, _sig.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop_event.set)
            except (NotImplementedError, ValueError):
                _sig.signal(sig, lambda s, f: stop_event.set())
        await stop_event.wait()
        await sv.shutdown_all(timeout=5.0)
        if os.path.exists(pidfile):
            os.remove(pidfile)

    try:
        import asyncio
        asyncio.run(_run())
    finally:
        if os.path.exists(pidfile):
            os.remove(pidfile)


def _cmd_status(args):
    """`topo status` — 各服务健康探针"""
    import urllib.request

    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    pidfile = os.path.join(data_dir, "topo-serve.pid")
    serve_pid = None
    if os.path.exists(pidfile):
        try:
            serve_pid = int(open(pidfile).read().strip())
        except ValueError:
            serve_pid = None

    print(f"data_dir: {data_dir}")
    print(f"serve pid: {serve_pid or 'not running'}")
    print(f"{'service':<12} {'port':<6} {'status':<10} detail")
    print("-" * 50)
    all_ok = True
    for name in _all_service_names():
        port = _service_port(name)
        url = f"http://127.0.0.1:{port}/health"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                ok = 200 <= resp.status < 400
            print(f"{name:<12} {port:<6} {'OK' if ok else 'FAIL':<10} {resp.status}")
            all_ok = all_ok and ok
        except Exception as e:
            print(f"{name:<12} {port:<6} {'DOWN':<10} {e}")
            all_ok = False
    sys.exit(0 if all_ok else 1)


def _cmd_doctor(args):
    """`topo doctor` — 诊断进程拓扑/端口/数据目录"""
    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    print(f"data_dir: {data_dir}")
    print()

    # 1. spawn 路径核查
    print("[1] spawn 路径一致性")
    # M03: kb 入口迁至核心包 engine/app.py（python -m topoone.engine）
    main_py = os.path.join(_PARENT, "packages", "core", "topoone", "engine", "app.py")
    main_src = open(main_py).read()
    no_spawn_support = "--no-spawn" in main_src
    # app.py 保留 mcp spawn 是 Electron 兼容路径；`topo serve` 经 --no-spawn 由 supervisor 接管。
    # M06: gateway 入口迁至核心包 topoone/gateway/server.py（不再自行 spawn runner/mcp）
    web_server_py = os.path.join(_PARENT, "packages", "core", "topoone", "gateway", "server.py")
    if os.path.exists(web_server_py):
        web_src = open(web_server_py).read()
        web_spawn = "coding_agent_runner" in web_src and "create_subprocess" in web_src
    else:
        web_spawn = False
    print(f"  engine/app.py --no-spawn 支持: {'YES (topo serve 经此接管)' if no_spawn_support else 'NO (缺失)'}")
    print(f"  web_server 含 runner/mcp:  {'YES (需移除)' if web_spawn else 'no (OK)'}")

    # 2. 端口占用
    print("\n[2] 端口")
    for name in _all_service_names():
        port = _service_port(name)
        used = _port_in_use(port)
        print(f"  {name:<12} :{port:<6} {'占用' if used else '空闲'}")

    # 3. 数据目录
    print("\n[3] 数据目录")
    for f in ("topoone.db", "sessions.db", "knowledge.db"):
        p = os.path.join(data_dir, f)
        print(f"  {f:<14} {'存在' if os.path.exists(p) else '缺失'}")
    return


def _port_in_use(port: int) -> bool:
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        try:
            s.bind(("127.0.0.1", port))
            return False
        except OSError:
            return True


# ═══════════════════════════════════════════════════════════════
# CLI RPC 客户端（P5）— 经网关 /api/rpc/{method} 连 daemon
# ═══════════════════════════════════════════════════════════════

def _default_data_dir() -> str:
    return os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
        os.path.expanduser("~"), ".topocode")


def _read_token(data_dir: str) -> str:
    p = os.path.join(data_dir, "token")
    if os.path.exists(p):
        with open(p) as f:
            tok = f.read().strip()
            if tok:
                return tok
    return ""


def _rpc(method: str, params: dict = None, http_port: int = 3456, data_dir: str = None) -> dict:
    """经网关 /api/rpc/{method} 调后端（带 token）。失败抛异常。"""
    import urllib.request
    import urllib.error
    import json as _json
    data_dir = data_dir or _default_data_dir()
    token = _read_token(data_dir)
    body = _json.dumps(params or {}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        f"http://127.0.0.1:{http_port}/api/rpc/{method}",
        data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return _json.loads(resp.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"RPC {method} failed: HTTP {e.code} {detail}")
    except Exception as e:
        raise RuntimeError(f"RPC {method} failed (is `topo serve` running on :{http_port}?): {e}")


def _is_daemon_up(http_port: int = 3456) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{http_port}/health", timeout=2):
            return True
    except Exception:
        return False


def _print_json(obj):
    import json as _json
    print(_json.dumps(obj, indent=2, default=str, ensure_ascii=False))


def _resolve_project(project_root: str, data_dir: str = None) -> str | None:
    """按项目根路径解析 project_id（查主库 ~/.topocode/topoone.db）。
    【P5 修正 query bug ①】原实现不查主库做 root_path↔project_id 解析。"""
    data_dir = data_dir or _default_data_dir()
    main_db = os.path.join(data_dir, "topoone.db")
    if not os.path.exists(main_db):
        return None
    from topoone.db.manager import SQLiteContext
    db = SQLiteContext(main_db)
    root = os.path.abspath(project_root)
    row = db.fetchone(
        "SELECT id FROM projects WHERE root_path = ? OR name = ? LIMIT 1",
        (root, os.path.basename(root)))
    if row:
        return row["id"]
    # 兜底：root_path LIKE 匹配
    row = db.fetchone(
        "SELECT id FROM projects WHERE root_path LIKE ? LIMIT 1",
        (root + "%",))
    if row:
        return row["id"]
    return None


def _resolve_task(project_id: str, task_name: str = "", data_dir: str = None) -> str | None:
    """按 project_id 解析 task_id（默认取最近分析任务）。
    【P5 修正 query bug ②】原实现 `SELECT DISTINCT task_id LIMIT 1` 取任意任务。"""
    data_dir = data_dir or _default_data_dir()
    main_db = os.path.join(data_dir, "topoone.db")
    if not os.path.exists(main_db):
        return None
    from topoone.db.manager import SQLiteContext
    db = SQLiteContext(main_db)
    if task_name:
        row = db.fetchone(
            "SELECT id FROM analysis_tasks WHERE project_id = ? AND name = ? ORDER BY created_at DESC LIMIT 1",
            (project_id, task_name))
        if row:
            return row["id"]
    row = db.fetchone(
        "SELECT id FROM analysis_tasks WHERE project_id = ? ORDER BY created_at DESC LIMIT 1",
        (project_id,))
    return row["id"] if row else None


def _cmd_query(args):
    """架构查询命令（离线直读 DB，P5 修正 project/task 解析）。"""
    project_root = os.path.abspath(args.project_root)
    use_json = getattr(args, "json", False)

    try:
        from topoone.db.manager import SQLiteContext
        # 【P5 修正】先经主库解析 project_id → task_id，再定位 project.db
        data_dir = getattr(args, "data_dir", None) or _default_data_dir()
        project_id = _resolve_project(project_root, data_dir)
        if not project_id:
            print(f"Project not found in main DB ({data_dir}): {project_root}")
            return
        task_id = _resolve_task(project_id, getattr(args, "task", ""), data_dir)
        if not task_id:
            print(f"No analysis task found for project: {project_root}")
            return
        db_path = os.path.join(data_dir, "projects", project_id, "project.db")
        if not os.path.exists(db_path):
            print(f"Project data not initialized: {project_root}")
            return
        db = SQLiteContext(db_path)
        from topoone.engine.analysis_context import AnalysisContext
        ctx = AnalysisContext(db, task_id)
    except Exception as e:
        print(f"Failed to load analysis data: {e}")
        return

    if args.command == "community":
        result = ctx.get_summary()
        communities = ctx._store.get_communities(
            ctx._task_id, edge_type=getattr(args, "type", "INCLUDE")
        )
        result["communities"] = [
            {"comm_id": c.get("comm_id"), "node_count": c.get("node_count"), "quality_score": c.get("quality_score")}
            for c in communities[:20]
        ]
    elif args.command == "arch":
        layer = ctx.get_project_layer()
        result = {"what": layer.what, "how": layer.how, "why": layer.why, "detail": layer.detail}
    elif args.command == "diff":
        result = {"message": "Diff requires SnapshotStore data. Run analysis with --snapshot mode."}
    elif args.command == "quality":
        result = {"message": "MCP functionality is disabled"}
    else:
        result = {"error": f"Unknown command: {args.command}"}

    if use_json:
        import json
        print(json.dumps(result, indent=2, default=str))
    else:
        import json as _rj
        print(_rj.dumps(result, indent=2, default=str, ensure_ascii=False))


def _cmd_daemon(args):
    """经 /api/rpc 连 daemon 的 CLI 命令（import/analyze/tasks/export/verify/settings）。"""
    http_port = getattr(args, "http_port", 3456)
    data_dir = getattr(args, "data_dir", None) or _default_data_dir()
    use_json = getattr(args, "json", False)
    cmd = args.command

    if not _is_daemon_up(http_port):
        print(f"daemon not running on :{http_port}. Start with: topo serve", file=sys.stderr)
        sys.exit(1)

    try:
        if cmd == "import":
            result = _rpc("project.import", {"path": os.path.abspath(args.path)},
                          http_port=http_port, data_dir=data_dir)
            _emit(result, use_json)

        elif cmd == "tasks":
            project_id = _resolve_project(args.path, data_dir)
            if not project_id:
                print(f"Project not found: {args.path}", file=sys.stderr)
                sys.exit(1)
            result = _rpc("analysis.listTasks", {"projectId": project_id},
                          http_port=http_port, data_dir=data_dir)
            _emit(result, use_json)

        elif cmd == "analyze":
            project_id = _resolve_project(args.path, data_dir)
            if not project_id:
                print(f"Project not found: {args.path}", file=sys.stderr)
                sys.exit(1)
            task_id = _resolve_task(project_id, getattr(args, "task", ""), data_dir)
            if not task_id:
                # 无任务则先创建一个默认分析任务
                task = _rpc("analysis.createTask",
                            {"projectId": project_id, "type": "full", "name": "full-analysis"},
                            http_port=http_port, data_dir=data_dir)
                task_id = (task.get("result") or task).get("id")
                if not task_id:
                    print(f"Failed to create task for {args.path}", file=sys.stderr)
                    sys.exit(1)
            result = _rpc("analysis.runTask", {"taskId": task_id},
                          http_port=http_port, data_dir=data_dir)
            _emit(result, use_json)

        elif cmd == "export":
            project_id = _resolve_project(args.path, data_dir)
            if not project_id:
                print(f"Project not found: {args.path}", file=sys.stderr)
                sys.exit(1)
            task_id = _resolve_task(project_id, getattr(args, "task", ""), data_dir)
            result = _rpc("system.exportProject",
                          {"projectId": project_id, "taskIds": [task_id] if task_id else []},
                          http_port=http_port, data_dir=data_dir)
            _emit(result, use_json)

        elif cmd == "verify":
            project_id = _resolve_project(args.path, data_dir)
            if not project_id:
                print(f"Project not found: {args.path}", file=sys.stderr)
                sys.exit(1)
            result = _rpc("system.verifyFiles", {"projectId": project_id},
                          http_port=http_port, data_dir=data_dir)
            _emit(result, use_json)

        elif cmd == "settings":
            result = {}
            if getattr(args, "get_models", False):
                result["models"] = _rpc("settings.getModels", {}, http_port=http_port, data_dir=data_dir)
            if getattr(args, "get_agents", False):
                result["agents"] = _rpc("settings.getAgents", {}, http_port=http_port, data_dir=data_dir)
            if getattr(args, "get_skills", False):
                result["skills"] = _rpc("settings.getSkills", {}, http_port=http_port, data_dir=data_dir)
            if not result:
                result = {"hint": "use --get-models/--get-agents/--get-skills"}
            _emit(result, use_json)

    except RuntimeError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _emit(result, use_json: bool):
    if use_json:
        _print_json(result)
    else:
        _print_json(result)


def _cmd_project(args):
    """项目初始化/清除。

    新架构：项目库统一在 {data_dir}/projects/<pid>/，源码目录只留 .topocode/proj-id 签名。
    """
    project_root = os.path.abspath(args.project_root)
    data_dir = getattr(args, "data_dir", None) or _default_data_dir()
    if args.command == "init":
        # 解析既有项目（签名或主库），登记中心项目库目录
        from topoone.db.manager import MultiDBManager
        m = MultiDBManager(data_dir)
        pid = MultiDBManager.read_proj_signature(project_root) or \
            _resolve_project(project_root, data_dir)
        if pid:
            os.makedirs(os.path.join(data_dir, "projects", pid), exist_ok=True)
            MultiDBManager.write_proj_signature(project_root, pid)
            print(f"topocode project initialized: {project_root} ({pid})")
        else:
            print(f"No project registered for {project_root} — import it first (topo import).")
        m.close_all()
    elif args.command == "uninit":
        MultiDBManager.remove_proj_signature(project_root)
        print(f"Cleared .topocode/proj-id signature: {project_root}")


def _cmd_arch(args):
    """架构操作命令。"""
    project_root = os.path.abspath(args.project_root)
    data_dir = getattr(args, "data_dir", None) or _default_data_dir()
    project_id = _resolve_project(project_root, data_dir)
    db_path = os.path.join(data_dir, "projects", project_id, "project.db") if project_id else ""
    if not project_id or not os.path.exists(db_path):
        print(f"Project not initialized: {project_root}")
        return

    action = getattr(args, "arch_action", None)
    if not action:
        print("Usage: topocode arch [analyze|overview|export|list]")
        return

    print(f"[arch] {action} — feature in development (AgentRuntime complete, pending integration)")
    print(f"  project: {project_root}")
    if action == "analyze":
        print(f"  level: {getattr(args, 'level', 'L0')}")
        print(f"  type: {getattr(args, 'edge_type', 'INCLUDE')}")
    elif action == "export":
        print(f"  format: {getattr(args, 'format', 'md')}")
        print(f"  output: {getattr(args, 'output') or '.topocode/architecture/'}")


def _cmd_track(args):
    """架构变更追踪命令。"""
    project_root = os.path.abspath(args.project_root)
    data_dir = getattr(args, "data_dir", None) or _default_data_dir()
    project_id = _resolve_project(project_root, data_dir)
    db_path = os.path.join(data_dir, "projects", project_id, "project.db") if project_id else ""
    if not project_id or not os.path.exists(db_path):
        print(f"Project not initialized: {project_root}")
        return

    action = getattr(args, "track_action", None)
    if not action:
        print("Usage: topocode track [start|stop|list|status]")
        return

    print(f"[track] {action} — feature in development (ArchSentinel complete, pending integration)")
    print(f"  project: {project_root}")
    if action == "start":
        tag = getattr(args, "tag", "") or f"v-auto-{int(time.time())}"
        print(f"  tag: {tag}")
    elif action == "list":
        print(f"  showing last {getattr(args, 'limit', 10)} records")


def _cmd_diff(args):
    """版本差异命令。"""
    project_root = os.path.abspath(args.project_root)
    print(f"[diff] — feature in development")
    if args.diff_action == "snapshots":
        print("  listing available snapshots...")
    elif args.diff_action == "compare":
        frm = getattr(args, "from_version", "") or "latest-previous"
        to = getattr(args, "to_version", "") or "current"
        print(f"  comparing: {frm} → {to}")


if __name__ == "__main__":
    main()
