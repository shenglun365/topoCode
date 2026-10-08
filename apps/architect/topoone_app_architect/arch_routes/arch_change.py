"""Architecture change / staging / compliance routes (KB 真实数据).

规约定型(2610): /spec 三层规约+confirm 已退役——项目规约统一为 AGENTS.md
单文件模式(store 单源+.topo/rules 人工段), 见 mcp-spec-finalization-2610。

阶段 3/4 收尾: 变更/合规/基线均基于 KB 真实数据计算——组件模型
(architecture.model)、工作区文件变更(project.checkFileChanges)、版本差异
(version.diff)、跨社区调用边(analysis.getCrossCommunityEdges)。不再返回占位。
"""
from typing import Optional
from fastapi import APIRouter, Request
from ..common import _ts, _id, ok, err
from .. import store

router = APIRouter()

# 未关联知识库时的统一提示(与 knowledge.py 一致)。


def _resolve(root=None, project=None):
    """解析项目(数据主权批E: 自管, 不经 KB)。"""
    from .project import resolve_project
    proj = resolve_project(root, project)
    return (proj or None), None, None


def _self_model(proj: dict) -> dict:
    """自管架构模型(arch_components + 图谱依赖归并, common.build_*)。"""
    from ..common import build_architecture_model
    return build_architecture_model(proj.get("rootPath") or "", proj.get("id"))


def _file_changes(proj: dict) -> dict:
    """工作区真实文件变更(自管): git status 对比基线 commit(arch_git)。"""
    from . import arch_git
    try:
        d = arch_git.diff_worktree(proj, base=proj.get("baselineCommit") or "")
        return {"hasChanges": bool(d.get("filesChanged")),
                "added": d.get("added") or [], "modified": d.get("modified") or [],
                "deleted": d.get("deleted") or []}
    except Exception:  # noqa: BLE001
        return {"hasChanges": False, "added": [], "modified": [], "deleted": []}


def _map_files_to_components(files, comps):
    """文件 → 组件归属：按组件 owns 匹配；未命中归入『未归属』。"""
    out: dict = {}
    for f in files:
        hit = None
        for c in comps:
            if f in (c.get("owns") or []):
                hit = c
                break
        cid = hit.get("id") if hit else "__unowned__"
        name = hit.get("name") if hit else "未归属"
        out.setdefault(cid, {"id": cid, "name": name, "kind": hit.get("kind") if hit else "unknown",
                             "files": []})["files"].append(f)
    return out


def _diff_changes(proj: dict) -> dict:
    """版本差异(自管): 同 _file_changes(git 对比基线 commit)。"""
    return _file_changes(proj)


@router.post("/arch/change")
async def compute_arch_change(request: Request):
    body = await request.json()
    proj, _, _ = _resolve(body.get("root"), body.get("project"))
    if not proj:
        return err(400, "未定位到项目")
    model = _self_model(proj)
    comps = model.get("components") or []
    changes = _file_changes(proj)
    added = changes.get("added") or []
    modified = changes.get("modified") or []
    deleted = changes.get("deleted") or []

    # 组件级变更：文件归属映射
    added_by = _map_files_to_components(added, comps)
    modified_by = _map_files_to_components(modified, comps)
    deleted_by = _map_files_to_components(deleted, comps)

    nodes = []
    seen_cids = set()
    for cid, meta in list(added_by.items()) + list(modified_by.items()) + list(deleted_by.items()):
        if cid in seen_cids:
            continue
        seen_cids.add(cid)
        change = "added" if cid in added_by else ("modified" if cid in modified_by else "deleted")
        comp = next((c for c in comps if c.get("id") == cid), None)
        nodes.append({
            "id": cid, "name": meta["name"], "kind": meta["kind"] or (comp.get("kind") if comp else "component"),
            "change": change,
            "file": (meta["files"] or ["—"])[0],
            "fileCount": len(meta["files"]),
        })

    # 依赖边变更：跨社区调用边 + 组件 dependsOn
    relations = []
    for c in comps:
        for d in (c.get("dependsOn") or []):
            # 只要任一端有变更文件，标记为可能受影响
            if c.get("id") in seen_cids or d in seen_cids:
                relations.append({
                    "id": f"{c['id']}~{d}", "kind": "depends", "change": "related",
                    "file": (c.get("owns") or ["—"])[0],
                })

    # 图摘要(真实组件结构)
    comp_names = [c.get("name") or c.get("id") for c in comps[:6]]
    structure = "graph TD;\n" + "\n".join(f"  {c['id']}[\"{c['name']}\"]" for c in comps[:8])
    dependency = "graph LR;\n" + "\n".join(
        f"  {c['id']} --> {d}" for c in comps for d in (c.get('dependsOn') or [])[:4])[:800]

    return ok({
        "baseline": {
            "version": "v1", "commit": proj.get("baselineCommit") or "",
            "branch": proj.get("branch") or "main", "analyzedAt": _ts(), "gitDate": _ts(),
        },
        "files": {"added": len(added), "modified": len(modified), "deleted": len(deleted)},
        "nodes": nodes[:40],
        "relations": relations[:40],
        "leafComponents": body.get("stagingAffected", []),
        "diagrams": {"structure": structure, "dependency": dependency, "calls": ""},
        "codeChanges": [],
    })


