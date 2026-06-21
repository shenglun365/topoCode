import os


def to_rel(path: str, root: str) -> str:
    """任意路径 → 项目相对路径（供内部流转使用）"""
    if not path or not root:
        return path
    return os.path.relpath(path, root) if os.path.isabs(path) else path


def to_abs(path: str, root: str) -> str:
    """相对路径 → 绝对路径（供文件读写 / SQL 使用）"""
    if not path or not root:
        return path
    return os.path.join(root, path) if not os.path.isabs(path) else path
