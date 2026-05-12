"""Go 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class GoAstParser(TreeSitterASTParser):
    LANG_NAME = "go"


class GoSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "function_declaration": "function",
        "method_declaration": "method",
        "type_declaration": "class",
    }


class GoCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "call_expression"


class GoDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "import_spec"


class GoLanguageProcessor(LanguageProcessor):
    language_name = "go"
    file_extensions = [".go"]
    priority = 10

    def get_ast_parser(self):
        return GoAstParser()

    def get_symbol_extractor(self):
        return GoSymbolExtractor()

    def get_call_graph_extractor(self):
        return GoCallGraphExtractor()

    def get_dependency_extractor(self):
        return GoDependencyExtractor()


LanguageRegistry.register(GoLanguageProcessor())
