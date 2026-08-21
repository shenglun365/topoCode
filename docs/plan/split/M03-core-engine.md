# M03 核心引擎（P2②）

> 阶段：P2 第 2 步 | 预估：3–4 d | 前置：M02 | 后续：M04–M08
> 状态：✅ 完成（2026-08-20）

## 0. 完成记录与计划偏差（2026-08-20）

**验收结果**：
- G1：`topoone.engine.*` 全部模块（19 引擎模块 + ingest + store + service 10 模块）可导入。
- G2：RPC 基线 204 方法一致（`check-rpc-parity.py` OK；serve 运行中需 `ZMQ_DEALER_PORT/ZMQ_PUB_PORT` 覆盖）。
- G3：`pytest packages/core/tests backend-core/tests` 95/95；`plugins/architect/tests` 145/145；前端 vitest 32/32。
- G6：`topo serve` 9 进程 /health 全 200；kb 以 `python3 -m topoone.engine` 运行，注册 204 core methods，
  插件从 `topoone/plugins` 新路径发现（Community Analysis + Parsers）。
- E2E（验收 #4）：demo 项目 `project.import`（后台任务 done 100%）→ `analysis.runTask`（done 100%，
  8 节点/4 边）→ `community`（ready:true）→ `render.testPlantuml` 路由正常，全链路跑通。
- `backend-core/` 剩余：llm 系（M04）、agent 系 + `context/`（M05）、main_cli/supervisor/plugin_manager（M07）、
  `config/prompt_templates.json`（M04）、`Bn`/`main.db`（M14）。

**与 §3 的偏差/补充**：
- core_service.py 解构落地布局：`_common.py` = 1–312 行共享区（GitIgnoreParser/MultiIgnoreParser/
  导入配置/`_IMPORT_JOBS`）+ `_simple_hash`；`project.py` 额外收编了**物理位于文件后段但逻辑属 project** 的
  后台导入实现（`_import_project_impl/_scan_and_import/_scan_file_tree/_compute_file_hash`）与文件树构建
  （`_build_flat_children/_build_file_tree/_is_empty_dir/_count_empty_chain/_flatten_tree`）；`report.py`
  收编 `_parse_dependency_file/_parse_toml_deps/_do_generate_project_summary`。`_export_graph_data`
  （全仓零调用的死代码）按"纯移动不删除"原则保留在 project.py。
- `plantuml_service.py`、`report_tree_service.py` **提前迁入 `engine/`**（原计划留 backend-core）：
  二者是 engine+plugins 共用依赖，收敛后 5 处使用者改 `topoone.engine.*`，避免跨层 import。
- `main.py` 拆为 **`engine/app.py`（BackendApp/main 主体）+ `engine/__main__.py`（4 行入口）**：
  app.py 可被 `scripts/rpc_common.py` 直接 import（`from topoone.engine.app import BackendApp`）；
  `python -m topoone.engine` 仍为进程入口。app.py 顶部 sys.path 自举 backend-core
  （过渡期 llm_service/plugin_manager/supervisor/agent_workflow 仍居 backend-core，已标 TODO(M04/M05/M07)）。
- `plugins/{parsers,community}` **提前迁入 `topoone/plugins/`**（原计划 M07 随插件系统整体迁移）：
  kb 入口经 `discover(plugins_dir=<topoone>/plugins)` 显式传新路径；`plugin_manager.py::_plugins_root()`
  的旧路径 fallback 未动（M07 统一处理）。
- `main_cli.py`：kb spawn 改 `[sys.executable, "-m", "topoone.engine", ...]`；`_cmd_doctor` 的
  `--no-spawn` 核查路径改 `engine/app.py`。
- `scripts/rpc_common.py`：`from main import BackendApp` → `from topoone.engine.app import BackendApp`。
- `logging_config.py` LOG_CATEGORIES：旧模块名前缀（core_service/task_manager/sqlite_ctx…）→
  新点号前缀（topoone.engine.*/topoone.db.*/topoone.rpc.*）；`parsers` 类别前移，保证
  `topoone.engine.analyst_runner` 日志仍路由 parsers.log。
