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

from ..common import _ts, ok, err, build_architecture_model
from .. import store

from ..agent.governance.timeouts import get as _timeout_of
# KB 关联子系统已拆出(§8.2); re-export 兼容 overview/dirs/engine 既有引用
from .kb_link import (  # noqa: E402,F401
    _DEFAULT_CONFIG, _KB_FIELDS, _kb_call, _list_kb_projects, _lookup_kb,
    _kb_baseline_head, _norm_url, _git_origin, _is_subpath,
    _classify_kb_source, _same_repo_source, _match_kb_candidates,
    link_arch_to_kb,
)
router = APIRouter()


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


def resolve_project(root: Optional[str] = None, project_id: Optional[str] = None) -> Optional[dict]:
    """按 URL 解析当前项目(arch_projects 为唯一事实源):
    - project=<architect行id>: 读 `arch_projects` 行;
    - project=<KB pid>(对话链路透传 proj-xxx): 按 kbProjectId 反查绑定行——
      双 id 体系兼容(KB 对话上下文只携带 KB pid，若按行 id 查不到就降级，
      组件目录/提取会静默走空，实测 topoOne-animation 提取 count:0 回归)；
    - root=<path>: 优先 get_by_root；未登记路径 → 临时合成的工作目录项目(降级，不再按路径猜 KB)。
    """
    if project_id:
        row = store.ProjectsStore.get(project_id)
        if row is not None:
            return row
        for r in store.ProjectsStore.all():
            if r.get("kbProjectId") == project_id:
                return r
        if root:
            root = str(root).strip()
            if root:
                return store.ProjectsStore.get_by_root(root) or _synthesize(root)
        return None
    if root:
        root = str(root).strip()
        if not root:
            return None
        row = store.ProjectsStore.get_by_root(root)
        if row:
            return row
        return _synthesize(root)
    return None


def kb_degraded(root: Optional[str] = None, project_id: Optional[str] = None) -> bool:
    """是否降级: 无项目 或 项目无 KB 基线(工作目录直开/无 KB 内容支撑)。

    项目选择持久化在 URL(?root=/?project=)，由前端随请求透传 root/project。
    全插件 KB 相关 API 共用的判定口径(requirements/arch_change/knowledge 复用)。
    """
    try:
        proj = resolve_project(root, project_id)
    except Exception:
        return True
    return not (proj and proj.get("baselineId"))

@router.get("/project/bound")
async def get_bound_project(root: Optional[str] = None, project: Optional[str] = None):
    return ok(resolve_project(root, project))


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
    proj = resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
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


@router.post("/project/rename")
async def rename_project(request: Request):
    """项目改名(仅 architect 本地 arch_projects，不联动 KB)。

    Body: { name, root?/execRoot? 或 project? }。
    名字独立保存在 arch_projects 行；KB(知识库)侧项目名不受影响。
    """
    body = await request.json() or {}
    name = str(body.get("name") or "").strip()
    if not name:
        return err(400, "项目名不能为空")
    proj = resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    if not proj or not proj.get("id"):
        return err(400, "未定位到项目")
    row = store.ProjectsStore.update(proj["id"], {"name": name, "updatedAt": _ts()})
    if not row:
        # 临时工作目录(_synthesize, 未入库)不支持改名——请先通过「打开工作目录」导入
        return err(400, "项目未登记(临时工作目录)，请先导入后再改名")
    return ok(row)


@router.post("/project/delete")
async def delete_project(request: Request):
    """删除项目列表记录(可选同时删除 architect 相关的项目数据)。

    Body: { root? 或 project?, deleteData?: boolean }。
    - 默认只删除 arch_projects 行(列表记录)，项目源码/工作目录不受影响；
    - deleteData=true 时，同时删除该项目的 architect 相关数据(如架构快照记录)。
    """
    body = await request.json() or {}
    proj = resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    if not proj or not proj.get("id"):
        return err(400, "未定位到项目")
    delete_data = bool(body.get("deleteData"))
    if delete_data:
        # 项目库整体删除(architect/<pid>/arch.db，含快照记录等全部项目数据)
        from .. import ctx as _ctx
        _ctx.delete_project_db(proj["id"])
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
    # 导入即补 .gitignore：topoCode 自身数据目录不入项目代码
    from . import arch_git
    arch_git.ensure_gitignore_entries(project["rootPath"])
    store.ProjectsStore.create(project)
    return ok(project)


