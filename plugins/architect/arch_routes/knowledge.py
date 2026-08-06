"""Knowledge base / architecture model routes.

KB-REQ-17(组件模型/资产/映射/规约)与 KB-REQ-16(图谱复合查询)仍为占位——
KB 侧待实现 `knowledge.graphQuery` 与组件索引接管。已实现的 KB 方法
(`version.*`、`knowledge.pullRequest/pendingUpdates/updateConfirm/updateCancel`)
经 `kb_gateway.call_kb` 直接接线，不可达时回退占位。
"""
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .common import _ts, _id, ok, err, build_architecture_model
from .kb_gateway import call_kb

router = APIRouter()


def _all_assets():
    """导出全部 kb 资产(供 requirements._match_assets 朴素命中)。"""
    model = build_architecture_model()
    return [{
        "assetId": c["id"], "name": c["name"], "type": "component",
        "change": c["change"], "desc": c["desc"], "file": f"app/{c['name']}.go",
        "lang": c["lang"], "kind": c["kind"],
        "responsibilities": c["responsibilities"], "owns": c["owns"], "dependsOn": c["dependsOn"],
    } for c in model["components"]]


@router.get("/kb/model")
async def get_kb_model(version: str = "v1"):
    # KB-REQ-17: 组件模型待 KB 组件索引接管(当前 build_architecture_model 占位)。
    return ok(build_architecture_model())


@router.get("/kb/assets/{asset_id}")
async def get_asset_detail(asset_id: str):
    model = build_architecture_model()
    for comp in model["components"]:
        if comp["id"] == asset_id:
            return ok({
                "assetId": comp["id"], "name": comp["name"], "type": "component",
                "change": comp["change"], "desc": comp["desc"],
                "file": f"app/{comp['name']}.go", "lang": comp["lang"],
                "kind": comp["kind"], "responsibilities": comp["responsibilities"],
                "owns": comp["owns"], "dependsOn": comp["dependsOn"],
            })
    return JSONResponse(status_code=404, content={"code": 404, "message": "Asset not found", "data": None})


@router.get("/kb/assets/search")
async def search_assets(q: Optional[str] = ""):
    model = build_architecture_model()
    comps = model["components"]
    if q:
        ql = q.lower()
        comps = [c for c in comps if ql in c["id"].lower() or ql in c["name"].lower()]
    return ok([{
        "assetId": c["id"], "name": c["name"], "type": "component",
        "change": c["change"], "desc": c["desc"], "file": f"app/{c['name']}.go",
        "lang": c["lang"], "kind": c["kind"],
        "responsibilities": c["responsibilities"], "owns": c["owns"], "dependsOn": c["dependsOn"],
    } for c in comps])


@router.get("/kb/code-mappings")
async def get_code_mappings():
    model = build_architecture_model()
    return ok([{
        "id": f"cm-{c['id']}", "targetType": "component", "targetId": c["id"],
        "targetName": c["name"], "file": f"app/{c['name']}.go",
        "line": "L1", "level": "logical", "note": c["desc"],
    } for c in model["components"]])


@router.get("/kb/coding-rules")
async def get_coding_rules():
    return "## 编码规约 v1.0\n\n### 提交规范\n- feat: 新功能\n- fix: 修复\n\n### 校验\n- 所有 public 函数必须有注释"


@router.post("/kb/query")
async def kb_query(request: Request):
    # KB-REQ-16: 图谱复合查询(需 KB 实现 knowledge.graphQuery)。当前占位。
    spec = await request.json()
    return ok({
        "id": _id("kq"), "spec": spec,
        "skills": [
            {"name": "kb.graph", "detail": "按依赖遍历组件依赖图"},
            {"name": "kb.component.info", "detail": "读取组件基本信息"},
        ],
        "summary": f"基于知识库分析完成，覆盖 {len(spec.get('compIds', []))} 个组件",
        "compResults": [
            {"componentId": cid, "name": cid, "kind": "service",
             "relMd": "## 依赖组件\n\n- 相关组件分析",
             "basicMd": f"## 基本信息\n\n组件 {cid} 分析结果",
             "structureMd": "## 核心数据结构\n\n待补充",
             "flowMd": "## 核心流程\n\n待补充"}
            for cid in spec.get("compIds", [])
        ],
        "cached": False, "baselineTag": "v1.0.0-order-service", "createdAt": _ts(),
    })


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
                  commit=body.get("commit"), note=body.get("note"))
    if res:
        return ok(res)
    # KB 不可达 → 本地占位(标记请求已登记)
    return ok({
        "requestId": _id("kupr"), "status": "pending",
        "projectId": body.get("kbProjectId") or body.get("projectId"),
        "commit": body.get("commit"), "createdAt": _ts(),
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
