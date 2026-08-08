"""Project, baseline, snapshot routes.

architect 项目与 KB **解耦**：`arch_projects` 是架构师自持项目的唯一事实源，
每个项目挂在一个工作目录上(`id=proj-<md5(root)>`、`rootPath=用户工作目录`)。
KB 仅作为**可选关联**元数据写入该行(`kb_project_id/kb_source_dir/baseline_id/…`)；
关联前必须经 `_same_repo_source` 校验 architect 工作目录与 KB 源码为同一仓库源。

选择持久化在 URL 内(?root=<path> / ?project=<arch行id>)，多页签各处理不同项目。
KB 相关请求一律经 `KbGateway`(_kb_call)，不进程内共享 zmq_server。
"""
import hashlib
import os
import subprocess
from typing import Optional
from fastapi import APIRouter, Request

from .common import _ts, ok, err, build_architecture_model
from . import store

router = APIRouter()

BASELINE_COMMIT = "1a2b3c4d5e6f"

_DEFAULT_CONFIG = {"estMinMin": 60, "estMinMax": 480, "acceptanceMax": 4, "p0SubsetMax": 5}

# KB 项目字段映射: main_db.projects 的 snake_case 列 → architect 消费的 camelCase。
# 派生字段 gitLinked/hasBaseline 供「选择 KB 项目做关联」做门槛判定(避免错误关联)。
_KB_FIELDS = {
    "id": "id", "name": "name", "root_path": "rootPath",
    "import_mode": "importMode", "remote_url": "remoteUrl",
    "local_repo_path": "localRepoPath", "source_cache_dir": "sourceCacheDir",
    "current_version_id": "currentVersionId", "status": "status",
    "language": "language", "file_count": "fileCount",
    "done_task_count": "doneTaskCount", "updated_at": "updatedAt",
}


def _stable_proj_id(root: str) -> str:
    """architect 项目稳定 id(按 root 哈希)，多页签共享同一目录时一致。"""
    return "proj-" + hashlib.md5((root or "").encode("utf-8")).hexdigest()[:10]


def _synthesize(root: str) -> dict:
    """未登记路径的临时工作目录项目(降级，不入库)。"""
    return {
        "id": _stable_proj_id(root),
        "name": root.rstrip("/").rsplit("/", 1)[-1] or "工作目录",
        "desc": "直接打开的工作目录(未预解析 KB 内容)",
        "rootPath": root, "kbRoot": "",
        "branch": "", "baselineId": None, "baselineCommit": "",
        "createdAt": 0, "active": True,
        "config": dict(_DEFAULT_CONFIG), "mode": "existing", "gitLinked": False,
        "pinned": False, "favorite": False,
    }


def _resolve_project(root: Optional[str] = None, project_id: Optional[str] = None) -> Optional[dict]:
    """按 URL 解析当前项目(arch_projects 为唯一事实源):
    - project=<architect行id>: 读 `arch_projects` 行;
    - root=<path>: 优先 get_by_root；未登记路径 → 临时合成的工作目录项目(降级，不再按路径猜 KB)。
    """
    if project_id:
        return store.ProjectsStore.get(project_id)
    if root:
        root = str(root).strip()
        if not root:
            return None
        row = store.ProjectsStore.get_by_root(root)
        if row:
            return row
        return _synthesize(root)
    return None


def _kb_call(method: str, **params):
    """调用 KB 方法(经 ctx 网关，拓扑无关)；结果 None/错误时回退。"""
    from .kb_gateway import call_kb
    return call_kb(method, **params)


def _list_kb_projects() -> list:
    """拉取 KB 全部项目(project.list)并映射为 architect 形状。"""
    rows = _kb_call("project.list") or []
    out = []
    for r in rows:
        item = {}
        for src, dst in _KB_FIELDS.items():
            if src in r:
                item[dst] = r[src]
        item["gitLinked"] = item.get("importMode") in ("git-local", "git-remote")
        item["hasBaseline"] = bool(item.get("currentVersionId"))
        item["sourceDir"] = item.get("rootPath") or ""
        if "sourceCacheDir" in item and not item["sourceCacheDir"]:
            item["sourceCacheDir"] = None
        out.append(item)
    return out