@router.get("/project/kb/list")
async def list_kb_projects():
    """列出 KB 项目(选择关联源的候选)。返回含 gitLinked/hasBaseline/sourceDir 标注。"""
    return ok(_list_kb_projects())


@router.get("/project/kb/match")
async def match_kb_projects(root: Optional[str] = None, project: Optional[str] = None):
    """按当前项目工作目录为可用知识库匹配可关联的 KB 候选。

    - 主参数为工作主目录(git 本地仓库/源码路径重叠) → `local` 组；
    - 辅参数为远端仓库地址(仅当工作目录与 KB 都配置了远端时生效) → `remote` 组；
    - 两组同时返回；未命中对应组为空数组，由前端逐组标明「无」。
    """
    proj = resolve_project(root, project)
    if not proj or not proj.get("rootPath"):
        return err(400, "未定位到工作目录")
    return ok(_match_kb_candidates(proj["rootPath"]))


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
    # 导入即补 .gitignore：topoCode 自身数据目录(.topocode/.codegraph)不入项目代码
    from . import arch_git
    arch_git.ensure_gitignore_entries(root)
    proj_id = _stable_proj_id(root)
    base = resolve_project(root, None) or _synthesize(root)
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
        # 基线提交：取 KB 基线版本 head（变更检测的 diff base），branch 用真实分支
        baseline_id = kb.get("currentVersionId")
        baseline_head = _kb_baseline_head(kb["id"], baseline_id)
        real_branch = (arch_git.repo_status(root) or {}).get("branch") or "main"
        store.ProjectsStore.upsert(proj_id, {
            "name": body.get("name") or base["name"], "desc": base["desc"],
            "rootPath": root, "kbRoot": kb.get("rootPath") or "",
            "branch": real_branch, "baselineId": baseline_id,
            "baselineCommit": baseline_head, "createdAt": _ts(), "active": True,
            "config": base.get("config") or dict(_DEFAULT_CONFIG),
            "mode": "existing",
            "kbProjectId": kb["id"], "kbSourceDir": kb.get("rootPath") or "",
            "gitLinked": True, "linkVerifiedAt": _ts(),
        })
        return ok(resolve_project(root, None))
    store.ProjectsStore.upsert(proj_id, {
        "name": body.get("name") or base["name"], "desc": base["desc"],
        "mode": "existing", "rootPath": root, "kbRoot": "",
        "branch": "main", "baselineId": None, "baselineCommit": "",
        "createdAt": _ts(), "active": True,
        "config": base.get("config") or dict(_DEFAULT_CONFIG),
        "gitLinked": False,
    })
    return ok(resolve_project(root, None))


@router.post("/project/link")
async def link_project(request: Request):
    """项目页后补关联：把已打开的 architect 工作目录关联到 KB 项目(先同一仓库源校验)。"""
    body = await request.json()
    kb_id = body.get("kbProjectId")
    if not kb_id:
        return err(400, "缺少 kbProjectId")
    root = (body.get("execRoot") or body.get("root") or "").strip()
    proj = None
    if root:
        proj = resolve_project(root, None)
    elif body.get("project"):
        proj = store.ProjectsStore.get(body["project"])
    if not proj or not proj.get("rootPath"):
        return err(400, "未定位到要关联的 architect 项目(缺 execRoot)")
    ok_, data = link_arch_to_kb(proj, kb_id, refresh_ttl=0)
    if not ok_:
        return err(400, data)
    return ok(data)


@router.get("/project/git-info")
async def git_info(request: Request):
    """工作目录 git 状态轻量探测(概览页初始化卡片): 不依赖 KB 关联。"""
    body_root = request.query_params.get("root") or request.query_params.get("execRoot") or ""
    proj = resolve_project(body_root or None, request.query_params.get("project"))
    root = (proj or {}).get("rootPath") or body_root
    if not root or not os.path.isdir(root):
        return ok({"isRepo": False, "root": root or ""})
    from . import arch_git
    if not arch_git.is_git_repo(root):
        return ok({"isRepo": False, "root": root})
    st = arch_git.repo_status(root)
    return ok({"isRepo": True, "root": root, "branch": st.get("branch", ""),
               "head": st.get("commit", ""), "dirty": st.get("dirty", False)})


