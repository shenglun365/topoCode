"""Greenfield routes — Blueprint / Scaffold / Extract / Launch / Guide.

契约见 docs/architect/api-knowledge-greenfield.md。服务端返回确定性的模拟结果，
形状与前端 blueprint-agent / scaffold-service / extract-service 对齐。
"""
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err
from . import store

router = APIRouter()

_MODEL_EMPTY = {
    "id": "root", "name": "系统", "kind": "system",
    "children": [], "deps": [],
}


def _model_of(blueprint):
    return (blueprint or {}).get("model") or _MODEL_EMPTY


# ── Blueprint ────────────────────────────────────────────────

@router.post("/blueprint/init")
async def blueprint_init(request: Request):
    body = await request.json()
    reqs = body.get("reqIds") or []
    product = body.get("productForm") or "web"
    stack = body.get("stack") or "go"
    bp_id = store.next_id("bp")
    blueprint = {
        "id": bp_id, "title": f"{product} 蓝图", "description": "从零构建的应用骨架与领域模型",
        "model": {
            "id": "root", "name": "系统", "kind": "system",
            "children": [
                {"id": "core", "name": "core", "kind": "module",
                 "children": [{"id": "api", "name": "api", "kind": "module", "children": [], "deps": ["core"]}],
                 "deps": []},
                {"id": "infra", "name": "infra", "kind": "module", "children": [], "deps": ["core"]},
            ],
            "deps": [],
        },
        "source": "topocode-blueprint", "status": "draft",
        "reqIds": reqs, "stack": stack, "createdAt": _ts(),
    }
    turns = [
        {"role": "user", "content": f"从零构建「{product}」应用({stack})，需求：{'、'.join(reqs) or '无'}"},
        {"role": "assistant", "content": f"已初始化蓝图 {bp_id}：{product} 骨架 + 领域模型草案。", "blueprintId": bp_id},
    ]
    store.BlueprintsStore.upsert(bp_id, blueprint)
    return ok({"turns": turns, "blueprint": blueprint})


@router.post("/blueprint/refine")
async def blueprint_refine(request: Request):
    body = await request.json()
    bp_id = body.get("blueprintId") or store.next_id("bp")
    existing = store.BlueprintsStore.get(bp_id) or {}
    blueprint = dict(existing)
    blueprint["status"] = "draft"
    blueprint["updatedAt"] = _ts()
    store.BlueprintsStore.upsert(bp_id, blueprint)
    questions = [
        {"key": "modules", "label": "模块划分与职责？", "type": "text", "hint": "一行一个模块"},
        {"key": "deployment", "label": "部署形态？", "type": "select", "hint": "单机/容器/K8s"},
    ]
    return ok({"blueprint": blueprint, "questions": questions})


@router.post("/blueprint/demo-freeze")
async def blueprint_demo_freeze(request: Request):
    body = await request.json()
    bp_id = body.get("blueprintId")
    existing = store.BlueprintsStore.get(bp_id) if bp_id else None
    blueprint = dict(existing or {})
    blueprint["id"] = bp_id or store.next_id("bp")
    blueprint["status"] = "frozen"
    blueprint["source"] = blueprint.get("source") or "agent+user"
    blueprint["updatedAt"] = _ts()
    if bp_id:
        store.BlueprintsStore.upsert(bp_id, blueprint)
    return ok({
        "blueprint": blueprint,
        "taskTreeHint": {"nodeCount": 6, "estMin": 240, "scaffoldTasks": ["scaffold-core", "scaffold-infra"]},
    })


@router.post("/blueprint/confirm")
async def blueprint_confirm(request: Request):
    body = await request.json()
    bp_id = body.get("blueprintId")
    existing = store.BlueprintsStore.get(bp_id) if bp_id else None
    if not existing:
        return err(404, "Blueprint not found")
    existing["status"] = "confirmed"
    existing["updatedAt"] = _ts()
    store.BlueprintsStore.upsert(bp_id, existing)
    return ok({"status": "confirmed"})


# ── Scaffold ─────────────────────────────────────────────────

@router.post("/scaffold/generate")
async def scaffold_generate(request: Request):
    body = await request.json()
    blueprint_id = body.get("blueprintId")
    module = (body.get("module") or "core")
    files = [
        {"path": "go.mod", "content": "module topo-scaffold\n\ngo 1.22\n"},
        {"path": "cmd/main.go", "content": "package main\n\nfunc main() {}\n"},
        {"path": f"internal/{module}/service.go", "content": f"package {module}\n\n// {module} service skeleton\n"},
        {"path": f"internal/{module}/service_test.go", "content": f"package {module}\n\nfunc TestService(t *testing.T) {{}}\n"},
        {"path": "README.md", "content": "# Scaffold\n"},
    ]
    validation = {
        "ok": True,
        "checks": [
            {"name": "go fmt", "status": "pass"},
            {"name": "module name", "status": "pass"},
        ],
    }
    return ok({
        "token": store.next_id("scaf"),
        "blueprintId": blueprint_id,
        "module": module,
        "files": files,
        "validation": validation,
    })