def _lookup_kb(kb_id: str) -> Optional[dict]:
    for p in _list_kb_projects():
        if p["id"] == kb_id:
            return p
    return None


# ── 同一仓库源校验 ───────────────────────────────────────────────

def _norm_url(u: str) -> str:
    u = (u or "").strip()
    u = u.replace("git@", "").replace("ssh://", "")
    if ":" in u and "/" in u and not u.startswith("http"):
        u = u.replace(":", "/", 1)
    return u.rstrip("/").removesuffix(".git").lower()


def _git_origin(path: str) -> str:
    if not os.path.isdir(path):
        return ""
    try:
        r = subprocess.run(
            ["git", "-C", path, "remote", "get-url", "origin"],
            capture_output=True, text=True, timeout=10,
        )
        return (r.stdout or "").strip()
    except Exception:
        return ""


def _is_subpath(child: str, parent: str) -> bool:
    try:
        return os.path.commonpath([os.path.abspath(child), os.path.abspath(parent)]) == os.path.abspath(parent)
    except Exception:
        return False


def _same_repo_source(arch_root: str, kb: dict) -> tuple:
    """判定 architect 工作目录与 KB 源码为同一仓库源。返回 (ok, reason/error)。"""
    arch = os.path.abspath(str(arch_root))
    kb_root = kb.get("rootPath") or ""
    kb_cache = kb.get("sourceCacheDir") or ""
    kb_remote = kb.get("remoteUrl") or ""
    kb_local = kb.get("localRepoPath") or ""
    if kb_root and _is_subpath(arch, kb_root):
        return True, "architect 工作目录为 KB 源码目录或其子目录"
    if kb_cache and _is_subpath(arch, kb_cache):
        return True, "architect 工作目录位于 KB 源码缓存目录内"
    a_remote = _norm_url(_git_origin(arch))
    if a_remote:
        if kb_remote and _norm_url(kb_remote) == a_remote:
            return True, "git 远端一致"
        k_remote = _norm_url(_git_origin(kb_root))
        if k_remote and k_remote == a_remote:
            return True, "git 远端一致"
    if kb_local and os.path.abspath(kb_local) == arch:
        return True, "与 KB 本地仓库来源路径一致"
    return False, "architect 工作目录与所选 KB 项目不是同一仓库源（路径不重叠、git 远端/本地仓库路径不匹配）"


# ── 路由 ─────────────────────────────────────────────────────────

@router.get("/project/bound")
async def get_bound_project(root: Optional[str] = None, project: Optional[str] = None):
    return ok(_resolve_project(root, project))


def list_recent_projects() -> list:
    """arch_projects 全部项目排序：置顶 → 收藏 → 最近更新倒序。

    供 overview「近期项目」与 /project/list 共用。
    """
    rows = store.ProjectsStore.all()
    rows.sort(key=lambda p: (
        not bool(p.get("pinned")),         # 置顶优先
        not bool(p.get("favorite")),       # 收藏次之
        -(p.get("updatedAt") or p.get("createdAt") or 0),  # 最近更新在前
    ))
    return rows


@router.get("/project/list")
async def list_projects():
    """近期项目列表：arch_projects 全部项目(置顶→收藏→最近更新倒序)。"""
    return ok(list_recent_projects())


@router.post("/project/flag")
async def flag_project(request: Request):
    """置顶 / 收藏 切换(arch_projects 行更新)。

    Body: { root? 或 project?, pinned? 或 favorite? }，pinned/favorite 布尔置位。
    """
    body = await request.json() or {}
    proj = _resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    if not proj or not proj.get("id"):
        return err(400, "未定位到项目")
    patch = {}
    if "pinned" in body:
        patch["pinned"] = 1 if body["pinned"] else 0
    if "favorite" in body:
        patch["favorite"] = 1 if body["favorite"] else 0
    if not patch:
        return err(400, "缺少 pinned/favorite")
    patch["updatedAt"] = _ts()
    row = store.ProjectsStore.update(proj["id"], patch)
    return ok(row or proj)


