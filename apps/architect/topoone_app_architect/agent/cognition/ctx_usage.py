"""会话上下文用量记账(认知层) — 通用上下文容量观测, 非特性硬编码。

职责三段:
  - estimate_msgs_tokens  估算口径单源(chars/token 常量, 与主后端 TokenBudget 一致)
  - resolve_budget        可用预算解析(薄封装 llm.resolve_context_budget, 探测缓存复用)
  - record_turn           回合账目落账(fail-soft, 经 ConversationsStore.merge_meta 通用能力)

数据契约: conversations.meta.ctxUsage = {used: int, budget: int(0=容量未知), at: epoch_ms}
消费面: GET /sessions 列表 meta 透传 → 前端 CtxUsageChip(发送按钮旁)。
扩展点: 后续 token 成本/每回合延迟等回合级指标可并入本模块同款落账路径。
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List

logger = logging.getLogger("arch.cognition.ctx_usage")

CHARS_PER_TOKEN = 2          # 估算口径单源(与主后端 apps/chat TokenBudget 一致)
CTX_USAGE_KEY = "ctxUsage"   # conversations.meta 账目键


def estimate_msgs_tokens(msgs: List[Dict[str, str]]) -> int:
    """消息组装体 token 估算(chars/CHARS_PER_TOKEN; 中文偏保守高估, 作容量提示足够)。"""
    return sum(len(str(m.get("content") or "")) for m in msgs or []) // CHARS_PER_TOKEN


def resolve_budget(model_id: str) -> int:
    """可用上下文预算(tokens); 探测不可得(纯 OpenAI 兼容远端) → 0=未知(不猜)。"""
    try:
        from .llm import resolve_context_budget
        b = resolve_context_budget(None, model_id or "")
        return int(b) if b else 0
    except Exception:  # noqa: BLE001 — 容量观测零阻塞主链
        return 0


def record_turn(conv_id: str, msgs: List[Dict[str, str]], model_id: str) -> None:
    """回合账目落账(fail-soft): used=本回合实际发送组装体估算, budget=可用预算。

    调用点约定: 回合落库阶段(_chat_land)——装配阶段保持纯函数, 持久化归 land。
    任何异常吞掉记 debug, 绝不阻塞回合主链。"""
    try:
        from ...arch_routes import store
        store.ConversationsStore.merge_meta(conv_id, {
            CTX_USAGE_KEY: {"used": estimate_msgs_tokens(msgs),
                            "budget": resolve_budget(model_id),
                            "at": int(time.time() * 1000)}})
    except Exception as e:  # noqa: BLE001
        logger.debug("[ctx-usage] 落账失败(忽略): %s", e)
