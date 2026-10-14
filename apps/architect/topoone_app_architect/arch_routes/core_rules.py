"""核心资产守护 REST(2610 重构): 规约库 + 挂载关联(挂载即核心, 无分级)。

三层目标(asset|component|file)统一联想端点 guard-targets 亦驻此域。
评估性守护: pre/post-flight 匹配改动面消费 list_effective(见 sem/core_guard.py)。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from ..common import err, ok

router = APIRouter()

CONFIG_KEY = "core_guard_injection"


@router.get("/arch/rule-defs")
async def list_rule_defs(project: str = "", q: str = ""):
    """规约库清单(按项目; q 过滤 title/content)。"""
    from .. import store
    if not project:
        return err(400, "缺少 project")
    return ok({"items": store.RuleDefStore.list(project, q=q)})


@router.post("/arch/rule-defs")
async def create_rule_def(request: Request):
    """新建规约。body: {project, title, content, source?}"""
    from .. import store
    body = await request.json()
    project = str(body.get("project") or "").strip()
    if not project:
        return err(400, "缺少 project")
    title = str(body.get("title") or "").strip()
    content = str(body.get("content") or "").strip()
    if not title or not content:
        return err(400, "title 与 content 必填")
    return ok(store.RuleDefStore.create(
        project, title, content, source=str(body.get("source") or "manual")))


@router.put("/arch/rule-defs/{rule_id}")
async def update_rule_def(rule_id: str, request: Request):
    """更新规约。body: {project, title?, content?}"""
    from .. import store
    body = await request.json()
    project = str(body.get("project") or "").strip()
    if not project:
        return err(400, "缺少 project")
    row = store.RuleDefStore.update(
        rule_id, title=str(body.get("title") or ""),
        content=str(body.get("content") if body.get("content") is not None else ""))
    if not row:
        return err(404, "规约不存在")
    return ok(row)


@router.delete("/arch/rule-defs/{rule_id}")
async def delete_rule_def(rule_id: str, project: str = ""):
    """删除规约(级联全目标卸载)。"""
    from .. import store
    if not project:
        return err(400, "缺少 project")
    if not store.RuleDefStore.delete(rule_id):
        return err(404, "规约不存在")
    return ok({"deleted": True})


@router.get("/arch/target-rules")
async def list_target_rules(project: str = "", targetType: str = ""):
    """挂载清单——effective 聚合展开(引擎/MCP 同一数据源)。

    → ok({items: [{targetType, targetId, title, rulesMd, rules:[{ruleId,title,content}]}]})
    """
    from .. import store
    if not project:
        return err(400, "缺少 project")
    rows = store.TargetRuleStore.list_effective(project)
    if targetType in store.TargetRuleStore.TYPES:
        rows = [x for x in rows if x["targetType"] == targetType]
    return ok({"items": rows})


@router.put("/arch/target-rules")
async def attach_target_rule(request: Request):
    """挂载规约。body: {project, targetType, targetId, ruleId, title?}——幂等。"""
    from .. import store
    body = await request.json()
    project = str(body.get("project") or "").strip()
    if not project:
        return err(400, "缺少 project")
    rule_id = str(body.get("ruleId") or "").strip()
    if not rule_id or not store.RuleDefStore.get(rule_id, project):
        return err(404, "规约不存在")
    try:
        row = store.TargetRuleStore.attach(
            project, str(body.get("targetType") or "asset"),
            str(body.get("targetId") or ""), rule_id,
            title=str(body.get("title") or ""))
    except ValueError as e:
        return err(400, str(e))
    return ok(row)


@router.delete("/arch/target-rules")
async def detach_target_rule(project: str = "", targetType: str = "",
                             targetId: str = "", ruleId: str = ""):
    """卸载规约。"""
    from .. import store
    if not project:
        return err(400, "缺少 project")
    if not store.TargetRuleStore.detach(project, targetType, targetId, ruleId):
        return err(404, "挂载不存在")
    return ok({"detached": True})


# ── 守护注入开关(裁决 3: 任务链自动+直通轻量自动, 会话 UI 可关) ──

def _read_overrides_raw() -> dict:
    import json as _json
    from .. import store
    try:
        raw = store.CollabConfigStore.get("agent.comp.overrides")
        return _json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


@router.get("/arch/guard-config")
async def get_guard_config():
    return ok({"autoInject": _read_overrides_raw().get(CONFIG_KEY, True)})


@router.put("/arch/guard-config")
async def set_guard_config(request: Request):
    import json as _json
    from .. import store
    body = await request.json()
    overrides = _read_overrides_raw()
    overrides[CONFIG_KEY] = bool(body.get("autoInject"))
    store.CollabConfigStore.set("agent.comp.overrides", _json.dumps(overrides))
    return ok({"autoInject": overrides[CONFIG_KEY]})


# ── 三层目标统一联想(后端分组独立实现: asset/component/file) ──

@router.get("/arch/guard-targets")
async def mark_targets(project: str = "", root: str = "",
                       q: str = "", type: str = "all", limit: int = 8):
    """标记目标统一联想(2610): 三层单接口, 后端按组分头实现(可独立演进)。

    - asset: 语义资产检索(engine._grouped_search_items, 与语义树搜索同口径)
    - component: 组件 catalog(knowledge.build_component_catalog)
    - file: 项目文件路径(git ls-files 优先 / walk 兜底, dirs.project_file_paths)
    type: asset|component|file|all(逗号组合)。→ ok({items:[{id,title,hint,type}], groups:{...}})
    """
    from ..sem.engine import _grouped_search_items
    from ..sem.paths import resolve_root
    from .dirs import project_file_paths
    from .knowledge import build_component_catalog
    r: Optional[str] = resolve_root(root, project)
    want = [t.strip() for t in (type or "all").split(",") if t.strip()]
    if "all" in want or not want:
        want = ["asset", "component", "file"]
    lim = max(1, min(int(limit or 8), 50))
    items: list = []
    groups: dict = {}
    if "asset" in want:
        rows = _grouped_search_items(r, project, q or "", None, lim, 0, None, "") or []
        groups["asset"] = len(rows)
        items += [{"id": x.get("id"), "title": x.get("name") or x.get("id"),
                   "hint": x.get("kind"), "type": "asset"} for x in rows[:lim]]
    if "component" in want:
        comps = (build_component_catalog(r, project).get("components") or [])
        ql = (q or "").strip().lower()
        if ql:
            comps = [c for c in comps
                     if ql in (c.get("id") or "").lower() or ql in (c.get("name") or "").lower()]
        groups["component"] = len(comps)
        items += [{"id": c.get("id"), "title": c.get("name") or c.get("id"),
                   "hint": "comp", "type": "component"} for c in comps[:lim]]
    if "file" in want:
        if not r:
            groups["file"] = 0
        else:
            paths = project_file_paths(r, q or "", lim)
            groups["file"] = len(paths)
            items += [{"id": f, "title": f, "type": "file"} for f in paths[:lim]]
    return ok({"items": items, "groups": groups})
