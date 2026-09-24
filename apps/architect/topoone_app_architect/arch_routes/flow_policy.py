"""流程驱动配置 REST(管理面) — GET/PUT/DELETE /flow-policy。

读: 生效表(load_flow_policy 深合并缺省) + 原始覆盖串 + 缺省表(前端对照)。
写: validate 严格拒绝(未知键/未知相位/未知意图名/坏正则/越界数字)——fail-fast。
删: 清空覆盖(回落代码缺省)。
行为开关(agent.comp.overrides: repair_note_injection/overflow_digest/
swallow_counters)不在此表, 见 agent/compensation/overrides.py。
"""
from fastapi import APIRouter, Request

from ..common import err, ok

router = APIRouter()


@router.get("/flow-policy")
async def api_flow_policy_get():
    from ..agent.governance.flow_policy import (
        DEFAULT_FLOW_POLICY, POLICY_KEY, load_flow_policy)
    from ..store import CollabConfigStore
    raw = CollabConfigStore.get(POLICY_KEY, "")
    return ok({"policy": load_flow_policy(CollabConfigStore.get),
               "overrideRaw": raw or "",
               "defaults": DEFAULT_FLOW_POLICY})


@router.put("/flow-policy")
async def api_flow_policy_put(request: Request):
    from ..agent.governance.flow_policy import POLICY_KEY, load_flow_policy, validate_flow_policy
    from ..store import CollabConfigStore
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "请求体须为 JSON")
    pol = body.get("policy") if isinstance(body, dict) else None
    if not isinstance(pol, dict):
        return err(400, "policy 必须是对象")
    okv, errs = validate_flow_policy(pol)
    if not okv:
        return err(400, "配置非法: " + "; ".join(errs[:8]))
    CollabConfigStore.set(POLICY_KEY, __import__("json").dumps(
        pol, ensure_ascii=False))
    return ok({"policy": load_flow_policy(CollabConfigStore.get)})


@router.delete("/flow-policy")
async def api_flow_policy_delete():
    from ..agent.governance.flow_policy import POLICY_KEY, load_flow_policy
    from ..store import CollabConfigStore
    CollabConfigStore.set(POLICY_KEY, "")
    return ok({"policy": load_flow_policy(CollabConfigStore.get)})
