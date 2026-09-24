"""LLM 通道(认知层) — architect 经 KbGateway 复用主后端 ai chat 能力。

P1 自 req_agent.py 迁入:
  - 模型/max_tokens 偏好(arch_collab_config: llm.modelId / llm.maxTokens)
  - llm.sync  同步调用(完整内容/结构化输出)
  - llm.chat  流式发起(requestId; chunk 经 ZMQ SUB 消费, 见 arch_routes.zmq_stream)

降级语义: 不可达/异常返回 None(调用方降级), 永不抛出。
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arch.cognition.llm")

_MODEL_KEY = "llm.modelId"
_MAX_TOKENS_KEY = "llm.maxTokens"
_CONTEXT_BUDGET_KEY = "llm.contextBudget"

_CTX_CACHE: Dict[str, tuple] = {}   # url → (monotonic_ts, n_ctx)，缓存 10 分钟
_CTX_CACHE_TTL = 600.0


class ModelNotConfigured(RuntimeError):
    """模型未配置(请求未指定且 architect 偏好为空)。

    用户裁决(cv-168): 静默兜底 KB 默认 = 替用户做一个他没选的决定,
    产物必非预期——明确报错优于垃圾输出。禁止在此类场景降级。"""

# LLM 同步调用超时(秒)：本地大模型结构化提取/工具循环耗时可能远超 KB 默认 10s，
# 缺省取统一超时单源 llm_call(600s)，可用 LLM_SYNC_TIMEOUT / TOPO_TIMEOUT_LLM_CALL 覆盖。
from ..governance.timeouts import get as _timeout_of
# 统一超时单源(governance.timeouts); 应急覆盖可用 TOPO_TIMEOUT_LLM_CALL 或遗留 LLM_SYNC_TIMEOUT
_LLM_CALL_TIMEOUT = float(os.environ.get("LLM_SYNC_TIMEOUT")
                          or _timeout_of("llm_call"))


def _now_ms() -> int:
    import time as _t
    return int(_t.time() * 1000)


def _kb_gateway():
    try:
        from ... import ctx
        g = ctx.kb()
        if g is not None:
            return g
    except Exception:
        pass
    from ...kb_gateway import get_gateway
    return get_gateway()


def get_model_preference() -> str:
    """architect 侧模型偏好(空 = 由主后端默认 is_default 兜底)。"""
    from ... import store
    return store.CollabConfigStore.get(_MODEL_KEY, "")


def resolve_call_model(explicit: Optional[str]) -> str:
    """architect 单源模型解析(显式 > architect 偏好 llm.modelId)。

    均空 → 抛 ModelNotConfigured(明确报错, 不再静默回落 KB 默认——
    cv-168 用户裁决: 兜底产物非用户所选, 属垃圾; KB 默认是 KB 的设置,
    不得隐式接管 architect 调用)。"""
    m = (explicit or "").strip() or get_model_preference()
    if not m:
        raise ModelNotConfigured(
            "未配置模型：请求未指定且 architect 偏好(llm.modelId)为空——"
            "请在设置中选择模型（KB 默认不再静默接管 architect 调用）。")
    return m


def set_model_preference(model_id: str) -> None:
    from ... import store
    store.CollabConfigStore.set(_MODEL_KEY, model_id)


def get_max_tokens_preference() -> Optional[int]:
    """architect 侧 max_tokens 偏好(空 = 主后端按 model_configs.max_tokens)。"""
    from ... import store
    raw = store.CollabConfigStore.get(_MAX_TOKENS_KEY, "")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def set_max_tokens_preference(value: Optional[int]) -> None:
    """设置 max_tokens 偏好；None/<=0 视为清除(回退主后端模型配置)。"""
    from ... import store
    store.CollabConfigStore.set(
        _MAX_TOKENS_KEY,
        str(int(value)) if value and int(value) > 0 else "",
    )


def get_context_budget_preference() -> int:
    """architect 侧上下文预算偏好(0 = 未设置 → 显式/探测兜底)。"""
    from ... import store
    try:
        return int(store.CollabConfigStore.get(_CONTEXT_BUDGET_KEY, "") or 0)
    except (TypeError, ValueError):
        return 0


def set_context_budget_preference(value: Optional[int]) -> None:
    """设置上下文预算偏好；None/<=0 视为清除(回退探测容量)。"""
    from ... import store
    store.CollabConfigStore.set(
        _CONTEXT_BUDGET_KEY,
        str(int(value)) if value and int(value) > 0 else "",
    )


def probe_context_window(url: str, model_hint: str = "") -> Optional[int]:
    """探测模型服务端真实上下文容量(尽力而为, 失败返回 None 不猜)。

    - llama.cpp server: GET /props → default_generation_settings.n_ctx
    - LM Studio: GET /api/v0/models → data[].max_context_length(按 model_hint 匹配)
    - 其余(纯 OpenAI 兼容): 无标准端点 → None
    结果按 url 缓存 10 分钟; 2 秒超时不阻塞调用链。"""
    import json as _json
    import time as _t
    import urllib.request
    base = (url or "").strip().rstrip("/")
    if base.endswith("/v1"):
        base = base[:-3]   # 探测端点(/props, /api/v0)从服务根发起
    if not base:
        return None
    cached = _CTX_CACHE.get(base)
    now = _t.monotonic()
    if cached and now - cached[0] < _CTX_CACHE_TTL:
        return cached[1]

    def _fetch(path: str):
        req = urllib.request.Request(base + path, method="GET")
        with urllib.request.urlopen(req, timeout=_timeout_of("probe_ping")) as r:
            return _json.loads(r.read().decode("utf-8", "replace"))

    n_ctx: Optional[int] = None
    try:
        d = _fetch("/props")   # llama.cpp
        n_ctx = int(((d.get("default_generation_settings") or {}).get("n_ctx")) or 0) or None
    except Exception:  # noqa: BLE001
        try:
            d = _fetch("/api/v0/models")   # LM Studio
            rows = [r for r in (d.get("data") or []) if isinstance(r, dict)]
            hit = next((r for r in rows
                        if model_hint and model_hint.lower() in str(r.get("id", "")).lower()), None)
            n_ctx = int((hit or (rows[0] if rows else {})).get("max_context_length") or 0) or None
        except Exception:  # noqa: BLE001
            n_ctx = None
    if n_ctx:
        _CTX_CACHE[base] = (now, n_ctx)
    return n_ctx


def _catalog_entry(model_id: str) -> Dict[str, Any]:
    """llm.models 目录条目(取 url/model 供探测)。"""
    from ... import store
    try:
        raw = store.CollabConfigStore.get("llm.models", "")
        for r in json.loads(raw) if raw else []:
            if isinstance(r, dict) and r.get("id") == model_id:
                return r
    except Exception:  # noqa: BLE001
        pass
    return {}


def resolve_context_budget(explicit: Optional[int], model_id: str) -> Optional[int]:
    """上下文预算解析: 显式 > llm.contextBudget 偏好 > 探测容量−生成预留−余量
    (用户要求: architect 尝试读取模型 API 的上下文容量设置以做容量控制)。

    全部不可得 → None(不裁剪, 不猜测)。"""
    b = int(explicit or 0) or get_context_budget_preference()
    if b > 0:
        return b
    entry = _catalog_entry(model_id or "")
    win = probe_context_window(str(entry.get("url") or ""),
                               str(entry.get("model") or entry.get("name") or ""))
    if not win:
        return None
    reserve = get_max_tokens_preference() or 8192
    return max(4096, int(win) - int(reserve) - 2048)


def llm_sync(messages: List[Dict[str, str]],
             mode: str = "chat",
             tools: Optional[List[str]] = None,
             output_schema: Optional[Dict[str, Any]] = None,
             max_tokens: Optional[int] = None,
             model_id: Optional[str] = None,
             on_error: Optional[Callable[[str], None]] = None,
             context_budget: Optional[int] = None) -> Optional[Dict[str, Any]]:
    """经 KbGateway 调主后端 llm.sync。不可达/异常返回 None(调用方降级)。

    model_id: 本次对话的模型偏好(对话侧单独选择)，优先于全局 `llm.modelId`；
    空串则回退全局偏好，再由主后端 is_default 兜底。
    on_error: 可选回调，捕获失败原因文本(KbError 详情/异常信息)，供调用方
    识别上下文超限等可重试错误(如逐行解读的二分降级)；不改变 None 返回语义。
    """
    model_id = resolve_call_model(model_id)   # 未配置 → 明确抛错, 不降级
    gateway = _kb_gateway()
    _t0 = _now_ms()
    body: Dict[str, Any] = {}
    try:
        body = {
            "modelId": model_id,
            "mode": mode,
            "messages": messages,
            "maxTokens": max_tokens,
            "contextBudget": resolve_context_budget(context_budget, model_id),
        }
        if tools:
            body["tools"] = tools
        if output_schema:
            body["outputSchema"] = output_schema
        res = gateway.call("llm.sync", timeout=_LLM_CALL_TIMEOUT, **body)
        try:
            from ..reflection import dataset as _lds
            _ok = isinstance(res, dict)
            _lds.record("llm_call", verb="sync", mode=mode, ok=_ok,
                        model=body.get("modelId") or "",
                        msgsChars=sum(len(m.get("content") or "") for m in messages),
                        maxTokens=max_tokens or "",
                        latencyMs=_now_ms() - _t0,
                        error="" if _ok else f"非dict:{type(res).__name__}")
        except Exception:  # noqa: BLE001
            pass
        if not isinstance(res, dict):
            logger.warning("[cognition.llm] llm.sync 返回非 dict(%s): %r",
                           type(res).__name__,
                           str(res)[:200] if res is not None else None)
            if on_error:
                try:
                    on_error(f"llm.sync 返回非 dict: {type(res).__name__}")
                except Exception:
                    pass
            return None
        if mode == "structured" and output_schema and res.get("output") is None:
            logger.warning("[cognition.llm] llm.sync structured 输出为空: "
                           "content_len=%d structuredError=%r",
                           len(res.get("content") or ""),
                           str(res.get("structuredError"))[:200])
        return res
    except Exception as e:
        logger.warning("[cognition.llm] llm.sync failed: %s", e, exc_info=True)
        try:
            from ..reflection import dataset as _lds
            _lds.record("llm_call", verb="sync", mode=mode, ok=False,
                        model=body.get("modelId") or "",
                        msgsChars=sum(len(m.get("content") or "") for m in messages),
                        maxTokens=max_tokens or "",
                        latencyMs=_now_ms() - _t0, error=str(e)[:300])
        except Exception:  # noqa: BLE001
            pass
        if on_error:
            try:
                on_error(str(e))
            except Exception:
                pass
        return None


def llm_chat_start(messages: List[Dict[str, str]],
                   model_id: Optional[str] = None,
                   session_id: str = "arch-req-chat",
                   max_tokens: Optional[int] = None,
                   context_budget: Optional[int] = None) -> Optional[str]:
    """发起流式对话(llm.chat)。成功返回 requestId；不可达/未配置/异常返回 None(调用方降级)。

    与 llm_sync 同通道(经 KbGateway 转发主后端)，但返回 requestId 而非完整内容：
    调用方随后经 ZMQ SUB 订阅 `llm.*`(按 requestId 过滤) 消费逐字 chunk。
    """
    model_id = resolve_call_model(model_id)   # 未配置 → 明确抛错, 不降级
    gateway = _kb_gateway()
    try:
        body: Dict[str, Any] = {
            "sessionId": session_id,
            "modelId": model_id,
            "mode": "chat",
            "messages": messages,
            "max_tokens": max_tokens,
            "contextBudget": resolve_context_budget(context_budget, model_id),
        }
        res = gateway.call("llm.chat", timeout=_LLM_CALL_TIMEOUT, **body)
        _chat_ok = isinstance(res, dict) and bool(res.get("requestId"))
        try:
            from ..reflection import dataset as _lds
            _lds.record("llm_call", verb="chat", mode="chat", ok=_chat_ok,
                        model=body.get("modelId") or "",
                        msgsChars=sum(len(m.get("content") or "") for m in messages),
                        maxTokens=max_tokens or "", latencyMs=0,
                        sessionId=session_id or "",
                        error="" if _chat_ok else "无 requestId")
        except Exception:  # noqa: BLE001
            pass
        if not _chat_ok:
            return None
        return res.get("requestId")
    except Exception as e:
        logger.warning("[cognition.llm] llm.chat failed: %s", e)
        try:
            from ..reflection import dataset as _lds
            _lds.record("llm_call", verb="chat", mode="chat", ok=False,
                        model=model_id,
                        msgsChars=sum(len(m.get("content") or "") for m in messages),
                        maxTokens=max_tokens or "", latencyMs=0,
                        sessionId=session_id or "", error=str(e)[:300])
        except Exception:  # noqa: BLE001
            pass
        return None
