# TopoOne 数据库设计文档

> 范围：本仓库全部持久化存储机制（KB 核心 + Architect 子系统）
> 代码基线：`packages/core/topoone/db/**`、`apps/architect/topoone_app_architect/arch_routes/{ctx,store,db_schema}.py`
> 更新日期：2026-08-24

---

## 1. 总体架构

### 1.1 技术选型

| 组件 | 选型 | 用途 |
|---|---|---|
| 主存储 | SQLite（WAL 模式） | 全部业务数据 |
| 写入串行化 | 自研 `WriteQueue` 单写线程 | 消除多线程 SQLITE_BUSY |
| KV 缓存 | diskcache（`CacheStore`） | 排名/失败计数/任务队列等临时状态，TTL+LRU |
| OLAP 只读加速 | DuckDB 内存引擎 ATTACH SQLite | 跨表 JOIN / 聚合 / 递归查询 |

无外部数据库依赖；单机文件存储，所有库集中于数据目录。

### 1.2 两套子系统

系统由两套相互独立的库群组成，仅共享连接层 `SQLiteContext`（`topoone.db.manager` 版），互不读写对方库文件：

| 子系统 | 入口 | 主库 | 项目库 |
|---|---|---|---|
| **KB 核心**（代码知识库/分析引擎） | `MultiDBManager`（engine 进程持有） | `topoone.db` + `knowledge.db` + `sessions.db` + `chat.db` | `projects/{pid}/project.db` |
| **Architect**（架构设计工作台，独立 FastAPI 进程） | `ctx.setup()` 注入 | `architect.db` | `architect/{pid}/arch.db` |

### 1.3 数据目录布局

数据目录默认 `~/.topocode`，可经 `TOPOCODE_DB_DIR`（KB）/ `ARCH_DATA_DIR`（Architect）覆盖：

```
~/.topocode/
├── topoone.db                    # KB 主库：项目注册 + 全局配置 + LLM 模板/日志
├── knowledge.db                  # 知识库文档
├── sessions.db                   # 非 ai_assistant 模块的 LLM 会话
├── chat.db                       # AI 助手会话 + 聊天持久化文档
├── architect.db                  # Architect 主库：项目注册 + 全局表 + 未绑定项目默认桶
├── projects/{pid}/project.db     # KB 项目库（每项目一库）
├── architect/{pid}/arch.db       # Architect 项目库（每项目一库）
├── cache/                        # diskcache KV 存储
└── source-cache/{pid}/           # 项目源码缓存目录（非 DB）
```

---

## 2. 建库建表机制

### 2.1 初始化入口

| 库 | 初始化时机 | 入口 |
|---|---|---|
| KB 四个全局库 | `MultiDBManager.__init__`（进程启动即建） | `main/knowledge/sessions/chat db.executescript(<*_TABLES_SQL>)` |
| KB 项目库 | **首次访问时懒创建**（`get_project_db` 发现文件不存在自动建） | `init_project_db()` + `_migrate_project_db()` |
| Architect 主库 | `ctx.setup(data_dir)`（进程启动） | `db_schema.init_architect_db()` |
| Architect 项目库 | **首次访问时懒创建**（`ctx.project_db(pid)`） | `db_schema.init_architect_project_db()` |

所有 DDL 以 Python 字符串常量集中管理：

- KB：`MAIN_DB_TABLES_SQL` / `KNOWLEDGE_DB_TABLES_SQL` / `SESSIONS_DB_TABLES_SQL` / `CHAT_DB_TABLES_SQL` / `PROJECT_DB_TABLES_SQL`（manager.py）
- Architect：`ARCH_MAIN_TABLES_SQL` / `ARCH_PROJECT_TABLES_SQL`（db_schema.py）

DDL 全部为 `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS`，天然幂等，每次打开连接即可重复执行。

### 2.2 Architect 主库的「默认桶」设计

```python
# db_schema.init_architect_db
db.executescript(ARCH_MAIN_TABLES_SQL + "\n" + ARCH_PROJECT_TABLES_SQL)
```

