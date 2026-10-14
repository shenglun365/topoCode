"""topoone.db — 数据库层（MultiDBManager / SQLiteContext / data_layer / state_store）。

零产品逻辑；被 engine / llm / agent / gateway / apps 依赖。
"""
from .connection import SQLiteContext
from .manager import MultiDBManager, WriteResult

__all__ = ["SQLiteContext", "MultiDBManager", "WriteResult"]
