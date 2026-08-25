"""I2 — chat 应用薄化到 tAgent（ChatAssistant 接线基础层）。

chat 现网是手写 agentic 循环（直连 /v1/chat/completions + 流式解析 + 工具执行 +
SSE）。本模块提供 tAgent 等价能力，供 send_chat_message 按 TOPOCODE_CHAT_BACKEND
切换（默认 legacy 保安全，tagent 启用薄化）：

- `make_chat_llm(model_id, model_cfg)`：tAgent LLMClient（OpenAI 兼容，复用主项目
  model_configs 的 url/api_key/model/温度等）。
- `build_web_tool_registry(tool_names, executor)`：把 web 工具适配为 tAgent
  AgentTool（复用 WebToolExecutor 执行 + 截断/空结果标记）。
- `run_tagent_chat(...)`：跑 tAgent 流式 agentic 循环（ConversationSession.stream，
  原生 + TextFallback 双策略），把 AgentEvent 映射为 chat 的 SSE 事件
  (chunk/reasoning/tool_call/tool_result/done/error)，并按需落库 assistant/tool 消息。

差异说明（tagent 路径 vs legacy）：
- 支持 TextFallback（无原生 function calling 的模型输出 [TOOL_CALL] 文本也能跑工具），
  比 legacy 更鲁棒。
- reasoning 流式：legacy 逐 token 推 reasoning；tagent 路径当前不单独推 reasoning
  （最终内容不受影响）。如需保留可后续扩展 tAgent stream 事件。
"""

from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Callable, Optional

from topocode_agent.conversation.session import ConversationSession
from topocode_agent.core.events import AgentEvent
from topocode_agent.core.llm.openai_compat import OpenAICompatLLMClient
from topocode_agent.core.tool.base import AgentTool, ToolRegistry, ToolResult

logger = logging.getLogger(__name__)


# ── LLM 客户端 ───────────────────────────────────────────────────

def make_chat_llm(model_cfg: dict, supports_tools: bool = True) -> OpenAICompatLLMClient:
    """由主项目 model_config 行构造 tAgent OpenAI 兼容 LLMClient。

    model_cfg 字段（model_configs 表行）：url / api_key / model / temperature /
    max_tokens / frequency_penalty / presence_penalty / timeout / extra_config。
    """
    url = (model_cfg.get("url") or "").rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3]
    api_key = model_cfg.get("api_key") or ""
    model = model_cfg.get("model") or ""
    timeout = model_cfg.get("timeout") or 300
    return OpenAICompatLLMClient(
        base_url=url, api_key=api_key, model=model,
        supports_tools=supports_tools, timeout=float(timeout),
    )


def llm_call_kwargs(model_cfg: dict) -> dict:
    """每次 chat 调用透传的温度/上限/额外参数（对齐 legacy payload）。"""
    kw: dict = {}
    if model_cfg.get("temperature") is not None:
        kw["temperature"] = model_cfg["temperature"]
    if model_cfg.get("max_tokens"):
        kw["max_tokens"] = model_cfg["max_tokens"]
    extra: dict = {}
    for k in ("frequency_penalty", "presence_penalty"):
        if model_cfg.get(k) is not None:
            extra[k] = model_cfg[k]
    raw = model_cfg.get("extra_config")
    if raw and isinstance(raw, str):
        try:
            e = json.loads(raw)
            if isinstance(e, dict):
                extra.update(e)
        except (json.JSONDecodeError, TypeError):
            pass
    if extra:
        kw["extra"] = extra
    return kw


# ── web 工具适配 ─────────────────────────────────────────────────

class _WebToolAdapter(AgentTool):
    """web 工具 → tAgent AgentTool（执行委托 WebToolExecutor，保留截断/空结果标记）。"""

    llm_visible = True
    version = "1.0"
    author = "chat"
    category = "web"

    def __init__(self, definition: dict, executor: Any):
        fn = definition.get("function", {})
        self.name = fn.get("name", "")
        self.description = fn.get("description", "")
        self._definition = definition
        self._executor = executor

    def to_openai_schema(self) -> Optional[dict]:
        if not self.llm_visible:
            return None
        return self._definition

    async def execute(self, **kwargs) -> ToolResult:
        import asyncio
        try:
            result = await asyncio.to_thread(self._executor.execute, self.name, kwargs)
            if isinstance(result, dict) and result.get("error"):
                return ToolResult.fail(str(result["error"]))
            return ToolResult.ok(result)
        except Exception as e:  # noqa: BLE001
            logger.warning("[ChatTool] %s failed: %s", self.name, e)
            return ToolResult.fail(str(e))


def build_web_tool_registry(tool_names: list, executor: Any,
                            definitions: Optional[list] = None) -> ToolRegistry:
    """tool_names → tAgent ToolRegistry（definitions 缺省用 web_tools 全量映射）。"""
    if definitions is None:
        from topoone_app_chat.web_tools import get_web_tool_definitions
        definitions = get_web_tool_definitions(tool_names)
    reg = ToolRegistry()
    for d in definitions or []:
        fn = d.get("function", {})
        name = fn.get("name", "")
        if name:
            reg.register(_WebToolAdapter(d, executor))
    return reg


