"""C 语言模式检测器注册"""

from parsers.patterns import register
from parsers.patterns.c.initcall import InitcallPattern
from parsers.patterns.c.callback_registry import CallbackRegistryPattern

register(InitcallPattern())
register(CallbackRegistryPattern())