@router.post("/scaffold/confirm")
async def scaffold_confirm(request: Request):
    body = await request.json()
    files_written = len(body.get("files") or [])
    return ok({
        "commit": "9f6e2b1a",
        "filesWritten": files_written,
        "buildPass": True,
        "branch": "main",
    })


# ── Extract(知识库抽取) ──────────────────────────────────────

@router.post("/kb/extract")
async def kb_extract(request: Request):
    """(KB-REQ-15) 真实代码抽取 —— 需 KB 提供 `knowledge.extractSnapshot`(尚未实现)。
    当前返回固定占位；KB 实现后改为经 gateway 调用并落 arch_kb_snapshots。"""
    body = await request.json()
    exec_root = body.get("execRoot") or "."
    snapshot_id = store.next_id("snap")
    snapshot = {
        "id": snapshot_id, "execRoot": exec_root,
        "gitCommit": body.get("commit"), "baselineVersion": body.get("baselineVersion"),
        "createdAt": _ts(),
    }
    store.SnapshotsStore.create(snapshot)
    return ok({
        "snapshotId": snapshot_id,
        "model": _MODEL_EMPTY,
        "mappings": [{"id": "cm-1", "targetType": "component", "targetId": "api", "targetName": "api", "file": "internal/api/service.go", "line": "L1"}],
        "metrics": {"files": 4, "symbols": 12, "durationMs": 840},
    })


@router.post("/kb/baseline")
async def kb_baseline(request: Request):
    """建立知识基线。已关联 KB 项目时经 `version.list`+`version.materialize` 取真实版本
    与文件清单写入快照；KB 能力不足/不可达 → 明确报错(不占位)。"""
    from .kb_gateway import call_kb
    body = await request.json()
    proj_id = body.get("kbProjectId") or body.get("projectId")
    commit = body.get("commit") or "HEAD"

    if not proj_id:
        return err(400, "缺少 kbProjectId/projectId，无法建立 KB 基线")
    versions = call_kb("version.list", projectId=proj_id) or []
    if not versions:
        return err(502, "KB 能力不足：version.list 未返回任何版本，无法建立基线。")
    current = versions[0]
    for v in versions:
        if v.get("id") == proj_id and (v.get("current_version_id") or v.get("current")):
            current = v
            break
    if current is None:
        current = versions[0]
    raw = call_kb("version.materialize", projectId=proj_id, versionId=current.get("id"))
    if raw is None:
        return err(502, "KB 能力不足：version.materialize 不可达，无法读取基线文件清单。")
    # version.materialize 可能返回裸 list 或 {files:[...]} dict，统一为路径列表
    if isinstance(raw, list):
        file_list = [f if isinstance(f, str) else (f.get("path") or f.get("file_path") or f.get("file_name") or str(f))
                     for f in raw]
    elif isinstance(raw, dict):
        items = raw.get("files") or raw.get("items") or []
        file_list = [f if isinstance(f, str) else (f.get("path") or f.get("file_path") or f.get("file_name") or str(f))
                     for f in items]
    else:
        file_list = []
    file_list = [f for f in file_list if f]
    store.SnapshotsStore.create({
        "id": store.next_id("snap"), "name": f"KB 基线 {commit}",
        "version": "v1", "taskId": "manual", "gitBranch": "main",
        "gitCommit": commit, "model": {"fileCount": len(file_list), "files": file_list},
        "createdAt": _ts(),
    })
    return ok({
        "baselineId": store.next_id("base"),
        "commit": current.get("currId") or current.get("current_version_id") or current.get("id") or commit,
        "mode": "existing", "tag": "v0.0.1",
        "kbProjectId": proj_id, "files": file_list,
    })


# ── Launch / Guide ───────────────────────────────────────────

_LAUNCH = {
    "execRoot": "/home/dev/topo-projects/order-service",
    "kbRoot": "/home/dev/topo-kb",
    "mode": "existing",
    "productForm": "web",
    "scaffold": None,
}


def launch_info() -> dict:
    return dict(_LAUNCH)


_MISSIONS = {
    "existing": [
        {"id": "mission-1", "title": "需求澄清", "desc": "从需求池挑选待执行需求并澄清边界", "docId": "api-knowledge-greenfield"},
        {"id": "mission-2", "title": "方案确认", "desc": "评估影响面并确认执行方案", "docId": "api-overview"},
        {"id": "mission-3", "title": "任务执行", "desc": "驱动 coding agent 完成改动", "docId": "api-execution"},
    ],
    "greenfield": [
        {"id": "mission-1", "title": "蓝图规划", "desc": "从零规划模块与领域模型", "docId": "api-knowledge-greenfield"},
        {"id": "mission-2", "title": "脚手架生成", "desc": "生成工程骨架", "docId": "api-knowledge-greenfield"},
        {"id": "mission-3", "title": "知识抽取", "desc": "抽取代码为知识库基线", "docId": "api-knowledge-greenfield"},
    ],
}


def guide_missions(mode: str = "existing") -> list:
    return [dict(m) for m in _MISSIONS.get(mode, _MISSIONS["existing"])]


@router.get("/launch")
async def launch_route():
    return ok(launch_info())


@router.get("/guide/missions")
async def missions_route(mode: str = "existing"):
    return ok(guide_missions(mode))