主库除全局表外**同时装载项目表全套 schema**。当请求无项目上下文（未绑定项目）时，项目表的读写回落到主库这张同构表，保证 API 永远可用；项目一旦定位则路由到独立项目库。这是分库体系中的关键兜底机制（见 §3.3/§3.4）。

### 2.3 迁移策略

无迁移框架/版本号表，采用**幂等探测式迁移**：启动或打开连接时执行，已存在则跳过。

**(1) 补列** —— `PRAGMA table_info(t)` 取现有列集合，缺失才 `ALTER TABLE ADD COLUMN`：
- KB 主库：`_migrate_main_tables()` 中 `columns_to_add` 字典声明式列出各表新增列
- KB 项目库：`_migrate_project_db()`（每次打开项目库都执行）
- Architect：通用工具 `_add_cols(db, table, [(name, type), ...])`

**(2) 表级重建** —— CHECK 约束无法用 ALTER 修改时，走「建新表 → INSERT SELECT 拷贝 → DROP 旧表 → RENAME」四步（如 `model_configs` provider/status 约束升级）。

**(3) 数据修复与规范化** —— 迁移内嵌一次性 UPDATE，如：
- `model_configs` 历史脏数据修复（`typeof(x)='text'` 判别后回写）
- Architect 语义资产旧类别归一：`data_structure/asset→entity`、`processing_flow→process`、`control_logic→decision`，粒度统一为 `implementation/logic/business`
- `component_analysis` 旧表数据搬入 `community_llm_results` 后 DROP

**(4) 去重 + 唯一索引兜底** —— 对 `graph_doc`、`community_hierarchy` 先按业务键 `DELETE NOT IN (SELECT MIN(id) ... GROUP BY)` 去重，再建 UNIQUE INDEX，防止历史重复数据导致建索引失败。

**(5) 种子数据** —— 主库初始化后 `_init_default_skills()` 以 `INSERT OR IGNORE` 写入 5 条默认校验技能配置。

**(6) 废弃表清理** —— `sessions.db` 初始化脚本直接 `DROP TABLE IF EXISTS coder_sessions/chat_messages`（v1 遗留）。

---

## 3. 分库分表设计

### 3.1 拆分模型

采用**按项目垂直分库**（database-per-project），不做水平分表：

- 一个项目 = 一个独立 .db 文件，物理隔离，单库体积可控，删除项目即删文件
- 全局维度数据（项目注册、模型配置、模板）留主库
- 表级归属由**白名单**显式声明，而非隐式规则

Architect 侧白名单（`store.PROJECT_TABLES`，共 20 张）：

```python
PROJECT_TABLES = frozenset({
    "arch_requirements", "arch_plans", "arch_task_trees",
    "arch_execution_tasks", "arch_agent_sessions", "arch_agent_messages",
    "arch_unit_tests", "arch_unit_test_sessions", "arch_unit_test_messages",
    "arch_conversations", "arch_conversation_messages",
    "arch_blueprints", "arch_tags", "arch_staging_scans",
    "arch_snapshot_records", "arch_kb_snapshots",
    "arch_semantic_assets", "arch_ast_cache", "arch_semantic_refs",
    "arch_extract_tasks",
})
```

不在白名单内的表（`arch_projects`、`arch_specs`、`arch_agent_configs` 等）为全局表，恒落主库。KB 侧同理：`source_files`、`graph_*`、社区分析等分析产物全在项目库，注册/配置在主库。

### 3.2 项目定位链

写入/查询前需解析出目标项目 id（`_resolve_pid`），优先级：

```
显式参数 > 请求上下文 contextvar（HTTP 中间件/WS 首消息 set_project）
        > 载荷字段 projectId > None（回落主库默认桶）
```

### 3.3 读路由（`_route_read` → 三模式）

| 模式 | 触发条件 | 行为 |
|---|---|---|
| `one` | 全局表；或项目表且有项目定位且其库存在 | 单库直查 |
| `empty` | 定位到项目但 `architect/{pid}/arch.db` 不存在 | 直接返回空集，**不跨项目泄漏** |
| `scan` | 项目表但无项目定位 | 遍历主库（默认桶）+ 磁盘上全部项目库逐库查询，内存合并；带 `ORDER BY` 时合并后在 Python 侧重排以保持语义一致 |

