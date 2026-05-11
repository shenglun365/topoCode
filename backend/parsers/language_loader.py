"""
Tree-sitter 语言包加载器

使用独立语言包方案（tree_sitter_c, tree_sitter_cpp 等），
支持 tree-sitter 0.23.x。不使用 tree_sitter_languages（已停止维护）。
"""
import logging
from typing import Dict, Optional
from tree_sitter import Language, Parser

logger = logging.getLogger(__name__)

# ==================== 导入独立语言包 ====================
_ts_modules = {}

try:
    import tree_sitter_c as tsc
    _ts_modules['c'] = ('tsc', getattr(tsc, 'language', None))
except ImportError:
    pass

try:
    import tree_sitter_cpp as tscpp
    _ts_modules['cpp'] = ('tscpp', getattr(tscpp, 'language', None))
except ImportError:
    pass

try:
    import tree_sitter_python as tspy
    _ts_modules['python'] = ('tspy', getattr(tspy, 'language', None))
except ImportError:
    pass

try:
    import tree_sitter_javascript as tsjs
    _ts_modules['javascript'] = ('tsjs', getattr(tsjs, 'language', None))
except ImportError:
    pass

try:
    import tree_sitter_typescript as tsts
    _ts_modules['typescript'] = ('tsts', getattr(tsts, 'language_typescript', None))
    _ts_modules['tsx'] = ('tsts_tsx', getattr(tsts, 'language_tsx', None))
except ImportError:
    pass

try:
    import tree_sitter_go as tsgo
    _ts_modules['go'] = ('tsgo', getattr(tsgo, 'language', None))
except ImportError:
    pass

try:
    import tree_sitter_java as tsjava
    _ts_modules['java'] = ('tsjava', getattr(tsjava, 'language', None))
except ImportError:
    pass

# ==================== 构建语言映射 ====================
LANGUAGES: Dict[str, Language] = {}
_PARSER_CACHE: Dict[str, Parser] = {}

for _lang_name, (_mod_name, _lang_fn) in _ts_modules.items():
    if _lang_fn:
        try:
            LANGUAGES[_lang_name] = Language(_lang_fn())
        except Exception as e:
            logger.warning(f"Failed to load {_lang_name} language: {e}")

logger.info(f"Loaded {len(LANGUAGES)} tree-sitter languages: {list(LANGUAGES.keys())}")


def get_language(lang_name: str) -> Optional[Language]:
    """获取 tree-sitter Language 对象"""
    return LANGUAGES.get(lang_name)


def get_parser(lang_name: str) -> Optional[Parser]:
    """
    获取指定语言的解析器（带缓存）

    Returns:
        Parser 实例，如果语言不支持则返回 None
    """
    if lang_name in _PARSER_CACHE:
        return _PARSER_CACHE[lang_name]

    lang = LANGUAGES.get(lang_name)
    if lang is None:
        logger.debug(f"Language '{lang_name}' not available in tree-sitter")
        return None

    parser = Parser(lang)
    _PARSER_CACHE[lang_name] = parser
    logger.info(f"Created parser for language: {lang_name}")
    return parser


def get_available_languages() -> list:
    """获取所有可用的 tree-sitter 语言列表"""
    return list(LANGUAGES.keys())