- 测试：`test_parse_file_ast.py`、`test_stack_graphs_service.py` 迁入 `packages/core/tests/`
  （后者 mock patch 目标改 `topoone.engine.stack_graphs_service.*`）；`test_imports.py`/`test_db_layout.py`
  改引 `topoone.engine.service`；`plugins/architect/tests/test_asset_pipeline.py` 的 parsers sys.path
  改新位置。
- `backend-core/store/` 目录删除（两个 store 已迁 `engine/store/`，新建 `engine/store/__init__.py` 导出）。
- 已知存量问题（**非 M03 引入**）：`pytest packages/core/tests plugins/architect/tests` 同命令收集时
  报 "No module named 'tests.*'"——两处 tests/ 均带 `__init__.py` 的包名冲突；分开跑全绿。

**执行中事故（已当场修复）**：批量 import 改写脚本中一个 sed 表达式误剥了 core_service.py 内 3 处
`import import_service` 的行首缩进（IndentationError）→ 恢复缩进后语法/全量回归确认无残留。

## 1. 改造目标

把核心引擎（项目导入 / AST 解析 / 符号图 / 社区检测 / 任务管理 / 版本 / 导出校验）+ kb 进程入口迁入 `packages/core/topoone/engine/`，并把 `core_service.py` 这个 3952 行方法注册中枢按 **RPC 命名空间解构**为独立模块（为 M10/M11 切出子项目薄层做准备）。引擎保持**零 LLM/Agent 直接 import**（需要 LLM 的路径经 llm 服务 HTTP 通道，现状已满足）。

## 2. 功能边界

**包含（In）**
- kb 进程入口（`main.py` → `engine/__main__.py`）：ZMQ + data_api(:3459) + ingest + 插件发现 + 方法注册
- 引擎能力：import / git / ast / ingest / symbol_graph / stack_graphs / community / task / analyst / incremental / analysis_context / version / export / verify / architecture_model / db_service（分布式 DB worker）
- 数据模型存储：`store/analysis_store.py`、`store/task_store.py`
- 本地插件发现机制之外的引擎侧模块管理：`module_manager.py`（资源中心模块注册表/下载，`module.*` 命名空间）
- 引擎插件：`plugins/parsers`（tree-sitter 18+ 语言）、`plugins/community`（Louvain）
- core_service.py 按命名空间解构（本步**全部仍由引擎进程注册**，行为零变化）

**不包含（Out）**
- llm.* / session.* 方法（M04）、agent.*/skill.*/tool.*（M05）、gateway（M06）、supervisor/CLI/TUI（M07）、mcp/runner（M08）
- knowledge.* / render.* / report.* 的**归属**（本步只是物理拆文件到 `engine/service/{knowledge,render,report}.py`，逻辑与注册方不变；M10/M11 才移入 apps 并改由 manifest 注册）

