# M02 共享内核（P2①）

> 阶段：P2 第 1 步 | 预估：1–2 d | 前置：M01 | 后续：M03–M08 全部
> 状态：✅ 完成（2026-08-20）

## 0. 完成记录与计划偏差（2026-08-20）

**验收结果**：`topoone.{db,rpc,messaging,config,logging_config,http_logging}` 全部可导入且零产品逻辑
import（仅日志文件名/注释提及）；G2 RPC 基线 204 方法一致；`pytest packages/core/tests backend-core/tests`
95/95 绿；`topo serve` 9 进程 /health 全 200 + 聚合 `/api/health` 200；backend-core 旧路径文件全部移除。

**与 §3 的偏差/补充**：
- `store/__init__.py` 半迁移：内核导出（SQLiteContext）移入 `topoone/db/__init__.py`，本文件仅保留
  TaskStore/AnalysisStore（M03 迁入 engine/store/ 后删除）；`store/{task,analysis}_store.py` 的
  `from .connection import` 同步改为 `from topoone.db.connection import`。
- 新建 `topoone/db/__init__.py`（导出 SQLiteContext/MultiDBManager/WriteResult）与 `topoone/rpc/__init__.py`。
- 两个 SQLiteContext 并存属预期：`db/manager.py`（原 sqlite_ctx.py，2148 行全功能）与
  `db/connection.py`（原 store/connection.py，轻量版，供 engine store 使用）。
- `plugins/reports/chat.py` 的 `import config` → `from topoone import config`（顺带去除重复 `import common`）。
- 测试路径修正：迁入 `packages/core/tests/` 的 test_db_layout/test_service_app 的 sys.path 指向改为
  `<repo>/backend-core`；test_imports 改为断言 `topoone.*` 内核模块。

**顺带修复的存量测试债**（非 M02 引入）：
- `test_db_layout.py::TestReassociation`：`project.import` 已在早前会话改为后台任务
  （返回 `{requestId}` + `project.importStatus` 轮询），测试仍按同步返回项目行的旧契约 → 适配新契约
  （轮询 importStatus + `project.get` 取行 + 合并 `reassociated` 标志）。
- `test_agentic_workflow.py::test_max_turn_timeout_default`：断言 180 vs 实际默认 900（早前会话调整）→ 更新为 900。

## 1. 改造目标

把平台级共享内核（数据库层 / RPC 框架 / 消息总线 / 基础设施）从 `backend-core/` 迁入 `packages/core/topoone/`，成为**零产品逻辑**的底层包：不 import 任何 engine/llm/agent 代码，被所有上层模块依赖。

## 2. 功能边界

**包含（In）**
- DB 层：`MultiDBManager` / `SQLiteContext` / data_layer（cache/duckdb/write_queue）/ state_store
- RPC 框架：`ZMQServer`（方法注册表+PUB）/ `rpc_ids` / `service_app`（MethodServer 轻量脚手架）/ `data_api`（`/zmq/{method}` HTTP 壳）
- 消息总线：`messaging/`（bus/transport/schema/remote/worker_signal）
- 基础设施：`config.py`（TOPO_MODE 等）/ `logging_config.py` / `http_logging.py`
- 对应测试迁移

**不包含（Out）**
- 任何业务方法注册（project.*/analysis.*/llm.* 等 → M03/M04）
- 进程入口（main.py → M03）；supervisor/CLI（→ M07）
- `store/analysis_store.py`、`store/task_store.py`（属引擎数据模型 → M03）
- `config/prompt_templates.json`（prompt 模板 → M04 llm）

**依赖方向**：内核 ←（engine / llm / agent / gateway / apps 全部依赖内核）。内核内禁止向上 import（CI 可用 import-linter 或 grep 断言）。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 | 说明 |
|---|---|---|
| `backend-core/sqlite_ctx.py` | `packages/core/topoone/db/manager.py` | MultiDBManager + SQLiteContext（2148 行，原样迁移） |
| `backend-core/store/connection.py` | `packages/core/topoone/db/connection.py` | |
| `backend-core/store/__init__.py` | `packages/core/topoone/db/__init__.py` | 内容并入（analysis_store/task_store 的导出移到 M03） |
| `backend-core/data_layer/{__init__,cache_store,duckdb_reader,write_queue}.py` | `packages/core/topoone/db/data_layer/`（同名） | |
| `backend-core/state_store.py` | `packages/core/topoone/db/state_store.py` | |
| `backend-core/zmq_server.py` | `packages/core/topoone/rpc/zmq_server.py` | |
| `backend-core/rpc_ids.py` | `packages/core/topoone/rpc/rpc_ids.py` | |
| `backend-core/service_app.py` | `packages/core/topoone/rpc/service_app.py` | MethodServer + create_service_app + run_service（docs/chat 服务的进程脚手架） |
| `backend-core/data_api.py` | `packages/core/topoone/rpc/data_api.py` | kb API（:3459）的 FastAPI 壳 |
| `backend-core/messaging/{__init__,bus,transport,schema,remote,worker_signal}.py` | `packages/core/topoone/messaging/`（同名） | |
| `backend-core/config.py` | `packages/core/topoone/config.py` | |
| `backend-core/logging_config.py` | `packages/core/topoone/logging_config.py` | |
| `backend-core/http_logging.py` | `packages/core/topoone/http_logging.py` | |
| `backend-core/tests/{test_sqlite_ctx,test_rpc_ids,test_service_app,test_db_layout,test_config,test_imports}.py` | `packages/core/tests/`（同名） | test_imports.py 的导入断言同步更新 |

