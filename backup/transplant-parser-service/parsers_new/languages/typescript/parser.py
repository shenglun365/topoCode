"""TypeScript 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class TSAstParser(TreeSitterASTParser):
    LANG_NAME = "typescript"


class TSSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "arrow_function": "function",
    }


class TSCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "call_expression"


class TSDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "import_statement"


class TypeScriptLanguageProcessor(LanguageProcessor):
    language_name = "typescript"
    file_extensions = [".ts", ".tsx"]
    priority = 10

    def get_ast_parser(self):
        return TSAstParser()

    def get_symbol_extractor(self):
        return TSSymbolExtractor()

    def get_call_graph_extractor(self):
        return TSCallGraphExtractor()

    def get_dependency_extractor(self):
        return TSDependencyExtractor()


LanguageRegistry.register(TypeScriptLanguageProcessor())
