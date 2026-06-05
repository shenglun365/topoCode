# parsers/symbol_parser/language_handlers.py
"""
语言特定的符号处理器

根据文件扩展名分发到对应的语言处理器，实现真正的文件级语言隔离。
"""
from typing import Dict, Any, Optional, List
from .base_handler import LanguageHandler
from .c_family_handler import CFamilyHandler


class JavaHandler(LanguageHandler):
    @property
    def preproc_node_types(self) -> List[str]:
        return []  # Java 无预处理宏

    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        return None

    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        # Java 方法名提取逻辑已在 extract_java_symbols 中实现
        name = func_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def extract_class_name(self, class_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = class_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None


class PythonHandler(LanguageHandler):
    @property
    def preproc_node_types(self) -> List[str]:
        return []  # Python 无预处理宏

    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        return None

    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = func_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def extract_class_name(self, class_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = class_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None


class JavaScriptHandler(LanguageHandler):
    @property
    def preproc_node_types(self) -> List[str]:
        return []

    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        return None

    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = func_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def extract_class_name(self, class_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = class_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None


class GoHandler(LanguageHandler):
    @property
    def preproc_node_types(self) -> List[str]:
        return []

    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        return None

    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        # 策略1: 直接 name 字段
        name = func_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        # 策略2: 从 refs 中提取（AST 解析器可能把 identifier 放在 refs 里）
        refs = func_node.get('refs')
        if refs:
            for ref in refs:
                if isinstance(ref, str) and ref.strip():
                    return ref.strip()
        return None

    def extract_class_name(self, class_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        # 策略1: 直接 name 字段 (type_declaration 有 type_identifier)
        name = class_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        # 策略2: 从 refs 中提取 (struct_type/interface_type 可能没有 name 但有 refs)
        refs = class_node.get('refs')
        if refs:
            for ref in refs:
                if isinstance(ref, str) and ref.strip():
                    return ref.strip()
        return None


class RustHandler(LanguageHandler):
    @property
    def preproc_node_types(self) -> List[str]:
        return []

    def extract_macro_name(self, node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        return None

    def extract_function_name(self, func_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = func_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None

    def extract_class_name(self, class_node: Dict[str, Any], all_nodes: Dict[int, Dict]) -> Optional[str]:
        name = class_node.get('name')
        if isinstance(name, str) and name.strip():
            return name.strip()
        return None


# 扩展名到语言处理器的映射
EXTENSION_TO_HANDLER: Dict[str, type] = {
    # C 家族
    '.c': CFamilyHandler,
    '.h': CFamilyHandler,
    '.cpp': CFamilyHandler,
    '.cc': CFamilyHandler,
    '.cxx': CFamilyHandler,
    '.hpp': CFamilyHandler,
    '.hh': CFamilyHandler,
    '.hxx': CFamilyHandler,

    # Java
    '.java': JavaHandler,

    # Python
    '.py': PythonHandler,
    '.pyw': PythonHandler,
    '.pyi': PythonHandler,

    # JavaScript/TypeScript
    '.js': JavaScriptHandler,
    '.jsx': JavaScriptHandler,
    '.mjs': JavaScriptHandler,
    '.es6': JavaScriptHandler,
    '.ts': JavaScriptHandler,
    '.tsx': JavaScriptHandler,
    '.cts': JavaScriptHandler,
    '.mts': JavaScriptHandler,

    # Go
    '.go': GoHandler,

    # Rust
    '.rs': RustHandler,
}


def get_handler_for_extension(ext: str) -> LanguageHandler:
    """
    根据文件扩展名获取对应的语言处理器

    Args:
        ext: 文件扩展名（带点号，如 '.py'）

    Returns:
        语言处理器实例
    """
    handler_class = EXTENSION_TO_HANDLER.get(ext.lower())
    if handler_class:
        return handler_class()
    # 默认返回 CFamilyHandler（兼容未知语言）
    return CFamilyHandler()