**依赖方向**：engine → 内核（db/rpc/messaging）+ plugins；禁止 import llm/agent 包（现状 core 仅 HTTP 调用 llm 服务）。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 | 说明 |
|---|---|---|
| `backend-core/main.py` | `packages/core/topoone/engine/__main__.py` | kb 进程入口；`python -m topoone.engine` 等价原 `python main.py` |
| `backend-core/core_service.py` | `packages/core/topoone/engine/service/`（解构，见 §3.1） | 3952 行 → 10 个命名空间模块 |
| `backend-core/import_service.py` | `topoone/engine/import_service.py` | |
| `backend-core/git_service.py` | `topoone/engine/git_service.py` | |
| `backend-core/ast_worker.py` | `topoone/engine/ast_worker.py` | |
| `backend-core/ingest/{__init__,consumer,writer}.py` | `topoone/engine/ingest/` | |
| `backend-core/symbol_graph.py` | `topoone/engine/symbol_graph.py` | |
| `backend-core/stack_graphs_service.py` | `topoone/engine/stack_graphs_service.py` | |
| `backend-core/community_data.py` | `topoone/engine/community_data.py` | |
| `backend-core/task_manager.py` | `topoone/engine/task_manager.py` | 3919 行，原样迁移 |
| `backend-core/analyst_runner.py` | `topoone/engine/analyst_runner.py` | |
| `backend-core/incremental_runner.py` | `topoone/engine/incremental_runner.py` | |
| `backend-core/analysis_context.py` | `topoone/engine/analysis_context.py` | |
| `backend-core/analysis_utils.py` | `topoone/engine/analysis_utils.py` | |
| `backend-core/version_sync_service.py` | `topoone/engine/version_sync_service.py` | |
| `backend-core/export_service.py` | `topoone/engine/export_service.py` | |
| `backend-core/verify_service.py` | `topoone/engine/verify_service.py` | |
| `backend-core/architecture_model_service.py` | `topoone/engine/architecture_model_service.py` | |
| `backend-core/db_service.py` | `topoone/engine/db_service.py` | 分布式模式 DB worker（`python -m topoone.engine.db_service`） |
| `backend-core/module_manager.py` | `topoone/engine/module_manager.py` | 资源中心模块管理（module.* 命名空间） |
| `backend-core/store/{analysis_store,task_store}.py` | `topoone/engine/store/` | 收尾删除 `backend-core/store/` |
| `plugins/parsers/`（整目录：plugin.json/plugin_entry.py/parsers//tests/） | `packages/core/topoone/plugins/parsers/` | 保留 plugin.json 机制 |
| `plugins/community/`（整目录） | `packages/core/topoone/plugins/community/` | |
| `backend-core/tests/{test_parse_file_ast,test_symbol_graph,test_stack_graphs_service}.py` | `packages/core/tests/` | |

### 3.1 core_service.py 解构表

| 注册函数 | 目标文件 | 最终归属 |
|---|---|---|
| `register_project_methods` | `engine/service/project.py` | 引擎（M03） |
| `register_dir_methods` | `engine/service/dir_service.py` | 引擎（M03） |
| `register_analysis_methods` | `engine/service/analysis.py` | 引擎（M03） |
| `register_settings_methods` | `engine/service/settings.py` | 引擎（M03） |
| `register_backend_methods` | `engine/service/backend.py` | 引擎（M03） |
| `register_module_methods` | `engine/service/module.py` | 引擎（M03） |
| `register_version_methods` | `engine/service/version.py` | 引擎（M03） |
| `register_knowledge_methods` | `engine/service/knowledge.py` | **M10 → apps/workbench/server** |
| `register_render_methods` | `engine/service/render.py` | **M11 → apps/docs/server** |
| `register_report_methods` | `engine/service/report.py` | **M11 → apps/docs/server** |

共享辅助函数（DB 查询助手、路径守卫等被多命名空间引用的部分）提取到 `engine/service/_common.py`。

`engine/service/__init__.py` 提供 `register_all_engine_methods(server, multi_db, plugin_manager)`：依次调用全部 10 个注册函数（M10/M11 后改为跳过已移交 apps 的命名空间，由 manifest 加载替代）。

## 4. 执行任务

### 任务 3.1 引擎文件迁移（不含 core_service）
- `git mv` §3 表中除 core_service 外的全部文件/目录；建 `topoone/engine/`、`topoone/engine/store/`、`topoone/plugins/`（含 `__init__.py`）
- 更新被迁文件的 import：内核符号用 `topoone.*`（M02 新路径），兄弟模块改 `topoone.engine.*` / `topoone.plugins.*`
- 更新**未移动文件**中对引擎符号的 import（llm_service/agent_workflow/plugins-reports/plugins-architect/main_cli 等，grep 清单存档）
- **验证**：G1 可导入；`python -m pytest packages/core/tests -v` 全绿

