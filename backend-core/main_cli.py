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

    if cmd in ("install", "uninstall", "detect"):
        _cmd_installer(args)

    elif cmd in ("community", "arch", "diff", "quality", "track", "status"):
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
        print(f"Failed to load installer plugin: {e}")

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
        from sqlite_ctx import SQLiteContext
        store_dir = os.path.join(project_root, ".topocode", "data")
        db_path = os.path.join(store_dir, "project.db")
        if not os.path.exists(db_path):
            print(f"Project not initialized: {project_root}")
            return
        db = SQLiteContext(db_path)
        from analysis_context import AnalysisContext
        rows = db.execute("SELECT DISTINCT task_id FROM graph_node LIMIT 1").fetchall()
        if not rows:
            print("No analysis data found, please run topocode init first")
            return
        ctx = AnalysisContext(db, rows[0][0])
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
    elif args.command == "status":
        result = ctx.get_summary()
    else:
        result = {"error": f"Unknown command: {args.command}"}

    if use_json:
        import json
        print(json.dumps(result, indent=2, default=str))
    else:
        import json as _rj
        print(_rj.dumps(result, indent=2, default=str, ensure_ascii=False))


def _cmd_project(args):
    """项目初始化/清除。"""
    project_root = os.path.abspath(args.project_root)
    store_dir = os.path.join(project_root, ".topocode", "data")
    if args.command == "init":
        os.makedirs(store_dir, exist_ok=True)
        print(f"topocode project initialized: {project_root}")
        print("Use 'topocode status' to view analysis status.")
    elif args.command == "uninit":
        import shutil
        topo_dir = os.path.join(project_root, ".topocode")
        if os.path.exists(topo_dir):
            shutil.rmtree(topo_dir)
            print(f"Cleared: {topo_dir}")


def _cmd_arch(args):
    """架构操作命令。"""
    project_root = os.path.abspath(args.project_root)
    store_dir = os.path.join(project_root, ".topocode", "data")
    db_path = os.path.join(store_dir, "project.db")
    if not os.path.exists(db_path):
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
    store_dir = os.path.join(project_root, ".topocode", "data")
    db_path = os.path.join(store_dir, "project.db")
    if not os.path.exists(db_path):
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
