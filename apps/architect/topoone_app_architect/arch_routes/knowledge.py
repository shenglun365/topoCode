"""Knowledge base / architecture model routes.

KB-REQ-16(图谱复合查询)仍为占位；KB-REQ-17 组件模型已由 KB `/zmq/architecture.model`
(backend-core/architecture_model_service.py，分析图社区→组件/代码映射/依赖/版本差异)接管，
`build_architecture_model` 经 KbGateway 拉取真实模型。已实现的 KB 方法
(`version.*`、`knowledge.pullRequest/pendingUpdates/updateConfirm/updateCancel`)
经 `kb_gateway.call_kb` 直接接线，不可达时回退占位。
"""
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .common import (_ts, _id, ok, err, build_architecture_model, empty_architecture_model,
                     build_component_catalog, KbUnavailableError, _MODEL_KEYS)
from .kb_gateway import call_kb

router = APIRouter()

# 未关联知识库时的统一提示。
KB_NOTE = "未关联知识库：无法读取项目组件信息。请在项目概览「查找关联」中关联知识库后重试。"

# 组件的字段统一转换。
def _comp_to_asset(c):
    owns = c.get("owns") or []
    first_file = "/".join(owns[:1]) if owns else f"app/{c.get('name')}"
    return {
        "assetId": c["id"], "name": c["name"], "type": "component",
        "change": c["change"], "desc": c["desc"],
        "file": first_file, "lang": c["lang"], "kind": c["kind"],
        "responsibilities": c["responsibilities"], "owns": owns,
        "dependsOn": c["dependsOn"],
        "edgeType": c.get("edgeType"), "hierLevel": c.get("level"),
        "parentId": c.get("parentId"), "parentName": c.get("parentName"),
        "fileCount": c.get("fileCount") or len(owns),
        "nodeCount": c.get("nodeCount"),
        "edgeCount": c.get("edgeCount"),
        "taskId": c.get("taskId"),
    }


def _project_ctx(root: Optional[str] = None, project: Optional[str] = None):
    """解析当前项目上下文；返回 (项目, 是否降级)。

    降级口径与 project.kb_degraded 一致：项目未解析或项目无 KB 基线。
    """
    from .project import _resolve_project, kb_degraded
    try:
        proj = _resolve_project(root, project)
    except Exception:
        return None, True
    return proj, kb_degraded(root, project)


def _all_assets(root: Optional[str] = None, project: Optional[str] = None):
    """导出全部成分资产(供 requirements._match_assets 朴素命中)。"""
    model = build_architecture_model(root, project)
    return [_comp_to_asset(c) for c in model["components"]]


def _empty_model():
    return {k: [] for k in _MODEL_KEYS}


@router.get("/kb/model")
async def get_kb_model(version: str = "v1", root: Optional[str] = None, project: Optional[str] = None):
    # KB-REQ-17: 真实组件模型经 KB `/zmq/architecture.model` 接管。
    # 未绑定 KB 基线 → 降级空模型 + note 提示；KB 调用失败 → 502 明确报错。
    _, degraded = _project_ctx(root, project)
    if degraded:
        return ok({**_empty_model(), "degraded": True, "note": KB_NOTE})
    try:
        return ok(build_architecture_model(root, project))
    except KbUnavailableError as e:
        return JSONResponse(status_code=502, content={"code": 502, "message": str(e), "data": None})


@router.get("/kb/assets/search")
async def search_assets(q: Optional[str] = "", root: Optional[str] = None, project: Optional[str] = None,
                        type: Optional[str] = None, level: Optional[str] = None):
    """搜索组件资产。注意：必须先于 `/kb/assets/{asset_id}` 注册，否则会被通配匹配。

    支持按分析类型(type: INCLUDE/CALL 或 依赖/调用)与层级(level: L0/L1)筛选；
    列表项含 parentId/parentName/fileCount 等元数据。
    """
    _, degraded = _project_ctx(root, project)
    if degraded:
        # 列表类端点：返回空数组(前端读 body.note 提示)。
        return ok([])
    try:
        catalog = build_component_catalog(root, project)
    except KbUnavailableError as e:
        return JSONResponse(status_code=502, content={"code": 502, "message": str(e), "data": None})
    comps = catalog.get("components") or []
    if q:
        ql = q.lower()
        comps = [c for c in comps if ql in c["id"].lower() or ql in c["name"].lower()]
    if type:
        t = type.upper().replace("依赖", "INCLUDE").replace("调用", "CALL")
        comps = [c for c in comps if (c.get("edgeType") or "").upper() == t]
    if level:
        lv = level.upper()
        comps = [c for c in comps if (c.get("level") or "").upper() == lv]
    return ok([_comp_to_asset(c) for c in comps])


