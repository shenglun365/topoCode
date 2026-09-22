"""CallCatalog — 单项调用统一目录(链3③, 整体设计 §4.1 / 需求规格 §6-⑨)。

一张目录表统一「目的 → 模型路由 / 脚手架 / 重试 / 兜底」入口; **配置域不合并**
(mixed-fleet 裁决: 资产助理工种(agent_roles)与编码编排轻任务(light_tasks)
按领域分列, 各自 REST/配置键不变)——本目录只做路由解析与 CallTurn 转发。
词汇别名(§6-⑨): 裸工种/轻任务名 → 目录键; Purpose 词表沿用 D10 冻结。
model_id 语义(护栏 R3): 显式传入 > 目录领域路由 > None(全局偏好兜底)。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

from ..compensation.ctx import Purpose
from ..governance.gears import DEFAULT_TIER_ID
from .call import call


def _light_route(key: str) -> Callable[[], Optional[str]]:
    """轻任务模型路由(编码编排侧, config `llm.lightTaskModels`)。"""
    def _resolve() -> Optional[str]:
        try:
            from ...arch_routes.agent_roles import load_light_tasks_cfg
            from ..governance.light_tasks import resolve_light_task_model
            return resolve_light_task_model(key, load_light_tasks_cfg()) or None
        except Exception:  # noqa: BLE001 — 路由失败回退全局偏好
            return None
    return _resolve


def _role_route(role: str) -> Callable[[], Optional[str]]:
    """资产助理工种路由(语义/数据资产管线, config `agent_roles`)。"""
    def _resolve() -> Optional[str]:
        try:
            from ..cognition.roles import role_model_id
            return role_model_id(role) or None
        except Exception:  # noqa: BLE001
            return None
    return _resolve


@dataclass(frozen=True)
class CatalogEntry:
    purpose: Purpose
    model_route: Callable[[], Optional[str]]


CATALOG: Dict[str, CatalogEntry] = {
    # ── 编码编排侧轻任务(governance.light_tasks 领域) ──
    "light:summary": CatalogEntry(Purpose.SUMMARY, _light_route("summary")),
    "light:probe": CatalogEntry(Purpose.PROBE, _light_route("probe")),
    "light:distill": CatalogEntry(Purpose.DISTILL, _light_route("distill")),
    # intent: 分类类探测调用, 复用 PROBE(D10 词表冻结不加成员; light_tasks
    # 单独绑定键, 缺省跟随现行为)
    "light:intent": CatalogEntry(Purpose.PROBE, _light_route("intent")),
    # ── 资产助理工种(cognition.roles 领域) ──
    "role:extract": CatalogEntry(Purpose.ROLE_EXTRACT, _role_route("extract")),
    "role:verify": CatalogEntry(Purpose.ROLE_VERIFY, _role_route("verify")),
    "role:induce": CatalogEntry(Purpose.ROLE_INDUCE, _role_route("induce")),
    "role:pseudo": CatalogEntry(Purpose.ROLE_PSEUDO, _role_route("pseudo")),
    "role:evaluate": CatalogEntry(Purpose.ROLE_EVALUATE, _role_route("evaluate")),
    "role:mine": CatalogEntry(Purpose.ROLE_MINE, _role_route("mine")),
    # ── 概要设计(跟随会话/显式模型, 无领域绑定) ──
    "design": CatalogEntry(Purpose.DESIGN, lambda: None),
}

# 词汇别名(裸名 → 目录键; 词汇迁移期兼容)
ALIASES: Dict[str, str] = {
    "summary": "light:summary", "probe": "light:probe", "distill": "light:distill",
    "intent": "light:intent",
    "extract": "role:extract", "verify": "role:verify", "induce": "role:induce",
    "pseudo": "role:pseudo", "evaluate": "role:evaluate", "mine": "role:mine",
}


def resolve_key(name: str) -> str:
    return ALIASES.get(name, name)


def catalog_call(name: str, messages, *, tier: str = DEFAULT_TIER_ID,
                 model_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
    """目录统一入口: key(或别名) → 领域模型路由 → CallTurn。

    model_id 显式传入时优先于目录路由(护栏 R3: explicit > 领域配置 > 全局)。
    其余参数(turns.call): tier/schema/max_tokens/validate/fallback/runner/root/project。
    """
    entry = CATALOG[resolve_key(name)]
    mid = model_id if model_id else entry.model_route()
    return call(entry.purpose, messages, tier=tier, model_id=mid, **kwargs)
