"""知识库路由(数据主权批E: 全部端点自管)。

common.build_architecture_model/build_component_catalog 已切 arch_components
(自管社区组件+图谱依赖归并), KB 转发链切断——端点路径与形状保留
(kb-assets.ts/architecture-store 消费), 数据源为 architect 自身。
"""
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from ..common import (_ts, _id, ok, err, build_architecture_model, empty_architecture_model,
                     build_component_catalog, KbUnavailableError, _MODEL_KEYS)

router = APIRouter()

# 未关联知识库时的统一提示。

def _all_assets(root: Optional[str] = None, project: Optional[str] = None):
    """导出全部成分资产(供 requirements._match_assets 朴素命中)。"""
    model = build_architecture_model(root, project)
    return [_comp_to_asset(c) for c in model["components"]]


@router.get("/kb/model")
async def get_kb_model(version: str = "v1", root: Optional[str] = None, project: Optional[str] = None):
    return ok(build_architecture_model(root, project, include_code_mappings=True))


@router.get("/kb/assets/search")
async def search_assets(q: Optional[str] = "", root: Optional[str] = None, project: Optional[str] = None,
                        type: Optional[str] = None, level: Optional[str] = None):
    """搜索组件资产。注意：必须先于 `/kb/assets/{asset_id}` 注册，否则会被通配匹配。

    支持按分析类型(type: INCLUDE/CALL 或 依赖/调用)与层级(level: L0/L1)筛选；
    列表项含 parentId/parentName/fileCount 等元数据。
    """
    catalog = build_component_catalog(root, project)
    comps = catalog.get("components") or []
    if q:
        ql = q.lower()
        comps = [c for c in comps if ql in c["id"].lower() or ql in c["name"].lower()]
    if type:
        t = (type or "").upper()
        comps = [c for c in comps if (c.get("edgeType") or "").upper() == t]
    if level:
        lv = level.upper()
        comps = [c for c in comps if (c.get("level") or "").upper() == lv]
    return ok([_comp_to_asset(c) for c in comps])


@router.get("/kb/assets/{asset_id}")
async def get_asset_detail(asset_id: str, root: Optional[str] = None, project: Optional[str] = None):
    model = build_architecture_model(root, project)
    for comp in model["components"]:
        if comp["id"] == asset_id:
            return ok(_comp_to_asset(comp))
    return JSONResponse(status_code=404, content={"code": 404, "message": "Asset not found", "data": None})


@router.get("/kb/code-mappings")
async def get_code_mappings(root: Optional[str] = None, project: Optional[str] = None):
    model = build_architecture_model(root, project, include_code_mappings=True)
    return ok(model.get("codeMappings") or [])


@router.get("/kb/coding-rules")
async def get_coding_rules(root: Optional[str] = None, project: Optional[str] = None):
    """编码规约(数据主权批E: 自管)——arch_naming_conventions 活跃规则聚合。

    路径与键名保留(kb-assets.ts 消费), 数据源已是 architect 自管表。"""
    try:
        from .. import ctx
        from ..arch_routes.project import resolve_project
        proj = resolve_project(root, project)
        pid = (proj or {}).get("id") or ""
        db = ctx.project_db(pid) if pid else None
        if db is None:
            return ""
        rows = db.fetchall(
            "SELECT rule_text, scope, source FROM arch_naming_conventions"
            " WHERE project_id=? AND status='active' ORDER BY rowid", (pid,))
        blocks = []
        for r in (rows or []):
            tag = {"induced": "派生", "manual": "人工"}.get(r["source"], r["source"])
            blocks.append(f"- [{tag}] {r['rule_text']}")
        if not blocks:
            return ""
        return "## 编码规约（自管，architect 独立维护）\n\n" + "\n".join(blocks)
    except Exception:  # noqa: BLE001
        return ""


# 组件的字段统一转换(自管组件字段缺省容错——数据主权批E 组件行无
# change/lang/kind/responsibilities 等 KB 分析域字段, 缺省同义值)。
def _comp_to_asset(c):
    owns = c.get("owns") or []
    first_file = "/".join(owns[:1]) if owns else f"app/{c.get('name')}"
    return {
        "assetId": c["id"], "name": c["name"], "type": "component",
        "change": c.get("change") or "same", "desc": c.get("desc") or "",
        "file": first_file, "lang": c.get("lang") or "", "kind": c.get("kind") or "component",
        "responsibilities": c.get("responsibilities") or [], "owns": owns,
        "dependsOn": c.get("dependsOn") or [],
        "edgeType": c.get("edgeType"), "hierLevel": c.get("level"),
        "parentId": c.get("parentId"), "parentName": c.get("parentName"),
        "fileCount": c.get("fileCount") or len(owns),
        "nodeCount": c.get("nodeCount"),
        "edgeCount": c.get("edgeCount"),
        "taskId": c.get("taskId"),
    }