@router.post("/project/delete")
async def delete_project(request: Request):
    """删除项目列表记录(可选同时删除 architect 相关的项目数据)。

    Body: { root? 或 project?, deleteData?: boolean }。
    - 默认只删除 arch_projects 行(列表记录)，项目源码/工作目录不受影响；
    - deleteData=true 时，同时删除该项目的 architect 相关数据(如架构快照记录)。
    """
    body = await request.json() or {}
    proj = _resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    if not proj or not proj.get("id"):
        return err(400, "未定位到项目")
    delete_data = bool(body.get("deleteData"))
    if delete_data:
        root = proj.get("rootPath") or ""
        db = store._db()
        db.execute("DELETE FROM arch_snapshot_records WHERE root_path = ?", (root,))
        db.commit()
    store.ProjectsStore.delete(proj["id"])
    return ok({"deleted": True, "deleteData": delete_data, "id": proj["id"]})


@router.post("/project/bound")
async def create_greenfield_project(request: Request):
    """Create a greenfield project."""
    body = await request.json()
    now = _ts()
    project = {
        "id": f"proj-{now:x}",
        "name": body.get("name", "新项目"),
        "desc": body.get("desc", ""),
        "rootPath": body.get("execRoot", ""),
        "kbRoot": body.get("kbRoot", ""),
        "branch": "main", "baselineId": None, "baselineCommit": "",
        "createdAt": now, "active": True,
        "config": {"estMinMin": 15, "estMinMax": 240, "acceptanceMax": 6, "p0SubsetMax": 4},
        "mode": "greenfield",
        "scaffold": {
            "language": body.get("language", ""),
            "framework": body.get("framework"),
            "moduleLayout": body.get("moduleLayout", "mono"),
        },
        "productForm": body.get("productForm"),
        "pinned": False, "favorite": False,
    }
    store.ProjectsStore.create(project)
    return ok(project)


@router.get("/project/kb/list")
async def list_kb_projects():
    """列出 KB 项目(选择关联源的候选)。返回含 gitLinked/hasBaseline/sourceDir 标注。"""
    return ok(_list_kb_projects())


@router.post("/project/bind")
async def bind_project(request: Request):
    """登记并打开一个 architect 项目(arch_projects 为唯一事实源)，可选关联 KB。

    - { execRoot, name? }                   → 仅工作目录(不关联 KB，KB 降级)；
    - { execRoot, kbProjectId, name? }      → 打开工作目录并关联 KB(先做同一仓库源校验)。
    """
    body = await request.json()
    exec_root = body.get("execRoot")
    if not exec_root:
        return err(400, "缺少 execRoot")
    root = str(exec_root).strip()
    if not root:
        return err(400, "工作目录不能为空")
    proj_id = _stable_proj_id(root)
    base = _resolve_project(root, None) or _synthesize(root)
    kb_id = body.get("kbProjectId") or body.get("projectId")
    if kb_id:
        kb = _lookup_kb(kb_id)
        if not kb:
            return err(400, "KB 项目中不存在该 id")
        if not kb.get("gitLinked") or not kb.get("hasBaseline"):
            return err(400, "该项目未 git 关联或尚无知识库基线，无法安全关联")
        ok_, reason = _same_repo_source(root, kb)
        if not ok_:
            return err(400, reason)
        store.ProjectsStore.upsert(proj_id, {
            "name": body.get("name") or base["name"], "desc": base["desc"],
            "rootPath": root, "kbRoot": kb.get("rootPath") or "",
            "branch": "main", "baselineId": kb.get("currentVersionId"),
            "baselineCommit": "", "createdAt": _ts(), "active": True,
            "config": base.get("config") or dict(_DEFAULT_CONFIG),
            "mode": "existing",
            "kbProjectId": kb["id"], "kbSourceDir": kb.get("rootPath") or "",
            "gitLinked": True, "linkVerifiedAt": _ts(),
        })
        return ok(_resolve_project(root, None))
    store.ProjectsStore.upsert(proj_id, {
        "name": body.get("name") or base["name"], "desc": base["desc"],
        "mode": "existing", "rootPath": root, "kbRoot": "",
        "branch": "main", "baselineId": None, "baselineCommit": "",
        "createdAt": _ts(), "active": True,
        "config": base.get("config") or dict(_DEFAULT_CONFIG),
        "gitLinked": False,
    })
    return ok(_resolve_project(root, None))


