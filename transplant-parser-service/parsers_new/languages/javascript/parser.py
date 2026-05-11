"""JavaScript 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class JSAstParser(TreeSitterASTParser):
    LANG_NAME = "javascript"


class JSSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "function_declaration": "function",
        "method_definition": "method",
        "class_declaration": "class",
        "arrow_function": "function",
    }


class JSCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "call_expression"


class JSDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "import_statement"


class JavaScriptLanguageProcessor(LanguageProcessor):
    language_name = "javascript"
    file_extensions = [".js", ".jsx", ".mjs"]
    priority = 10

    def get_ast_parser(self):
        return JSAstParser()

    def get_symbol_extractor(self):
        return JSSymbolExtractor()

    def get_call_graph_extractor(self):
        return JSCallGraphExtractor()

    def get_dependency_extractor(self):
        return JSDependencyExtractor()


LanguageRegistry.register(JavaScriptLanguageProcessor())