@router.post("/project/init-git")
async def init_git_repo(request: Request):
    """自动初始化工作目录 git 仓库(概览页按钮授权; 已是 repo 则幂等返回)。"""
    body = await request.json() or {}
    proj = resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    root = (proj or {}).get("rootPath") or (body.get("root") or "").strip()
    if not root or not os.path.isdir(root):
        return err(400, "工作目录不存在")
    from . import arch_git
    if arch_git.is_git_repo(root):
        st = arch_git.repo_status(root)
        return ok({"alreadyRepo": True, "branch": st.get("branch", ""),
                   "head": st.get("commit", "")})
    head_branch = arch_git.ensure_git_repo(root)
    store.ProjectsStore.update(proj["id"], {"branch": head_branch.get("branch", "main"),
                                            "updatedAt": _ts()}) if proj else None
    return ok({"initialized": True, **head_branch})


@router.post("/project/unlink")
async def unlink_project(request: Request):
    """解除 KB 关联(architect 项目保留，回到降级)。"""
    body = await request.json() or {}
    proj = resolve_project(body.get("root") or body.get("execRoot"), body.get("project"))
    if not proj or not proj.get("id"):
        return err(400, "未定位到已关联的 architect 项目")
    store.ProjectsStore.update(proj["id"], {
        "kbProjectId": "", "kbRoot": "", "kbSourceDir": "",
        "baselineId": None, "gitLinked": False, "linkVerifiedAt": 0,
        "updatedAt": _ts(),
    })
    return ok(resolve_project(None, proj["id"]) or resolve_project(body.get("root"), None))


@router.post("/project/unbind")
async def unbind_project():
    """解除选择。选择持久化在 URL，由前端清除；此处仅作空操作。"""
    return ok(True)


@router.get("/project/status")
async def get_project_status(root: Optional[str] = None, project: Optional[str] = None):
    proj = resolve_project(root, project)
    if not proj:
        return ok(None)
    if not proj.get("baselineId"):
        # 未关联知识库 → 无基线状态(返回 None)，由前端提示降级。
        return ok(None)
    from . import arch_git
    work_dir = proj.get("rootPath") or ""
    st = arch_git.repo_status(work_dir) if work_dir else {}
    head = {
        "commit": arch_git.head_commit(work_dir) if work_dir else "",
        "branch": st.get("branch", ""),
        "ahead": st.get("ahead", 0),
    }
    # 基线提交：存量数据 baselineCommit 可能为空 → 按 baselineId 从 KB 版本补齐并惰性回写
    baseline_head = proj.get("baselineCommit") or ""
    kb_project_id = proj.get("kbProjectId") or ""
    version = ""
    if kb_project_id:
        try:
            from ..kb_gateway import call_kb
            versions = call_kb("version.list", projectId=kb_project_id) or []
        except Exception:
            versions = []
        matched = None
        if versions:
            matched = next((v for v in versions if v.get("id") == proj.get("baselineId")), None) or versions[0]
            version = matched.get("label") or matched.get("id") or ""
            if not baseline_head:
                baseline_head = matched.get("head") or ""
    if baseline_head and not proj.get("baselineCommit"):
        try:
            store.ProjectsStore.update(proj["id"], {"baselineCommit": baseline_head, "updatedAt": _ts()})
            proj = {**proj, "baselineCommit": baseline_head}
        except Exception:
            pass
    diff_raw = arch_git.diff_worktree(proj, base=baseline_head) if work_dir else {
        "filesChanged": 0, "added": 0, "modified": 0, "deleted": 0,
        "deletedHighRisk": False, "files": []}
    diff = {
        "filesChanged": diff_raw.get("filesChanged", 0),
        "added": diff_raw.get("added", 0),
        "modified": diff_raw.get("modified", 0),
        "deleted": diff_raw.get("deleted", 0),
        "deletedHighRisk": diff_raw.get("deletedHighRisk", False),
        "files": [f.get("path") if isinstance(f, dict) else str(f)
                  for f in diff_raw.get("files", [])],
    }
    baseline = {
        "id": proj.get("baselineId") or "",
        "version": version,
        "commit": baseline_head or proj.get("baselineCommit") or "",
        "manifestHash": "",
        "createdAt": 0,
    }
    return ok({
        "baseline": baseline,
        "head": head,
        "diff": diff,
        "lastRebaseline": None,
    })