**import 改写规则**（全仓 sed + 人工确认）：

| 旧 import | 新 import |
|---|---|
| `from sqlite_ctx import ...` / `import sqlite_ctx` | `from topoone.db.manager import ...` |
| `from store.connection import ...` | `from topoone.db.connection import ...` |
| `from data_layer import ...` / `from data_layer.xxx import ...` | `from topoone.db.data_layer...` |
| `import state_store` / `from state_store import ...` | `from topoone.db.state_store import ...` |
| `from zmq_server import ...` | `from topoone.rpc.zmq_server import ...` |
| `import rpc_ids` / `from rpc_ids import ...` | `from topoone.rpc.rpc_ids import ...` |
| `from service_app import ...` | `from topoone.rpc.service_app import ...` |
| `from data_api import ...` | `from topoone.rpc.data_api import ...` |
| `from messaging.xxx import ...` | `from topoone.messaging.xxx import ...` |
| `from config import ...`（注意与 `agent_workflow/...` 无冲突） | `from topoone.config import ...` |
| `from logging_config import ...` / `from http_logging import ...` | `from topoone.logging_config import ...` / `from topoone.http_logging import ...` |

**受影响但暂不移动的文件**（本步只改 import，位置不动）：`main.py`、`core_service.py`、`llm_service*.py`、`agent_workflow/**`、`plugins/reports/*.py`、`plugins/architect/**`、`main_cli.py`、`supervisor.py`、各 `*_service_app.py`、`db_service.py` 等。

## 4. 执行任务

### 任务 2.1 目录与包结构
- 建 `packages/core/topoone/{db,db/data_layer,rpc,messaging}/` 与 `__init__.py`
- **验证**：`pip install -e packages/core` 成功（G1）

### 任务 2.2 文件迁移
- `git mv` 上表 22 个文件到目标路径；`store/__init__.py` 内容拆分：内核导出入 `db/__init__.py`，analysis/task store 导出留待 M03 写入 `engine/store/__init__.py`（本步 `store/` 目录保留给 M03 的两个文件）
- **验证**：无（随任务 2.3 一起验）

### 任务 2.3 import 批量改写
- 按 §3 规则全仓替换（`grep -rln` 先列受影响文件清单存档）；逐文件确认无 `config` 误伤（如 `os.path.config`、fastapi 内部 config 等）
- **验证**：`python -c "import topoone.db, topoone.rpc, topoone.messaging"` 无 ImportError；`python scripts/check-rpc-parity.py` 通过（方法集不变，G2）

### 任务 2.4 测试迁移与回归
- `git mv` 6 个测试文件；更新测试内 import 与路径断言（test_db_layout 涉及数据目录布局，确认路径无关性）
- 全量回归：`python -m pytest packages/core/tests backend-core/tests -v`（旧 tests 目录剩余文件此步仍须全绿）
- `bash scripts/serve.sh foreground` 拉起 9 进程 + `GET /api/health` 200（G6）
- **验证**：G1+G2+G3+G6 全过

## 5. 验收标准

1. `topoone.{db,rpc,messaging}` 可导入且无产品逻辑依赖（grep 断言：`topoone/db|rpc|messaging` 内不出现 `core_service|llm_service|agent_workflow|community_data` 等符号）
2. G2 RPC 方法集与基线完全一致
3. 9 进程健康、pytest 全绿
4. `backend-core/` 中不再存在 `sqlite_ctx.py`、`zmq_server.py`、`messaging/` 等已迁文件

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| `config.py` 名称过泛，sed 误伤 | 替换用完整 `from config import` / `import config` 模式 + 逐文件 diff 复核 |
| 各 `*_service_app.py` 的 `sys.path.insert` 引导逻辑 | 保留原逻辑（editable 安装后 `topoone` 全局可见，sys.path 引导仅为兼容旧兄弟模块，M03–M08 逐步删除） |
| `data_api.py` 中 `set_globals(multi_db, server)` 被 gateway 侧（reports）引用 | reports/common.py 的 import 在本步同步改写（文件位置不动） |
| 旧 `store/` 目录半迁移状态 | `store/__init__.py` 先迁内核部分并留注释，M03 收尾时删除 `backend-core/store/` |
