"""LLM Provider 基类 — 所有 provider 须实现此接口"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


def llm_request_timeout(model_config: Dict[str, Any]) -> Tuple[int, int]:
    """计算 requests 超时 (connect, read)，秒。

    长上下文推理可能持续 10–15 分钟以上：
    - streaming：read 是 chunk 间最大静默时长（含 prefill 阶段无输出期），
      静默超过该值才判定 provider 无响应；
    - non-streaming：read 是等待首字节的最长时间。
    model_configs.timeout 作为 per-model 覆盖（下限 60s，防止误配过小
    把正常本地模型推理掐断）。
    """
    try:
        idle = int(model_config.get('timeout') or 0)
    except (TypeError, ValueError):
        idle = 0
    if idle <= 0:
        idle = 1800
    return (30, max(60, idle))


class BaseLLMProvider(ABC):
    """LLM 提供者基类 — 插件 provider 须实现此接口"""

    supports_tools: bool = False  # 该 provider 是否支持原生 function calling

    @abstractmethod
    def chat_stream(
        self,
        model_config,
        messages,
        chunk_queue,
        tools: Optional[List[str]] = None,
        mode: str = 'chat',
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """在独立线程中运行: 流式调用 LLM，逐 chunk 放入队列
        Returns: token info dict {prompt_tokens, completion_tokens, total_tokens}
        """

    @abstractmethod
    def chat_sync(
        self,
        model_config: Dict[str, Any],
        messages: List[Dict[str, str]],
        mode: str,
        tools: Optional[List[str]],
        output_schema: Optional[Dict[str, Any]],
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """非流式调用 LLM，返回 {'content': str, 'usage': dict}"""