@router.get("/kb/assets/{asset_id}")
async def get_asset_detail(asset_id: str, root: Optional[str] = None, project: Optional[str] = None):
    _, degraded = _project_ctx(root, project)
    if degraded:
        return JSONResponse(status_code=400, content={"code": 400, "message": KB_NOTE, "data": None})
    try:
        model = build_architecture_model(root, project)
    except KbUnavailableError as e:
        return JSONResponse(status_code=502, content={"code": 502, "message": str(e), "data": None})
    for comp in model["components"]:
        if comp["id"] == asset_id:
            return ok(_comp_to_asset(comp))
    return JSONResponse(status_code=404, content={"code": 404, "message": "Asset not found", "data": None})


@router.get("/kb/code-mappings")
async def get_code_mappings(root: Optional[str] = None, project: Optional[str] = None):
    _, degraded = _project_ctx(root, project)
    if degraded:
        return ok([])
    model = build_architecture_model(root, project, include_code_mappings=True)
    mappings = model.get("codeMappings") or []
    if mappings:
        return ok(mappings)
    return ok([{
        "id": f"cm-{c['id']}", "targetType": "component", "targetId": c["id"],
        "targetName": c["name"], "file": f"{'/'.join((c.get('owns') or [])[:1]) or 'app/' + str(c['name'])}",
        "line": "L1", "level": "logical", "note": c["desc"],
    } for c in model["components"]])


@router.get("/kb/coding-rules")
async def get_coding_rules():
    return "## 编码规约 v1.0\n\n### 提交规范\n- feat: 新功能\n- fix: 修复\n\n### 校验\n- 所有 public 函数必须有注释"


@router.post("/kb/query")
async def kb_query(request: Request):
    """KB 复合查询(真实)：以组件依赖图为轴，按 kind=depends/calls 计算
    依赖/被调用关系，并展开基本信息/结构/流程片段。

    数据全部来自 KB 真实架构模型(architecture.model 的组件 dependsOn/owns/desc)
    与跨社区调用边(analysis.getCrossCommunityEdges)。
    """
    spec = await request.json()
    _, degraded = _project_ctx(spec.get("root"), spec.get("project"))
    if degraded:
        return JSONResponse(status_code=400, content={"code": 400, "message": KB_NOTE, "data": None})
    try:
        model = build_architecture_model(spec.get("root"), spec.get("project"))
    except KbUnavailableError as e:
        return JSONResponse(status_code=502, content={"code": 502, "message": str(e), "data": None})
    comps = model.get("components") or []
    by_id = {c["id"]: c for c in comps}
    name_of = {c["id"]: c.get("name") or c["id"] for c in comps}
    kind_of = {c["id"]: c.get("kind") or "service" for c in comps}
    # 上游：谁依赖了该组件(被调用方)
    upstream: Dict[str, List[str]] = {}
    for c in comps:
        for d in (c.get("dependsOn") or []):
            upstream.setdefault(d, []).append(c["id"])
    # 跨社区调用边(调用分析 CALL) — 提供 flow 片段
    flow_by: Dict[str, List[str]] = {}
    try:
        from . import project as _project_mod
        proj = _project_mod._resolve_project(spec.get("root"), spec.get("project"))
        kb_id = (proj or {}).get("kbProjectId") or (proj or {}).get("kb_project_id")
        if kb_id:
            tasks = call_kb("analysis.listTasks", projectId=kb_id) or []
            tid = ""
            for t in tasks:
                if t.get("status") == "done":
                    tid = t.get("id") or ""
                    break
            if tid:
                ce = call_kb("analysis.getCrossCommunityEdges", taskId=tid) or {}
                for e in (ce.get("crossEdges") or []):
                    src = e.get("source") or e.get("sourceId") or ""
                    tgt = e.get("target") or e.get("targetId") or ""
                    if src in by_id:
                        flow_by.setdefault(src, []).append(name_of.get(tgt, tgt))
                    if tgt in by_id:
                        flow_by.setdefault(tgt, []).append(name_of.get(src, src))
    except Exception:
        pass  # 跨社区边不可用不阻塞；依赖/基本信息仍来自真实模型

    comp_results = []
    for cid in spec.get("compIds") or []:
        comp = by_id.get(cid)
        if not comp:
            comp_results.append({
                "componentId": cid, "name": cid, "kind": "service",
                "relMd": f"## 关联组件\n\nKB 中未命中组件 {cid}，请核对组件 ID。",
                "basicMd": "", "structureMd": "", "flowMd": "",
            })
            continue
        name = name_of[cid]
        if spec.get("kind") == "calls":
            rel = upstream.get(cid) or []
            rel_title = "被调用方(依赖本组件)"
        else:
            rel = comp.get("dependsOn") or []
            rel_title = "依赖组件(本组件依赖)"
        rel_names = [name_of.get(r, r) for r in rel]
        rel_md = (f"## 关联组件({rel_title})\n\n" +
                  ("、\n".join(f"- {n} (`{r}`)" for n, r in zip(rel_names, rel)) if rel
                   else "（无直接关联组件）"))
        owns = comp.get("owns") or []
        structure_md = ("## 核心结构\n\n" + "\n".join(f"- `{f}`" for f in owns[:10]) if owns
                        else "## 核心结构\n\n（无文件清单）")
        flow = flow_by.get(cid) or []
        flow_md = ("## 核心流程\n\n调用/被调用边：" + "、".join(flow) if flow
                   else "## 核心流程\n\n（无跨社区调用边记录）")
        comp_results.append({
            "componentId": cid, "name": name, "kind": kind_of.get(cid, "service"),
            "relMd": rel_md,
            "basicMd": (comp.get("desc") or "").strip()[:600],
            "structureMd": structure_md,
            "flowMd": flow_md,
        })

    baseline_tag = "v1"
    try:
        kb_id = _resolve_kb_id(spec.get("root"), spec.get("project"))
        if kb_id:
            versions = call_kb("version.list", projectId=kb_id) or []
            if versions:
                baseline_tag = versions[0].get("label") or versions[0].get("id") or "v1"
    except Exception:
        pass

    return ok({
        "id": _id("kq"), "spec": spec,
        "skills": [
            {"name": "kb.graph", "detail": "按依赖遍历组件依赖图"},
            {"name": "kb.component.info", "detail": "读取组件基本信息"},
        ],
        "summary": f"基于知识库真实依赖分析完成，覆盖 {len(comp_results)} 个组件",
        "compResults": comp_results,
        "cached": False, "baselineTag": baseline_tag, "createdAt": _ts(),
    })


