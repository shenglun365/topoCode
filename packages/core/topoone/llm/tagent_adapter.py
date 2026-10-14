"""tAgent LLMClient adapter — 复用主项目 LLM 服务（provider 路由 / 模型配置 / 用量审计）。

TopoLLMClientAdapter 实现 topocode_agent 的 LLMClient Protocol（INTEGRATION.md §4）:
  - chat():        非流式，支持原生 tools 模式 → LLMService._sync_call_for_retry
  - chat_stream(): 流式 → provider.chat_stream（线程 + 队列逐 chunk 推送）
  - supports_tools: 由 provider 声明决定（ollama / openai_compat 均 True）

行为约定:
  - 模型默认值与主后端一致（model_configs.is_default）；
  - 用量审计走 service._save_call_log（session 前缀 agent-，template_id='tagent'，
    与旧 agent_workflow/llm_adapter.py 口径一致，便于对账）；
  - 流式路径统一 mode='chat'：工具调用由 tAgent 策略层从文本标记解析
    （text_fallback），与主项目 ai-chat 行为一致；tools 参数在流式下忽略。
"""

from __future__ import annotations

import asyncio
import json
import logging
import queue
import time
from typing import Any, AsyncIterator, Optional

from topocode_agent.core.llm.protocol import ChatResponse, StreamEvent, ToolCall

logger = logging.getLogger(__name__)


def _parse_tool_call(d: dict) -> ToolCall:
    fn = d.get("function", {})
    args_raw = fn.get("arguments", "{}")
    args: Any = {}
    if isinstance(args_raw, str) and args_raw:
        try:
            args = json.loads(args_raw)
        except (json.JSONDecodeError, ValueError):
            args = {}
    elif isinstance(args_raw, dict):
        args = args_raw
    return ToolCall(name=fn.get("name", ""), arguments=args or {},
                    id=d.get("id", ""), raw_arguments=args_raw if isinstance(args_raw, str) else "")


