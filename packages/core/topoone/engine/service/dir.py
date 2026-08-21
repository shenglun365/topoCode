"""dir.* 目录命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""

import os
from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
def register_dir_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册服务器目录浏览器方法 — Web 端替代 Electron dialog 选目录。

    供「导入项目」等场景按层级浏览服务器目录、新建目录，并对选定目录做
    git/重复项目/源码签名识别（移植自 architect plugins/architect/arch_routes/dirs.py）。
    """
    import socket
    import stat as _stat
    import subprocess

    main_db = multi_db.main_db

    # 分析时跳过系统/隐藏目录，避免目录树噪声
    _SKIP = {".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".DS_Store",
             "node_modules", "dist", "build"}

    def _access(path: str) -> dict:
        r, w = os.access(path, os.R_OK), os.access(path, os.W_OK)
        return {"readable": r, "writable": w, "r": r, "w": w}

    def _entry_stat(full: str) -> dict:
        try:
            st = os.stat(full)
            return {
                "mtime": int(st.st_mtime * 1000),
                "size": st.st_size if not _stat.S_ISDIR(st.st_mode) else 0,
            }
        except OSError:
            return {"mtime": 0, "size": 0}

    def _host_info() -> dict:
        name = socket.gethostname()
        ip = ""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except OSError:
            ip = ""
        return {"name": name, "ip": ip}

    def _git_toplevel(path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", path, "rev-parse", "--show-toplevel"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return ""
        return (r.stdout or "").strip() if r.returncode == 0 else ""

    def _git_branch(path: str) -> str:
        try:
            r = subprocess.run(
                ["git", "-C", path, "branch", "--show-current"],
                capture_output=True, text=True, timeout=10,
            )
        except Exception:
            return ""
        return (r.stdout or "").strip() if r.returncode == 0 else ""

    def _has_code(path: str) -> bool:
        try:
            names = os.listdir(path)
        except OSError:
            return False
        for n in names:
            if n.startswith(".") or n in _SKIP:
                continue
            full = os.path.join(path, n)
            if os.path.isfile(full) or os.path.isdir(full):
                return True
        return False

    @server.register("dir.list")
    def dir_list(path: str = None):
        """列出服务器目录内容（顶层目录/文件），按目录优先 + 名称排序。"""
        abs_path = os.path.abspath(os.path.expanduser(path or os.path.expanduser("~")))
        if not os.path.isdir(abs_path):
            raise ValueError(f"Directory not found or not a directory: {abs_path}")
        try:
            names = sorted(os.listdir(abs_path),
                           key=lambda n: (not os.path.isdir(os.path.join(abs_path, n)), n.lower()))
        except OSError as e:
            raise ValueError(f"Failed to read directory: {e}")
        entries = []
        for name in names:
            if name in _SKIP or name.startswith("."):
                continue
            full = os.path.join(abs_path, name)
            is_dir = os.path.isdir(full)
            info = _entry_stat(full)
            entries.append({
                "name": name, "isDir": is_dir,
                "size": info["size"], "mtime": info["mtime"],
                **(_access(full) if is_dir else {}),
            })
        return {
            "path": abs_path,
            "parent": os.path.dirname(abs_path) if os.path.dirname(abs_path) != abs_path else None,
            "host": _host_info(),
            **_access(abs_path),
            "entries": entries,
        }

    @server.register("dir.create")
    def dir_create(parent: str = None, name: str = None):
        """在指定父目录下新建一个目录（需父目录写权限）。"""
        parent = os.path.abspath(os.path.expanduser(parent or ""))
        name = (name or "").strip()
        if not parent or not name:
            raise ValueError("parent and name are required")
        if not os.path.isdir(parent):
            raise ValueError(f"Parent directory not found: {parent}")
        if not os.access(parent, os.W_OK):
            raise PermissionError(f"Parent directory is not writable: {parent}")
        if os.sep in name or name in (".", "..") or "\x00" in name:
            raise ValueError(f"Invalid directory name: {name}")
        target = os.path.join(parent, name)
        if os.path.exists(target):
            raise ValueError(f"Directory already exists: {target}")
        try:
            os.makedirs(target)
        except OSError as e:
            raise ValueError(f"Failed to create directory: {e}")
        return {"path": target, "name": name, **_access(target)}

    @server.register("dir.analyze")
    def dir_analyze(root: str = None):
        """分析选定目录：git 顶层/分支、是否空、是否有代码、重复项目、签名重关联。"""
        root = (root or "").strip()
        if not root:
            raise ValueError("root is required")
        abs_root = os.path.abspath(os.path.expanduser(root))
        if not os.path.isdir(abs_root):
            raise ValueError(f"Directory not found or not a directory: {abs_root}")

        toplevel = _git_toplevel(abs_root)
        is_git_root = bool(toplevel) and os.path.normpath(toplevel) == os.path.normpath(abs_root)

        names = []
        try:
            names = os.listdir(abs_root)
        except OSError:
            pass
        isEmpty = not any(n for n in names if not n.startswith(".") and n not in _SKIP)
        hasCode = not isEmpty and _has_code(abs_root)

        # 重复项目：KB projects 表中同 root_path 的项目
        duplicate = None
        try:
            existing = main_db.fetchone("SELECT * FROM projects WHERE root_path = ?", (abs_root,))
            if existing:
                duplicate = {
                    "id": existing["id"], "name": existing["name"],
                    "rootPath": existing["root_path"], "mode": existing.get("import_mode", ""),
                }
        except Exception:
            duplicate = None

        # proj-id 签名重关联提示：源码目录整体移动后指向已有项目
        signature_project = None
        sig_id = multi_db.read_proj_signature(abs_root)
        if sig_id:
            sig_row = main_db.fetchone("SELECT id, name, root_path FROM projects WHERE id = ?", (sig_id,))
            if sig_row:
                signature_project = {
                    "id": sig_row["id"], "name": sig_row["name"],
                    "rootPath": sig_row["root_path"],
                }

        return {
            "root": abs_root,
            "name": abs_root.rstrip("/").rsplit("/", 1)[-1] or "/",
            **_access(abs_root),
            "isGitRoot": is_git_root,
            "gitToplevel": toplevel or None,
            "gitBranch": _git_branch(abs_root) or None,
            "isEmpty": isEmpty,
            "hasCode": hasCode,
            "duplicate": duplicate,
            "signatureProject": signature_project,
        }


# ==================== KB 版本基线方法 ====================
