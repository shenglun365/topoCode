"""Host directory browser routes — 打开/新建项目时选择宿主机目录。

前端「打开新项目」弹窗需要按文件目录层级浏览宿主机目录、可新建目录、
并对选定的目录自动识别：
- 是否为本地 git 主目录(顶层)；
- 是否空目录、是否已有代码；
- 是否重复打开一个已建立的 architect 项目(arch_projects 中同一 root)；
- 是否存在可安全关联的有效 KB 项目(同一仓库源校验)。

分析结果由 `POST /dir/analyze` 一次性返回，前端据此做出提示与绑定决策
(绑定复用 `/project/bind`)。目录读写权限均用宿主机会话权限判定(os.access)。
"""
import os
import socket
import stat
import subprocess
from typing import Optional
from fastapi import APIRouter, Request

from .common import _ts, ok, err
from . import store
from .project import _list_kb_projects, _same_repo_source

router = APIRouter()

# 分析时跳过系统/隐藏目录，避免目录树噪声。
_SKIP = {".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".DS_Store",
         "node_modules", "dist", "build"}


def _host_info() -> dict:
    """宿主机标识：主机名 + 对外 IP(支持远程 Web-UI 访问时供用户确认目录所在机器)。"""
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


def _access(path: str) -> dict:
    r, w = os.access(path, os.R_OK), os.access(path, os.W_OK)
    return {"readable": r, "writable": w, "r": r, "w": w}


def _entry_stat(full: str) -> dict:
    try:
        st = os.stat(full)
        return {
            "mtime": int(st.st_mtime * 1000),
            "size": st.st_size if not stat.S_ISDIR(st.st_mode) else 0,
        }
    except OSError:
        return {"mtime": 0, "size": 0}


@router.get("/dir/list")
async def dir_list(path: Optional[str] = None):
    """列出宿主机目录内容(顶层目录/文件)，按目录优先 + 名称排序。

    path 缺省为当前用户主目录。返回条目含 isDir/readable/writable，
    供前端按层级逐级进入。
    """
    abs_path = os.path.abspath(os.path.expanduser(path or os.path.expanduser("~")))
    if not os.path.isdir(abs_path):
        return err(400, f"目录不存在或不是目录：{abs_path}")
    try:
        names = sorted(os.listdir(abs_path), key=lambda n: (not os.path.isdir(os.path.join(abs_path, n)), n.lower()))
    except OSError as e:
        return err(400, f"无法读取目录：{e}")
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
    return ok({
        "path": abs_path,
        "parent": os.path.dirname(abs_path) if os.path.dirname(abs_path) != abs_path else None,
        "host": _host_info(),
        **_access(abs_path),
        "entries": entries,
    })


@router.post("/dir/create")
async def dir_create(request: Request):
    """在指定父目录下新建一个目录(需父目录写权限)。"""
    body = await request.json() or {}
    parent = (body.get("parent") or "").strip()
    name = (body.get("name") or "").strip()
    if not parent or not name:
        return err(400, "缺少 parent 或 name")
    parent = os.path.abspath(os.path.expanduser(parent))
    if not os.path.isdir(parent):
        return err(400, f"父目录不存在：{parent}")
    if not os.access(parent, os.W_OK):
        return err(403, "父目录无写权限，无法新建目录")
    if os.sep in name or name in (".", "..") or "\x00" in name:
        return err(400, "目录名不合法")
    target = os.path.join(parent, name)
    if os.path.exists(target):
        return err(400, f"目录已存在：{target}")
    try:
        os.makedirs(target)
    except OSError as e:
        return err(400, f"创建失败：{e}")
    return ok({"path": target, "name": name, **_access(target)})


def _git_toplevel(path: str) -> str:
    """返回 path 所在 git 仓库顶层目录；非 git 仓库返回空串。"""
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
    """顶层存在非隐藏条目(除可忽略系统目录外)即认为已有代码/内容。"""
    try:
        names = os.listdir(path)
    except OSError:
        return False
    for n in names:
        if n.startswith(".") or n in _SKIP:
            continue
        full = os.path.join(path, n)
        if os.path.isfile(full):
            return True
        if os.path.isdir(full) and not n.startswith("."):
            return True
    return False


@router.post("/dir/analyze")
async def dir_analyze(request: Request):
    """分析选定目录，建立 architect 项目根目录之前的前置识别。

    返回: git 顶层/分支、是否空、是否有代码、是否重复打开已建立的
    architect 项目(同一 root_path)、可安全关联的有效 KB 候选清单。
    """
    body = await request.json() or {}
    root = (body.get("root") or "").strip()
    if not root:
        return err(400, "缺少 root")
    abs_root = os.path.abspath(os.path.expanduser(root))
    if not os.path.isdir(abs_root):
        return err(400, f"目录不存在或不是目录：{abs_root}")

    toplevel = _git_toplevel(abs_root)
    is_git_root = bool(toplevel) and os.path.normpath(toplevel) == os.path.normpath(abs_root)

    names = []
    try:
        names = os.listdir(abs_root)
    except OSError:
        pass
    isEmpty = not any(n for n in names if not n.startswith(".") and n not in _SKIP)
    hasCode = not isEmpty and _has_code(abs_root)

    # 重复打开已建立的 architect 项目(arch_projects 中同 root_path)。
    existing = store.ProjectsStore.get_by_root(abs_root)
    duplicate = {
        "id": existing.get("id"), "name": existing.get("name"),
        "rootPath": existing.get("rootPath"), "mode": existing.get("mode"),
    } if existing else None

    # 可安全关联的有效 KB 项目(同仓库源校验通过且已有基线)。
    kbCandidates = []
    for kb in _list_kb_projects():
        if not kb.get("gitLinked") or not kb.get("hasBaseline"):
            continue
        ok_, reason = _same_repo_source(abs_root, kb)
        if ok_:
            kbCandidates.append({
                "id": kb.get("id"), "name": kb.get("name"),
                "rootPath": kb.get("rootPath"), "reason": reason,
            })

    return ok({
        "root": abs_root,
        "name": abs_root.rstrip("/").rsplit("/", 1)[-1] or "/",
        **_access(abs_root),
        "isGitRoot": is_git_root,
        "gitToplevel": toplevel or None,
        "gitBranch": _git_branch(abs_root) or None,
        "isEmpty": isEmpty,
        "hasCode": hasCode,
        "duplicate": duplicate,
        "kbCandidates": kbCandidates,
    })