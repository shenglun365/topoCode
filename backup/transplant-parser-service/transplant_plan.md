# Transplant Plan — 完整分析流程移植方案 (v0.2)

> 基于《源码分析程序详细设计.md》对齐 | 日期: 2026-05-11

---

## 1. 目标

将 `full_analyst.py` 的 6 步分析流程从 **Celery + MongoDB + Redis** 架构移植到目标系统的 **ZMQ + SQLite** 架构中，作为 `_do_parse()` 的真实实现，完全符合《源码分析程序详细设计.md》定义的接口、协议和数据库规范。

### 1.1 核心变化

| 维度 | 原架构 (full_analyst.py) | 移植后 (符合目标设计) |
|------|------------------------|---------------------|
| 任务接收 | Celery task chain | ZMQ DEALER RPC (端口 5671, 3 帧协议) |
| 事件推送 | Redis Pub/Sub | ZMQ PUB/SUB (端口 5680, 3 帧协议) |
| 持久化 | MongoDB (5 集合) | SQLite (topoone.db: 4 张任务表 + 项目库: 分析数据表) |
| 任务编排 | Celery chain (6 步) | asyncio + ThreadPoolExecutor, 6 步作为 `_do_parse()` 内部流程 |
| 进程模型 | Celery worker (prefork) | 单进程 + asyncio event loop + 4 worker 线程 |
| 数据库管理 | db_pools (全局连接池) | MultiDBManager (LRU 缓存, 最多 3 连接) |

### 1.2 不变部分

- **语言处理器** (`parsers/languages/*/`) — 保留 LanguageRegistry 路由机制
- **分析算法** — AST 解析、符号提取、调用图、依赖图、社区检测算法不变
- **配置文件** — `parser_config.py`, `cross_lang_call_rules.py` 等配置不变
- **Tree-sitter 语法包** — 各语言的 parser 二进制不变

---

## 2. 整体架构

```
┌────────────────────────────────────────────────────────────────────────────┐
│                        Electron 前端 (已存在)                               │
│  Pinia Store (analysis.ts) ──IPC──▶ preload ──▶ ipcMain                   │
└───────────────────────────┬────────────────────────────────────────────────┘
                            │ ZMQ DEALER (3帧RPC)
                            │ port 5671
                            ▼
┌───────────────────────────────────────────────────────────────────────────┐
│                    Transplant Server (本次移植)                            │
│                                                                           │
│  ┌─────────────────────────────────────────────────────────────────────┐  │
│  │  rpc_server.py                                                      │  │
│  │  ┌───────────────────────────────────────────────────────────────┐  │  │
│  │  │  DEALER socket (5671) — 接收 3 帧 RPC 请求                    │  │  │
│  │  │  PUB socket (5680) — 发布 3 帧事件                             │  │  │
│  │  │  注册 13+3 个 analysis.* 方法                                  │  │  │
│  │  └───────────────────────────────────────────────────────────────┘  │  │
│  └────────────────────────┬────────────────────────────────────────────┘  │
│                           │                                               │
│  ┌────────────────────────▼────────────────────────────────────────────┐  │
│  │  task_manager.py — 任务生命周期管理                                   │  │  │
│  │  ├─ create_task() / list_tasks() / get_task()                       │  │  │
│  │  ├─ run_task() → asyncio.create_task(_execute_task)                 │  │  │
│  │  ├─ stop_task() / resume_task() / cancel_task()                     │  │  │
│  │  ├─ update_task_config() → task_config_history                      │  │  │
│  │  ├─ re_run_task() / delete_task()                                   │  │  │
│  │  └─ scan_file_stats()                                               │  │  │
│  └────────────────────────┬────────────────────────────────────────────┘  │
│                           │                                               │
│  ┌────────────────────────▼────────────────────────────────────────────┐  │
│  │  analyst_runner.py — _execute_task() + _do_parse()                  │  │  │
│  │  ├─ ThreadPoolExecutor(max_workers=4)                               │  │  │
│  │  ├─ _execute_task(): 校验 → 创建run → 提交线程池                     │  │  │
│  │  ├─ _do_parse(): 6 步分析流程                                        │  │  │
│  │  │   ├─ Step 1: AST 解析 (按语言路由)                                │  │  │
│  │  │   ├─ Step 2: 符号提取                                             │  │  │
│  │  │   ├─ Step 3: 调用图提取                                           │  │  │
│  │  │   ├─ Step 4: 依赖图提取                                           │  │  │
│  │  │   ├─ Step 5: 社区分析                                             │  │  │
│  │  │   └─ Step 6: 结果汇总 + 写入 analysis_reports                     │  │  │
│  │  └─ _update_progress(): 每 5 文件更新进度 + PUB 推送                  │  │  │
│  └────────────────────────┬────────────────────────────────────────────┘  │
│                           │                                               │
│  ┌────────────────────────▼────────────────────────────────────────────┐  │
│  │  sqlite_store/ — SQLite 存储层                                       │  │  │
│  │  ├─ connection.py: MultiDBManager (LRU, WAL, 主库+项目库)            │  │  │
│  │  ├─ schema.sql: DDL + 迁移                                           │  │  │
│  │  ├─ task_store.py: analysis_tasks / runs / reports / history         │  │  │
│  │  └─ analysis_store.py: 分析数据 (替代 MongoDB 集合)                   │  │  │
│  └────────────────────────┬────────────────────────────────────────────┘  │
│                           │                                               │
│  ┌────────────────────────▼────────────────────────────────────────────┐  │
│  │  adapters/ — MongoDB → SQLite 适配层                                 │  │  │
│  │  ├─ mongo_adapter.py: 模拟 pymongo.Collection 接口                   │  │  │
│  │  └─ dataframe_loader.py: 社区分析 DataFrame 加载                     │  │  │
│  └────────────────────────┬────────────────────────────────────────────┘  │
│                           │                                               │
│  ┌────────────────────────▼────────────────────────────────────────────┐  │
│  │  parsers_patch/db_injector.py — 运行时注入 SQLite 后端                │  │  │
│  └─────────────────────────────────────────────────────────────────────┘  │
│                                                                           │
└───────────────────────────────────────────────────────────────────────────┘
         │                                              │
   topoone.db (主库)                          {project_id}.db (项目库)
   - analysis_tasks                           - source_files
   - analysis_task_runs                       - base_node (AST)
   - analysis_reports                         - graph_node (符号/调用/依赖)
   - task_config_history                      - graph_doc (社区)
                                              - community_hierarchy
```