class TopoLLMClientAdapter:
    """主项目 LLM 服务 → tAgent LLMClient 桥接（进程内，复用 multi_db）。"""

    def __init__(self, multi_db, model_id: str = "", session_suffix: str = "tagent"):
        self._multi_db = multi_db
        self._model_id = model_id
        self._session_suffix = session_suffix

    # ── 模型解析 ──

    def _default_model_id(self) -> str:
        try:
            configs = self._multi_db.main_db.fetchall(
                "SELECT * FROM model_configs ORDER BY is_default DESC, name")
            defaults = [m for m in configs if m.get("is_default")]
            if defaults:
                return defaults[0]["id"]
            return configs[0]["id"] if configs else ""
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoLLM] default model resolve failed: %s", e)
            return ""

    def _resolve_model_id(self, model: str = "") -> str:
        return model or self._model_id or self._default_model_id()

    def _model_row(self, model_id: str) -> Optional[dict]:
        from topoone.llm.service import _get_model_by_id
        try:
            return _get_model_by_id(self._multi_db, model_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoLLM] model lookup failed: %s", e)
            return None

    @property
    def supports_tools(self) -> bool:
        """provider 声明 supports_tools 才为 True（与主项目 create_strategy 判定一致）。"""
        mod_id = self._resolve_model_id()
        if not mod_id:
            return False
        mod = self._model_row(mod_id)
        if not mod:
            return False
        try:
            from topoone.llm.providers import get_provider
            provider = get_provider(mod.get("provider", "ollama"))
            return bool(provider and provider.supports_tools)
        except Exception:  # noqa: BLE001
            return False

    # ── 非流式 ──

    async def chat(self, messages: list[dict], *, tools: Optional[list[dict]] = None,
                   model: str = "", temperature: float = 0.3,
                   max_tokens: Optional[int] = None,
                   extra: Optional[dict] = None) -> ChatResponse:
        from topoone.llm.service import LLMService

        mod_id = self._resolve_model_id(model)
        if not mod_id:
            raise RuntimeError("No model configured")
        mod = self._model_row(mod_id)
        if not mod:
            raise RuntimeError(f"Model not found: {mod_id}")

        service = LLMService(self._multi_db)
        tool_payload = list(tools) if (tools and self.supports_tools) else None
        mode = "tools" if tool_payload else "chat"
        start_ts = time.time()
        request_id = f"tagent-{mod_id}-{int(start_ts)}"
        try:
            raw = await service._sync_call_for_retry(
                mod, list(messages), mode, tool_payload, None, max_tokens=max_tokens)
        except Exception as e:
            self._audit(service, mod, messages, "", "error", str(e), start_ts, request_id)
            raise

        content = raw.get("content") or ""
        usage = raw.get("usage") or {}
        tool_calls = [_parse_tool_call(d) for d in (raw.get("tool_calls") or [])]
        latency_ms = int((time.time() - start_ts) * 1000)
        self._audit(service, mod, messages, content, "success", "", start_ts, request_id,
                    usage, latency_ms, tool_calls)
        return ChatResponse(
            content=content,
            reasoning_content=raw.get("reasoning_content") or "",
            tool_calls=tool_calls,
            usage=usage,
            model=mod_id,
            finish_reason=raw.get("finish_reason") or "",
        )

    # ── 流式 ──

    def chat_stream(self, messages: list[dict], *, tools: Optional[list[dict]] = None,
                    model: str = "", temperature: float = 0.3,
                    max_tokens: Optional[int] = None,
                    extra: Optional[dict] = None) -> AsyncIterator[StreamEvent]:
        if tools:
            # 流式路径不下发原生 tools（provider.chat_stream 的 tools 参数是主项目
            # 工具注册表名称，与 tAgent OpenAI schema 不兼容）；工具调用经文本标记解析。
            logger.info("[TopoLLM] chat_stream: tools ignored (text tool calling via tAgent strategy)")

        async def gen() -> AsyncIterator[StreamEvent]:
            from topoone.llm.providers import get_provider
            from topoone.llm.service import LLMService

            mod_id = self._resolve_model_id(model)
            if not mod_id:
                raise RuntimeError("No model configured")
            mod = self._model_row(mod_id)
            if not mod:
                raise RuntimeError(f"Model not found: {mod_id}")
            provider = get_provider(mod.get("provider", "ollama"))
            if provider is None:
                raise RuntimeError(f"Unknown LLM provider '{mod.get('provider')}'")

            q: "queue.Queue" = queue.Queue()
            loop = asyncio.get_event_loop()
            fut = loop.run_in_executor(
                None, lambda: provider.chat_stream(
                    mod, list(messages), q, tools=None, mode="chat", max_tokens=max_tokens))

            start_ts = time.time()
            full_content = ""
            stream_tool_calls: list[dict] = []
            token_info: dict = {}
            try:
                while True:
                    item = await loop.run_in_executor(None, q.get)
                    if isinstance(item, str):
                        full_content += item
                        yield StreamEvent(type="delta", content=item)
                    elif isinstance(item, dict):
                        itype = item.get("type")
                        if itype == "tool_calls":
                            try:
                                stream_tool_calls = json.loads(item.get("data") or "[]")
                            except (json.JSONDecodeError, ValueError):
                                stream_tool_calls = []
                        elif itype == "error":
                            raise RuntimeError(f"LLM stream error: {item.get('message', '')}")
                        elif itype == "done":
                            try:
                                token_info = await fut or {}
                            except Exception:  # noqa: BLE001
                                token_info = {}
                            tcs = [_parse_tool_call(d) for d in stream_tool_calls] or None
                            yield StreamEvent(
                                type="done",
                                content=item.get("content") or full_content,
                                tool_calls=tcs,
                                usage=token_info,
                                finish_reason="tool_calls" if tcs else "stop",
                            )
                            break
            finally:
                latency_ms = int((time.time() - start_ts) * 1000)
                try:
                    service = LLMService(self._multi_db)
                    self._audit(service, mod, messages, full_content,
                                "success", "", start_ts,
                                f"tagent-stream-{mod_id}-{int(start_ts)}",
                                token_info, latency_ms)
                except Exception as e:  # noqa: BLE001
                    logger.warning("[TopoLLM] stream audit failed: %s", e)

        return gen()

    # ── 审计 ──

    def _audit(self, service, mod: dict, messages: list[dict], content: str,
               status: str, error_message: str, start_ts: float, request_id: str,
               usage: Optional[dict] = None, latency_ms: int = 0,
               tool_calls: Optional[list[ToolCall]] = None) -> None:
        """llm_call_logs + model_daily_usage（与旧 llm_adapter.py 口径一致）。"""
        try:
            latency_ms = latency_ms or int((time.time() - start_ts) * 1000)
            token_data = usage or {}
            if not token_data.get("total_tokens"):
                prompt_chars = sum(len(m.get("content") or "") for m in messages)
                token_data = {
                    "prompt_tokens": max(1, int(prompt_chars / 3.5)),
                    "completion_tokens": max(1, int(len(content or "") / 3.5)),
                    "total_tokens": max(1, int((prompt_chars + len(content or "")) / 3.5)),
                }
            tcs_recorded = [
                {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                for tc in (tool_calls or [])
            ]
            service._save_call_log(
                main_db=self._multi_db.main_db,
                session_id=f"agent-{self._session_suffix}",
                messages=messages,
                full_content=content,
                model={"id": mod.get("id", "")},
                request_id=request_id,
                template_id="tagent",
                extra_meta={"source": "topocode_agent"},
                tool_calls_recorded=tcs_recorded,
                latency_ms=latency_ms,
                status=status,
                error_message=error_message,
                token_data=token_data,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoLLM] audit failed: %s", e)
