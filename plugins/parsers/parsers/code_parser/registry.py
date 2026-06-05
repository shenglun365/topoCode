# parsers/languages/code_parser/registry.py
"""
Language configuration registry.

This module implements a per-process singleton pattern for language configs.
In Celery workers (multi-process model), each process loads configs once and caches them.
No need for thread locking since Celery defaults to prefork (process-based).
"""

import threading
from typing import Dict
from .lang_base import LanguageConfig

# Per-process cache — acts as a singleton within each Celery worker process
_LANGUAGE_CONFIGS: Dict[str, LanguageConfig] = {}
# Optional: add lock if you ever use Celery with threads (e.g., --pool=threads)
# _CONFIG_LOCK = threading.RLock()


def get_language_config(lang: str) -> LanguageConfig:
    """
    Get the language config for `lang`. Loads and caches it on first access.
    This function is safe in Celery's default prefork (multi-process) mode.
    """
    if lang in _LANGUAGE_CONFIGS:
        return _LANGUAGE_CONFIGS[lang]

    mapping = {
        "go": "parsers.code_parser.lang_go",
        "rust": "parsers.code_parser.lang_rust",
        "swift": "parsers.code_parser.lang_swift",
        "php": "parsers.code_parser.lang_php",
        "csharp": "parsers.code_parser.lang_csharp",
        "c": "parsers.code_parser.lang_c",
        "cpp": "parsers.code_parser.lang_cpp",
        "java": "parsers.code_parser.lang_java",
        "python": "parsers.code_parser.lang_python",
        "javascript": "parsers.code_parser.lang_js",
        "typescript": "parsers.code_parser.lang_ts",
        "tsx": "parsers.code_parser.lang_ts",
    }

    if lang not in mapping:
        raise ValueError(f"Unsupported language: {lang}")

    # Lazy import — only load when needed
    module = __import__(mapping[lang], fromlist=['CONFIG'])
    config = module.CONFIG

    # Cache for future calls (per-process singleton)
    _LANGUAGE_CONFIGS[lang] = config
    return config