def _comp_depth(comp_id: str, by_id: dict) -> int:
    """组件在 parentId 链上的深度(根=0)；带环保护(访问过即止)。"""
    depth, cur, seen = 0, comp_id, set()
    while cur:
        if cur in seen:
            break
        seen.add(cur)
        parent = (by_id.get(cur) or {}).get("parentId") or ""
        if not parent or parent not in by_id:
            break
        depth += 1
        cur = parent
    return depth


def _by_kb_components(files: list, proj: dict) -> list:
    """按 KB 组件汇总工作树变更(概览页「组件变更情况」口径)。

    - 文件归属：按组件 owns 匹配，命中多个时归入最深(最具体)组件，父层经上卷获得；
    - 展示名：KB 有 name 用 name，没有用组件 id；未命中任何组件 → 「未归属」桶；
    - 层级汇总：父子层级向上上卷，父组件的 added/modified/deleted/files 含全部子孙；
    - KB 未关联/不可达/无组件 → 空列表(前端降级文案)；
    - 只保留子树内有变更的组件，输出按层级 DFS 先序(父先于子)。
    """
    kb_id = proj.get("kbProjectId") or ""
    if not kb_id:
        return []
    try:
        # 组件目录(architecture.catalog)：唯一 id + parentId + owns，含 L0-L2 父子层级。
        # ⚠️ 不用 architecture.model——其 components 被拍平(parentId 丢失、id 序号重复)，
        # 无法构建组件树(实测 nginx-src：catalog 99 组件带层级 vs model 21 组件 id 重复)。
        from ..common import build_component_catalog
        catalog = build_component_catalog(proj.get("rootPath"), proj.get("id"))
        comps = catalog.get("components") or []
    except Exception:
        return []
    by_id = {c.get("id"): c for c in comps if c.get("id")}
    if not by_id:
        return []
    depth = {cid: _comp_depth(cid, by_id) for cid in by_id}
    children = {cid: [] for cid in by_id}
    for cid, c in by_id.items():
        pid = c.get("parentId") or ""
        if pid in by_id:
            children[pid].append(cid)

    # 路径对齐：catalog owns 相对 KB 镜像根(仓库根)，变更文件相对 architect 工作目录
    # (可能是仓库的子目录，如 nginx-src/src)。双向后缀匹配兼容两种基准。
    def _owns_match(owned: str, changed: str) -> bool:
        return (owned == changed
                or owned.endswith("/" + changed)
                or changed.endswith("/" + owned))

    def _owner_of(path: str) -> str:
        from ..sem.paths import _norm_path
        p = _norm_path(path)
        owners = [cid for cid, c in by_id.items()
                  if any(_owns_match(_norm_path(o), p) for o in (c.get("owns") or []))]
        return max(owners, key=lambda cid: depth[cid]) if owners else "__unowned__"

    own = {cid: {"added": 0, "modified": 0, "deleted": 0, "files": []} for cid in by_id}
    unowned = {"added": 0, "modified": 0, "deleted": 0, "files": []}
    fstatus: dict = {}   # path -> A/M/D(独占计数用)
    for f in files:
        path = f.get("path") if isinstance(f, dict) else str(f)
        status = f.get("status") if isinstance(f, dict) else ""
        target = _owner_of(path)
        bucket = own.get(target) or unowned
        bucket["files"].append(path)
        fstatus[path] = status
        if status == "A":
            bucket["added"] += 1
        elif status == "D":
            bucket["deleted"] += 1
        else:
            bucket["modified"] += 1

    # 自底向上上卷：深组件先处理，其已累计的合计再加给父组件
    agg = {cid: {"added": own[cid]["added"], "modified": own[cid]["modified"],
                 "deleted": own[cid]["deleted"], "fileset": set(own[cid]["files"])}
           for cid in by_id}
    for cid in sorted(by_id, key=lambda c: depth[c], reverse=True):
        pid = (by_id[cid].get("parentId") or "")
        if pid in agg and pid != cid:
            agg[pid]["added"] += agg[cid]["added"]
            agg[pid]["modified"] += agg[cid]["modified"]
            agg[pid]["deleted"] += agg[cid]["deleted"]
            agg[pid]["fileset"] |= agg[cid]["fileset"]

    # 独占文件 = 自身归属且未被任何子孙覆盖。文件清单只在叶子完整列出，
    # 上级组件仅列未被子组件覆盖的文件(消重复)；增/改/删 chips 仍为子树上卷合计。
    def _desc_files(cid: str) -> set:
        out: set = set()
        stack = list(children[cid])
        while stack:
            ch = stack.pop()
            out |= set(own[ch]["files"])
            stack.extend(children[ch])
        return out

    excl_cache: dict = {}

    def _exclusive(cid: str) -> dict:
        if cid not in excl_cache:
            desc = _desc_files(cid)
            excl = [f for f in own[cid]["files"] if f not in desc]
            cnt = {"added": 0, "modified": 0, "deleted": 0}
            for f in excl:
                st = fstatus.get(f)
                cnt["added" if st == "A" else "deleted" if st == "D" else "modified"] += 1
            excl_cache[cid] = {"files": sorted(excl), **cnt}
        return excl_cache[cid]

    out: list = []

    def _emit(cid: str, level: int, seen: set):
        if cid in seen:
            return
        seen.add(cid)
        a = agg[cid]
        if a["added"] or a["modified"] or a["deleted"]:
            ex = _exclusive(cid)
            # KB 未解析的组件(named=False，name 为路径族推导的临时名如 "src") → 显示组件 ID
            comp_meta = by_id[cid]
            disp_name = (comp_meta.get("name") or "").strip()
            if not comp_meta.get("named", True) or not disp_name:
                disp_name = cid
            out.append({
                "id": cid, "name": disp_name,
                "parentId": comp_meta.get("parentId") or "", "level": level,
                # files/added/modified/deleted = 自身独占(未被子孙覆盖，消重复)
                "files": ex["files"],
                "added": ex["added"], "modified": ex["modified"], "deleted": ex["deleted"],
                # 子树上卷合计(父含子，供 chips 汇总展示)
                "totalAdded": a["added"], "totalModified": a["modified"],
                "totalDeleted": a["deleted"], "totalFiles": len(a["fileset"]),
            })
        for ch in children[cid]:
            _emit(ch, level + 1, seen)

    for cid in by_id:
        pid = by_id[cid].get("parentId") or ""
        if pid not in by_id:
            _emit(cid, 0, set())
    if unowned["files"]:
        out.append({"id": "__unowned__", "name": "", "parentId": "", "level": 0,
                    "added": unowned["added"], "modified": unowned["modified"],
                    "deleted": unowned["deleted"], "files": unowned["files"],
                    "totalAdded": unowned["added"], "totalModified": unowned["modified"],
                    "totalDeleted": unowned["deleted"], "totalFiles": len(unowned["files"])})
    return out


