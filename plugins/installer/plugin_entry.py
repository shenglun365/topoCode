"""Installer Plugin Entry. CLI commands: install, uninstall, detect."""

import logging
import sys
import os

logger = logging.getLogger(__name__)

# Resolve plugin directory on path for absolute imports
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)


def _import_targets():
    """Import targets module, trying both relative and absolute paths."""
    try:
        from targets import detect_all, TARGETS, get_target
        return detect_all, TARGETS, get_target
    except ImportError:
        from .targets import detect_all, TARGETS, get_target
        return detect_all, TARGETS, get_target


def _cmd_detect():
    detect_all, TARGETS, _ = _import_targets()
    detected = detect_all()
    print(f"已安装的 AI Coding Agents ({len(detected)}/{len(TARGETS)}):")
    for tid in sorted(TARGETS.keys()):
        marker = "[x]" if tid in detected else "[ ]"
        print(f"  {marker} {TARGETS[tid].name} ({tid})")


def _cmd_install(agents: list = None, global_: bool = False):
    _, _, get_target = _import_targets()
    detect_all, _, _ = _import_targets()

    if not agents:
        agents = detect_all()
        if not agents:
            print("未检测到任何已安装的 AI Coding Agent。")
            return

    for agent_id in agents:
        target = get_target(agent_id)
        if not target:
            print(f"  [skip] 未知 agent: {agent_id}")
            continue
        try:
            path = target.install(global_=global_)
            scope = "全局" if global_ else "项目"
            print(f"  [ok] {target.name} ({scope}) -> {path}")
        except Exception as e:
            print(f"  [err] {target.name}: {e}")


def _cmd_uninstall(agents: list = None, global_: bool = False):
    _, TARGETS, get_target = _import_targets()

    if not agents:
        agents = list(TARGETS.keys())

    for agent_id in agents:
        target = get_target(agent_id)
        if not target:
            print(f"  [skip] 未知 agent: {agent_id}")
            continue
        try:
            path = target.uninstall(global_=global_)
            if path:
                print(f"  [ok] {target.name} -> 已从 {path} 移除")
            else:
                print(f"  [skip] {target.name} -> 未找到配置")
        except Exception as e:
            print(f"  [err] {target.name}: {e}")


def register_methods(server, multi_db):
    if hasattr(server, "register"):
        server.register("installer.detect", _cmd_detect)
        server.register("installer.install", _cmd_install)
        server.register("installer.uninstall", _cmd_uninstall)
    logger.info("Installer plugin registered")
