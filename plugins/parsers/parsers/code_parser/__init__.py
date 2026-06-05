# config/__init__.py
from .registry import get_language_config
from .lang_base import LanguageConfig

__all__ = ["get_language_config", "LanguageConfig"]