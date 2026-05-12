"""Java 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class JavaAstParser(TreeSitterASTParser):
    LANG_NAME = "java"


class JavaSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "method_declaration": "method",
        "class_declaration": "class",
        "constructor_declaration": "function",
    }


class JavaCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "method_invocation"


class JavaDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "import_declaration"


class JavaLanguageProcessor(LanguageProcessor):
    language_name = "java"
    file_extensions = [".java"]
    priority = 10

    def get_ast_parser(self):
        return JavaAstParser()

    def get_symbol_extractor(self):
        return JavaSymbolExtractor()

    def get_call_graph_extractor(self):
        return JavaCallGraphExtractor()

    def get_dependency_extractor(self):
        return JavaDependencyExtractor()


LanguageRegistry.register(JavaLanguageProcessor())