def _looks_like_remote_url(url: str) -> bool:
    """区分远端仓库地址与本地路径：URL scheme(git/ssh/http[s]) 或 scp 形如 user@host:path
    才算远端；纯文件路径(如 KB git-local 导入写进 remote_url 的源目录)不算。"""
    u = (url or "").strip()
    if not u:
        return False
    import re
    if re.match(r"^(https?|ssh|git|ftps?)://", u, re.I):
        return True
    if u.startswith("git@"):
        return True
    # scp 形式 user@host:path(排除 Windows 盘符 C:\ 与纯相对路径)
    return bool(re.match(r"^[^/@\\]+@[^/\\]+:[^/]", u)) and not re.match(r"^[A-Za-z]:[\\/]", u)


@router.get("/project/overview")
async def get_project_overview(root: Optional[str] = None, project: Optional[str] = None):
    """项目概览(工作区首页)：工作目录、远端仓库、知识库关联、基线、相对基线的代码变更与组件变更。

    组件变更(byComponent)按 KB 组件目录(architecture.catalog)的父子层级输出：
    文件经 owns 归属(最深组件)；文件清单只在叶子完整列出，父组件仅列未被子组件
    覆盖的独占文件(files/added/modified/deleted)，另附子树上卷合计(total*)；未归属
    文件归「__unowned__」分组。
    """
    proj = resolve_project(root, project)
    if not proj:
        return ok(None)
    from . import arch_git
    work_dir = proj.get("rootPath") or ""
    remote = _git_origin(work_dir)
    # 仓库类型：git origin 存在且形如远端 URL → remote；否则本地仓库。
    # KB 的 remote_url 字段在 git-local 导入时会写入本地路径，禁止直接当远端展示。
    if not _looks_like_remote_url(remote):
        remote = ""
    st = arch_git.repo_status(work_dir)
    # 基线提交兜底：存量数据为空时按 baselineId 从 KB 版本取 head，并惰性回写
    baseline_head = proj.get("baselineCommit") or ""
    if not baseline_head and proj.get("kbProjectId") and proj.get("baselineId"):
        baseline_head = _kb_baseline_head(proj["kbProjectId"], proj["baselineId"])
        if baseline_head:
            try:
                store.ProjectsStore.update(proj["id"], {"baselineCommit": baseline_head, "updatedAt": _ts()})
                proj = {**proj, "baselineCommit": baseline_head}
            except Exception:
                pass
    diff = arch_git.diff_worktree(proj, base=baseline_head) if work_dir else {
        "filesChanged": 0, "added": 0, "modified": 0, "deleted": 0,
        "deletedHighRisk": False, "files": [], "byComponent": []}
    # KB 绑定健康检测：architect 端已绑定，但 KB 端项目可能已被删除
    # (kbReachable=None 表示 KB 服务不可达，无法判定；kbExists=False 才是"KB 端已删除")
    kb_health = {"kbReachable": None, "kbExists": None, "kbProjectName": ""}
    kb_view = {"mounted": 0, "coveragePct": None, "viewVersion": 0, "stale": False}
    if proj.get("kbProjectId"):
        rows = _kb_call("project.list")
        kb_health["kbReachable"] = rows is not None
        matched = next((p for p in (rows or []) if p.get("id") == proj["kbProjectId"]), None)
        if rows is not None:
            kb_health["kbExists"] = matched is not None
        kb_health["kbProjectName"] = (matched or {}).get("name") or ""
        # 基线视图摘要：对外生效任务数/覆盖率/stale（architect 不感知任务，仅看视图代际）
        if matched is not None:
            try:
                from ..kb_gateway import call_kb
                summary = call_kb("view.summary", projectId=proj["kbProjectId"])
            except Exception:
                summary = None
            if isinstance(summary, dict):
                kb_view = {
                    "mounted": len(summary.get("mountedTaskIds") or []),
                    "coveragePct": summary.get("coveragePct"),
                    "viewVersion": summary.get("viewVersion") or 0,
                    "stale": bool(summary.get("stale")),
                }
    return ok({
        "workDir": work_dir,
        # 仅真实远端 URL(git origin)；本地仓库为空串，仓库类型见 repoKind
        "remoteUrl": remote,
        "repoKind": "remote" if remote else "local",
        "branch": st.get("branch") or proj.get("branch") or "",
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
            **kb_health,
            "kbView": kb_view,
        },
        "baseline": {
            "id": proj.get("baselineId"),
            "commit": proj.get("baselineCommit") or "",
            "exists": bool(proj.get("baselineCommit") or proj.get("baselineId")),
        },
        "diff": {"filesChanged": diff["filesChanged"], "added": diff["added"],
                 "modified": diff["modified"], "deleted": diff["deleted"],
                 "deletedHighRisk": diff["deletedHighRisk"],
                 "files": diff["files"],
                 "byComponent": _by_kb_components(diff.get("files") or [], proj)},
    })