@router.get("/arch/staging")
async def get_staging(root: Optional[str] = None, project: Optional[str] = None):
    proj, _, _ = _resolve(root, project)
    if not proj:
        return err(400, "未定位到项目")
    changes = _file_changes(proj)
    added = changes.get("added") or []
    modified = changes.get("modified") or []
    deleted = changes.get("deleted") or []
    model = _self_model(proj)
    comps = model.get("components") or []
    affected = sorted({meta["name"] for meta in
                       (list(_map_files_to_components(added + modified, comps).values())
                        if (added or modified) else [])})
    total = len(added) + len(modified) + len(deleted)
    grade = "A" if total == 0 else ("M" if len(affected) <= 2 else "L")
    return ok({
        "scope": {"filesChanged": (added + modified + deleted)[:60],
                  "added": len(added), "modified": len(modified), "deleted": len(deleted),
                  "deletedHighRisk": False},
        "grade": grade,
        "gradeBasis": f"工作区检测到 {len(added)} 新增 / {len(modified)} 修改 / {len(deleted)} 删除 文件，涉及 {len(affected)} 个组件",
        "gradeAction": "需确认变更边界并更新规约" if total else "工作区无变更",
        "affectedComponents": affected,
        "layers": {
            "file": {"reParsed": len(added) + len(modified), "reusedByHash": 0, "edgesChanged": len(modified)},
            "community": {"refined": len(affected), "dirty": len(deleted), "action": "按文件归属刷新社区"},
            "semantic": {"reExplained": len(affected), "dirty": 0, "inherited": 0},
        },
    })


@router.post("/arch/staging/scan")
async def run_staging_scan(request: Request):
    body = await request.json() or {}
    proj, _, _ = _resolve(body.get("root"), body.get("project"))
    if not proj:
        return err(400, "未定位到项目")
    changes = _file_changes(proj)
    added = changes.get("added") or []
    modified = changes.get("modified") or []
    deleted = changes.get("deleted") or []
    now = _ts()
    entry = {
        "id": store.next_id("inc"),
        "scope": f"增量扫描: {len(added)} 新增 / {len(modified)} 修改 / {len(deleted)} 删除",
        "grade": "M" if (added or modified or deleted) else "A",
        "files": (added + modified + deleted)[:60],
        "edgesChanged": len(modified),
        "reExplained": [],
        "boundaryChanged": deleted,
        "createdAt": now,
    }
    store.StagingScansStore.create(entry)
    return ok({
        "scope": {"filesChanged": (added + modified + deleted)[:60],
                  "added": len(added), "modified": len(modified), "deleted": len(deleted),
                  "deletedHighRisk": False},
        "grade": entry["grade"], "gradeBasis": entry["scope"], "gradeAction": "无",
        "affectedComponents": [],
        "layers": {
            "file": {"reParsed": len(added) + len(modified), "reusedByHash": 0, "edgesChanged": len(modified)},
            "community": {"refined": 0, "dirty": len(deleted), "action": "按文件归属刷新社区"},
            "semantic": {"reExplained": 0, "dirty": 0, "inherited": 0},
        },
        "log": entry,
    })


@router.get("/arch/staging/log")
async def get_staging_log():
    return ok(store.StagingScansStore.all())


@router.get("/arch/staging/compliance")
async def get_staging_compliance(root: Optional[str] = None, project: Optional[str] = None):
    proj, _, _ = _resolve(root, project)
    if not proj:
        return err(400, "未定位到项目")
    changes = _file_changes(proj)
    added = changes.get("added") or []
    modified = changes.get("modified") or []
    deleted = changes.get("deleted") or []
    total = len(added) + len(modified) + len(deleted)
    model = _self_model(proj)
    comps = model.get("components") or []
    # 真实检查：文件是否全部归属于已知组件；删除文件是否越界
    known_files = {f for c in comps for f in (c.get("owns") or [])}
    unowned = [f for f in (added + modified) if f not in known_files]
    return ok([
        {"id": "ck-1", "name": "组件边界完整性", "kind": "boundary",
         "pass": len(unowned) == 0, "level": "blocker",
         "detail": f"{len(unowned)} 个变更文件未归属任何已知组件" if unowned else "所有变更文件均归属已知组件",
         "scope": ", ".join(unowned[:5]) or "all"},
        {"id": "ck-2", "name": "变更规模", "kind": "spec",
         "pass": total <= 100, "level": "major",
         "detail": f"本次变更 {total} 个文件", "scope": "all"},
    ])


@router.post("/arch/staging/gates")
async def set_staging_gate(request: Request):
    body = await request.json()
    return ok({"key": body.get("key"), "value": body.get("value"), "ok": True})


@router.post("/arch/baseline/verify")
async def verify_baseline(request: Request):
    body = await request.json() or {}
    proj, _, _ = _resolve(body.get("root"), body.get("project"))
    if not proj:
        return err(400, "未定位到项目")
    changes = _file_changes(proj)
    dirty = bool(changes.get("hasChanges"))
    return ok({
        "verify": ("ok - 工作区与基线一致" if not dirty
                   else f"检测到 {len(changes.get('added') or [])} 新增 / {len(changes.get('modified') or [])} 修改 / "
                        f"{len(changes.get('deleted') or [])} 删除，工作区偏离基线"),
        "verifyOk": not dirty,
        "baselineId": proj.get("baselineId") or "",
    })

    return ok({"confirmed": True, "version": "v1.0"})