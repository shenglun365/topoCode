"""topocode CLI 入口。

命令结构:
  topocode init/uninit/status            — 项目初始化
  topocode community/arch/diff/quality    — 架构查询
  topocode serve                          — MCP Server
  topocode session                        — AI 会话追踪 (待实现)
  topocode install/uninstall/detect       — Agent Installer
"""

import argparse
import os
import sys

# Ensure backend-core and plugins on path
_CORE_DIR = os.path.dirname(os.path.abspath(__file__))
_PARENT = os.path.dirname(_CORE_DIR)
sys.path.insert(0, _CORE_DIR)
sys.path.insert(0, os.path.join(_PARENT, "plugins"))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="topocode",
        description="topocode — 代码架构认知工具。提升人的架构认知水平。",
    )
    sub = parser.add_subparsers(dest="command", help="子命令")

    # === 项目 ===
    sub.add_parser("init", help="初始化项目分析")
    sub.add_parser("uninit", help="清除分析数据")
    sub.add_parser("status", help="分析统计")

    # === 架构查询 ===
    p_comm = sub.add_parser("community", help="查看社区结构")
    p_comm.add_argument("--type", choices=["INCLUDE", "CALL"], default="INCLUDE")
    p_comm.add_argument("--level", type=int, default=0)
    p_comm.add_argument("--json", action="store_true")

    p_arch = sub.add_parser("arch", help="架构总览")
    p_arch.add_argument("--focus", default="overview")
    p_arch.add_argument("--json", action="store_true")

    p_diff = sub.add_parser("diff", help="版本差异")
    p_diff.add_argument("from_commit", nargs="?", default="HEAD~1")
    p_diff.add_argument("to_commit", nargs="?", default="HEAD")
    p_diff.add_argument("--scope", default="full")
    p_diff.add_argument("--json", action="store_true")

    p_qual = sub.add_parser("quality", help="质量检查")
    p_qual.add_argument("--focus", default="all")
    p_qual.add_argument("--json", action="store_true")

    # === MCP ===
    p_serve = sub.add_parser("serve", help="启动 MCP Server")
    p_serve.add_argument("--mcp", action="store_true", help="MCP 模式 (默认)")
    p_serve.add_argument("--proxy", action="store_true")
    p_serve.add_argument("--port", type=int, default=0)

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

    parser.add_argument("--project-root", default=".", help="项目根目录")
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

    elif cmd in ("install", "uninstall", "detect"):
        _cmd_installer(args)

    elif cmd in ("community", "arch", "diff", "quality", "status"):
        _cmd_query(args)

    elif cmd in ("init", "uninit"):
        _cmd_project(args)

    elif cmd == "session":
        _cmd_session(args)


def _cmd_serve(args):
    """启动 MCP Server。"""
    project_root = os.path.abspath(args.project_root)
    print(f"topocode MCP Server starting for project: {project_root}")
    print("(stdio mode — ready for AI agent connection)")
    from mcp_server.__main__ import main as mcp_main
    sys.argv = ["mcp_server", "--project-root", project_root]
    mcp_main()


def _cmd_installer(args):
    """Agent Installer 命令。"""
    import importlib.util
    # Load installer plugin directly
    installer_path = os.path.join(_PARENT, "plugins", "installer", "plugin_entry.py")
    try:
        spec = importlib.util.spec_from_file_location("installer", installer_path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
    except Exception as e:
        print(f"无法加载 installer 插件: {e}")

    if args.command == "detect":
        installer._cmd_detect()
    elif args.command == "install":
        installer._cmd_install(args.agents, args.global_)
    elif args.command == "uninstall":
        installer._cmd_uninstall(args.agents, args.global_)


def _cmd_query(args):
    """架构查询命令。"""
    project_root = os.path.abspath(args.project_root)
    use_json = getattr(args, "json", False)

    try:
        from store.connection import SQLiteContext
        store_dir = os.path.join(project_root, ".topocode", "data")
        db_path = os.path.join(store_dir, "project.db")
        if not os.path.exists(db_path):
            print(f"项目未初始化: {project_root}")
            return
        db = SQLiteContext(db_path)
        from analysis_context import AnalysisContext
        rows = db.execute("SELECT DISTINCT task_id FROM graph_node LIMIT 1").fetchall()
        if not rows:
            print("未找到分析数据，请先运行 topocode init")
            return
        ctx = AnalysisContext(db, rows[0][0])
    except Exception as e:
        print(f"加载分析数据失败: {e}")
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
        result = {"message": "Diff 需要 SnapshotStore 数据。使用 --snapshot 模式运行分析。"}
    elif args.command == "quality":
        from mcp_server.dispatcher import ToolDispatcher
        d = ToolDispatcher(project_root, context=ctx)
        result = d._handle_quality_inspect({"focus": getattr(args, "focus", "all")})
    elif args.command == "status":
        result = ctx.get_summary()
    else:
        result = {"error": f"未知命令: {args.command}"}

    if use_json:
        import json
        print(json.dumps(result, indent=2, default=str))
    else:
        from mcp_server.dispatcher import _json_dumps
        print(_json_dumps(result))


def _cmd_project(args):
    """项目初始化/清除。"""
    project_root = os.path.abspath(args.project_root)
    store_dir = os.path.join(project_root, ".topocode", "data")
    if args.command == "init":
        os.makedirs(store_dir, exist_ok=True)
        print(f"topocode 项目已初始化: {project_root}")
        print("使用 'topocode status' 查看分析状态。")
    elif args.command == "uninit":
        import shutil
        topo_dir = os.path.join(project_root, ".topocode")
        if os.path.exists(topo_dir):
            shutil.rmtree(topo_dir)
            print(f"已清除: {topo_dir}")


def _cmd_session(args):
    """AI 会话追踪。"""
    print("session 追踪功能待集成 ai_session_tracker 模块。")


if __name__ == "__main__":
    main()
