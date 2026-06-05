"""LM Studio LLM Provider — 使用 OpenAI 兼容 API

LM Studio 使用 OpenAI-compatible API (/v1/chat/completions),
直接复用 providers.openai_compat.LmStudioProvider。
"""

from providers.base import BaseLLMProvider
from providers.openai_compat import LmStudioProvider  # noqa: F401


def register_methods(server, multi_db):
    from providers import register_provider
    register_provider('lm-studio', LmStudioProvider)