@router.post("/project/link")
async def link_project(request: Request):
    """项目页后补关联：把已打开的 architect 工作目录关联到 KB 项目(先同一仓库源校验)。"""
    body = await request.json()
    kb_id = body.get("kbProjectId")
    if not kb_id:
        return err(400, "缺少 kbProjectId")
    kb = _lookup_kb(kb_id)
    if not kb:
        return err(400, "KB 项目中不存在该 id")
    if not kb.get("gitLinked") or not kb.get("hasBaseline"):
        return err(400, "该项目未 git 关联或尚无知识库基线，无法安全关联")
    root = (body.get("execRoot") or body.get("root") or "").strip()
    proj = None
    if root:
        proj = _resolve_project(root, None)
    elif body.get("project"):
        proj = store.ProjectsStore.get(body["project"])
    if not proj or not proj.get("rootPath"):
        return err(400, "未定位到要关联的 architect 项目(缺 execRoot)")
    arch_root = proj["rootPath"]
    ok_, reason = _same_repo_source(arch_root, kb)
    if not ok_:
        return err(400, reason)
    data = {
        "name": proj.get("name") or arch_root.rstrip("/").rsplit("/", 1)[-1],
        "desc": proj.get("desc", ""), "mode": proj.get("mode", "existing"),
        "rootPath": arch_root,
        "kbRoot": kb.get("rootPath") or "", "kbSourceDir": kb.get("rootPath") or "",
        "baselineId": kb.get("currentVersionId"), "branch": "main",
        "gitLinked": True, "linkVerifiedAt": _ts(), "active": True,
        "config": proj.get("config") or dict(_DEFAULT_CONFIG),
        "createdAt": proj.get("createdAt") or _ts(), "updatedAt": _ts(),
    }
    store.ProjectsStore.upsert(proj["id"], data)
    return ok(_resolve_project(None, proj["id"]))


@router.post("/project/unlink")
async def unlink_project(request: Request):
    """解除 KB 关联(architect 项目保留，回到降级)。"""
    body = await request.json() or {}
    proj = _resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    if not proj or not proj.get("id"):
        return err(400, "未定位到已关联的 architect 项目")
    store.ProjectsStore.update(proj["id"], {
        "kbProjectId": "", "kbRoot": "", "kbSourceDir": "",
        "baselineId": None, "gitLinked": False, "linkVerifiedAt": 0,
        "updatedAt": _ts(),
    })
    return ok(_resolve_project(None, proj["id"]) or _resolve_project(body.get("root"), None))


@router.post("/project/unbind")
async def unbind_project():
    """解除选择。选择持久化在 URL，由前端清除；此处仅作空操作。"""
    return ok(True)


@router.get("/project/status")
async def get_project_status(root: Optional[str] = None, project: Optional[str] = None):
    if not _resolve_project(root, project):
        return ok(None)
    return ok({
        "baseline": {
            "id": "baseline_id = N", "version": "v0.0.1", "commit": BASELINE_COMMIT,
            "manifestHash": "sha256:9f7...c21", "createdAt": _ts() - 86400000 * 3,
        },
        "head": {"commit": "a1b2c3d4e5f6", "branch": "main", "ahead": 6},
        "diff": {
            "filesChanged": 5, "added": 2, "modified": 3, "deleted": 0,
            "deletedHighRisk": False, "files": [
                "order-service/order.go", "order-service/service.go",
                "order-service/close.go", "outbox-service/relay.go",
                "tests/integration_test.go",
            ],
        },
        "lastRebaseline": None,
    })


