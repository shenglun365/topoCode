"""OpenAI-compatible LLM Provider — 插件版本

复用 providers.openai_compat.OpenAIProvider（同步 requests 实现）。
"""

from providers.base import BaseLLMProvider  # noqa: F401
from providers.openai_compat import OpenAIProvider


def register_methods(server, multi_db):
    from providers import register_provider
    register_provider('openai', OpenAIProvider)
