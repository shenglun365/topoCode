"""资产助理注册表(实现层, 原名 tAgent 角色注册表) — 数据资产管理·语义提取
管线的「工种 → 模型」绑定。

资产助理 = {name, label, modelId, note}；配置三级：全局偏好 < 项目级 < 主 KB 下发。
消费方式：**per-call model_id 参数**生效（护栏 R3：不得写全局 llm 配置）。
消费点全部在语义/数据资产管线（asset_extract / sem.engine / naming / evaluator）；
与编码编排侧的「轻任务模型」(governance/light_tasks.py) 是两个领域，勿混；
与已清退的会话角色(T4, sessions._roles_of 僵尸兼容) 无涉。

REST(GET/PUT /agent/roles)留在 arch_routes.agent_roles 适配层。
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from ...arch_routes.store import CollabConfigStore

logger = logging.getLogger("arch.agent.roles")

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


def _known_model_ids() -> List[str]:
    """architect 模型目录(llm.models)的有效 id 集(现读, 写路径低频无性能压力)。

    目录为空(未同步/新装)时返回空表 → 校验跳过, 不误伤。"""
    try:
        raw = CollabConfigStore.get("llm.models", "")
        rows = json.loads(raw) if raw else []
        return [str(r.get("id") or "") for r in rows
                if isinstance(r, dict) and r.get("id")]
    except Exception:  # noqa: BLE001
        return []


def set_roles(roles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """写入角色覆盖（仅接受已知 name；modelId 越界剥离并告警）。

    教训(cv-168 一揽子对齐): modelId 越界曾静默透传 → 网关侧静默回退
    KB 默认模型, 实际执行模型与角色路由配置不一致。目录为空时跳过校验。"""
    known = {d["name"] for d in DEFAULT_ROLES}
    valid_ids = _known_model_ids()
    clean = []
    for r in roles or []:
        if not isinstance(r, dict) or r.get("name") not in known:
            continue
        mid = (r.get("modelId") or "").strip()
        if mid and valid_ids and mid not in valid_ids:
            logger.warning("[roles] 角色 %s 配置的 modelId %r 不在模型目录, 已剥离"
                           "(防止网关静默回退 KB 默认)", r.get("name"), mid)
            mid = ""
        clean.append({"name": r["name"], "label": r.get("label") or "",
                      "modelId": mid})
    CollabConfigStore.set(_ROLES_KEY, json.dumps(clean, ensure_ascii=False))
    return get_roles()


def role_model_id(role: str) -> str:
    """角色 → 配置的 modelId（空串 = 调用方回退全局偏好/会话选择）。

    写入侧已在 set_roles 校验越界; 此处不再查目录(避免每调用 IO)。

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