磁盘项目发现：`glob("architect/*/arch.db")`，目录名即项目 id，无需注册表反查。

### 3.4 写路由（`_target_db`）

```
全局表                     → 主库
项目表 + 有项目定位         → ctx.project_db(pid)   # 库不存在则按需建库+迁移
项目表 + 无项目定位         → 主库默认桶
```

### 3.5 行级定位（`_locate_db`）

更新/删除单行时先确定行所在库：有项目定位 → 直查该库；无定位 → 按 PK `SELECT id FROM t WHERE id=?` 依次探测各库（主库 + 各项目库），命中即锁定目标库；全部未命中返回「默认写目标 + found=False」。这解决了「同一张项目表的行可能散落在主库默认桶和各项目库」的定位问题。

### 3.6 连接生命周期管理

| 机制 | KB（`MultiDBManager`） | Architect（`ctx`） |
|---|---|---|
| 项目库缓存 | `OrderedDict` LRU，容量 100，空闲 300s 自动关闭剔除 | 进程级 dict + 双检锁，常驻不淘汰 |
| 打开 | 懒创建/打开 + 迁移，注册进 WriteQueue | 懒创建 + 幂等建表迁移 |
| 删除 | checkpoint → 切 DELETE 模式释放句柄 → 重试删 wal/shm/db（Windows 兼容） | close → 删三件套 → 清空空目录 |
| 源码目录关联 | 中心路径与源码目录解耦；源码目录只写签名文件 `.topocode/proj-id`，目录整体移动后可快速重关联 | 项目 id 即目录名，无签名文件 |

### 3.7 历史归档模式（活表 + `_history`）

KB 项目库的版本化方案（`ensure_history_table`）：

- 历史表 = 活表同构（`CREATE TABLE ... AS SELECT * FROM t WHERE 1=0`，CTAS 不保留 PK/UNIQUE，允许同 id 多版本区间共存）+ `version_from` / `version_to` 两列
- 被覆盖/删除的行从活表移入历史表并标注区间 `[version_from, version_to)`
- 重建任意版本 V 的视图：`活表(version_from<=V) UNION 历史(version_from<=V AND version_to>V)`
- 已实例化对：`source_files` ↔ `source_files_history`；该机制可推广至任意活表

---

## 4. 读写管理

### 4.1 写路径 —— WriteQueue 单线程串行化

所有 KB 库的写操作经 `is_write_sql()` 判定（INSERT/UPDATE/DELETE/CREATE/ALTER/DROP/REPLACE 前缀 + 带赋值的 PRAGMA）后转入单一后台写线程（`sqlite-writer`）：

| API | 语义 |
|---|---|
| `execute_sync(label, sql, params, timeout=30)` | 阻塞等待结果 `{lastrowid, rowcount, error}` |
| `execute(label, ...)` | fire-and-forget，适合日志/统计类 |
| `execute_batch(label, items)` | 多语句单事务（BEGIN…commit / 异常 rollback），超时 600s |

- 连接按 `label` 区分：`main` / `knowledge` / `sessions` / `chat` / `project:{pid}`（Architect 进程不经 WriteQueue，见 §4.5）
- 每条写入自提交，上层 `SQLiteContext.commit()` 在 WQ 模式下退化为兼容空操作
- 优雅关闭：`wal_checkpoint(TRUNCATE)` 后关闭全部连接，确保落盘

### 4.2 PRAGMA 与容错

全局 PRAGMA（`config.SQLITE_PRAGMAS`）：`journal_mode=WAL`、`busy_timeout=5000`、`synchronous=NORMAL`、`cache_size=10000`、`foreign_keys=ON`。

多层容错：

1. 打开连接：WAL 失败 → 回退 DELETE 日志模式重试（不删 wal/shm）；仍失败 → 清理 stale `-wal/-shm` 后最后重试
2. 运行期：`disk I/O error` / `abort due to ROLLBACK` 类瞬时错误自动重连并重试（最多 3 次）
3. Architect 侧无 WQ：依赖连接内 RLock + WAL busy_timeout 串行化本进程写，跨进程靠文件锁