@router.get("/project/snapshots")
async def get_snapshots(root: Optional[str] = None, project: Optional[str] = None):
    proj = resolve_project(root, project)
    if not proj or not proj.get("baselineId"):
        # 未关联知识库 → 无基线快照可读，返回空列表(前端提示降级)。
        return ok([])
    now = _ts()
    model = build_architecture_model(root, project)
    return ok([
        {"id": "snap-v0", "name": "基线快照", "version": "v0",
         "createdAt": now - 86400000 * 3, "model": model},
        {"id": "snap-v1", "name": "当前快照", "version": "v1",
         "createdAt": now, "model": model},
    ])


@router.post("/project/snapshots")
async def create_snapshot(request: Request, root: Optional[str] = None, project: Optional[str] = None):
    body = await request.json()
    resolved = resolve_project(root, project)
    if not resolved:
        return err(400, "未绑定项目，无法创建架构快照")
    snap_id = store.next_id("snap")
    now = _ts()
    from . import arch_git
    work_dir = resolved.get("rootPath") or ""
    commit = (body.get("commit") or "").strip() or (arch_git.head_commit(work_dir) if work_dir else "")
    branch = (body.get("branch") or "").strip()
    if not branch:
        branch = (arch_git.repo_status(work_dir) or {}).get("branch", "main") if work_dir else "main"
    db = store._target_db("arch_snapshot_records")
    db.execute(
        "INSERT INTO arch_snapshot_records (id, name, version, task_id, git_branch, git_commit, model, root_path, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snap_id, body.get("name", "架构快照"), body.get("version", "v1"),
         body.get("taskId", "manual"), branch, commit,
         store._dumps(body.get("model") or build_architecture_model(root, project)),
         resolved.get("rootPath") or "", now),
    )
    db.commit()
    return ok({"id": snap_id, "name": body.get("name", "架构快照"),
               "version": body.get("version", "v1"),
               "createdAt": now, "model": body.get("model") or build_architecture_model(root, project)})


