"""
ToolCallingStrategy — 策略抽象层。

策略负责:
  1. 构造请求参数（原生 tools payload 或文本注入）
  2. 调用 LLM provider
  3. 解析响应为统一 AgentChatResponse 格式

新增策略只需继承 ToolCallingStrategy 并实现 chat() 方法。
"""

import json
import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from . import AgentChatResponse, ToolCall
from .fallback_extractors import (
    extract_fallback_tool_calls, extract_fallback_content, clean_model_content,
)

logger = logging.getLogger(__name__)


def _sanitize_tool_args(args: dict) -> dict:
    """Normalize tool call arguments from model to avoid downstream serialization differences.

    Qwen3.5 MTP may not strictly follow OpenAI schema,
    e.g. serializing arrays as JSON strings: '["a","b"]' instead of native ["a","b"].
    """
    sanitized = {}
    for k, v in args.items():
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
                if isinstance(parsed, (list, dict)):
                    sanitized[k] = parsed
                    continue
            except (json.JSONDecodeError, ValueError):
                pass
        sanitized[k] = v
    return sanitized


class ToolCallingStrategy(ABC):
    """Tool Calling 策略基类"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        multi_db,
        model_id: str = "",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> AgentChatResponse:
        """向 LLM 发送消息并返回结构化响应"""
        ...

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """策略标识"""
        ...


class NativeToolCallingStrategy(ToolCallingStrategy):
    """
    原生 function calling 策略。
    
    通过 API 的 tools 参数传递工具定义，解析返回的 tool_calls。
    适用于 OpenAI / Qwen3 / DeepSeek 等支持原生 function calling 的模型。
    """

    @classmethod
    def name(cls) -> str:
        return "native"

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        multi_db,
        model_id: str = "",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> AgentChatResponse:
        from llm_service import LLMService
        service = LLMService(multi_db) if multi_db else None

        if not service:
            return AgentChatResponse(content="", finish_reason="error")

        # 解析 model_id
        model = model_id
        if not model:
            model = _resolve_model_id(multi_db)
        if not model:
            return AgentChatResponse(content="", finish_reason="error")

        model_config = None
        try:
            row = multi_db.main_db.fetchone(
                "SELECT * FROM model_configs WHERE id=?", (model,)
            )
            model_config = dict(row) if row else None
        except Exception:
            pass
        if not model_config:
            return AgentChatResponse(content="", finish_reason="error")

        provider_name = model_config.get("provider", "ollama")
        from providers import get_provider
        provider = get_provider(provider_name)
        if not provider:
            return AgentChatResponse(content="", finish_reason="error")

        # 转换 tool schemas 为 OpenAI 兼容的 tools 列表
        tool_payload = None
        tool_names: Optional[list[str]] = None
        if tools:
            tool_names = [t.get("function", {}).get("name", "") for t in tools if t.get("function")]
            tool_payload = tools

        from llm_service import _get_model_by_id
        mod = _get_model_by_id(multi_db, model)
        if not mod:
            return AgentChatResponse(content="", finish_reason="error")

        try:
            raw = await service._sync_call_for_retry(
                mod, messages,
                mode="tools" if tool_payload else "chat",
                tools=tool_payload,
                output_schema=None,
                max_tokens=max_tokens,
            )
        except Exception as e:
            logger.warning(f"[NativeStrategy] chat failed: {e}, falling back to text")
            return await TextFallbackToolCallingStrategy().chat(
                messages, tools, multi_db, model_id, temperature, max_tokens,
            )

        content = raw.get("content") or ""
        reasoning_content = raw.get("reasoning_content") or ""
        usage = raw.get("usage", {})
        tokens = (usage.get("total_tokens") or
                  (usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)))

        tool_calls: list[ToolCall] = []
        raw_calls = raw.get("tool_calls", [])
        for rc in raw_calls:
            fid = rc.get("id", "")
            fn = rc.get("function", {})
            name = fn.get("name", "")
            args_raw = fn.get("arguments", "{}")
            args = {}
            try:
                args = json.loads(args_raw) if isinstance(args_raw, str) else (args_raw or {})
            except json.JSONDecodeError:
                args = {"_raw": args_raw}
            tool_calls.append(ToolCall(name=name, arguments=_sanitize_tool_args(args), id=fid))

        finish_reason = raw.get("finish_reason", "")

        # 当原生 tool_calls 为空且 content 也为空时，尝试从
        # reasoning_content 中提取文本格式工具调用或回退文本。
        # 兼容 Qwen3.5 等模型在 reasoning_content 中输出 XML 格式工具调用。
        if not tool_calls and not content and reasoning_content:
            fb_calls = extract_fallback_tool_calls(reasoning_content)
            if fb_calls:
                tool_calls = fb_calls
                finish_reason = "tool_calls"
                logger.info(f"[NativeStrategy] parsed {len(fb_calls)} XML tool calls from reasoning_content")
            else:
                clean = extract_fallback_content(reasoning_content)
                if clean:
                    content = clean
                    logger.info(f"[NativeStrategy] extracted fallback text from reasoning_content: {len(clean)} chars")
                else:
                    logger.warning(f"[NativeStrategy] reasoning_content has no valid content (len={len(reasoning_content)})")
        elif not tool_calls and not content:
            logger.warning("[NativeStrategy] LLM returned empty content with no tool_calls")

        # 清理模型输出格式（去除代码围栏等）
        content = clean_model_content(content)

        # 旁路：记录 token 用量到 model_daily_usage（NativeStrategy 漏计）
        try:
            if usage and usage.get('total_tokens') and model_config:
                mid = model_config.get('id')
                if mid:
                    from llm_service import LLMService
                    LLMService(multi_db)._record_usage(mid, usage)
        except Exception:
            pass

        return AgentChatResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_used=tokens,
            finish_reason=finish_reason,
        )


class TextFallbackToolCallingStrategy(ToolCallingStrategy):
    """
    文本标记 tool calling 策略。
    
    将工具定义作为文本注入 system prompt，
    通过 [TOOL_CALL: name] args [/TOOL_CALL] 标记解析工具调用。
    适用于不支持原生 function calling 的模型（如部分 Ollama 本地模型）。
    """

    @classmethod
    def name(cls) -> str:
        return "text_fallback"

    async def chat(
        self,
        messages: list[dict],
        tools: Optional[list[dict]],
        multi_db,
        model_id: str = "",
        temperature: float = 0.3,
        max_tokens: Optional[int] = None,
    ) -> AgentChatResponse:
        from llm_service import LLMService
        from agent_workflow.llm_adapter import create_llm_chat_fn

        prepared = list(messages)

        # 注入工具文本到 system prompt
        if tools:
            tools_lines = []
            for t in tools:
                fn = t.get("function", {})
                name = fn.get("name", "?")
                desc = fn.get("description", "")
                params = fn.get("parameters", {})
                props = params.get("properties", {})
                param_desc = ", ".join(
                    f"{k}: {v.get('description', '')}"
                    for k, v in props.items()
                )
                tools_lines.append(f"- {name}: {desc}" + (f" (params: {param_desc})" if param_desc else ""))
            tools_text = (
                "\n\nAvailable tools:\n" + "\n".join(tools_lines)
                + "\n\nWhen you need to call a tool, use the following format:\n"
                + "[TOOL_CALL: tool_name]\n{\"arg1\": \"val1\"}\n[/TOOL_CALL]\n"
                + "When analysis is complete, directly output the final result."
            )
            for i in range(len(prepared) - 1, -1, -1):
                if prepared[i].get("role") == "system":
                    prepared[i]["content"] = (prepared[i]["content"] or "") + tools_text
                    break

        llm_fn = create_llm_chat_fn(multi_db, model_id)
        try:
            text = await llm_fn(messages=prepared, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            logger.warning(f"[TextFallbackStrategy] chat failed: {e}")
            return AgentChatResponse(content="", finish_reason="error")

        text = text or ""
        tool_calls = extract_fallback_tool_calls(text)
        clean_content = extract_fallback_content(text) if tool_calls else text
        clean_content = clean_model_content(clean_content)

        return AgentChatResponse(
            content=clean_content,
            tool_calls=tool_calls,
            tokens_used=len(text) // 4,
            finish_reason="tool_calls" if tool_calls else "stop",
        )


# ─── 策略工厂 ───

def _resolve_provider_capabilities(multi_db, model_id: str) -> bool:
    """
    查询模型配置判断是否支持原生 function calling。
    仅 Provider 声明 supports_tools=True 时才返回 True。
    """
    try:
        row = multi_db.main_db.fetchone(
            "SELECT * FROM model_configs WHERE id=?", (model_id,)
        )
        if not row:
            return False
        cfg = dict(row)
        provider_name = cfg.get("provider", "ollama")
        from providers import get_provider
        provider = get_provider(provider_name)
        return provider.supports_tools if provider else False
    except Exception:
        return False


def create_strategy(
    multi_db=None,
    model_id: str = "",
    preferred: str = "",
) -> ToolCallingStrategy:
    """
    根据模型配置自动选择合适的策略。
    
    Args:
        multi_db: 数据库管理器
        model_id: 模型 ID（用于查询 provider 能力）
        preferred: 首选策略名（"native" / "text_fallback"），空则自动判断
    
    Returns:
        ToolCallingStrategy 实例
    """
    if preferred == "native":
        return NativeToolCallingStrategy()
    if preferred == "text_fallback":
        return TextFallbackToolCallingStrategy()

    # 自动解析 model_id（如果未提供）
    if not model_id and multi_db:
        model_id = _resolve_model_id(multi_db)

    # 自动判断：Provider 声明 supports_tools 则用 native，否则 fallback
    if model_id and multi_db:
        if _resolve_provider_capabilities(multi_db, model_id):
            logger.info(f"[ToolCalling] selected NativeStrategy (model={model_id})")
            return NativeToolCallingStrategy()

    logger.info(f"[ToolCalling] selected TextFallbackStrategy (model={model_id or 'unknown'})")
    return TextFallbackToolCallingStrategy()


# ── 共享工具函数 ──

def _resolve_model_id(multi_db) -> str:
    """从数据库中解析默认模型 ID"""
    try:
        configs = multi_db.main_db.fetchall(
            "SELECT id FROM model_configs ORDER BY is_default DESC, name"
        )
        if configs:
            return configs[0].get("id") or configs[0].get("model_id", "")
    except Exception:
        pass
    return ""
