"""模式增强层 — 语言特定调用边补充

在所有语言的 Resolver 完成后运行，识别标准解析器遗漏的调用模式（函数指针注册、
回调登记、虚表分发等），生成补充 CALLS / CALLBACK 边。

插件自动发现：patterns/<lang>/__init__.py 中注册 CallPattern 子类。
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from parsers.core.symbol_model import FileSymbolTable, Node, Edge, EdgeKind, Provenance

logger = logging.getLogger(__name__)


class CallPattern(ABC):
    """语言特定调用模式检测基类"""

    language: str                  # 适用语言，如 "c", "rust", "go"
    priority: int = 0              # 执行顺序（值越大约优先）

    @abstractmethod
    def process(
        self,
        tables: list[FileSymbolTable],
        node_index: dict[str, Node],
    ) -> list[Edge]:
        ...


# ==================== 注册表 ====================

_pattern_registry: dict[str, list[CallPattern]] = {}


def register(pattern: CallPattern):
    """注册一个模式检测器"""
    lang = pattern.language
    if lang not in _pattern_registry:
        _pattern_registry[lang] = []
    _pattern_registry[lang].append(pattern)
    logger.debug(f"[Pattern] registered {type(pattern).__name__} for '{lang}'")


# ==================== 入口 ====================


def run_patterns(
    tables: list[FileSymbolTable],
    extensions: list[str],
) -> list[Edge]:
    """
    运行当前任务扩展名对应的所有模式检测器。
    在 step2（标准解析）之后、step5（社区分析）之前调用。
    """
    if not tables:
        return []

    # 收集全部 node.id → Node
    node_index: dict[str, Node] = {}
    for t in tables:
        for n in t.nodes:
            node_index[n.id] = n

    all_edges: list[Edge] = []
    for lang in set(extensions):
        lang = _normalize_lang(lang)
        patterns = _pattern_registry.get(lang, [])
        if not patterns:
            logger.debug(f"[Pattern] no patterns for '{lang}'")
            continue
        patterns.sort(key=lambda p: p.priority, reverse=True)
        for pattern in patterns:
            try:
                edges = pattern.process(tables, node_index)
                if edges:
                    all_edges.extend(edges)
                    logger.info(
                        f"[Pattern] {type(pattern).__name__} generated {len(edges)} edges"
                    )
            except Exception as e:
                logger.error(
                    f"[Pattern] {type(pattern).__name__} failed: {e}", exc_info=True
                )

    return all_edges


# ==================== 辅助工具 ====================


def _normalize_lang(lang: str) -> str:
    """统一语言标识（如 'c_header' → 'c', 'tsx' → 'typescript'）"""
    mapping = {
        "c_header": "c",
        "cpp_header": "cpp",
        "tsx": "typescript",
        "jsx": "javascript",
        "luau": "lua",
    }
    return mapping.get(lang, lang)


# ==================== 自动发现语言模式 ====================

def _discover_patterns():
    """导入所有 patterns/<lang>/ 子模块，触发 register() 调用"""
    import pkgutil
    import importlib
    pkg_path = __path__
    for importer, mod_name, is_pkg in pkgutil.iter_modules(pkg_path):
        if is_pkg and mod_name not in ("__pycache__",):
            importlib.import_module(f"{__name__}.{mod_name}")


_discover_patterns()
