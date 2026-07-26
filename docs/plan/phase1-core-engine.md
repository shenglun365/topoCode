# Phase 1: 核心引擎详细设计

> 文件名: `docs/plan/phase1-core-engine.md`
> 目标包: `topoone/core/` (位于 `next/backend/topoone/core/`)
> 依赖: 零 LLM 依赖，零 Agent 依赖
> 代码量: 约 9500 行 (迁移 + 适配)

---

## 目录

1. [包结构总览](#1-包结构总览)
2. [逐文件规格](#2-逐文件规格)
   - [2.1 core/db/ — 数据库层](#21-coredb--数据库层)
   - [2.2 core/config/ — 配置层](#22-coreconfig--配置层)
   - [2.3 core/store/ — 数据存取层](#23-corestore--数据存取层)
   - [2.4 core/project/ — 项目管理](#24-coreproject--项目管理)
   - [2.5 core/parser/ — 代码解析](#25-coreparser--代码解析)
   - [2.6 core/analysis/ — 分析数据](#26-coreanalysis--分析数据)
   - [2.7 core/transport/ — 通信层](#27-coretransport--通信层)
   - [2.8 core/__init__.py — 包入口](#28-core__init__py--包入口)
3. [模块依赖关系图](#3-模块依赖关系图)
4. [与旧代码的映射关系](#4-与-old-代码的映射关系)
5. [Phase 1 不移入的内容](#5-phase-1-不移入的内容)
6. [测试规划](#6-测试规划)
7. [验证清单](#7-验证清单)

---

## 1. 包结构总览

```
topoone/core/                          # 核心引擎 (zero LLM dependencies)
├── __init__.py                        # 导出 CoreEngine 聚合类
├── db/                                # 数据库层
│   ├── __init__.py
│   ├── pragmas.py                     # SQLite PRAGMA 常量
│   ├── connection.py                  # SQLiteContext (单连接封装)
│   ├── manager.py                     # MultiDBManager (多数据库管理)
│   └── schema.py                      # 所有 DDL 定义
├── config/                            # 配置层
│   ├── __init__.py
│   ├── settings.py                    # 全局配置常量
│   ├── logging.py                     # 日志配置
│   └── state.py                       # StateStore (内存+缓存双写)
├── store/                             # 数据存取层
│   ├── __init__.py
│   ├── write_queue.py                 # WriteQueue (写串行化)
│   ├── cache_store.py                 # CacheStore (diskcache 封装)
│   ├── duckdb_reader.py               # DuckDBReader (OLAP 查询)
│   ├── task_store.py                  # TaskStore (analysis_tasks CRUD)
│   └── analysis_store.py             # AnalysisStore (图/社区/LLM 结果 CRUD)
├── project/                           # 项目管理
│   ├── __init__.py
│   ├── scanner.py                     # 文件扫描 + GitIgnore
│   ├── service.py                     # project.* RPC 处理器
│   ├── group.py                       # group.* RPC 处理器
│   ├── git.py                         # Git 信息
│   ├── export.py                      # 导出服务 (JSONL+Zip)
│   ├── import.py                      # 导入服务 (Zip→JSONL)
│   └── verify.py                      # 文件校验服务
├── parser/                            # 代码解析
│   ├── __init__.py
│   ├── symbol_graph.py                # SymbolGraph (NetworkX 封装)
│   ├── stack_graphs.py                # StackGraphsService (外部 CLI)
│   ├── hasher.py                      # 文件哈希工具
│   ├── pipeline.py                    # 6 步分析流水线 (原 analyst_runner)
│   └── ast_worker.py                  # AST Worker 子进程管理
├── analysis/                          # 分析数据
│   ├── __init__.py
│   ├── community.py                   # 社区数据提取 (原 community_data.py)
│   ├── task.py                        # analysis.* RPC 处理器 (无 Agent)
│   ├── cascade.py                     # 级联层级计算
│   ├── ranks.py                       # 文件排名计算
│   ├── report.py                      # 报告文档服务
│   ├── positions.py                   # 图位置管理
│   └── external.py                    # 外部依赖统计
└── transport/                         # 通信层
    ├── __init__.py
    ├── server.py                      # ZMQServer (ROUTER+PUB)
    ├── rpc_ids.py                     # RPC ID 映射
    └── event.py                       # 事件类型常量
```

---

## 2. 逐文件规格

### 2.1 `core/db/` — 数据库层

#### `core/db/__init__.py`

```python
"""数据库层 - 线程安全 SQLite 数据库管理"""
from .pragmas import SQLITE_PRAGMAS
from .connection import SQLiteContext
from .manager import MultiDBManager
from .schema import (
    MAIN_DB_TABLES_SQL,
    KNOWLEDGE_DB_TABLES_SQL,
    SESSIONS_DB_TABLES_SQL,
    PROJECT_DB_TABLES_SQL,
)
```

---

#### `core/db/pragmas.py`

**源文件**: `backend-core/config.py:20-34` (SQLITE_PRAGMAS 字典)

**内容**: SQLite 连接 PRAGMA 常量

```python
SQLITE_PRAGMAS = {
    "journal_mode": "WAL",
    "busy_timeout": 5000,
    "synchronous": "NORMAL",
    "cache_size": -65536,       # 64MB
    "temp_store": "MEMORY",
    "mmap_size": 268435456,     # 256MB
    "page_size": 4096,
}
```

**依赖**: 无

---

#### `core/db/connection.py`

**源文件**: `backend-core/store/connection.py` (96 行, 更干净的版本)
补充方法: 从 `backend-core/sqlite_ctx.py` 中的 SQLiteContext 挑选 fetchall/fetchone/insert/update/delete

**类**: `SQLiteContext`

```python
class SQLiteContext:
    """线程安全的单连接 SQLite 封装"""
    def __init__(self, db_path: str, *, label: str = "", write_queue=None):

    def connect(self) -> sqlite3.Connection:
        """创建/返回连接, 初始化 PRAGMA"""

    @property
    def conn(self) -> sqlite3.Connection:
        """获取当前连接, 不存在则创建"""

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行 SQL (有 write_queue 则走队列, 否则直接执行)"""

    def executemany(self, sql: str, params_list: list) -> None:
        """批量执行"""

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询多行 → list[dict]"""

    def fetchone(self, sql: str, params: tuple = ()) -> dict | None:
        """查询单行 → dict | None"""

    def insert(self, table: str, data: dict) -> str:
        """INSERT 并返回 lastrowid"""

    def update(self, table: str, data: dict, where: str, where_params: tuple = ()) -> int:
        """UPDATE 返回 rowcount"""

    def delete(self, table: str, where: str, where_params: tuple = ()) -> int:
        """DELETE 返回 rowcount"""

    def executescript(self, sql: str) -> None:
        """执行多语句脚本 (DDL 迁移)"""

    def commit(self) -> None:
        """提交事务"""

    def close(self) -> None:
        """关闭连接"""

    def __enter__(self) -> "SQLiteContext": ...
    def __exit__(self, *args) -> None: ...
```

**设计决策**:
- 使用 `store/connection.py` 的简洁版本为基础, 从 `sqlite_ctx.py` 补充 fetchall/fetchone/insert/update/delete/executescript
- `RLock` 保证线程安全 (继承自原 store/connection.py)
- `write_queue` 可选参数: 传入时 execute 通过 `is_write_sql` 判断, 写 SQL 走队列

**依赖**: `core/db/pragmas.py`,  `core/store/write_queue.py` (可选)

---

#### `core/db/manager.py`

**源文件**: `backend-core/sqlite_ctx.py:1104-1819` (MultiDBManager 类, 约 700 行)

**类**: `MultiDBManager`

```python
class MultiDBManager:
    """多数据库管理器 - 管理 main/knowledge/sessions + 项目 DB LRU 缓存"""

    def __init__(self, data_dir: str | None = None):
        """
        初始化数据库目录, 创建:
        - WriteQueue (写队列)
        - CacheStore (diskcache)
        - DuckDBReader (OLAP)
        - main_db (topoone.db)
        - knowledge_db (knowledge.db)
        - sessions_db (sessions.db)
        初始化 all 表结构 + 迁移
        """

    # --- 属性 ---
    @property
    def write_queue(self) -> WriteQueue: ...
    @property
    def cache_store(self) -> CacheStore: ...
    @property
    def duckdb(self) -> DuckDBReader: ...

    # --- 主库初始化 ---
    def _init_main_tables(self):
        """执行 MAIN_DB_TABLES_SQL (DDL)"""
    def _migrate_main_tables(self):
        """执行迁移 SQL"""

    # --- 知识库库 ---
    def _init_knowledge_tables(self): ...
    def _init_sessions_tables(self): ...

    # --- 项目数据库 ---
    def _project_db_path(self, project_id: str, project_root: str = None) -> str: ...
    def _get_project_root(self, project_id: str) -> str: ...
    def init_project_db(self, project_id: str, project_root: str = None):
        """创建项目 DB + DDL + 迁移"""
    def get_project_db(self, project_id: str) -> SQLiteContext: ...
        """获取项目 DB (LRU 缓存, 自动 evict)"""
    def close_project_db(self, project_id: str): ...
    def delete_project_db(self, project_id: str): ...

    # --- 工具方法 ---
    def compute_md5(self, file_path: str) -> str: ...

    def close_all(self):
        """关闭所有 DB 连接 + WriteQueue + CacheStore + DuckDB"""
```

**设计决策**:
- Phase 1 只初始化 main_db 和 project_db, knowledge_db 和 sessions_db 留空
- 移除所有与 `TOPO_MODE == "distributed"` 相关的逻辑 (将在 Phase 2 或独立模块处理)
- 移除 `_init_default_skills` 内部函数 (属于 Agent 系统, Phase 4)
- 接受 `data_dir` 参数, 默认 `~/.topocode/` 可通过环境变量 `DATA_DIR` 覆盖

**依赖**:
- `core/db/connection.py` (SQLiteContext)
- `core/db/schema.py` (DDL 字符串)
- `core/store/write_queue.py` (WriteQueue)
- `core/store/cache_store.py` (CacheStore)
- `core/store/duckdb_reader.py` (DuckDBReader, 可选延迟加载)
- `core/config/settings.py` (SQLITE_PRAGMAS, MAX_DB_CONNECTIONS 等)

---

#### `core/db/schema.py`

**源文件**: `backend-core/sqlite_ctx.py` 中的 4 个 DDL 字符串常量 (散布在文件中)

**内容**: 全部 DDL 定义 (从 sqlite_ctx.py 逐条提取)

```python
MAIN_DB_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS projects (...);
CREATE TABLE IF NOT EXISTS analysis_tasks (...);
CREATE TABLE IF NOT EXISTS analysis_task_runs (...);
CREATE TABLE IF NOT EXISTS analysis_reports (...);
CREATE TABLE IF NOT EXISTS model_configs (...);
CREATE TABLE IF NOT EXISTS agent_configs (...);
CREATE TABLE IF NOT EXISTS skill_configs (...);
CREATE TABLE IF NOT EXISTS llm_prompt_templates (...);
CREATE TABLE IF NOT EXISTS llm_call_logs (...);
CREATE TABLE IF NOT EXISTS project_groups (...);
CREATE TABLE IF NOT EXISTS project_group_map (...);
CREATE TABLE IF NOT EXISTS app_config (...);
CREATE TABLE IF NOT EXISTS project_git_info (...);
CREATE TABLE IF NOT EXISTS agent_instructions (...);
CREATE TABLE IF NOT EXISTS task_model_bindings (...);
CREATE TABLE IF NOT EXISTS code_index_messages (...);
CREATE TABLE IF NOT EXISTS user_node_styles (...);
CREATE TABLE IF NOT EXISTS context_store (...);
CREATE TABLE IF NOT EXISTS report_interaction_log (...);
CREATE TABLE IF NOT EXISTS model_daily_usage (...);
CREATE TABLE IF NOT EXISTS ai_sessions (...);
CREATE TABLE IF NOT EXISTS arch_snapshots (...);
CREATE TABLE IF NOT EXISTS graph_node_positions (...);
CREATE TABLE IF NOT EXISTS doc_project_map (...);
"""

KNOWLEDGE_DB_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS knowledge_docs (...);
"""

SESSIONS_DB_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS llm_sessions (...);
CREATE TABLE IF NOT EXISTS llm_messages (...);
CREATE TABLE IF NOT EXISTS analysis_sessions (...);
"""

PROJECT_DB_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS source_files (...);
CREATE TABLE IF NOT EXISTS ast_data (...);
CREATE TABLE IF NOT EXISTS dependencies (...);
CREATE TABLE IF NOT EXISTS call_chains (...);
CREATE TABLE IF NOT EXISTS components (...);
CREATE TABLE IF NOT EXISTS project_config (...);
CREATE TABLE IF NOT EXISTS graph_node (...);
CREATE TABLE IF NOT EXISTS graph_edge (...);
CREATE TABLE IF NOT EXISTS graph_doc (...);
CREATE TABLE IF NOT EXISTS community_hierarchy (...);
CREATE TABLE IF NOT EXISTS community_llm_results (...);
CREATE TABLE IF NOT EXISTS report_subdocs (...);
CREATE TABLE IF NOT EXISTS file_summaries (...);
CREATE TABLE IF NOT EXISTS ai_qa (...);
CREATE TABLE IF NOT EXISTS agent_task_history (...);
CREATE TABLE IF NOT EXISTS file_hashes (...);
"""
```

**设计决策**:
- 逐表完整列定义从 `sqlite_ctx.py` 中逐字拷贝
- Phase 1 不修改任何表的 schema (保持向后兼容)
- 迁移 SQL 同样从 `sqlite_ctx.py` 中的 `_migrate_main_tables` 逐条拷贝
- agent_task_history 表虽然属于 Agent 系统, 但 DDL 定义保留在 schema 中 (不初始化则无影响)

**依赖**: 无

---

### 2.2 `core/config/` — 配置层

#### `core/config/__init__.py`

```python
from .settings import Settings
from .logging import setup_logging
from .state import StateStore, get_store
```

---

#### `core/config/settings.py`

**源文件**: `backend-core/config.py` (87 行)

**类**: `Settings` (改用 pydantic-settings 风格, 保持全部字段)

```python
@dataclass
class Settings:
    """全局配置（环境变量可覆盖）"""

    # ZMQ
    zmq_bind_host: str = "127.0.0.1"
    zmq_dealer_port: int = 5671
    zmq_pub_port: int = 5680

    # 数据库
    sqlite_pragmas: dict = field(default_factory=lambda: { ... })
    max_db_connections: int = 3

    # 解析
    parse_workers: int = 4
    max_file_size: int = 512 * 1024     # 512KB
    max_ast_nodes: int = 100000
    batch_insert_size: int = 5000
    progress_interval: int = 5

    # 社区分析
    community_min_node_include: int = 6
    community_min_node_call: int = 12
    hub_degree_ratio: float = 0.3
    hub_min_degree: int = 50
    orphan_max_degree: int = 0
    intra_file_edge_weight: float = 1.0
    intra_file_edge_fallback_weight: float = 0.1

    # 日志
    log_dir: str = ""
    log_level: str = "INFO"

    # 其他
    rpc_timeout: int = 30
    data_dir: str = ""          # 默认 ~/.topocode
    large_graph_node_threshold: int = 5000

# 模块级单例
settings = Settings()
```

**设计决策**:
- 使用 dataclass 替代裸常量, 提供 `settings.xxx` 访问
- 所有字段保持默认值与旧 config.py 一致
- `data_dir` 和 `log_dir` 留空则在运行时通过 `os.path.expanduser("~/.topocode")` 解析

**依赖**: 无

---

#### `core/config/logging.py`

**源文件**: `backend-core/logging_config.py` (150 行)

```python
def setup_logging(level_str: str | None = None, log_dir: str | None = None):
    """
    统一日志配置:
    - TimedRotatingFileHandler (按天轮转)
    - 按日志器名称分类到不同文件 (core.log, project.log, parser.log, analysis.log)
    - 同时输出到 stdout
    - 使用 core/config/settings.py 的配置作为默认
    """
```

**依赖**: `core/config/settings.py` (获取 log_dir, log_level)

---

#### `core/config/state.py`

**源文件**: `backend-core/state_store.py` (235 行)

**类**: `StateStore`

```python
class StateStore:
    """全局状态 - 双写模式 (内存 + CacheStore)"""

    def __init__(self, cache_store=None, mode: str = "dual"):
        """
        mode:
        - "memory": 仅内存 (无缓存持久化)
        - "cache": 仅 CacheStore
        - "dual": 同时写入内存和 CacheStore (默认)
        """

    def set_stop(self, task_id: str): ...
    def clear_stop(self, task_id: str): ...
    def should_stop(self, task_id: str) -> bool: ...

    def add_executing(self, task_id: str): ...
    def remove_executing(self, task_id: str): ...
    def is_executing(self, task_id: str) -> bool: ...

    def get_ps_failed(self, task_id: str) -> int: ...
    def set_ps_failed(self, task_id: str, count: int): ...
    def incr_ps_failed(self, task_id: str, delta: int = 1) -> int: ...
    def reset_ps_failed(self, task_id: str): ...

    def get_ranks(self, task_id: str) -> dict | None: ...
    def set_ranks(self, task_id: str, ranks: dict, ttl: int = 3600): ...
    def delete_ranks(self, task_id: str): ...

    def get_subagent_failed(self, task_id: str) -> int: ...
    def set_subagent_failed(self, task_id: str, count: int): ...
    def reset_subagent_failed(self, task_id: str): ...

def get_store() -> StateStore:
    """返回模块级单例 StateStore"""
```

**设计决策**:
- 纯内存方法 (stop/executing) 保持同步
- cache 方法直接委托给 `core/store/cache_store.py` (从 `data_layer/cache_store.py` 迁移)
- `subagent_failed` 方法虽然名字含"subagent", 但只是计数器, 保留在 Phase 1

**依赖**: `core/store/cache_store.py` (可选, mode=="memory" 时不依赖)

---

### 2.3 `core/store/` — 数据存取层

#### `core/store/__init__.py`

```python
from .write_queue import WriteQueue, is_write_sql
from .cache_store import CacheStore
from .duckdb_reader import DuckDBReader
from .task_store import TaskStore
from .analysis_store import AnalysisStore
```

---

#### `core/store/write_queue.py`

**源文件**: `backend-core/data_layer/write_queue.py` (260 行)
**变更**: 无修改, 直接迁移

**类**: `WriteQueue`
**函数**: `is_write_sql(sql: str) -> bool`

```python
class WriteQueue:
    """SQLite 写串行化队列 - 单后台线程处理所有写操作"""

    def __init__(self, db_paths: dict[str, str] | None = None): ...
    def register_db(self, label: str, path: str): ...
    def execute(self, label, sql, params=(), _commit=True): ...       # 异步 (fire-and-forget)
    def execute_sync(self, label, sql, params=(), _commit=True, timeout=30.0) -> dict: ...
    def execute_batch(self, label, items) -> list[dict]: ...
    def shutdown(self, timeout=5.0): ...
```

**依赖**: 无外部依赖 (只使用标准库 sqlite3, queue, threading)

---

#### `core/store/cache_store.py`

**源文件**: `backend-core/data_layer/cache_store.py` (157 行)
**变更**: 无修改, 直接迁移

**类**: `CacheStore`

```python
class CacheStore:
    """diskcache 封装"""

    def __init__(self, cache_dir: str): ...
    def get(self, key, default=None): ...
    def set(self, key, value, expire=None): ...
    def delete(self, key): ...
    def incr(self, key, delta=1) -> int: ...
    def get_file_ranks(self, task_id) -> dict | None: ...
    def set_file_ranks(self, task_id, ranks, ttl=3600): ...
    def delete_file_ranks(self, task_id): ...
    def get_ps_failed(self, task_id) -> int: ...
    def incr_ps_failed(self, task_id, delta=1) -> int: ...
    def reset_ps_failed(self, task_id): ...
    def set_ps_failed(self, task_id, count): ...
    def get_executing_tasks(self) -> set: ...
    def add_executing_task(self, task_id): ...
    def remove_executing_task(self, task_id): ...
    def is_task_executing(self, task_id) -> bool: ...
    def get_agent_tasks(self) -> list[dict]: ...            # 标记 deprecated
    def set_agent_tasks(self, tasks: list[dict]): ...       # 标记 deprecated
    def get_agent_task(self, agent_id) -> dict | None: ...  # 标记 deprecated
    def set_agent_task(self, task_dict: dict): ...           # 标记 deprecated
    def delete_agent_task(self, agent_id): ...               # 标记 deprecated
    def clear_agent_tasks(self): ...                         # 标记 deprecated
    def close(self): ...
    def clear(self): ...
```

**依赖**: 第三方 `diskcache`

---

#### `core/store/duckdb_reader.py`

**源文件**: `backend-core/data_layer/duckdb_reader.py` (275 行)
**变更**: 无修改, 直接迁移

**类**: `DuckDBReader`

```python
class DuckDBReader:
    """DuckDB OLAP 查询加速器"""

    def __init__(self, multi_db): ...

    def compute_file_ranks(self, task_id, pid, components, project_root) -> dict: ...
    def get_cascade_levels(self, task_id, pid, edge_type) -> list[dict]: ...
    def get_external_imports(self, task_id, pid) -> list[dict]: ...
    def count_by_extensions(self, pid, scopes, extensions, exclude_dirs) -> list[dict]: ...
    def extract_call_edges(self, task_id, pid, file_path, limit=50) -> list[dict]: ...
    def get_call_chain_bfs(self, task_id, pid, source_id, max_depth=5) -> list[dict]: ...
    def get_usage_stats(self, model_id, start_date, end_date) -> list[dict]: ...

    def close(self): ...
```

**依赖**: 第三方 `duckdb` (延迟导入), `core/db/manager.py` (MultiDBManager)

---

#### `core/store/task_store.py`

**源文件**: `backend-core/store/task_store.py` (372 行)
**变更**: 无修改, 直接迁移

**类**: `TaskStore`

```python
class TaskStore:
    """analysis_tasks + runs + reports 表 CRUD"""

    def __init__(self, main_db: SQLiteContext): ...

    def create_task(self, task: dict) -> dict: ...
    def get_task(self, task_id: str) -> dict | None: ...
    def list_tasks(self, project_id: str) -> list[dict]: ...
    def update_task_status(self, task_id, status, progress=None, current=None, error=None): ...
    def update_task_config(self, task_id, config: dict) -> dict: ...
    def delete_task(self, task_id: str) -> int: ...
    def update_task_meta(self, task_id, **kwargs) -> dict: ...

    def create_run(self, task_id: str, config_snapshot: dict) -> dict: ...
    def get_task_runs(self, task_id: str) -> list[dict]: ...
    def update_run_progress(self, run_id, progress, current): ...
    def finish_run(self, run_id, status, error=None): ...

    def upsert_report(self, report: dict): ...
    def get_results(self, task_id, run_id=None) -> dict: ...
    def get_task_logs(self, task_id, run_id=None) -> dict: ...
```

**依赖**: `core/db/connection.py` (SQLiteContext)

---

#### `core/store/analysis_store.py`

**源文件**: `backend-core/store/analysis_store.py` (731 行)
**变更**: 无修改, 直接迁移

**类**: `AnalysisStore`

```python
class AnalysisStore:
    """graph_node, graph_edge, community_*, file_summaries 等表 CRUD"""

    def __init__(self, project_db: SQLiteContext): ...

    def count_by_extensions(self, ...) -> dict[str, int]: ...
    def count_files(self, ...) -> int: ...
    def list_file_paths(self, ...) -> list[str]: ...
    def list_source_files(self, ...) -> list[dict]: ...
    def get_file_by_path(self, file_path) -> dict | None: ...
    def get_file_by_id(self, file_id) -> dict | None: ...

    def bulk_insert_graph_nodes(self, nodes: list[dict]): ...
    def get_graph_nodes(self, task_id, kind=None) -> list[dict]: ...
    def count_graph_nodes(self, task_id, kind=None) -> int: ...
    def bulk_insert_edges(self, edges: list[dict]): ...
    def get_graph_edges(self, task_id, kind=None) -> list[dict]: ...
    def get_symbols(self, task_id, symbol_type=None) -> list[dict]: ...
    def get_call_edges(self, task_id) -> list[dict]: ...
    def get_dep_edges(self, task_id) -> list[dict]: ...

    def bulk_insert_communities(self, communities: list[dict]): ...
    def get_best_community(self, task_id, edge_type) -> dict | None: ...
    def get_communities(self, task_id, edge_type=None, comm_lv=None) -> list[dict]: ...
    def count_communities(self, task_id, edge_type=None) -> int: ...
    def delete_hierarchy_by_task(self, task_id): ...
    def bulk_insert_hierarchy(self, hierarchies: list[dict]): ...
    def delete_communities(self, task_id, edge_type, comm_ids: list[str]): ...
    def delete_community_llm_results(self, task_id, edge_type, comm_ids: list[str]): ...

    def bulk_insert_llm_results(self, results: list[dict]): ...
    def list_llm_results(self, task_id, edge_type) -> list[dict]: ...
    def get_llm_result(self, task_id, edge_type, comm_lv, comm_id) -> dict | None: ...
    def update_community_name(self, task_id, edge_type, comm_lv, comm_id, name): ...

    def save_agent_task_history(self, record: dict): ...
    def list_agent_task_history(self, task_id, offset=0, limit=10) -> dict: ...
    def clear_agent_task_history(self, project_id, task_id): ...

    def clear_task_data(self, task_id): ...
    def clear_communities_for_task(self, task_id, edge_type): ...
```

**依赖**: `core/db/connection.py` (SQLiteContext), `core/config/settings.py` (BATCH_INSERT_SIZE)

---

### 2.4 `core/project/` — 项目管理

#### `core/project/__init__.py`

```python
from .scanner import GitIgnoreParser, MultiIgnoreParser, build_effective_ignore_patterns
from .service import ProjectService
from .group import GroupService
from .export import ExportService
from .import import ImportService
from .verify import VerifyService
from .git import GitService
```

---

#### `core/project/scanner.py`

**源文件**: `backend-core/core_service.py` 中的 GitIgnoreParser, MultiIgnoreParser, 文件扫描函数 (约 300 行)

**类**:

```python
class GitIgnoreParser:
    """解析单个 .gitignore 文件"""
    def __init__(self): ...
    def load_file(self, filepath: str) -> "GitIgnoreParser": ...
    def add_pattern(self, pattern: str): ...
    def is_ignored(self, path: str, is_dir: bool = False) -> bool: ...

class MultiIgnoreParser:
    """多文件合并的 gitignore 解析器"""
    def __init__(self): ...
    def load_files(self, root_path: str, filenames: list[str] | None = None) -> "MultiIgnoreParser": ...
    def is_ignored(self, rel_path: str, is_dir: bool = False) -> bool: ...
```

**函数**:

```python
def build_effective_ignore_patterns(config: dict) -> list[str]:
    """构建用户配置 + 默认忽略列表"""
def should_ignore_file(rel_path, gitignore_parser, is_dir, extra_patterns) -> bool:
    """综合判断文件/目录是否应忽略"""
```

**设计决策**: 从 `core_service.py` 提取出纯文件扫描逻辑, 不包含任何 RPC 注册代码

**依赖**: 无

---

#### `core/project/service.py`

**源文件**: `backend-core/core_service.py` 中的 register_project_methods + 内部函数 (约 1200 行)

**类**: `ProjectService`

```python
class ProjectService:
    """project.* RPC 处理器 - 项目管理"""

    def __init__(self, multi_db: MultiDBManager, state_store: StateStore):
        self.multi_db = multi_db
        self.state = state_store

    def list_projects(self) -> list[dict]: ...
    def get_project(self, id: str) -> dict | None: ...
    def update_project_meta(self, id: str, **kwargs) -> dict: ...
    def remove_project(self, id: str) -> dict: ...

    async def import_project(self, path: str) -> dict:
        """异步导入: 扫描文件 → 建项目记录 → 发布事件"""

    async def sync_project(self, id: str) -> dict:
        """同步: 重新扫描文件树, 检测变更"""

    def get_file_tree(self, id: str, from_path: str = None) -> list: ...
    def update_path(self, id: str, new_root_path: str) -> dict: ...

    async def check_file_changes(self, id: str) -> dict: ...
    def check_path_validity(self, id: str) -> dict: ...

    def get_config(self, project_id: str, key: str) -> dict: ...
    def set_config(self, project_id: str, key: str, value) -> dict: ...
    def clear_sample_data(self, project_id: str) -> dict: ...
    def get_storage_stats(self, project_id: str = None) -> dict: ...

    def resource_import_project(self, ...) -> dict: ...

    def register(self, server: "ZMQServer"):
        """将方法注册到 ZMQServer"""
```

**设计决策**:
- 移除 `_do_generate_project_summary` (LLM 调用, Phase 3 移入 `topoone/llm/`)
- 移除 `register_knowledge_methods`, `register_settings_methods`, `register_backend_methods`, `register_module_methods`, `register_render_methods`, `register_report_methods` (属于其他子系统)
- RPC 方法签名保持与旧 API 完全兼容
- 通过 `register(server)` 方法注册到 ZMQServer, 而非直接操作 server.methods 字典

**依赖**:
- `core/db/manager.py` (MultiDBManager)
- `core/config/state.py` (StateStore)
- `core/project/scanner.py` (GitIgnoreParser, etc.)
- `core/project/git.py` (GitService)
- `core/project/export.py` (ExportService - 委托)
- `core/project/import.py` (ImportService - 委托)
- `core/project/verify.py` (VerifyService - 委托)
- `core/transport/server.py` (ZMQServer - 用于 register)

---

#### `core/project/group.py`

**源文件**: `backend-core/core_service.py` 中 group.* 相关的 RPC 处理器 (约 150 行)

**类**: `GroupService`

```python
class GroupService:
    """group.* RPC 处理器 - 项目分组"""

    def __init__(self, multi_db: MultiDBManager): ...

    def list_groups(self) -> list[dict]: ...
    def create_group(self, name: str, parent_id: str = None) -> dict: ...
    def update_group(self, id: str, name: str = None, parent_id: str = None) -> dict: ...
    def delete_group(self, id: str) -> dict: ...
    def add_project_to_group(self, project_id: str, group_id: str) -> dict: ...
    def remove_project_from_group(self, project_id: str, group_id: str) -> dict: ...
    def get_project_groups(self, project_id: str) -> list[dict]: ...

    def register(self, server: "ZMQServer"): ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

#### `core/project/git.py`

**源文件**: `backend-core/task_manager.py` 中的 `detect_git_info`, `save_git_info`, `get_git_info` (约 60 行)

**类**: `GitService`

```python
class GitService:
    """Git 信息查询"""

    def __init__(self, multi_db: MultiDBManager): ...

    def detect_git_info(self, project_id: str) -> dict: ...
    def save_git_info(self, project_id: str, info: dict) -> dict: ...
    def get_git_info(self, project_id: str) -> dict | None: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

#### `core/project/export.py`

**源文件**: `backend-core/export_service.py` (303 行)
**变更**: 无修改, 直接迁移

**类**: `ExportService`

```python
class ExportService:
    """项目导出服务 - JSONL + Zip"""

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_ERROR = "error"

    def start_export(self, multi_db, project_id, task_ids, publish_fn) -> str: ...
    def get_export_status(self, export_id: str) -> dict | None: ...
    def remove_archive(self, archive_path: str) -> bool: ...
    def cleanup_old_archives(self, multi_db, project_id, days=7): ...
```

**依赖**: 无 (multi_db 作为参数传入)

---

#### `core/project/import.py`

**源文件**: `backend-core/import_service.py` (465 行)
**变更**: 无修改, 直接迁移

**类**: `ImportService`

```python
class ImportService:
    """项目导入服务 - Zip → JSONL"""

    MODE_SHARE = "share"
    MODE_RESTORE = "restore"

    def start_import(self, multi_db, archive_path, publish_fn, import_mode, target_project_id, cleanup_archive) -> str: ...
    def get_import_status(self, import_id: str) -> dict | None: ...
```

**依赖**: 无 (multi_db 作为参数传入)

---

#### `core/project/verify.py`

**源文件**: `backend-core/verify_service.py` (166 行)
**变更**: 无修改, 直接迁移

**类**: `VerifyService`

```python
class VerifyService:
    """文件完整性校验 - MD5 比对"""

    def start_verify(self, multi_db, project_id, publish_fn) -> str: ...
    def get_verify_status(self, verify_id: str) -> dict | None: ...
```

**依赖**: 无 (multi_db 作为参数传入)

---

### 2.5 `core/parser/` — 代码解析

#### `core/parser/__init__.py`

```python
from .symbol_graph import SymbolGraph
from .stack_graphs import StackGraphsService, StackGraphsResult
from .hasher import compute_file_hash
from .pipeline import AnalysisPipeline
from .ast_worker import AstWorkerManager
```

---

#### `core/parser/symbol_graph.py`

**源文件**: `backend-core/symbol_graph.py` (152 行)
**变更**: 无修改, 直接迁移

**类**: `SymbolGraph`

```python
class SymbolGraph:
    """NetworkX 有向图封装 - 符号解析图"""

    def __init__(self): ...

    @classmethod
    def from_tables(cls, tables: list) -> "SymbolGraph": ...

    def add_resolution(self, source_qn, target_qn, confidence, method): ...
    def add_call_edge(self, caller_qn, callee_qn, confidence=1.0): ...
    def add_dependency_edge(self, from_path, to_path, dep_type="imports"): ...

    @property
    def graph(self) -> nx.DiGraph: ...
    @property
    def node_count(self) -> int: ...
    @property
    def edge_count(self) -> int: ...

    def successors(self, node: str) -> list[dict]: ...
    def predecessors(self, node: str) -> list[dict]: ...
    def neighbors(self, node: str, max_depth: int = 1) -> dict: ...
    def subgraph(self, nodes: list[str]) -> "SymbolGraph": ...
    def to_json(self) -> dict: ...
```

**依赖**: 第三方 `networkx`

---

#### `core/parser/stack_graphs.py`

**源文件**: `backend-core/stack_graphs_service.py` (200 行)
**变更**: 无修改, 直接迁移

**数据类**: `StackGraphsResult`

```python
@dataclass
class StackGraphsResult:
    file: str
    line: int
    column: int
    scope_stack: list[dict]
```

**类**: `StackGraphsService`

```python
class StackGraphsService:
    """Stack Graphs 外部 CLI 封装 - 定义/引用查询"""

    def __init__(self, project_root: str, language: str): ...

    @property
    def available(self) -> bool: ...

    async def index(self) -> bool: ...
    async def definition(self, file, line, col) -> StackGraphsResult | None: ...
    async def references(self, file, line, col) -> list[StackGraphsResult]: ...
    async def shutdown(self): ...
```

**依赖**: 无 (通过 subprocess 调用外部 stack-graphs CLI)

---

#### `core/parser/hasher.py`

**源文件**: `backend-core/core_service.py` 中的 `_compute_file_hash` 和 `_simple_hash` (约 20 行)

```python
def compute_file_hash(file_path: str) -> str:
    """计算文件 MD5 哈希"""

def simple_hash(path: str) -> str:
    """字符串路径的简单哈希 (hash + hex)"""
```

**依赖**: 无

---

#### `core/parser/pipeline.py`

**源文件**: `backend-core/analyst_runner.py` (1204 行) — 去除 LLM 调用部分

**类**: `AnalysisPipeline`

```python
class AnalysisPipeline:
    """6 步分析流水线 (原 analyst_runner 的 _execute_task)"""

    STEP_PARSE_AST = 1
    STEP_RESOLVE_REFS = 2
    STEP_EXTRACT_IMPORTS = 3
    STEP_SYNTHESIZE_FRAMEWORKS = 4
    STEP_DETECT_COMMUNITIES = 5
    STEP_GENERATE_SUMMARY = 6         # 占位: 实际 LLM 调用在顶层控制

    def __init__(self, server, multi_db, task_id, run_id, start_time):
        """
        server: 用于 publish 进度的 ZMQServer 实例 (或任何具有 publish(topic, type, data) 的对象)
        multi_db: MultiDBManager
        """

    async def run(self, summary_callback=None) -> dict:
        """
        执行 6 步流水线, 返回结果 dict {status, result, error}
        summary_callback: 可选回调, 在 step 6 时调用 (LLM 调用由外部注入)
        """

    def stop(self): ...

    @property
    def progress(self) -> float: ...
    @property
    def current_step(self) -> int: ...

@dataclass
class PipelineContext:
    """流水线上下文 - 各步骤之间传递数据"""
    task_id: str
    run_id: str
    project_root: str
    project_db: SQLiteContext
    task_store: TaskStore
    analysis_store: AnalysisStore
    state_store: StateStore
    task_config: dict
    all_files: list
    all_tables: list
    edges: list
    all_communities: list
    community_hierarchy: list
    progress: float
    current_step: str
```

**设计决策**:
- 将 `analyst_runner.py` 的全部内容迁移到 `AnalysisPipeline` 类中
- 核心 6 步流水线保留 (AST 解析 → 符号解析 → 导入提取 → 框架合成 → 社区检测 → 总结)
- 最后一步(`_generate_summary`) 中调用 LLM 的逻辑(`_do_generate_project_summary`) 抽取为 `summary_callback` 参数, 由调用方注入
- `enqueue_analysis_task` 改为 `AnalysisPipeline.run()` 的同步包装
- 进度发布通过 server.publish 回调实现

**依赖**:
- `core/db/manager.py` (MultiDBManager)
- `core/db/connection.py` (SQLiteContext)
- `core/store/task_store.py` (TaskStore)
- `core/store/analysis_store.py` (AnalysisStore)
- `core/config/state.py` (StateStore)
- `core/parser/hasher.py` (compute_file_hash)
- 第三方: `parsers.core.*` (tree-sitter AST 解析器套件)
- 第三方: `community_analysis` (社区检测算法)

---

#### `core/parser/ast_worker.py`

**源文件**: `backend-core/ast_worker.py` (115 行)
**变更**: 移除 `messaging.worker_signal` 依赖, 移除 distributed 模式专用逻辑

**类**: `AstWorkerManager`

```python
class AstWorkerManager:
    """AST Worker 子进程管理 (用于 distributed 模式)"""

    def spawn(self, task_id: str, run_id: str, data_dir: str) -> subprocess.Popen | None: ...
    def stop(self, task_id: str): ...
    def stop_all(self): ...
```

**设计决策**:
- 将 `ast_worker.py` 重写为 `AstWorkerManager` 类
- monolith 模式下: 不启动子进程, 直接调用 `AnalysisPipeline`
- distributed 模式下: `spawn()` 启动子进程, `stop()` 发送 SIGTERM
- worker 信号通过 stdout JSON 行 + 轮询 DB 实现, 而非 ZMQ

**依赖**: 无 (通过 subprocess 启动 worker)

---

### 2.6 `core/analysis/` — 分析数据

#### `core/analysis/__init__.py`

```python
from .community import CommunityService
from .task import AnalysisTaskService
from .cascade import CascadeService
from .ranks import RankService
from .report import ReportService
from .positions import PositionService
from .external import ExternalService
```

---

#### `core/analysis/community.py`

**源文件**: `backend-core/community_data.py` (1119 行)
**变更**: 无修改, 直接迁移, 改为类封装

**类**: `CommunityService`

```python
class CommunityService:
    """社区数据提取 - 从 DB 读取社区图数据并聚合"""

    def __init__(self, multi_db: MultiDBManager): ...

    # L1: 原始 DB 查询
    def read_graph_doc_rows(self, task_id, edge_type, comm_lv, comm_id) -> list[dict]: ...
    def read_graph_doc_children(self, task_id, edge_type, parent_comm_id) -> list[dict]: ...
    def expand_communities_to_depth(self, task_id, edge_type, rows, depth) -> list[dict]: ...
    def read_graph_doc_all_nodes(self, task_id, edge_type, comm_lv) -> list[dict]: ...
    def read_graph_edges(self, task_id, kind) -> list[dict]: ...
    def read_graph_node_map(self, task_id, symbol_ids) -> dict: ...
    def read_community_names(self, task_id, edge_type) -> dict: ...
    def read_community_hierarchy(self, task_id, edge_type, parent_comm_id) -> list[dict]: ...

    # L2: 文件级提取
    def extract_file_nodes(self, raw_rows, edge_type, rel_fn, name_map) -> dict: ...
    def extract_file_edges(self, raw_rows, edge_type, rel_fn, existing_nodes) -> tuple: ...
    def build_file_comm_map(self, raw_rows, rel_fn) -> dict: ...
    def extract_cross_file_edges(self, task_id, edge_type, file_comm, rel_fn, hash_to_path) -> tuple: ...
    def extract_cross_comm_file_edges(self, task_id, edge_type, file_comm, rel_fn, all_ge, hash_to_path) -> tuple: ...
    def resolve_call_symbols(self, task_id, all_ge, rel_fn) -> dict: ...
    def extract_external_deps(self, task_id) -> list[dict]: ...
    def extract_external_calls(self, task_id) -> list[dict]: ...

    # L3: 聚合
    def aggregate_to_community_graph(self, file_nodes, file_edges, comm_meta) -> tuple: ...
    def build_heatmap_matrix(self, task_id, edge_type, comm_lv, rel_fn) -> dict: ...
    def inject_community_names(self, items, task_id, edge_type): ...

    # L4: 端到端入口
    def get_community_graph_file(self, task_id, edge_type, comm_lv, comm_id, project_root) -> dict: ...
    def get_community_graph_component(self, task_id, edge_type, comm_lv, comm_id, project_root, depth) -> dict: ...
    def get_external_stats(self, task_id, project_root) -> dict: ...
    def get_community_children(self, task_id, edge_type, parent_comm_id) -> list[dict]: ...
    def get_cascade_levels(self, task_id, edge_type) -> dict: ...
    def get_heatmap(self, task_id, edge_type, project_root, comm_lv, size) -> dict: ...
    def get_external_graph(self, task_id, edge_type, depth, comm_id, project_root) -> dict: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

#### `core/analysis/task.py`

**源文件**: `backend-core/task_manager.py` 中 analysis.* 的非 LLM RPC 处理器 (约 1500 行)

**类**: `AnalysisTaskService`

```python
class AnalysisTaskService:
    """analysis.* RPC 处理器 - 任务管理 + 查询 (无 Agent/LLM 方法)"""

    def __init__(self, multi_db: MultiDBManager, state_store: StateStore): ...

    # --- 任务 CRUD ---
    def list_tasks(self, params: dict) -> list[dict]: ...
    def create_task(self, params: dict) -> dict: ...
    def get_task(self, params: dict) -> dict: ...
    def update_task(self, params: dict) -> dict: ...
    def delete_task(self, params: dict) -> dict: ...
    def update_task_config(self, params: dict) -> dict: ...
    def get_task_runs(self, params: dict) -> list[dict]: ...
    def get_task_logs(self, params: dict) -> dict: ...
    def list_running_tasks(self) -> list[dict]: ...

    # --- 运行控制 (不含 Agent) ---
    def run_task(self, params: dict) -> dict: ...
        """委托 AnalysisPipeline.run()"""
    def stop_task(self, params: dict) -> dict: ...
    def re_run_task(self, params: dict) -> dict: ...

    # --- 缓存管理 ---
    def clear_project_cache(self, params: dict) -> dict: ...
    def get_clear_cache_counts(self, params: dict) -> dict: ...
    def clear_project_cache_table(self, params: dict) -> dict: ...

    # --- 数据查询 ---
    def get_results(self, params: dict) -> dict: ...
    def scan_file_stats(self, params: dict) -> dict: ...
    def get_community_graph(self, params: dict) -> dict: ...
    def get_symbol_detail(self, params: dict) -> dict: ...
    def get_edge_detail(self, params: dict) -> dict: ...
    def get_query_stats(self, params: dict) -> dict: ...
    def get_cross_community_edges(self, params: dict) -> dict: ...
    def get_community_node_lists(self, params: dict) -> dict: ...
    def get_community_file_graph(self, params: dict) -> dict: ...
    def get_report_dashboard(self, params: dict) -> dict: ...
    def get_progress_stats(self, params: dict) -> dict: ...

    # --- LLM 结果存取 (存储层) ---
    def save_community_result(self, params: dict) -> dict: ...
    def get_community_result(self, params: dict) -> dict: ...
    def list_community_results(self, params: dict) -> dict: ...
    def update_community_name(self, params: dict) -> dict: ...

    def register(self, server: "ZMQServer"): ...
```

**设计决策**:
- 只包含纯数据操作 (CRUD + 聚合查询) 的 RPC 方法
- `run_task` 委托给 `AnalysisPipeline` (不含 LLM 的 5 步流水线)
- LLM/Agent 相关的方法由 `topoone/agent/` 和 `topoone/llm/` 在后续 Phase 实现
- Method 签名保持与旧 API 完全兼容

**不包含的 RPC 方法** (由 Agent/LLM 子系统实现):
- `analysis.startOverview` / `startPipeline` / `startPreSummary` / `startPreSummaryPipeline`
- `analysis.analyzeComponents` / `cancelAgentTask` / `getAgentProgress`
- `analysis.getAgentTaskHistory` / `clearAgentTaskHistory` / `dispatchArchNL`
- `analysis.getFileSummary` / `deleteFileSummary` / `rerunFileSummary`
- `analysis.getPreSummaryStatus` / `listPreSummaryFiles`

**依赖**:
- `core/db/manager.py` (MultiDBManager)
- `core/config/state.py` (StateStore)
- `core/analysis/community.py` (CommunityService)
- `core/analysis/cascade.py` (CascadeService)
- `core/analysis/ranks.py` (RankService)
- `core/analysis/positions.py` (PositionService)
- `core/analysis/external.py` (ExternalService)
- `core/parser/pipeline.py` (AnalysisPipeline)

---

#### `core/analysis/cascade.py`

**源文件**: `backend-core/analysis_utils.py` (105 行)

**类**: `CascadeService`

```python
class CascadeService:
    """级联层级计算"""

    def __init__(self, multi_db: MultiDBManager): ...

    def get_cascade_levels(self, task_id: str, edge_type: str, parent_id: str = None) -> dict: ...
    def get_l0_components(self, task_id: str) -> list[dict]: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

#### `core/analysis/ranks.py`

**源文件**: `backend-core/task_manager.py` 中的 `_compute_file_ranks` + `data_layer/duckdb_reader.py` 中的 `compute_file_ranks`

**类**: `RankService`

```python
class RankService:
    """文件排名计算"""

    def __init__(self, multi_db: MultiDBManager): ...

    def compute_file_ranks(self, task_id: str) -> dict: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager), `core/store/duckdb_reader.py` (DuckDBReader)

---

#### `core/analysis/report.py`

**源文件**: `backend-core/report_tree_service.py` (36 行)
**变更**: 无修改, 直接迁移

**类**: `ReportService`

```python
class ReportService:
    """报告文档服务"""

    def __init__(self, multi_db: MultiDBManager): ...

    def save_overall_doc(self, task_id: str, title: str, content: str) -> dict: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

#### `core/analysis/positions.py`

**源文件**: `backend-core/task_manager.py` 中的 `save_positions`, `load_positions`, `list_position_keys`, `clear_positions` (约 80 行)

**类**: `PositionService`

```python
class PositionService:
    """图位置持久化管理"""

    def __init__(self, multi_db: MultiDBManager): ...

    def save_positions(self, task_id, edge_type, drill_key, layout_type, positions, snapshot_id) -> dict: ...
    def load_positions(self, task_id, edge_type, drill_key, layout_type, snapshot_id) -> dict: ...
    def list_position_keys(self, project_id) -> dict: ...
    def clear_positions(self, task_id, edge_type, drill_key, layout_type) -> dict: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

#### `core/analysis/external.py`

**源文件**: `backend-core/community_data.py` 中的 `extract_external_deps`, `extract_external_calls`, `get_external_stats`

**类**: `ExternalService`

```python
class ExternalService:
    """外部依赖/调用统计"""

    def __init__(self, multi_db: MultiDBManager): ...

    def get_external_stats(self, task_id, project_root) -> dict: ...
    def get_external_imports(self, task_id) -> list[dict]: ...
    def get_external_calls(self, task_id) -> list[dict]: ...
```

**依赖**: `core/db/manager.py` (MultiDBManager)

---

### 2.7 `core/transport/` — 通信层

#### `core/transport/__init__.py`

```python
from .server import ZMQServer
from .rpc_ids import get_rpc_id, RPC_IDS
from .event import EventType
```

---

#### `core/transport/server.py`

**源文件**: `backend-core/zmq_server.py` (345 行)
**变更**: 移除 `messaging.bus.MessageBus` 依赖

**类**: `ZMQServer`

```python
class ZMQServer:
    """ZMQ RPC 服务器 - ROUTER + PUB 双 socket"""

    def __init__(self, multi_db: "MultiDBManager",
                 dealer_port: int = None, pub_port: int = None,
                 bind_host: str = None): ...

    def register(self, name: str) -> Callable: ...
    def register_many(self, methods: dict[str, Callable]): ...
    def publish(self, topic: str, event_type: str, data: dict): ...
    async def run(self): ...
    async def run_forever(self): ...
    def stop(self): ...
```

**依赖**: 第三方 `pyzmq`, `core/db/manager.py` (MultiDBManager)

---

#### `core/transport/rpc_ids.py`

**源文件**: `backend-core/rpc_ids.py` (212 行)
**变更**: 无修改, 直接迁移

```python
RPC_IDS: dict[str, str] = {
    "project.list": "API-001",
    "project.import": "API-002",
    ...
}

def get_rpc_id(method_name: str) -> str: ...
```

**依赖**: 无

---

#### `core/transport/event.py`

**源文件**: 新建

```python
@dataclass
class EventType:
    TASK_PROGRESS = "task.progress"
    TASK_STATUS = "task.status"
    TASK_LOG = "task.log"
    PROJECT_IMPORTED = "project.imported"
    PROJECT_SYNCED = "project.synced"
    PROJECT_REMOVED = "project.removed"
    BACKEND_READY = "backend.ready"
    BACKEND_SHUTDOWN = "backend.shutdown"
    EXPORT_PROGRESS = "export.progress"
    IMPORT_PROGRESS = "import.progress"
    VERIFY_PROGRESS = "verify.progress"
```

**依赖**: 无

---

### 2.8 `core/__init__.py` — 包入口

**新建**

```python
"""topoone.core - 核心引擎 (零 LLM 依赖)"""

from .config import Settings, setup_logging, StateStore, get_store
from .db import SQLiteContext, MultiDBManager
from .transport import ZMQServer

class CoreEngine:
    """核心引擎聚合类 - 组装所有组件并启动"""

    def __init__(self, data_dir: str | None = None):
        self.settings = Settings()
        if data_dir:
            self.settings.data_dir = data_dir

        setup_logging(self.settings.log_level, self.settings.log_dir)

        self.multi_db = MultiDBManager(data_dir or self.settings.data_dir)
        self.state = get_store()
        self.state._inject_cache(self.multi_db.cache_store)

        self.server = ZMQServer(
            multi_db=self.multi_db,
            dealer_port=self.settings.zmq_dealer_port,
            pub_port=self.settings.zmq_pub_port,
        )

        self._register_services()

    def _register_services(self):
        """将所有 core.* 服务注册到 ZMQServer"""
        from .project import ProjectService, GroupService, GitService
        from .analysis import AnalysisTaskService

        ProjectService(self.multi_db, self.state).register(self.server)
        GroupService(self.multi_db).register(self.server)
        GitService(self.multi_db).register(self.server)
        AnalysisTaskService(self.multi_db, self.state).register(self.server)

    async def run(self):
        await self.server.run_forever()

    def stop(self):
        self.server.stop()
        self.multi_db.close_all()
```

---

## 3. 模块依赖关系图

```
config/ ← 全无依赖
  ↓
db/ ← 依赖 config/
  ↓
store/ ← 依赖 db/
  ↓
project/ ← 依赖 db/ + config/ + store/
parser/ ← 依赖 db/ + store/ + config/
analysis/ ← 依赖 db/ + store/ + config/ + parser/
transport/ ← 依赖 db/
```

无循环依赖。

---

## 4. 与旧代码的映射关系

| 目标文件 | 源文件 | 行数 | 变更 |
|----------|--------|------|------|
| `core/db/pragmas.py` | `config.py:20-34` | ~15 | 提取常量 |
| `core/db/connection.py` | `store/connection.py` + `sqlite_ctx.py` | ~120 | 整合重写 |
| `core/db/manager.py` | `sqlite_ctx.py:1104-1819` | ~700 | 移除 distributed 逻辑 |
| `core/db/schema.py` | `sqlite_ctx.py` DDL | ~300 | 提取 |
| `core/config/settings.py` | `config.py` | ~80 | dataclass 化 |
| `core/config/logging.py` | `logging_config.py` | ~150 | 直接迁移 |
| `core/config/state.py` | `state_store.py` | ~235 | 直接迁移 |
| `core/store/write_queue.py` | `data_layer/write_queue.py` | ~260 | 直接迁移 |
| `core/store/cache_store.py` | `data_layer/cache_store.py` | ~157 | 直接迁移 |
| `core/store/duckdb_reader.py` | `data_layer/duckdb_reader.py` | ~275 | 直接迁移 |
| `core/store/task_store.py` | `store/task_store.py` | ~372 | 直接迁移 |
| `core/store/analysis_store.py` | `store/analysis_store.py` | ~731 | 直接迁移 |
| `core/project/scanner.py` | `core_service.py` | ~300 | 提取 |
| `core/project/service.py` | `core_service.py` | ~800 | 提取+移除 LLM |
| `core/project/group.py` | `core_service.py` | ~150 | 提取 |
| `core/project/git.py` | `task_manager.py` | ~60 | 提取 |
| `core/project/export.py` | `export_service.py` | ~303 | 直接迁移 |
| `core/project/import.py` | `import_service.py` | ~465 | 直接迁移 |
| `core/project/verify.py` | `verify_service.py` | ~166 | 直接迁移 |
| `core/parser/symbol_graph.py` | `symbol_graph.py` | ~152 | 直接迁移 |
| `core/parser/stack_graphs.py` | `stack_graphs_service.py` | ~200 | 直接迁移 |
| `core/parser/hasher.py` | `core_service.py` | ~20 | 提取 |
| `core/parser/pipeline.py` | `analyst_runner.py` | ~1100 | 抽取 LLM 回调 |
| `core/parser/ast_worker.py` | `ast_worker.py` | ~80 | 重写为类 |
| `core/analysis/community.py` | `community_data.py` | ~1119 | 直接迁移 |
| `core/analysis/task.py` | `task_manager.py` | ~1000 | 提取非 LLM 部分 |
| `core/analysis/cascade.py` | `analysis_utils.py` | ~105 | 直接迁移 |
| `core/analysis/ranks.py` | `task_manager.py` | ~100 | 提取 |
| `core/analysis/report.py` | `report_tree_service.py` | ~36 | 直接迁移 |
| `core/analysis/positions.py` | `task_manager.py` | ~80 | 提取 |
| `core/analysis/external.py` | `community_data.py` | ~200 | 提取 |
| `core/transport/server.py` | `zmq_server.py` | ~345 | 移除 MessageBus |
| `core/transport/rpc_ids.py` | `rpc_ids.py` | ~212 | 直接迁移 |
| `core/transport/event.py` | 新建 | ~30 | 新建 |

**总计**: 迁移 ~9500 行

---

## 5. Phase 1 不移入的内容

**LLM 相关** (Phase 3 → `topoone/llm/`):
- `LLMService`, `providers/`, `context/`, `prompt_manager.py`
- `_do_generate_project_summary` (AI 项目摘要)

**Agent 相关** (Phase 4 → `topoone/agent/`):
- `agent_workflow/`, `agent_worker.py`
- `skill_registry.py`, `jsonl_store.py`, `file_summary_cache.py`

**Agent RPC 方法** (Phase 4):
- `startOverview`, `startPipeline`, `startPreSummary`, `startPreSummaryPipeline`
- `analyzeComponents`, `cancelAgentTask`, `getAgentProgress`
- `getAgentTaskHistory`, `clearAgentTaskHistory`
- `getFileSummary`, `deleteFileSummary`, `rerunFileSummary`
- `getPreSummaryStatus`, `listPreSummaryFiles`

**其他子系统**:
- `knowledge.*` RPC (Phase 4)
- `settings.*` RPC (Phase 3)
- `session.*` / `report.*` / `render.*` RPC (Phase 3/4)
- `plugin.*` / `module.*` RPC (Phase 2)

---

## 6. 测试规划

```
next/backend/tests/
├── conftest.py               # fixtures: tmp_data_dir, multi_db, project_db
├── core/
│   ├── test_pragmas.py
│   ├── test_connection.py
│   ├── test_manager.py
│   ├── test_settings.py
│   ├── test_logging.py
│   ├── test_state.py
│   ├── test_write_queue.py
│   └── test_cache_store.py
├── project/
│   ├── test_scanner.py
│   ├── test_service.py
│   ├── test_group.py
│   ├── test_export.py
│   ├── test_import.py
│   └── test_verify.py
├── parser/
│   ├── test_symbol_graph.py
│   ├── test_stack_graphs.py
│   ├── test_pipeline.py
│   └── test_hasher.py
├── analysis/
│   ├── test_community.py
│   ├── test_task.py
│   ├── test_cascade.py
│   ├── test_ranks.py
│   └── test_positions.py
└── transport/
    ├── test_server.py
    └── test_rpc_ids.py
```

### conftest.py 关键 fixture

```python
@pytest.fixture
def tmp_data_dir(tmp_path) -> str:
    return str(tmp_path / ".topocode")

@pytest.fixture
def multi_db(tmp_data_dir) -> MultiDBManager:
    db = MultiDBManager(tmp_data_dir)
    yield db
    db.close_all()

@pytest.fixture
def project_db(multi_db) -> SQLiteContext:
    pid = "test-proj"
    multi_db.init_project_db(pid, "/tmp/test")
    return multi_db.get_project_db(pid)
```

---

## 7. 验证清单

```bash
# 1. 包导入
python -c "
from topoone.core import CoreEngine
from topoone.core.config import Settings, setup_logging, StateStore
from topoone.core.db import SQLiteContext, MultiDBManager
from topoone.core.store import WriteQueue, CacheStore, TaskStore, AnalysisStore
from topoone.core.project import ProjectService, GroupService
from topoone.core.parser import SymbolGraph, AnalysisPipeline
from topoone.core.analysis import CommunityService, AnalysisTaskService
from topoone.core.transport import ZMQServer, get_rpc_id
print('All OK')
"

# 2. 数据库
python -c "
from topoone.core.db import MultiDBManager
import tempfile
d = tempfile.mkdtemp()
db = MultiDBManager(d)
assert db.write_queue is not None
assert db.cache_store is not None
db.close_all()
print('DB OK')
"

# 3. 全部测试
cd next/backend && python -m pytest tests/ -v

# 4. 启动验证
python -c "
from topoone.core import CoreEngine
import asyncio
async def t():
    e = CoreEngine('/tmp/topoone-test')
    assert len(e.server.methods) > 0
    e.stop()
asyncio.run(t())
print('Engine OK')
"
```

**Phase 1 完成标志**:
1. 全部 Python 导入通过
2. 全部 pytest 测试通过
3. `MultiDBManager` 可正常创建/查询/关闭数据库
4. `AnalysisPipeline` 可对示例项目运行 5 步流水线 (不含 LLM)
5. `ZMQServer` 可注册并响应 RPC 请求
6. 与旧 `backend-core/` 零冲突
