"""W6 资产 REST（2610-B1）——arch_assets 表面（D-1 表为真相源）。

管理面先行（C1 先例：REST 先行 UI 后置）；kind=skill 的 payload 校验
route_hint 非空（路由协议要求）。LLM 侧消费走 prompt skill_catalog 块。
"""
from typing import Dict, Optional

from fastapi import APIRouter, Request

from ..common import err, ok

router = APIRouter()


@router.get("/arch/assets")
async def list_assets(kind: str = "", project: str = ""):
    from .. import store
    return ok(store.ArchAssetsStore.all(kind=kind or "",
                                        project_id=project or ""))


@router.post("/arch/assets")
async def upsert_asset(request: Request):
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001
        return err(400, "invalid json")
    kind = str(body.get("kind") or "skill")
    if kind == "skill" and not str((body.get("payload") or {})
                                   .get("route_hint") or "").strip():
        return err(400, "skill 资产 payload.route_hint 必填(路由协议)")
    try:
        from .. import store
        return ok(store.ArchAssetsStore.upsert(body))
    except ValueError as e:
        return err(400, str(e))


@router.delete("/arch/assets/{asset_id}")
async def delete_asset(asset_id: str):
    from .. import store
    return ok({"deleted": store.ArchAssetsStore.delete(asset_id)})


@router.get("/arch/skills")
async def list_skills(project: str = ""):
    """技能能力配置目录(分类分组, 2610 技能管理面)。

    内置(category 分组) ∪ 表技能(同名覆盖; 管理视角含禁用行——禁用即回退
    内置, D-1); 需求/任务等软件开发类资产不在本面(仅 kind=skill)。
    """
    from ..agent.tools.registry import architect_skills
    table: Dict[str, dict] = {}
    try:
        from .. import store
        for a in store.ArchAssetsStore.all(kind="skill",
                                           project_id=project or ""):
            table[str(a.get("name"))] = a
    except Exception:  # noqa: BLE001 — 表不可用时仅显内置
        pass

    def _entry(name: str, desc: str, a: Optional[dict]) -> dict:
        p = (a or {}).get("payload") or {}
        return {"name": name, "description": desc,
                "route_hint": str(p.get("route_hint") or ""),
                "child_registry": list(p.get("child_registry") or []),
                "source": "asset" if a else "builtin",
                "enabled": bool(a.get("enabled")) if a else True,
                "assetId": str((a or {}).get("id") or "")}

    groups: Dict[str, list] = {}
    for s in architect_skills():
        name = str(s.get("name"))
        groups.setdefault(str(s.get("category") or "builtin"), []).append(
            _entry(name, s.get("description") or "", table.get(name)))
    for name, a in table.items():
        if name in {str(x.get("name")) for x in architect_skills()}:
            continue
        groups.setdefault("custom", []).append(
            _entry(name, a.get("description") or "", a))
    return ok([{"category": c, "skills": items}
               for c, items in sorted(groups.items())])
