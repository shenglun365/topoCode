"""
agentic_chat — 统一 Agentic 聊天入口。

此函数是 _run_agentic 与 LLM 之间的唯一通信接口。
策略选择由 create_strategy 自动完成，调用方无需关心具体策略。
"""

import logging
from typing import Optional

from . import AgentChatResponse
from .strategy import create_strategy, ToolCallingStrategy

logger = logging.getLogger(__name__)


async def agentic_chat(
    messages: list[dict],
    tools: Optional[list[dict]] = None,
    multi_db=None,
    model_id: str = "",
    strategy: Optional[ToolCallingStrategy] = None,
    temperature: float = 0.3,
    max_tokens: Optional[int] = None,
) -> AgentChatResponse:
    """
    统一 Agentic 聊天函数。
    
    与 _run_agentic 之间:
      - 输入: 消息列表 + 工具定义
      - 输出: 统一 AgentChatResponse（content / tool_calls）
      - 不关心: 具体是什么策略（原生 / 文本 fallback）
    """
    if strategy is None:
        strategy = create_strategy(multi_db, model_id)

    return await strategy.chat(
        messages=messages,
        tools=tools,
        multi_db=multi_db,
        model_id=model_id,
        temperature=temperature,
        max_tokens=max_tokens,
    )