---

## 3. 目录结构

```
transplant/
├── transplant_plan.md              # 本方案文档
├── config.py                       # ZMQ端口、SQLite路径、线程池配置
├── rpc_server.py                   # ZMQ RPC 服务器 (DEALER 5671 + PUB 5680)
├── task_manager.py                 # 13+3 个 analysis.* 后端方法
├── analyst_runner.py               # _execute_task + _do_parse (6步流程) + _update_progress
├── sqlite_store/
│   ├── __init__.py
│   ├── connection.py               # MultiDBManager (LRU缓存, WAL, busy_timeout)
│   ├── schema.sql                  # 建表 DDL (主库4表 + 项目库5表 + 索引)
│   ├── migration.py                # ALTER TABLE 迁移逻辑
│   ├── task_store.py               # analysis_tasks / runs / reports / history CRUD
│   └── analysis_store.py           # 分析数据 CRUD (base_node, graph_node, graph_doc, ...)
├── adapters/
│   ├── __init__.py
│   ├── mongo_adapter.py            # MongoCollectionAdapter (模拟 pymongo)
│   └── dataframe_loader.py         # load_data_from_sqlite (替代 load_data_from_mongodb)
├── parsers_patch/
│   ├── __init__.py
│   └── db_injector.py              # inject_sqlite_backend (替换 get_mongo_client)
└── tests/
    ├── test_task_store.py
    ├── test_analysis_store.py
    ├── test_mongo_adapter.py
    ├── test_analyst_runner.py
    └── test_rpc_server.py
```

---

## 4. 数据库设计

### 4.1 数据库分类 (符合目标设计 §4.1)

| 数据库 | 文件 | 表 | 用途 |
|--------|------|---|------|
| **主库** | `topoone.db` | `analysis_tasks`, `analysis_task_runs`, `analysis_reports`, `task_config_history` | 任务配置/运行/报告/历史 |
| **项目库** | `{project_id}.db` | `source_files`, `base_node`, `graph_node`, `graph_doc`, `community_hierarchy` | 源文件 + 分析结果 |

