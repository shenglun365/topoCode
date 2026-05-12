"""C 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class CAstParser(TreeSitterASTParser):
    LANG_NAME = "c"


class CSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "function_definition": "function",
        "struct_specifier": "class",
        "macro_definition": "macro",
    }


class CCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "call_expression"


class CDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "include_directive"


class CLanguageProcessor(LanguageProcessor):
    language_name = "c"
    file_extensions = [".c", ".h"]
    priority = 10

    def get_ast_parser(self) -> CAstParser:
        return CAstParser()

    def get_symbol_extractor(self) -> CSymbolExtractor:
        return CSymbolExtractor()

    def get_call_graph_extractor(self) -> CCallGraphExtractor:
        return CCallGraphExtractor()

    def get_dependency_extractor(self) -> CDependencyExtractor:
        return CDependencyExtractor()


# 自动注册
LanguageRegistry.register(CLanguageProcessor())