def split_history(context_messages: list[dict], user_content: str) -> tuple:
    """把 DB 上下文拆为 (history, user_input)：以末条 user 消息为界。

    context_messages 含已入库的本次 user 消息；stream 会再追加 user_input，
    故 history 需剔除末条 user 以免重复。
    """
    for i in range(len(context_messages) - 1, -1, -1):
        if (context_messages[i].get("role") or "") == "user":
            return context_messages[:i], context_messages[i].get("content", user_content)
    return list(context_messages), user_content


# ── 事件映射 + 落库 ──────────────────────────────────────────────

class ChatEventSink:
    """把 tAgent AgentEvent 映射为 chat SSE 事件 dict，并收集需落库的消息。"""

    def __init__(self, session_id: str, sdb, persist: bool = True):
        self.session_id = session_id
        self._sdb = sdb
        self._persist = persist
        self.events: list[dict] = []
        # 本轮新增待落库消息（assistant/tool），stream 结束后统一落库
        self.pending_messages: list[dict] = []
        self._tool_ids: list[str] = []

    def on_event(self, ev: AgentEvent) -> None:
        t = ev.type
        d = ev.data
        if t == "token":
            self.events.append({"type": "chunk", "text": d.get("text", "")})
        elif t == "tool_call":
            tcid = d.get("tool_call_id") or f"tc_{len(self._tool_ids)}"
            self._tool_ids.append(tcid)
            self.events.append({"type": "tool_call", "id": tcid,
                                "name": d.get("name", ""),
                                "arguments": d.get("arguments", {})})
        elif t == "tool_result":
            self.events.append({"type": "tool_result", "id": d.get("tool_call_id", ""),
                                "name": d.get("name", ""),
                                "result": {"ok": d.get("success", False),
                                           "preview": d.get("preview", "")}})
        elif t == "error":
            self.events.append({"type": "error", "message": d.get("message", "")})
        # done 由调用方在 stream 结束后补发（含 content/quality）


def _persist_messages(sdb, session_id: str, messages: list[dict],
                      base_len: int) -> None:
    """把 stream 后新增的 assistant/tool 消息落库（对齐 legacy 的角色/元数据）。"""
    import datetime
    from topoone_app_chat.chat import _make_message_id
    now = datetime.datetime.now().isoformat()
    for m in messages[base_len:]:
        role = m.get("role")
        if role not in ("assistant", "tool"):
            continue
        content = m.get("content") or ""
        if role == "assistant":
            meta = {}
            tcs = m.get("tool_calls")
            if tcs:
                meta["tool_calls"] = [
                    {"name": tc.get("function", {}).get("name", ""),
                     "arguments": _safe_json(tc.get("function", {}).get("arguments", "{}"))}
                    for tc in tcs
                ]
            meta_json = json.dumps(meta, ensure_ascii=False) if meta else "{}"
        else:
            meta_json = json.dumps({"tool_call_id": m.get("tool_call_id", "")})
        try:
            sdb.execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (_make_message_id(), session_id, role, content, meta_json, now),
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("[tagent_chat] persist %s failed: %s", role, e)


def _safe_json(raw) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


# ── 流式 agentic 运行器 ──────────────────────────────────────────

async def run_tagent_chat(
    *,
    llm,
    tools: ToolRegistry,
    system_prompt: str,
    history: list[dict],
    user_input: str,
    model: str = "",
    temperature: float = 0.3,
    max_turns: int = 8,
    session_id: str = "",
    sdb=None,
    persist: bool = True,
) -> AsyncIterator[dict]:
    """跑 tAgent 流式 agentic 循环，产出 chat SSE 事件 dict 流。

    history：DB 载入的上下文（system + 之前各轮，**不含本次 user 消息**）。
    user_input：本次用户消息（由 stream 追加）。最终 yield 一个
    {type:done, content, quality} 事件。
    """
    session = ConversationSession(
        llm, tools, system_prompt=system_prompt,
        max_turns=max_turns, model=model, temperature=temperature,
    )
    # 用 DB 历史做种子（_ensure_system 见首条非 system 才补 system）
    if history:
        session._messages = [dict(m) for m in history]
    base_len = len(session._messages)

    sink = ChatEventSink(session_id, sdb, persist=persist)
    final_content = ""

    async for ev in session.stream(user_input):
        sink.on_event(ev)
        if ev.type == "token":
            final_content += ev.data.get("text", "")
        for out in sink.events:
            if out["type"] == "tool_call":
                # 工具轮：此前的 token 是工具调用前导（含 [TOOL_CALL] 文本），
                # 不属于最终答案 → 重置，只保留末轮（最终答案）内容。
                final_content = ""
            if out["type"] == "chunk" and "[TOOL_CALL" in out.get("text", ""):
                continue  # 不向前端泄漏工具调用标记（TextFallback 工具轮文本）
            yield out
        sink.events.clear()

    # 收尾：落库新增消息 + done
    if persist and sdb is not None:
        _persist_messages(sdb, session_id, session.history(), base_len)
    quality = "ok" if final_content.strip() else "low"
    yield {"type": "done", "content": final_content.strip() if quality == "ok" else "",
           "quality": quality, "reasoning": ""}