> **关键决策**: 分析数据 (AST/符号/调用图/社区) 写入项目库，而非主库。主库仅管理任务元数据。

### 4.2 主库表结构 (完全对齐目标设计 §5)

```sql
-- ============================================
-- analysis_tasks — 任务配置表
-- ============================================
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('ast', 'call-chain', 'dependency', 'dataflow', 'full')),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'modified', 'running', 'done', 'error', 'cancelled', 'stopped', 'paused')),
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 100,
    current INTEGER DEFAULT 0,
    error TEXT,
    result_data TEXT,
    favorite INTEGER DEFAULT 0,
    pinned INTEGER DEFAULT 0,
    tags TEXT,
    agent_id TEXT,
    scope TEXT,
    scopes TEXT,
    extensions TEXT,
    exclude_dirs TEXT,
    report_types TEXT,
    pattern_type TEXT,
    pattern TEXT,
    config_version INTEGER DEFAULT 1,
    last_run_id TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_project ON analysis_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status);

-- ============================================
-- analysis_task_runs — 运行记录表
-- ============================================
CREATE TABLE IF NOT EXISTS analysis_task_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'done', 'error', 'stopped', 'paused')),
    progress INTEGER DEFAULT 0,
    total INTEGER DEFAULT 100,
    current INTEGER DEFAULT 0,
    error TEXT,
    started_at TEXT DEFAULT (datetime('now')),
    finished_at TEXT,
    duration_ms INTEGER,
    snapshot_scope TEXT,
    snapshot_scopes TEXT,
    snapshot_extensions TEXT,
    snapshot_exclude_dirs TEXT,
    snapshot_report_types TEXT,
    FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_task_runs_task ON analysis_task_runs(task_id);
CREATE INDEX IF NOT EXISTS idx_task_runs_status ON analysis_task_runs(status);

-- ============================================
-- analysis_reports — 分析报告表
-- ============================================
CREATE TABLE IF NOT EXISTS analysis_reports (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_id TEXT,
    ast_data TEXT,
    call_chain TEXT,
    dependencies TEXT,
    dataflow TEXT,
    summary TEXT,
    logs TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reports_task ON analysis_reports(task_id);
CREATE INDEX IF NOT EXISTS idx_reports_run ON analysis_reports(run_id);

-- ============================================
-- task_config_history — 配置历史表
-- ============================================
CREATE TABLE IF NOT EXISTS task_config_history (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    config_version INTEGER NOT NULL,
    name TEXT,
    scope TEXT,
    scopes TEXT,
    extensions TEXT,
    exclude_dirs TEXT,
    report_types TEXT,
    pattern_type TEXT,
    pattern TEXT,
    changed_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_config_history_task ON task_config_history(task_id);
```

### 4.3 项目库表结构 (分析数据 — MongoDB 集合映射)