### 4.3 读路径

- 常规读：调用方连接直接执行（读不排队），`fetchall/fetchone` 返回 dict
- **DuckDB 加速**（`DuckDBReader`）：内存引擎按需 `ATTACH '<path>' AS xx (TYPE sqlite)` 直接读取 SQLite 文件，零复制承担文件排名计算、社区级联层级等 JOIN/递归/聚合查询；distributed 模式下 DuckDB 仅运行于 DB Service 进程

### 4.4 分布式模式（`TOPO_MODE=distributed`）

进程拓扑：Main / AST Worker / Agent Worker 经 ZMQ DEALER 连接独立 **DB Service** 进程（ROUTER，端口 `DB_SERVICE_PORT=18762`）。

- 业务进程侧 `RemoteWriteQueue` 保持与本地 WriteQueue 相同接口（register_db / execute / execute_sync / execute_batch），内部转 JSON 帧转发，含 request_id 幂等去重（60s TTL）、断线自动重连一次、慢查询 >500ms 记日志
- `RemoteCacheStore` 将 cache_get/set/delete/incr 一并代理到 DB Service
- DB Service 内部仍是「WriteQueue 单写线程 + 读连接池 + CacheStore」，读写方法集白名单分发
- 建表亦远程执行：`execute_sync(label, <TABLES_SQL>, timeout=60)`

单体模式（默认 `monolith`）下上述组件全部进程内直连，Worker 退化为线程池。

### 4.5 缓存层与状态存储

- `CacheStore`：diskcache 封装（`{data_dir}/cache`），命名空间键如 `ranks:{task_id}`、`ps_failed:{task_id}`、`executing_tasks`、`agent_tasks`，支持 TTL 过期与原子 incr
- `StateStore`：过渡期双写（内存 dict + CacheStore，读优先 cache 回落 dict），预留切 `cache` 单写模式，为分布式收敛做准备

---

## 5. 数据字典（关键表）

> 约定：KB 各库时间列为 `TEXT DEFAULT (datetime('now'))`；Architect 各表时间为 `INTEGER DEFAULT 0`（epoch ms）。JSON 列在 Architect store 层透明编解码（§6）。仅列核心表与关键列，长尾配置类表归组简述。

### 5.1 topoone.db（KB 主库）

