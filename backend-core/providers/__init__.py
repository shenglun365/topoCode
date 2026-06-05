"""Provider 注册中心 — 统一管理所有 LLM Provider

所有内置 provider 在 import 时自动注册到 _provider_registry。
外部代码通过 get_provider(name) 获取 provider 实例。
"""

import logging
from typing import Any, Dict, Optional

from providers.base import BaseLLMProvider

# 导入所有 provider 实现（触发类定义）
from providers.ollama import OllamaProvider
from providers.openai_compat import (
    CustomCloudProvider,
    CustomLocalProvider,
    DeepSeekProvider,
    LmStudioProvider,
    MiniMaxCNProvider,
    MiniMaxGlobalProvider,
    OpenRouterProvider,
)

logger = logging.getLogger(__name__)

_provider_registry: Dict[str, type] = {}


def register_provider(name: str, cls: type) -> None:
    """注册 LLM Provider 类（内置或插件）"""
    if not issubclass(cls, BaseLLMProvider):
        raise TypeError(f"Provider class must inherit from BaseLLMProvider, got {cls}")
    _provider_registry[name] = cls
    logger.debug(f"Registered LLM provider: {name} ({cls.__name__})")


def get_provider(name: str) -> Optional[BaseLLMProvider]:
    """获取 Provider 实例"""
    cls = _provider_registry.get(name)
    if cls is None:
        return None
    return cls()

def list_providers() -> list[str]:
    """返回所有已注册的 provider 名称列表"""
    return list(_provider_registry.keys())


def register_all():
    """注册所有内置 provider"""
    # 本地模型
    register_provider('ollama', OllamaProvider)
    register_provider('lm-studio', LmStudioProvider)
    register_provider('custom-local', CustomLocalProvider)
    # 云服务
    register_provider('deepseek', DeepSeekProvider)
    register_provider('minimax-cn', MiniMaxCNProvider)
    register_provider('minimax-global', MiniMaxGlobalProvider)
    register_provider('openrouter', OpenRouterProvider)
    register_provider('custom-cloud', CustomCloudProvider)
    logger.info(f"Registered {len(_provider_registry)} built-in LLM providers: {list(_provider_registry.keys())}")


# 模块导入时自动注册
register_all()
