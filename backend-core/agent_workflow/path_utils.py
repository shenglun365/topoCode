import os
import logging

logger = logging.getLogger(__name__)


def to_rel(path: str, root: str) -> str:
    """任意路径 → 项目相对路径（供内部流转使用），返回值统一使用正斜杠。"""
    if not path or not root:
        return path
    rel = os.path.relpath(path, root) if os.path.isabs(path) else path
    return rel.replace('\\', '/')


def to_abs(path: str, root: str) -> str:
    """相对路径 → 绝对路径（供文件读写 / SQL 使用）"""
    if not path or not root:
        return path
    return os.path.join(root, path) if not os.path.isabs(path) else path


def resolve_file(path: str, project_root: str) -> str | None:
    """解析文件路径。精确路径不存在时，按 basename 模糊匹配兜底。

    Returns:
        解析后的绝对路径，文件不存在则返回 None。
    """
    abs_path = to_abs(path, project_root)
    if os.path.isfile(abs_path):
        return abs_path

    basename = os.path.basename(path)
    if not basename:
        return None

    try:
        for dirpath, dirnames, files in os.walk(project_root):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            if basename in files:
                resolved = os.path.join(dirpath, basename)
                logger.info(f"[resolve_file] fuzzy match: {path} → {os.path.relpath(resolved, project_root)}")
                return resolved
    except Exception:
        pass

    return None