```sql
-- ============================================
-- source_files — 源文件列表 (scanFileStats 数据源)
-- ============================================
CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    language TEXT,
    size INTEGER,
    hashcode TEXT,
    mtime REAL
);
CREATE INDEX IF NOT EXISTS idx_source_files_lang ON source_files(language);
CREATE INDEX IF NOT EXISTS idx_source_files_path ON source_files(file_path);

-- ============================================
-- base_node — AST 节点 (替代 MongoDB base_node 集合)
-- ============================================
CREATE TABLE IF NOT EXISTS base_node (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id INTEGER NOT NULL,
    node_id TEXT NOT NULL,
    scope_node_id TEXT,
    def_node_id TEXT,
    type TEXT NOT NULL,
    name TEXT,
    op TEXT,
    refs TEXT,              -- JSON array
    start TEXT NOT NULL,    -- "line,col"
    end TEXT NOT NULL,      -- "line,col"
    content_size INTEGER,
    FOREIGN KEY (file_id) REFERENCES source_files(id)
);
CREATE INDEX IF NOT EXISTS idx_base_node_file ON base_node(file_id);
CREATE INDEX IF NOT EXISTS idx_base_node_type ON base_node(type);
CREATE INDEX IF NOT EXISTS idx_base_node_name ON base_node(name);

-- ============================================
-- graph_node — 符号 + 调用边 + 依赖边 (替代 MongoDB graph_node 集合)
-- ============================================
CREATE TABLE IF NOT EXISTS graph_node (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol_node_type TEXT NOT NULL,
    file_id INTEGER,
    func_name TEXT,
    class_name TEXT,
    macro_name TEXT,
    method_name TEXT,
    caller_file_id INTEGER,
    caller_func_name TEXT,
    caller_node_id TEXT,
    callee_name TEXT,
    callee_file_id INTEGER,
    callee_node_id INTEGER,
    callee_type TEXT,
    call_site_node_id TEXT,
    call_site_file_id INTEGER,
    include_path TEXT,
    is_system INTEGER DEFAULT 0,
    extra TEXT,             -- JSON: 扩展字段
    FOREIGN KEY (file_id) REFERENCES source_files(id)
);
CREATE INDEX IF NOT EXISTS idx_graph_type ON graph_node(symbol_node_type);
CREATE INDEX IF NOT EXISTS idx_graph_caller ON graph_node(caller_file_id);
CREATE INDEX IF NOT EXISTS idx_graph_callee ON graph_node(callee_name);

-- ============================================
-- graph_doc — 社区分析结果 (替代 MongoDB graph_doc 集合)
-- ============================================
CREATE TABLE IF NOT EXISTS graph_doc (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_type TEXT NOT NULL,
    comm_lv TEXT NOT NULL,
    parent_comm_id TEXT,
    comm_id TEXT NOT NULL,
    node_list TEXT NOT NULL,
    node_count INTEGER NOT NULL,
    edge_list TEXT,
    edge_count INTEGER DEFAULT 0,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_graph_doc_type ON graph_doc(edge_type);
CREATE INDEX IF NOT EXISTS idx_graph_doc_comm ON graph_doc(comm_id);

-- ============================================
-- community_hierarchy — 社区层级 (替代 MongoDB community_hierarchy 集合)
-- ============================================
CREATE TABLE IF NOT EXISTS community_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_type TEXT NOT NULL,
    comm_lv TEXT NOT NULL,
    comm_id TEXT NOT NULL,
    parent_comm_id TEXT,
    node_count INTEGER,
    quality_score REAL,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_comm_hier_type ON community_hierarchy(edge_type);
```

### 4.4 SQLite 性能策略 (对齐目标设计 §4.2-4.3)

```python
# 每个连接初始化时执行
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=10000;       # ~10MB
PRAGMA foreign_keys=ON;
```

**MultiDBManager**: LRU 缓存最多 3 个打开的连接，超出时回收最久未用。

### 4.5 级联删除

```
analysis_tasks (DELETE)
  ├──▶ analysis_task_runs (CASCADE)
  ├──▶ analysis_reports (CASCADE)
  └──▶ task_config_history (CASCADE)
```

---

## 5. ZMQ 协议 (完全对齐目标设计 §3)

### 5.1 端口

| 端口 | Socket | 方向 | 用途 |
|------|--------|------|------|
| **5671** | DEALER | Electron ↔ Python | RPC 请求/响应 |
| **5680** | PUB/SUB | Python → Electron | 事件推送 |

环境变量: `ZMQ_DEALER_PORT`, `ZMQ_PUB_PORT`

### 5.2 RPC 请求/响应 (3 帧)

```
请求:  Frame1: requestId  | Frame2: method  | Frame3: params_json
响应:  Frame1: requestId  | Frame2: result_json | Frame3: error_json
```

### 5.3 事件推送 (3 帧)

```
Frame1: topic ("task") | Frame2: event_type | Frame3: data_json
```

| 事件类型 | 前端通道 | 数据 | 触发时机 |
|---------|---------|------|---------|
| `progress` | `event:task.progress` | `{taskId, runId, progress, total, current}` | 每处理 5 个文件 |
| `complete` | `event:task.complete` | `{taskId, runId, status: "done", progress: 100}` | 解析完成 |
| `error` | `event:task.error` | `{taskId, runId, error: str}` | 解析异常 |
| `stopped` | `event:task.stopped` | `{taskId, runId, status: "paused"\|"stopped"}` | 暂停/终止 |

---

## 6. 后端方法 (13 + 3 待新增)

全部通过 `@server.register("analysis.*")` 注册到 rpc_server.py。

### 6.1 已实现方法 (13 个)

