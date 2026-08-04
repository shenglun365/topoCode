"""Knowledge base / architecture model routes."""
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from .common import _ts, _id, ok, err, build_architecture_model

router = APIRouter()


@router.get("/kb/model")
async def get_kb_model(version: str = "v1"):
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
