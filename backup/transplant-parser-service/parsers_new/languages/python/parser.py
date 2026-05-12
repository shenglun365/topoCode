"""Python 语言处理器"""
from ...base import LanguageProcessor
from ...ast_parser import TreeSitterASTParser
from ...symbol_extractor import BaseSymbolExtractor
from ...call_graph_extractor import BaseCallGraphExtractor
from ...dependency_extractor import BaseDependencyExtractor
from ...language_registry import LanguageRegistry


class PythonAstParser(TreeSitterASTParser):
    LANG_NAME = "python"


class PythonSymbolExtractor(BaseSymbolExtractor):
    SYMBOL_NODE_TYPES = {
        "function_definition": "function",
        "class_definition": "class",
        "method_definition": "method",
    }


class PythonCallGraphExtractor(BaseCallGraphExtractor):
    CALL_EXPR_TYPE = "call"


class PythonDependencyExtractor(BaseDependencyExtractor):
    INCLUDE_NODE_TYPE = "import_statement"


class PythonLanguageProcessor(LanguageProcessor):
    language_name = "python"
    file_extensions = [".py", ".pyw"]
    priority = 10

    def get_ast_parser(self):
        return PythonAstParser()

    def get_symbol_extractor(self):
        return PythonSymbolExtractor()

    def get_call_graph_extractor(self):
        return PythonCallGraphExtractor()

    def get_dependency_extractor(self):
        return PythonDependencyExtractor()


LanguageRegistry.register(PythonLanguageProcessor())
