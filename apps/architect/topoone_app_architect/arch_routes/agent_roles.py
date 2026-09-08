"""tAgent 角色注册表 — plan-C §9（不同认知工作绑不同模型/API）。

角色 = {name, label, modelId, note}；配置三级：全局偏好 < 项目级 < 主 KB 下发。
本期落全局注册表（arch_collab_config key=`agent_roles`，主库）；项目级/主 KB
下发留位（resolve 时依次覆盖，未实现层恒回退全局）。

消费方式：**per-call model_id 参数**生效（护栏 R3：不得写全局 llm 配置）。
REST：GET/PUT /agent/roles。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from .common import err, ok
from .store import CollabConfigStore

logger = logging.getLogger(__name__)

router = APIRouter()

_ROLES_KEY = "agent_roles"

# 初始角色集（plan-C §9；modelId 空 = 跟随调用方缺省模型）
DEFAULT_ROLES: List[Dict[str, Any]] = [
    {"name": "extract", "label": "提取", "modelId": "",
     "note": "快模型即可——API 归一化管线会裁决命名"},
    {"name": "verify", "label": "验收比对", "modelId": "",
     "note": "强模型——严 profile，L3 按需辅助"},
    {"name": "induce", "label": "归纳", "modelId": "",
     "note": "中档模型——规约/术语提议"},
    {"name": "pseudo", "label": "伪码解释", "modelId": "",
     "note": "快模型——PseudoExplainer"},
    {"name": "evaluate", "label": "方案/结果评估", "modelId": "",
     "note": "强模型——评估报告 LLM 增强段(WS4 评估器机械段不依赖)"},
    {"name": "mine", "label": "能力提炼", "modelId": "",
     "note": "强模型——历史会话→规约/流程/技巧提案(WS7 提炼器)"},
]


def get_roles() -> List[Dict[str, Any]]:
    """读取角色注册表：默认集 ∪ 已存覆盖（按 name 合并，未知 name 丢弃）。"""
    stored: Dict[str, Any] = {}
    try:
        raw = CollabConfigStore.get(_ROLES_KEY, "")
        if raw:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                stored = {r.get("name"): r for r in parsed if isinstance(r, dict) and r.get("name")}
    except Exception as e:
        logger.warning("[agent-roles] 读取失败: %s", e)
    out: List[Dict[str, Any]] = []
    for d in DEFAULT_ROLES:
        row = dict(d)
        over = stored.get(d["name"])
        if over:
            row["modelId"] = over.get("modelId") or row.get("modelId") or ""
            if over.get("label"):
                row["label"] = over["label"]
        out.append(row)
    return out


def set_roles(roles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """写入角色覆盖（仅接受已知 name；modelId 越界校验交由前端/调用方）。"""
    known = {d["name"] for d in DEFAULT_ROLES}
    clean = []
    for r in roles or []:
        if not isinstance(r, dict) or r.get("name") not in known:
            continue
        clean.append({"name": r["name"], "label": r.get("label") or "",
                      "modelId": (r.get("modelId") or "").strip()})
    CollabConfigStore.set(_ROLES_KEY, json.dumps(clean, ensure_ascii=False))
    return get_roles()


def role_model_id(role: str) -> str:
    """角色 → 配置的 modelId（空串 = 调用方回退全局偏好/会话选择）。

    三级覆盖预留：项目级(project config) > 主 KB 下发 > 全局注册表。
    """
    if not role:
        return ""
    for r in get_roles():
        if r["name"] == role:
            return r.get("modelId") or ""
    return ""


def resolve_role_model(role: str, explicit: str = "") -> Optional[str]:
    """per-call 模型解析（护栏 R3：只作 per-call 参数，不写全局 llm 配置）。

    优先级：explicit(会话/前端显式选择) > 角色注册表 > None。
    返回 None = 调用方回退全局偏好(get_model_preference)，再由主后端 is_default 兜底。
    """
    explicit = (explicit or "").strip()
    if explicit:
        return explicit
    return role_model_id(role) or None


# 对话场景 → 角色（对话通道 tAgent 循环入口按 skillScenarios 路由；
# 通用需求对话无对应角色 → 返回 '' 保持既有模型链不变）
_SCENARIO_ROLE = {
    "extract": "extract",
    "accept": "verify",
    "naming": "induce",
}


def scenario_role(scenarios) -> str:
    """首个命中角色映射的场景生效；均未命中返回 ''（保持既有模型链）。"""
    for s in scenarios or []:
        r = _SCENARIO_ROLE.get(str(s or "").strip())
        if r:
            return r
    return ""


@router.get("/agent/roles")
async def api_roles_get():
    return ok({"roles": get_roles()})


@router.put("/agent/roles")
async def api_roles_put(request: Request):
    body = await request.json()
    roles = body.get("roles") if isinstance(body, dict) else None
    if roles is None or not isinstance(roles, list):
        return err(400, "roles 必须是数组")
    return ok({"roles": set_roles(roles)})