| 表 | 用途 | 关键列 / 要点 |
|---|---|---|
| `projects` | 项目注册表（中心枢纽） | `root_path UNIQUE`；`status`(synced/syncing/error)；`import_mode`(static/git-local/git-remote)；`current_version_id`；存储统计缓存列 `db_size_bytes/source_size_bytes/storage_checked_at`（避免首页扫描各项目库） |
| `analysis_tasks` | 分析任务配置持久化 | `type`(ast/call-chain/dependency/dataflow/full)；`status`(pending/modified/running/done/error/cancelled)；配置列族 scope/scopes/extensions/exclude_dirs/report_types/pattern*；`config_version`+`last_run_id`；FK→projects CASCADE；idx(project_id, status, created_at) |
| `task_config_history` | 任务配置变更历史 | FK→analysis_tasks；按 config_version 存档 |
| `analysis_task_runs` | 运行记录（一次运行一条） | `run_number`、`duration_ms`、snapshot_* 冻结当时配置 |
| `analysis_reports` | 分析报告（大对象） | `ast_data/call_chain/dependencies/dataflow/summary/logs` 均 TEXT 大 JSON；关联 run_id |
| `model_configs` | LLM 模型配置 | `provider` CHECK 八种（ollama/lm-studio/custom-local/deepseek/minimax-cn/minimax-global/openrouter/custom-cloud）；`type`(local/cloud)；采样参数 + `context_window` + 每日配额列 |
| `agent_configs` / `agent_executions` | 外部 Agent CLI 配置与执行记录 | executions 记录 command/stdout_path/stderr_path/exit_code/duration_ms |
| `skill_configs` | 校验技能开关 | 启动时播种 5 条默认（INSERT OR IGNORE） |
| `task_model_bindings` | 任务类型→模型绑定 | priority 排序取用 |
| `llm_prompt_templates` | Prompt 模板 | `mode`(chat/tools/structured) × `module_type` 四模块；system/user 模板 + tools_json + output_schema_json + variables_json |
| `llm_call_logs` | LLM 调用审计 | request_id、token_prompt/completion/total、latency_ms、status(success/error/aborted) |
| `report_interaction_log` | 报告管线交互日志 | `meta_json` 携带 template_id/pipeline_step/community_id 等上下文 |
| `code_index_messages` | 报告页对话历史 | message_type(node/edge/community/ai-explain) |
| `user_node_styles` | 图节点样式偏好 | symbol_type 维度索引 |
| `project_groups` / `project_group_map` | 分组树（≤4 层）+ 项目 M:N 关联 | depth CHECK 0..3；复合 PK(project_id, group_id) |
| `project_git_info` | 项目 Git 元信息 | branch/commit/tags/recent_commits（JSON TEXT） |
| `doc_project_map` | doc_id→project_id 映射 | 加速文档定位，避免遍历项目库 |
| `project_versions` | KB 版本基线注册表 | `parent_version_id` 链；change_type(minor/major)；is_baseline 标记；idx(project_id, created_at DESC) |
| `project_version_files` | 版本间文件级 delta | change_type(A/M/D) + file_path |
| `project_update_requests` | 「待更新」工作流 | repo_url+branch+head；status(pending/confirmed/done/cancelled) |
| `context_store` / `app_config` / `agent_instructions` | 通用 KV / 系统配置 / 预留指令表 | key-value 形态 |

### 5.2 knowledge.db / sessions.db / chat.db

| 库.表 | 用途 | 要点 |
|---|---|---|
| `knowledge.knowledge_docs` | 知识文档 | type(document/snippet/note/spec)；status(draft/published/archived)；`embedding_id` 预留向量关联 |
| `sessions.llm_sessions` | 统一会话表（v2） | `module_type` CHECK 四类：project_resource / project_analysis / knowledge_base / ai_assistant；metadata JSON 扩展 |
| `sessions.llm_messages` | 统一消息表 | role(user/assistant/system/tool)；FK→llm_sessions CASCADE |
| `sessions.analysis_sessions` | 报告会话三级隔离 | project_id/task_id/report_id 映射到 llm_session |
| `chat.chat_drafts` / `chat_archives` / `doc_categories` | 便签草稿 / 归档 / 文档分类树 | 分类树 parent_id 自引用 |
| `chat.llm_sessions` / `chat.llm_messages` | AI 助手会话副本结构 | module_type='ai_assistant' 的会话由 llm_service 路由至此库，与其余模块隔离 |

### 5.3 projects/{pid}/project.db（KB 项目库）

