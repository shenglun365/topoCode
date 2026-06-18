"""
Tool Calling 策略层 — 统一 Agent 与 LLM 的 tool calling 接口。

三层架构（由高到低）:
  1. Agent Runtime (_run_agentic) — ReAct 循环, 不感知策略细节
  2. ToolCallingStrategy — 策略抽象, 决定"如何调用工具"
  3. Provider — LLM API 通信, 不感知 tool calling 策略

两种策略:
  - NativeStrategy:     原生 function calling (OpenAI/Qwen3/DeepSeek)
  - TextFallbackStrategy:文本标记 [TOOL_CALL:] 注入 (弱模型/Ollama 旧版)
"""

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolCall:
    """LLM 发起的工具调用请求（与代理和策略无关的统一格式）"""
    name: str
    arguments: dict[str, Any]
    id: str = ""


@dataclass
class AgentChatResponse:
    """统一聊天响应 — 无论何种策略都返回此格式"""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_used: int = 0
    finish_reason: str = ""


from .strategy import (
    ToolCallingStrategy,
    NativeToolCallingStrategy,
    TextFallbackToolCallingStrategy,
    create_strategy,
)
from .chat import agentic_chat