| 方法 | 所在模块 | 说明 |
|------|---------|------|
| `analysis.listTasks` | task_manager.py | 按 project_id 查询，LEFT JOIN runs |
| `analysis.createTask` | task_manager.py | UUID v4, JSON 序列化数组字段 |
| `analysis.runTask` (async) | task_manager.py | 校验 → 创建 run → asyncio.create_task |
| `analysis.getTask` | task_manager.py | 单个任务 + JSON 解析 |
| `analysis.getResults` | task_manager.py | 按 run_id → last_run_id → task_id 优先级 |
| `analysis.updateTask` | task_manager.py | favorite/pinned/tags |
| `analysis.deleteTask` | task_manager.py | CASCADE 删除 |
| `analysis.stopTask` | task_manager.py | 暂停语义 (D7) + 发布事件 |
| `analysis.reRunTask` (async) | task_manager.py | 复用当前配置 |
| `analysis.getTaskRuns` | task_manager.py | run_number DESC |
| `analysis.getTaskLogs` | task_manager.py | 嵌套传参兼容 |
| `analysis.updateTaskConfig` | task_manager.py | 历史审计 + config_version++ |
| `analysis.scanFileStats` | task_manager.py | 项目库 source_files 查询 |

### 6.2 待新增方法 (3 个)

| 方法 | 说明 | 优先级 |
|------|------|--------|
| `analysis.exportResults` (D6) | JSONL 导出 | 中 |
| `analysis.resumeTask` (D7) | 恢复暂停任务 | 中 |
| `analysis.cancelTask` (D7) | 终止任务 (不可恢复) | 中 |

---

## 7. 核心模块设计

### 7.1 `rpc_server.py` — ZMQ RPC 服务器

```python
class RPCHandler:
    def __init__(self):
        self.context = zmq.Context()
        self.dealer = self.context.socket(zmq.DEALER)   # port 5671
        self.pub = self.context.socket(zmq.PUB)          # port 5680
        self.methods = {}  # method_name -> callable

    def register(self, name):
        """装饰器: @server.register('analysis.createTask')"""

    def handle_request(self):
        """解析 3 帧请求 → 调用方法 → 返回 3 帧响应"""

    def publish(self, topic: str, event_type: str, data: dict):
        """发送 3 帧事件推送"""

    def start(self):
        """主循环: poll(dealer) + 非阻塞 publish"""
```

### 7.2 `task_manager.py` — 任务生命周期管理

```python
class TaskManager:
    def __init__(self, server: RPCHandler, multi_db: MultiDBManager):
        self.server = server
        self.db = multi_db
        self._running_tasks = {}  # task_id -> asyncio.Task

    async def run_task(self, task_id: str) -> dict:
        """校验 → 创建 run → 后台启动 → 立即返回"""
        # 1. 校验任务存在且不在 running
        # 2. 查询 max(run_number) + 1
        # 3. INSERT analysis_task_runs (快照配置)
        # 4. UPDATE analysis_tasks SET status='running', progress=0
        # 5. asyncio.create_task(_execute_task(...))
        # 6. 返回 {taskId, runId, runNumber, status: 'running'}

    def _execute_task(self, task_id, run_id, start_time):
        """asyncio 协程: 提交到 ThreadPoolExecutor"""
        loop = asyncio.get_event_loop()
        future = loop.run_in_executor(
            parse_executor,
            _do_parse,
            self.server, task_id, run_id, start_time
        )
        result = await future
        # 更新最终状态 + 发布事件
```

### 7.3 `analyst_runner.py` — 6 步分析流程