### 任务 3.2 core_service.py 解构
- 按 §3.1 拆分为 10 个模块 + `_common.py`；**纯函数移动，不改注册逻辑**；`engine/service/__init__.py` 聚合注册
- 机械校验：拆分前后 `register_all` 注册的方法名集合一致（本地脚本断言，先于 G2）
- **验证**：`python -c "from topoone.engine.service import register_all_engine_methods"` 成功；G2 RPC 基线 diff 为空

### 任务 3.3 入口迁移（main.py）
- `git mv main.py → topoone/engine/__main__.py`；import 全部改为 `topoone.*`
- `register_all` 内 agent_workflow skill 同步 import 暂保持兼容（M05 后改为 `topoone.agent.*`，留 TODO 标记）
- `_start_optional_services` 的三个 spawn 路径（reports/architect/mcp）标注 TODO，随 M06/M13/M08 迁移时更新（本步用 `no_spawn` 路径验证，`topo serve` 默认即 no_spawn）
- `backend-core/requirements.txt` 内容并入 `packages/core/pyproject.toml`（本步先全量拷贝，M14 收敛）
- **验证**：`pip install -e packages/core`；`bash scripts/serve.sh foreground` 9 进程健康（G6）；`python scripts/check-rpc-parity.py` 通过（G2）

### 任务 3.4 插件目录迁移
- `git mv plugins/parsers plugins/community → packages/core/topoone/plugins/`
- `PluginManager.discover` 的默认插件根目录改为 `topoone/plugins`（此文件本步不动，M07 迁移时改；本步通过 `discover(plugins_dir=...)` 参数传入新路径验证）
- 确认 tree-sitter `.deps` 机制在新路径下可用（`pip install --target topoone/plugins/parsers/.deps` 路径跟随插件目录，机制不变）
- **验证**：核心进程启动日志出现 `Discovered plugins: [community, parsers]`；`topo analyze` 全链路（导入→解析→社区）冒烟 1 次（G7 后端侧）

### 任务 3.5 测试与回归
- 迁移 3 个引擎测试；更新 `test_imports.py` 断言路径
- 全量：`python -m pytest packages/core/tests backend-core/tests -v` + G2 + G6
- **验证**：全绿后提交

## 5. 验收标准

1. G1：`from topoone.engine import import_service, task_manager, community_data`（等）无 ImportError
2. G2：RPC 方法集与基线完全一致（含 knowledge.*/render.*/report.*，仍由引擎注册）
3. G3：pytest 全绿
4. G6：9 进程健康；一次真实项目导入→解析→社区检测任务跑通
5. `backend-core/` 剩余文件仅为：llm 系（M04）、agent 系（M05）、supervisor/cli/tui（M07）、`Bn`/`main.db`（M14 清理）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| core_service 解构引入行为差异（最高风险） | 纯移动 + 方法集断言（§4 任务 3.2 机械校验）+ G2 基线 diff + 每命名空间抽查 RPC 调用（project.import / analysis.runTask / render.plantuml 各 1 次） |
| `_common.py` 抽取边界不清导致循环 import | 只提取无状态的查询/路径助手；有状态对象（multi_db 引用）保持函数参数传入 |
| main.py 中 distributed 模式引用 supervisor（M07 才迁） | 过渡期 `sys.path` 兼容 import；M07 完成后统一改 `topoone.supervisor` |
| 引擎插件 .deps 离线安装路径变化 | 机制跟随 `info.dir_path`，目录整体 `git mv` 后路径自动跟随；任务 3.4 显式验证 |
| `backend-core` 作为启动目录的脚本/文档引用（serve.sh、README） | serve.sh 的 `cd backend-core` 改为 `python -m topoone.engine`（本步同步改）；README 更新放 M14 |
