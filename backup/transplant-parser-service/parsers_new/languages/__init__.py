"""自动注册所有语言处理器"""
from .c.parser import CLanguageProcessor
from .cpp.parser import CPPLanguageProcessor
from .java.parser import JavaLanguageProcessor
from .python.parser import PythonLanguageProcessor
from .javascript.parser import JavaScriptLanguageProcessor
from .typescript.parser import TypeScriptLanguageProcessor
from .go.parser import GoLanguageProcessor

__all__ = [
    "CLanguageProcessor",
    "CPPLanguageProcessor",
    "JavaLanguageProcessor",
    "PythonLanguageProcessor",
    "JavaScriptLanguageProcessor",
    "TypeScriptLanguageProcessor",
    "GoLanguageProcessor",
]
