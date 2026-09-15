"""LLM 通道(认知层) — architect 经 KbGateway 复用主后端 ai chat 能力。

P1 自 req_agent.py 迁入:
  - 模型/max_tokens 偏好(arch_collab_config: llm.modelId / llm.maxTokens)
  - llm.sync  同步调用(完整内容/结构化输出)
  - llm.chat  流式发起(requestId; chunk 经 ZMQ SUB 消费, 见 arch_routes.zmq_stream)

降级语义: 不可达/异常返回 None(调用方降级), 永不抛出。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("arch.cognition.llm")

_MODEL_KEY = "llm.modelId"
_MAX_TOKENS_KEY = "llm.maxTokens"


class ModelNotConfigured(RuntimeError):
    """模型未配置(请求未指定且 architect 偏好为空)。

    用户裁决(cv-168): 静默兜底 KB 默认 = 替用户做一个他没选的决定,
    产物必非预期——明确报错优于垃圾输出。禁止在此类场景降级。"""

# LLM 同步调用超时(秒)：本地大模型结构化提取/工具循环耗时可能远超 KB 默认 10s，
# 与 model_configs.timeout 对齐(默认 300s)，可用 LLM_SYNC_TIMEOUT 覆盖。
_LLM_CALL_TIMEOUT = float(os.environ.get("LLM_SYNC_TIMEOUT", "300"))


def _now_ms() -> int:
    import time as _t
    return int(_t.time() * 1000)


def _kb_gateway():
    try:
        from ...arch_routes import ctx
        g = ctx.kb()
        if g is not None:
            return g
    except Exception:
        pass
    from ...arch_routes.kb_gateway import get_gateway
    return get_gateway()


def get_model_preference() -> str:
    """architect 侧模型偏好(空 = 由主后端默认 is_default 兜底)。"""
    from ...arch_routes import store
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
    from ...arch_routes import store
    store.CollabConfigStore.set(_MODEL_KEY, model_id)


def get_max_tokens_preference() -> Optional[int]:
    """architect 侧 max_tokens 偏好(空 = 主后端按 model_configs.max_tokens)。"""
    from ...arch_routes import store
    raw = store.CollabConfigStore.get(_MAX_TOKENS_KEY, "")
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def set_max_tokens_preference(value: Optional[int]) -> None:
    """设置 max_tokens 偏好；None/<=0 视为清除(回退主后端模型配置)。"""
    from ...arch_routes import store
    store.CollabConfigStore.set(
        _MAX_TOKENS_KEY,
        str(int(value)) if value and int(value) > 0 else "",
    )


def llm_sync(messages: List[Dict[str, str]],
             mode: str = "chat",
             tools: Optional[List[str]] = None,
             output_schema: Optional[Dict[str, Any]] = None,
             max_tokens: Optional[int] = None,
             model_id: Optional[str] = None,
             on_error: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
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
                   max_tokens: Optional[int] = None) -> Optional[str]:
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