| 表 | 用途 | 关键列 / 要点 |
|---|---|---|
| `source_files` | 源码文件清单（活表） | `file_path UNIQUE`；content_hash/hashcode 双哈希；`version_from` 版本化起点 |
| `source_files_history` | 过期文件行 δ 归档 | 同构 + version_from/version_to 区间；idx(file_path, version_from, version_to) |
| `ast_data` | 文件 AST（仅最新） | ast_json 大 TEXT；file_path UNIQUE |
| `dependencies` / `call_chains` | 依赖边 / 调用边 | caller/callee file(+func)+line_number |
| `file_summaries` | 文件摘要缓存 | (project_id, file_path) 索引 |
| `graph_node` | 符号节点（任务级隔离） | task_id 维度全部联合索引；(task_id,kind)/(task_id,file_path)/(task_id,qualified_name)；signature/decorators/type_parameters 元数据 |
| `graph_edge` | 关系边 | source_id/target_id/kind(INCLUDE/CALL…)；provenance(parser/llm)；idx(task_id, kind, target_id) 服务邻接展开 |
| `graph_doc` | 社区分层分析结果 | comm_lv 层级 + parent_comm_id 父链 + quality_score；UNIQUE(task_id, edge_type, comm_id)（迁移去重后补建） |
| `community_hierarchy` | 社区层级元数据 | UNIQUE(task_id, edge_type, comm_lv, comm_id) |
| `report_subdocs` | 分析报告子文档 | (task_id, comm_id, created_at) 排序索引 |
| `community_llm_results` | 社区 LLM 命名/摘要 | UNIQUE(task_id, edge_type, comm_lv, comm_id)；component_type/status 兼容列 |
| `arch_snapshots` / `arch_snapshot_communities` | 架构快照及社区明细 | snapshot↔community UNIQUE；node_list/file_list/edge_list JSON |
| `graph_node_positions` | 图节点拖拽位置 | 两个部分唯一索引区分「活动布局(snapshot IS NULL)」与「快照布局」 |
| `community_overrides` | 用户手动组件划分 | action(rename/merge/split/reassign/freeze)；增量更新不覆盖手动划分 |
| `ai_sessions` + `ai_session_changes` / `ai_session_issues` | AI 编码会话追踪 | 变更前后签名/内容对比；问题 severity 索引 |
| `model_daily_usage` | 模型每日用量 | UNIQUE(model_id, date) upsert 累计 |
| `agent_task_history` | Agent 任务历史 | agent_id UNIQUE；idx(task_id, created_at DESC) |
| `components` / `ai_qa` / `project_config` | 组件 / QA 记录 / 项目级 KV | 辅助表 |

### 5.4 architect.db（Architect 主库）

**全局表：**

| 表 | 用途 | 关键列 / 要点 |
|---|---|---|
| `arch_projects` | Architect 项目注册表 | root_path(execRoot)/kb_root；baseline_id/commit；mode(existing/greenfield)+scaffold；KB 绑定列 kb_project_id/kb_source_dir/link_verified_at；git 绑定 remote_url/default_branch |
| `arch_specs` | 规范版本 | version PK；overrides/explicit_rules/derived_rules/changelog JSON |
| `arch_agent_configs` | Agent 适配器配置 | adapter(opencode/codex/claude…)；mode(server/cli)；models JSON；instance_mode(managed/external)；健康检查 last_status/detail/at |
| `arch_agent_instances` | Agent 实例池 | state(starting/ready/busy/idle/stopped/error)；pid/port；repo_url/base_commit/task_branch(arch/)；ref_count 引用计数 + idle_until 空闲回收 |
| `arch_mcp_calls` / `arch_interactions` | MCP 工具调用 / 交互审计日志 | input/output JSON |
| `arch_collab_config` | 协作配置 KV | key-value |
| `arch_id_seqs` | 全局 ID 序列 | prefix PK + last_seq，`ON CONFLICT DO UPDATE` 原子自增（§6.1） |

**项目表（兼作未绑定项目默认桶）**：schema 与项目库完全一致（见 5.5）。

### 5.5 architect/{pid}/arch.db（Architect 项目库）

