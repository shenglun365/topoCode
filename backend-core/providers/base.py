"""LLM Provider 基类 — 所有 provider 须实现此接口"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class BaseLLMProvider(ABC):
    """LLM 提供者基类 — 插件 provider 须实现此接口"""

    @abstractmethod
    def chat_stream(
        self,
        model_config: Dict[str, Any],
        messages: List[Dict[str, str]],
        chunk_queue,
        tools: Optional[List[str]] = None,
        mode: str = 'chat',
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
    ) -> Dict[str, Any]:
        """非流式调用 LLM，返回 {'content': str, 'usage': dict}"""
