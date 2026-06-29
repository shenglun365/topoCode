"""
data_layer — 统一数据访问层

三层设计：
  WriteQueue  — 单线程序列化 SQLite 写入
  DuckDBReader — 列式引擎加速 OLAP 只读查询
  CacheStore   — diskcache 持久化键值存储
"""

from .write_queue import WriteQueue, is_write_sql
from .cache_store import CacheStore
from .duckdb_reader import DuckDBReader

__all__ = ["WriteQueue", "is_write_sql", "CacheStore", "DuckDBReader"]