```python
def _do_parse(server, task_id, run_id, start_time):
    """
    线程池中的阻塞执行函数 — 替代 mock 实现
    对应 full_analyst.py 的 6 步 Celery chain
    """
    # 1. 加载任务配置 (analysis_tasks)
    task = task_store.get_task(task_id)
    project_db = multi_db.get_project_db(task.project_id)

    # 2. 注入 SQLite 后端 (替换 get_mongo_client)
    inject_sqlite_backend(project_db.path)

    # 3. 获取文件列表 (应用 scopes/extensions/exclude_dirs 过滤)
    files = project_db.query_source_files(task.scopes, task.extensions, ...)

    # 4. 按语言分组
    files_by_lang = group_by_language(files)

    # 5. 6 步分析流程
    total = len(files)
    current = 0
    context = {'task_id': task_id, 'run_id': run_id, 'pid': task.project_id, ...}

    for step_name, step_func in STEPS:
        if _should_stop(task_id):
            # 检查停止标志
            break
        context = step_func(context, project_db)
        current = context.get('files_processed', current)
        # 每 5 个文件推送一次进度
        if current % 5 == 0:
            _update_progress(server, task_id, run_id, current, total)

    # 6. 汇总结果 → analysis_reports
    report = {
        'ast_data': ...,
        'call_chain': ...,
        'dependencies': ...,
        'summary': ...,
    }
    task_store.insert_report(task_id, run_id, report)

    # 7. 更新最终状态
    task_store.update_status(task_id, 'done', progress=100)
    task_store.update_run_status(run_id, 'done', duration_ms=...)
    server.publish("task", "complete", {...})
```

**6 步映射**:

| 步骤 | 原 Celery Task | 移植后函数 | 说明 |
|------|---------------|-----------|------|
| 1 | `parse_source_code` | `_step1_parse_ast()` | 按语言路由 AST 解析 |
| 2 | `parse_def_mac_node` | `_step2_extract_symbols()` | 符号提取 |
| 3 | `parse_call_node` | `_step3_extract_call_graph()` | 调用图 |
| 4 | `parse_include_dependency` | `_step4_extract_dependency()` | 依赖图 |
| 5 | `community_analysis` | `_step5_community_analysis()` | 社区检测 |
| 6 | `finalize_task` | `_step6_finalize()` | 结果汇总写入 analysis_reports |

### 7.4 `sqlite_store/connection.py` — MultiDBManager

```python
class MultiDBManager:
    MAX_CONNECTIONS = 3  # LRU 缓存上限

    def __init__(self, db_dir: str):
        self._cache = OrderedDict()  # project_id -> SQLiteContext
        self._main_db = None

    @property
    def main_db(self):
        if self._main_db is None:
            self._main_db = SQLiteContext(os.path.join(self.db_dir, 'topoone.db'))
            self._main_db._init_pragmas()
            self._main_db._migrate()
        return self._main_db

    def get_project_db(self, project_id: str) -> SQLiteContext:
        """获取项目库连接，LRU 缓存 + 自动回收"""
        if project_id in self._cache:
            self._cache.move_to_end(project_id)
            return self._cache[project_id]
        if len(self._cache) >= self.MAX_CONNECTIONS:
            oldest_id, _ = self._cache.popitem(last=False)
            self._cache[oldest_id].close()
        db = SQLiteContext(os.path.join(self.db_dir, f'{project_id}.db'))
        db._init_pragmas()
        db._migrate()
        self._cache[project_id] = db
        return db
```

### 7.5 `adapters/mongo_adapter.py` — MongoDB 适配层

```python
class MongoCollectionAdapter:
    """模拟 pymongo.Collection 接口，底层写入 SQLite"""

    def __init__(self, sqlite_conn, table_name: str):
        self._conn = sqlite_conn
        self._table = table_name

    def insert_one(self, document) -> pymongo.InsertOneResult:
        ...
    def insert_many(self, documents) -> pymongo.InsertManyResult:
        ...
    def find(self, filter=None, projection=None) -> MongoCursorAdapter:
        ...
    def find_one(self, filter) -> dict | None:
        ...
    def update_one(self, filter, update, upsert=False) -> pymongo.UpdateResult:
        ...
    def delete_many(self, filter) -> pymongo.DeleteResult:
        ...
    def count_documents(self, filter) -> int:
        ...
    def bulk_write(self, operations, ordered=True) -> pymongo.BulkWriteResult:
        """处理 InsertOne/UpdateOne/ReplaceOne/DeleteOne 操作"""
        ...

class MongoCursorAdapter:
    """模拟 pymongo.Cursor，支持迭代、sort、limit"""
    ...

class MongoDatabaseAdapter:
    """模拟 pymongo.Database，get_collection() 返回 MongoCollectionAdapter"""
    ...

class MongoClientAdapter:
    """模拟 pymongo.MongoClient，get_database() 返回 MongoDatabaseAdapter"""
    ...
```

### 7.6 `parsers_patch/db_injector.py` — 依赖注入