| 表 | 用途 | 关键列 / 要点 |
|---|---|---|
| `arch_requirements` | 需求（提案池→需求池） | tier(raw/analyzed)；location(proposal/pool)；priority（默认 P2）；acceptance/analysis/suggestion/design JSON；追溯链 parent_id/related_to/merged_into；asset_invalidated(+at) 资产失效联动 |
| `arch_plans` | 实施方案 | req_ids/changes/impact JSON；base_commit 定基线 |
| `arch_task_trees` | 任务树 | `root` TaskNode JSON 整树存储；revision 乐观锁；history 缩略快照（上限 20） |
| `arch_execution_tasks` | 执行任务 | adapter/model；session_ids/test_ids/amendments/stats JSON；分支管理 task_branch+branch_mode(auto)；run_count/tree_revision |
| `arch_agent_sessions` / `arch_agent_messages` | 执行会话与消息 | messages idx(session_id)；tool 列存 AgentToolCall JSON |
| `arch_unit_tests` / `arch_unit_test_sessions` / `arch_unit_test_messages` | 单测资产与会话 | levels JSON(TestLevel[])；channel(agent/cli)；asset_refs 关联语义资产 |
| `arch_conversations` / `arch_conversation_messages` | 通用对话流 | kind(requirement/design/execution/unit-test/generic)；meta 存意图/rejected 等 |
| `arch_blueprints` / `arch_kb_snapshots` / `arch_tags` / `arch_staging_scans` / `arch_snapshot_records` | 蓝图 / KB 快照 / 标签 / 暂存扫描 / 架构快照记录 | 辅助实体表 |
| `arch_semantic_assets` | 语义资产（核心表） | `kind` 六类(entity/contract/state/rule/process/decision) × `level` 三粒度(implementation/logic/business)；作用域锚定 scope_type(files/symbols/comm)+scope_key+scope_comm_id；增量判定 src_hash+anchor_hashes({relFile:md5})；canonical_key 稳定标识 + renamed_from/name_alias 溯源；软删 deleted_at；H 级聚合 parent_id；idx(project_id, kind)/(project_id, canonical_key)/(project_id, status) |
| `arch_semantic_refs` | 资产引用登记 | PK(asset_id, ref_type, ref_id)；role(core/related)；反向索引 ref_type+ref_id |
| `arch_ast_cache` | 文件级 AST 解析缓存 | PK(project_id, file_path)；symbols/imports/refs/statements/routes/constants JSON 列族 |
| `arch_extract_tasks` | 语义提取任务 | comp_ids/progress/messages JSON；status(running/done/partial/failed) |

---

## 6. 设计约定与注意事项

### 6.1 ID 生成

Architect 采用**前缀单调序列**而非 UUID：`next_id(prefix)` → `"{prefix}-{n}"`，序列存 `arch_id_seqs` 表，`bump_seq(prefix, min_seq)` 用于与种子数据 id 对齐防碰撞。KB 侧 id 由应用层生成（uuid 等），DB 不设 AUTOINCREMENT 主键（少数日志类表除外，如 `graph_doc`、`llm_call_logs` 用 `INTEGER PRIMARY KEY AUTOINCREMENT`）。

### 6.2 命名与形状转换（Architect store 层契约）

- DB 列名 snake_case，API/前端契约 camelCase：`_row_to_api` / `_data_to_db` 自动双向转换
- JSON 列（`_JSON_COLUMNS` 白名单约 35 列）读取自动 `loads`、写入自动 `dumps`，业务层感知不到序列化
- Router 保持 thin，所有 SQL 收敛在 store.py 的通用 CRUD（`_insert/_update/_delete/_all/_get`）与分域 Store 类（ProjectsStore、RequirementsStore…）

### 6.3 时间戳风格差异（历史包袱）

| 体系 | 类型 | 默认值 |
|---|---|---|
| KB 全部库 | TEXT | `datetime('now')` |
| Architect 全部表 | INTEGER | `0`（epoch 毫秒，应用层填充） |

跨子系统做时间比较时注意单位与类型不同。

### 6.4 两处 `SQLiteContext` 变体

- `topoone/db/connection.py`：轻量懒加载版（messaging 等底层场景使用）
- `topoone/db/manager.py`：完整版（WAL→DELETE 回退、瞬时错误重连、WriteQueue 集成）——**业务代码（engine services、architect ctx）统一使用此版**

### 6.5 其他注意事项

- **事务边界**：WriteQueue 模式下单条写自提交；需要真事务时必须用 `execute_batch`（单事务批量），不要依赖 `commit()`
- **跨库查询**：项目表无定位时的 `scan` 模式是 O(库数) 遍历，项目多时列表接口应尽量携带项目上下文；`doc_project_map` 即为此优化而设
- **默认桶清理**：项目绑定后主库默认桶中的历史行不会被自动搬迁，行级 `_locate_db` 的跨库探测保证了旧数据仍可命中
- **LRU 上限**：`config.MAX_DB_CONNECTIONS=3` 为历史配置值，实际生效的是 `manager._project_db_max=100` + 300s 空闲剔除
- **Windows 兼容**：删库前强制 `wal_checkpoint(TRUNCATE)` + 切 DELETE 模式释放句柄，文件删除带重试
