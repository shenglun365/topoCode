"""
LLM 适配器 — 包装 LLMService 为 AgentTool 可调用的 async callable。
同时追加 llm_call_logs + model_daily_usage 审计日志。
"""

from __future__ import annotations

import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)


def create_llm_chat_fn(multi_db, model_id: str = "") -> Callable:
    """
    创建 async llm_chat_fn，供 AgentTool 调用。

    使用方式:
        llm_fn = create_llm_chat_fn(multi_db, model_id)
        result = await llm_fn(messages=[...], temperature=0.3, max_tokens=2000)
    """

    async def _chat(messages: list[dict], temperature: float = 0.3,
                    max_tokens: int = 2000, **kwargs) -> str:
        start_ts = time.time()
        try:
            from llm_service import LLMService
            service = LLMService(multi_db)
            model = model_id
            if not model:
                configs = multi_db.main_db.fetchall(
                    "SELECT * FROM model_configs ORDER BY is_default DESC, name")
                defaults = [m for m in configs if m.get("is_default")]
                model = defaults[0]["id"] if defaults else (configs[0]["id"] if configs else "")

            if not model:
                return ""

            content = await service.sync_chat(
                messages=messages,
                model_id=model,
            )

            latency_ms = int((time.time() - start_ts) * 1000)
            input_chars = sum(len(m.get("content", "")) for m in messages)
            token_data = {
                "prompt_tokens": input_chars // 4,
                "completion_tokens": len(content) // 4,
                "total_tokens": (input_chars + len(content)) // 4,
            }

            try:
                session_id = f"agent-{kwargs.get('session_suffix', 'default')}"
                service._save_call_log(
                    main_db=multi_db.main_db,
                    session_id=session_id,
                    messages=messages,
                    full_content=content,
                    model={"id": model},
                    request_id=f"agent-{model}-{int(start_ts)}",
                    template_id="agent_direct",
                    extra_meta={"source": "agent_workflow", "estimated": True},
                    tool_calls_recorded=[],
                    latency_ms=latency_ms,
                    status="success",
                    error_message="",
                    token_data=token_data,
                )
                service._record_usage(model, token_data)
            except Exception as log_err:
                logger.warning(f"[llm_adapter] log failed: {log_err}")

            return content if content else ""

        except Exception as e:
            latency_ms = int((time.time() - start_ts) * 1000)
            try:
                from llm_service import LLMService
                service = LLMService(multi_db)
                service._save_call_log(
                    main_db=multi_db.main_db,
                    session_id=f"agent-{kwargs.get('session_suffix', 'default')}",
                    messages=messages,
                    full_content="",
                    model={"id": model_id or "unknown"},
                    request_id=f"agent-error-{int(start_ts)}",
                    template_id="agent_direct",
                    extra_meta={"source": "agent_workflow"},
                    tool_calls_recorded=[],
                    latency_ms=latency_ms,
                    status="error",
                    error_message=str(e),
                    token_data={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                )
            except Exception:
                pass
            logger.warning(f"[llm_adapter] chat failed: {e}")
            raise RuntimeError(f"LLM chat failed: {e}") from e

    return _chat