@router.get("/project/overview")
async def get_project_overview(root: Optional[str] = None, project: Optional[str] = None):
    """项目概览(工作区首页)：工作目录、远端仓库、知识库关联、基线、相对基线的代码变更与组件变更。"""
    proj = _resolve_project(root, project)
    if not proj:
        return ok(None)
    from . import arch_git
    work_dir = proj.get("rootPath") or ""
    remote = _git_origin(work_dir)
    st = arch_git.repo_status(work_dir)
    diff = arch_git.diff_worktree(proj) if work_dir else {
        "filesChanged": 0, "added": 0, "modified": 0, "deleted": 0,
        "deletedHighRisk": False, "files": [], "byComponent": []}
    return ok({
        "workDir": work_dir,
        "remoteUrl": remote or proj.get("remoteUrl") or "",
        "branch": proj.get("branch") or st.get("branch") or "",
        "defaultBranch": proj.get("defaultBranch") or "",
        "head": {"commit": st.get("commit") or "", "branch": st.get("branch") or "",
                 "ahead": st.get("ahead", 0), "behind": st.get("behind", 0),
                 "dirty": bool(st.get("dirty"))},
        "kb": {
            "linked": bool(proj.get("kbProjectId")),
            "kbProjectId": proj.get("kbProjectId"),
            "kbSourceDir": proj.get("kbSourceDir"),
            "kbRoot": proj.get("kbRoot"),
            "linkVerifiedAt": proj.get("linkVerifiedAt"),
        },
        "baseline": {
            "id": proj.get("baselineId"),
            "commit": proj.get("baselineCommit") or "",
            "exists": bool(proj.get("baselineCommit") or proj.get("baselineId")),
        },
        "diff": {"filesChanged": diff["filesChanged"], "added": diff["added"],
                 "modified": diff["modified"], "deleted": diff["deleted"],
                 "deletedHighRisk": diff["deletedHighRisk"],
                 "files": diff["files"], "byComponent": diff["byComponent"]},
    })


@router.get("/project/snapshots")
async def get_snapshots(root: Optional[str] = None, project: Optional[str] = None):
    if not _resolve_project(root, project):
        return ok([])
    now = _ts()
    model = build_architecture_model()
    return ok([
        {"id": "snap-v0", "name": "基线快照", "version": "v0",
         "createdAt": now - 86400000 * 3, "model": model},
        {"id": "snap-v1", "name": "当前快照", "version": "v1",
         "createdAt": now, "model": model},
    ])


@router.post("/project/snapshots")
async def create_snapshot(request: Request, root: Optional[str] = None, project: Optional[str] = None):
    body = await request.json()
    resolved = _resolve_project(root, project)
    if not resolved:
        return err(400, "未绑定项目，无法创建架构快照")
    snap_id = store.next_id("snap")
    now = _ts()
    db = store._db()
    db.execute(
        "INSERT INTO arch_snapshot_records (id, name, version, task_id, git_branch, git_commit, model, root_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snap_id, body.get("name", "架构快照"), body.get("version", "v1"),
         body.get("taskId", "manual"), body.get("branch", "main"),
         body.get("commit", BASELINE_COMMIT),
         store._dumps(body.get("model") or build_architecture_model()),
         resolved.get("rootPath") or "", now),
    )
    db.commit()
    return ok({"id": snap_id, "name": body.get("name", "架构快照"),
               "version": body.get("version", "v1"),
               "createdAt": now, "model": body.get("model") or build_architecture_model()})


@router.get("/project/baseline/meta")
async def get_baseline_meta():
    return ok({
        "gitTag": "v1.0.0-order-service", "branch": "main",
        "gitDate": _ts() - 86400000 * 3, "analyzedAt": _ts() - 86400000 * 3,
        "archVersion": "v1", "commit": BASELINE_COMMIT,
        "desc": "订单领域服务（示例）",
    })


@router.get("/project/baseline/dirty")
async def get_baseline_dirty():
    return ok({"dirty": True})


@router.post("/project/baseline/sync")
async def sync_baseline(request: Request):
    body = await request.json()
    return ok({
        "success": True, "commit": body.get("commit", BASELINE_COMMIT),
        "baselineId": "baseline_id = N+1",
    })


@router.patch("/project/config")
async def update_project_config(request: Request, root: Optional[str] = None, project: Optional[str] = None):
    patch = await request.json()
    resolved = _resolve_project(root, project)
    if not resolved:
        return err(400, "未绑定项目")
    config = dict(resolved.get("config") or {})
    config.update(patch)
    row = store.ProjectsStore.update(resolved["id"], {"config": config, "updatedAt": _ts()})
    return ok(row or {**resolved, "config": config})