@router.get("/project/baseline/meta")
async def get_baseline_meta(root: Optional[str] = None, project: Optional[str] = None):
    proj = resolve_project(root, project)
    if not proj or not proj.get("baselineId"):
        return err(400, "未关联知识库，无法读取基线信息。请在项目概览「查找关联」中关联知识库后重试。")
    from . import arch_git
    work_dir = proj.get("rootPath") or ""
    st = arch_git.repo_status(work_dir) if work_dir else {}
    name = proj.get("name") or ""
    return ok({
        "gitTag": f"v1.0.0-{name}" if name else "v1.0.0",
        "branch": st.get("branch") or proj.get("branch") or "main",
        "gitDate": 0, "analyzedAt": 0,
        "archVersion": "v1",
        "commit": proj.get("baselineCommit") or "",
        "desc": proj.get("desc") or "",
    })


@router.get("/project/baseline/dirty")
async def get_baseline_dirty(root: Optional[str] = None, project: Optional[str] = None):
    proj = resolve_project(root, project)
    if not proj or not proj.get("baselineId"):
        return err(400, "未关联知识库，无法读取基线状态。")
    from . import arch_git
    work_dir = proj.get("rootPath") or ""
    st = arch_git.repo_status(work_dir) if work_dir else {}
    # dirty 语义：相对 KB 基线提交存在任何差异（含已提交+未提交），或本地领先 upstream。
    # 不依赖 @{upstream}：无 remote 的本地仓库此前恒判"干净"。
    baseline_head = proj.get("baselineCommit") or _kb_baseline_head(
        proj.get("kbProjectId") or "", proj.get("baselineId") or "")
    if baseline_head and work_dir:
        diff = arch_git.diff_worktree(proj, base=baseline_head)
        dirty = bool(diff.get("filesChanged")) or bool(st.get("ahead", 0))
    else:
        dirty = bool(st.get("dirty")) or bool(st.get("ahead", 0))
    return ok({"dirty": bool(dirty)})


@router.post("/project/baseline/sync")
async def sync_baseline(request: Request):
    body = await request.json() or {}
    root = body.get("root") or request.query_params.get("root")
    project = body.get("project") or request.query_params.get("project")
    proj = resolve_project(root, project)
    if not proj or not proj.get("baselineId"):
        return err(400, "未关联知识库，无法同步基线。请在项目概览「查找关联」中关联知识库后重试。")
    from . import arch_git
    work_dir = proj.get("rootPath") or ""
    head = arch_git.head_commit(work_dir) if work_dir else ""
    commit = (body.get("commit") or head).strip()
    # 如实返回真实 commit + 项目当前 baselineId（不伪造新基线号）。
    return ok({
        "success": True, "commit": commit,
        "baselineId": proj.get("baselineId") or "",
    })


@router.patch("/project/config")
async def update_project_config(request: Request, root: Optional[str] = None, project: Optional[str] = None):
    patch = await request.json()
    resolved = resolve_project(root, project)
    if not resolved:
        return err(400, "未绑定项目")
    config = dict(resolved.get("config") or {})
    config.update(patch)
    row = store.ProjectsStore.update(resolved["id"], {"config": config, "updatedAt": _ts()})
    return ok(row or {**resolved, "config": config})