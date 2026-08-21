"""静态源解析 — manifest 驱动（static_dir × static_mount），无 legacy 回退（M14 终态）。

规则：manifest static_dir 为准；目录缺失时返回该路径（路由层报「not built」）。
"""

import logging
import os

# 仓库根（topoone/gateway/static_sources.py → parents[4]）
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))))

PORTAL_DIR = os.path.join(_REPO_ROOT, "packages", "web-core", "dist-portal")

logger = logging.getLogger(__name__)


def portal_dir() -> str | None:
    """门户（home.html）静态目录：web-core dist-portal（M09 产出）；未构建返回 None。"""
    return PORTAL_DIR if os.path.isdir(PORTAL_DIR) else None


def _resolve(static_dir: str) -> str:
    return static_dir if os.path.isabs(static_dir) else os.path.join(_REPO_ROOT, static_dir)


def spa_static_dir() -> str:
    """SPA html 静态目录（docs app static_dir，manifest 驱动；无 legacy 回退）。"""
    from topoone.manifest import discover_apps
    try:
        apps = discover_apps(_REPO_ROOT)
        m = apps.get("docs")
        if m and m.static_dir:
            return _resolve(m.static_dir)
    except Exception as e:
        logger.warning(f"[gateway] discover_apps failed: {e}; using default docs dist")
    return os.path.join(_REPO_ROOT, "apps", "docs", "dist")


def main_app_mounts() -> list[tuple[str, str]]:
    """目录型静态挂载（static_mount × static_dir，目录存在者）。

    workbench（kind=core）: /app → dist/；service app dist 就绪后（M11–M13）同样生效。
    docs 的 static_mount 是 html 页面路由（见 vue_routes），不在此挂载。
    """
    from topoone.manifest import discover_apps
    out: list[tuple[str, str]] = []
    try:
        apps = discover_apps(_REPO_ROOT)
    except Exception as e:
        logger.warning(f"[gateway] discover_apps failed: {e}; no manifest static mounts")
        return out
    for name, m in apps.items():
        if name == "docs" or not m.static_dir or not m.static_mount:
            continue
        d = _resolve(m.static_dir)
        if not os.path.isdir(d):
            continue
        for mount in m.static_mount:
            out.append((mount, d))
    return out