```python
def inject_sqlite_backend(project_db_path: str):
    """
    全局替换 get_mongo_client() 的返回值，
    让所有调用 get_mongo_client().get_database('topocode')
    返回适配了 SQLite 的伪 Database 对象
    """
    import databases.db_pools as db_pools
    from adapters.mongo_adapter import MongoClientAdapter

    conn = sqlite3.connect(project_db_path)
    mock_client = MongoClientAdapter(conn)
    db_pools.get_mongo_client = lambda: mock_client
    db_pools.get_redis_connection = lambda: None  # 屏蔽 Redis
```

---

## 8. 任务状态机

```
pending ──▶ running ──▶ done
  ↑           │
  │           ├──▶ paused ──▶ running (resume)
  │           │
  │           ├──▶ paused ──▶ stopped (cancel, 不可恢复)
  │           │
  │           └──▶ error
  │
modified ──┘
cancelled/stopped ──▶ running (reRun)
```

| 操作 | 前置状态 | 后置状态 | 事件 |
|------|---------|---------|------|
| `runTask` | pending/modified/done/error/stopped | running | — |
| `stopTask` (暂停) | running | paused | `task.stopped` |
| `resumeTask` | paused | running | — |
| `cancelTask` | running/paused | stopped | `task.stopped` |
| `reRunTask` | done/error/stopped | running | — |
| `updateTaskConfig` | non-running | pending | — |

---

## 9. 数据流: 分析结果写入

原流程将分析结果分散写入 MongoDB 的 5 个集合。移植后:

```
_do_parse() 执行过程:
  │
  ├─ Step 1: AST 解析
  │   └─ 写入项目库 base_node 表 (供后续步骤读取)
  │
  ├─ Step 2: 符号提取
  │   └─ 写入项目库 graph_node 表 (symbol_node_type='function'/'macro'/...)
  │
  ├─ Step 3: 调用图提取
  │   └─ 写入项目库 graph_node 表 (symbol_node_type='call_relation')
  │
  ├─ Step 4: 依赖图提取
  │   └─ 写入项目库 graph_node 表 (symbol_node_type='dependence')
  │
  ├─ Step 5: 社区分析
  │   └─ 写入项目库 graph_doc + community_hierarchy 表
  │
  └─ Step 6: 结果汇总
      └─ 写入主库 analysis_reports 表:
          ├─ ast_data: 从 base_node 提取关键统计
          ├─ call_chain: 从 graph_node(call_relation) 提取
          ├─ dependencies: 从 graph_node(dependence) 提取
          ├─ summary: 文本摘要
          └─ logs: [{timestamp, message}]
```

---

## 10. 错误处理

| 场景 | 策略 |
|------|------|
| ZMQ 连接断开 | 上游重发，通过 task_id 去重 |
| 单文件解析失败 | 记录日志，继续下一个文件 (原 full_analyst 行为) |
| 整步失败 | status='error', publish error 事件, 不执行后续步骤 |
| SQLite 锁冲突 | busy_timeout=5000ms, 超时后重试 1 次 |
| 重复运行 | runTask 校验 status != 'running' |
| 任务停止 | 检查 `_stop_flags[task_id]` 标志，每步之间检查 |

---

## 11. 实施计划

| 阶段 | 内容 | 产出 | 依赖 |
|------|------|------|------|
| **Phase 1** | MultiDBManager + schema + migration + task_store | sqlite_store/ 完整 | 确认 Q1-Q3 |
| **Phase 2** | MongoCollectionAdapter + CursorAdapter + bulk_write | adapters/mongo_adapter.py | 确认 Q4 |
| **Phase 3** | analysis_store (项目库 CRUD) + db_injector | analysis_store.py + parsers_patch/ | Phase 1, 2 |
| **Phase 4** | analyst_runner: _execute_task + _do_parse + 6 步函数 | analyst_runner.py | Phase 3 |
| **Phase 5** | task_manager: 13 个后端方法 | task_manager.py | Phase 1 |
| **Phase 6** | rpc_server: DEALER + PUB + 3 帧协议 | rpc_server.py + config.py | Phase 4, 5 |
| **Phase 7** | dataframe_loader (社区分析适配) | adapters/dataframe_loader.py | 确认 Q5 |
| **Phase 8** | 集成测试 + 性能验证 | tests/ | 全部 |

