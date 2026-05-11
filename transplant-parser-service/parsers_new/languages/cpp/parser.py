"""C++ 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class CPpAstParser(TreeSitterASTParser):
    LANG_NAME = "cpp"


class CPpSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "function_definition": "function",
        "class_specifier": "class",
        "method_definition": "method",
        "macro_definition": "macro",
    }


class CPpCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "call_expression"


class CPpDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "include_directive"


class CPPLanguageProcessor(LanguageProcessor):
    language_name = "cpp"
    file_extensions = [".cpp", ".cc", ".cxx", ".hpp", ".h"]
    priority = 11  # 高于 C，因为 .h 两者都匹配

    def get_ast_parser(self):
        return CPpAstParser()

    def get_symbol_extractor(self):
        return CPpSymbolExtractor()

    def get_call_graph_extractor(self):
        return CPpCallGraphExtractor()

    def get_dependency_extractor(self):
        return CPpDependencyExtractor()


LanguageRegistry.register(CPPLanguageProcessor())