def _resolve_kb_id(root, project) -> str:
    """辅助：解析项目 KB 关联 id(供 version.list 等)。"""
    from . import project as _project_mod
    proj = _project_mod._resolve_project(root, project)
    return (proj or {}).get("kbProjectId") or (proj or {}).get("kb_project_id") or ""


# ── KB 版本与基线更新(KB 已实现 method，经网关直达；不可达回退占位) ──

@router.get("/kb/versions")
async def list_kb_versions(project_id: str = ""):
    """列出 KB 项目版本基线(经 `version.list`)。"""
    if not project_id:
        return ok([])
    versions = call_kb("version.list", projectId=project_id)
    return ok(versions or [])


@router.post("/kb/update-request")
async def kb_update_request(request: Request):
    """主动向 KB 发起基线更新请求(仅写待更新标记，不执行)。"""
    body = await request.json()
    res = call_kb("knowledge.pullRequest",
                  projectId=body.get("kbProjectId") or body.get("projectId"),
                  head=body.get("commit"), note=body.get("note"))
    if res:
        return ok(res)
    # KB 能力不足(方法不可达/参数错误)→ 明确报错，不再占位假装成功
    return JSONResponse(status_code=502, content={
        "code": 502, "message": "KB 能力不足：knowledge.pullRequest 未打通或参数错误，无法登记基线更新请求。",
        "data": None,
    })


@router.get("/kb/update-requests")
async def kb_update_requests(project_id: str = ""):
    res = call_kb("knowledge.pendingUpdates", projectId=project_id or None)
    return ok(res or [])


@router.post("/kb/update-requests/{req_id}/confirm")
async def kb_update_confirm(req_id: str, request: Request):
    body = await request.json()
    res = call_kb("knowledge.updateConfirm",
                  requestId=req_id, method=body.get("method", "pull"))
    return ok(res or {"requestId": req_id, "status": "confirmed"})


@router.post("/kb/update-requests/{req_id}/cancel")
async def kb_update_cancel(req_id: str):
    res = call_kb("knowledge.updateCancel", requestId=req_id)
    return ok(res or {"requestId": req_id, "cancelled": True})