---

## 12. 待确认事项 (需要你逐一答复)

### 12.1 数据库路径

> **Q1**: SQLite 数据库文件存放在哪个目录？
> - 方案 A: 项目目录下 `.topocode/` 隐藏文件夹
> - 方案 B: 固定系统目录 (如 `~/.topocode/data/`)
> - 方案 C: 可配置路径 (config.py 中指定)

### 12.2 项目库文件列表来源

> **Q2**: 项目库的 `source_files` 表由谁填充？
> - 方案 A: transplant 服务在创建任务时自动扫描项目目录填充
> - 方案 B: 由上游 Electron 端在创建项目时预先填充
> - 方案 C: 由独立的扫描服务负责

### 12.3 原有 parsers 修改策略

> **Q3**: 对 `parsers/` 目录下原有代码的修改容忍度？
> - 方案 A: **零修改** — 纯运行时注入，MongoCollectionAdapter 模拟完整 pymongo 接口（适配工作量大）
> - 方案 B: **最小修改** — 在 parsers 入口增加 `db_backend` 参数（需改 ~5-10 个文件）
> - 方案 C: **复制改造** — 在 transplant/ 下复制关键文件并直接改为 SQLite（代码冗余但安全）

### 12.4 社区分析临时文件

> **Q4**: 社区分析 (`_analyze_communities`) 当前写 JSON 到 `/tmp/community_temp/`，是否保留？
> - 方案 A: 保留临时文件行为 (改动最小)
> - 方案 B: 改为纯内存处理 (需修改 `utils/analyser/communities/`)

### 12.5 分析结果粒度

> **Q5**: `analysis_reports` 表中的 `ast_data`, `call_chain`, `dependencies` 字段应该存储什么粒度？
> - 方案 A: 完整数据 (所有 AST 节点/调用边/依赖边序列化为 JSON) — 数据量大
> - 方案 B: 仅存储统计摘要 (节点数/边数/社区数)，详细数据在项目库中查询 — 推荐
> - 方案 C: 存储 Top-N 关键数据 (如 Top 100 调用链)

### 12.6 任务类型与 6 步流程的映射

> **Q6**: 目标设计定义了 5 种任务类型 (`ast`, `call-chain`, `dependency`, `dataflow`, `full`)，但原 full_analyst 只有全量分析。如何处理？
> - 方案 A: `full` 执行完整 6 步，其他类型只执行对应步骤 (如 `ast` 只执行 Step 1)
> - 方案 B: 初期只支持 `full`，其他类型后续扩展
> - 方案 C: 所有类型都执行完整 6 步，只是 `analysis_reports` 中只返回对应部分

### 12.7 数据清理策略

> **Q7**: 重新运行同一任务时，是否需要先清理项目库中的旧分析数据？
> - 方案 A: 每次运行前 DELETE 项目库中该任务相关的所有分析数据
> - 方案 B: 不清理，多次运行的数据共存 (通过 run_id 区分)
> - 方案 C: 仅清理 base_node 和 graph_node，保留 graph_doc (社区分析耗时久)

### 12.8 停止任务的实现方式

> **Q8**: 任务停止 (stopTask 暂停) 如何实现？
> - 方案 A: 设置 `_stop_flags[task_id]` 标志位，每步之间检查 (简单但粒度粗)
> - 方案 B: 在线程池中用 `concurrent.futures.Future.cancel()` (Python 不保证立即取消)
> - 方案 C: 文件级别检查标志位，每处理一个文件检查一次 (粒度细但开销大)

### 12.9 并发策略

> **Q9**: 目标设计 D3 说"单项目串行"，是否意味着同一项目不能有多个 running 任务，但不同项目可以并行？
> - 确认: 同项目串行 + 跨项目并行 (ThreadPoolExecutor 天然支持)

### 12.10 前端已有的 ZMQ 基础设施

> **Q10**: 目标设计中提到的 ZMQ RPC 基础设施 (rpc_server.py 的 `@server.register` 装饰器, 3 帧协议解析) 是否已有实现？
> - 方案 A: 已有，transplant 只需注册新方法
> - 方案 B: 需要从零实现 rpc_server.py

---

*方案版本: v0.2 | 日期: 2026-05-11 | 基于《源码分析程序详细设计.md》对齐*
