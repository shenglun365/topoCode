# M07 进程治理（P2⑥）

> 阶段：P2 第 6 步 | 预估：1 d | 前置：M02–M06 | 后续：M08
> 状态：✅ 完成（2026-08-20）
>
> 实施说明：
> - 迁移：`supervisor.py`→`topoone/supervisor/supervisor.py`（逻辑不变）；`main_cli.py`→`topoone/supervisor/cli.py`（`topo` 入口，`__main__.py` 转发）；`tui/`→`topoone/supervisor/tui/`；`plugin_manager.py`→`topoone/plugins/manager.py`（`_plugins_root()` 改指向 `topoone/plugins` 自身）；`tests/{test_main_cli,test_tui,test_symbol_graph}.py`→`packages/core/tests/`。
> - import 改写：cli 内 `from supervisor import`/`from tui import` → `topoone.supervisor.*`；`engine/app.py` 的 `plugin_manager`/`supervisor` import + `_run_distributed` 的 `-m db_service`→`-m topoone.engine.db_service`、`-m agent_worker`→`-m topoone.agent`（风险#4）。
> - **进程注册表 manifest 驱动**：`_FIXED_SERVICES`（kb/gateway/llm/agent + 生态 mcp/runner）+ `_manifest_apps()`（kind=service app 动态）；`_all_service_names()`/`_service_port()`/`_health_url()` 统一两源；`_make_manifest_cmd()` 由 manifest 的 python_entry+port 生成命令，architect 的 kb/mcp URL 经 env（`KB_BASE_URL`/`MCP_BASE_URL`）注入。改 docs manifest port → `topo status`/注册表随之改变（验收#2 手工验证）。
> - `plugins/installer`→`topoone/plugins/installer`（cli installer_path 同步）；插件发现日志含 community/parsers/llm-provider-*/installer（6 插件）。
> - `scripts/serve.sh` + `cleanup-stack.sh` 切 `python -m topoone.supervisor.cli`；`backend-core/` 仅剩 doc/chat service app（M11/M12）+ Bn/main.db/requirements（M14）。
> - 验收：G1 import + CLI --help 绿；G2 RPC 204 一致；G3 pytest 107/107（含迁入 12 测试）；G6 `topo serve` 9 进程全 ready + kill docs 自动重启（PID 变化 + health 200）；G7 现状 URL 布局全 200；`topo status/doctor` 全过。

## 1. 改造目标

把进程治理组件（supervisor / `topo` CLI / TUI / 本地插件发现机制）迁入 `packages/core/topoone/`，并让 **`topo serve` 的进程注册表改为 manifest 驱动**：核心固定进程（kb/gateway/llm/agent）+ 各 app manifest 中 `kind=service` 的进程（docs/chat/architect）+ 生态进程（mcp/runner），实现"拓扑唯一 owner"在新目录结构下延续。

## 2. 功能边界

**包含（In）**
- `supervisor.py`：子进程 spawn/心跳/HTTP 探针/崩溃重启/backoff（逻辑不变）
- `main_cli.py`（814 行）：`topo` CLI —— serve/status/doctor/import/analyze/tasks/export/verify/settings/community/arch/tui
- `tui/`：Textual TUI（服务状态/任务/日志三标签）
- `plugin_manager.py`：本地插件发现/加载/依赖安装（.deps 机制，插件根目录 → `topoone/plugins`）
- 进程注册表：`_SERVICE_DEFS` 硬编码 9 进程 → **固定核心 5 进程（kb/gateway/llm/agent/mcp 或并入固定表）+ manifest 动态加载**

**不包含（Out）**
- mcp/runner 的代码本体（M08）；任何业务逻辑

**依赖方向**：supervisor/CLI/TUI → 内核 + manifest 加载器；被 `scripts/serve.sh` 调用（`python -m topoone.supervisor.cli serve`）。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 | 说明 |
|---|---|---|
| `backend-core/supervisor.py` | `packages/core/topoone/supervisor/supervisor.py` | 逻辑不变 |
| `backend-core/main_cli.py` | `packages/core/topoone/supervisor/cli.py` | `topo` 入口 = `python -m topoone.supervisor.cli`（`__main__.py` 转发） |
| `backend-core/tui/{__init__,__main__}.py` | `topoone/supervisor/tui/` | |
| `backend-core/plugin_manager.py` | `packages/core/topoone/plugins/manager.py` | `discover()` 默认插件根 → `topoone/plugins` |
| `backend-core/tests/{test_main_cli,test_tui}.py` | `packages/core/tests/` | |

**`_SERVICE_DEFS` 改造**（cli.py 内）：
- 固定表保留：`kb`（`-m topoone.engine`）、`gateway`（`-m topoone.gateway`）、`llm`（`-m topoone.llm`）、`agent`（`-m topoone.agent`）
- `docs` / `chat` / `architect` / `mcp` / `runner` → 由 manifest 生成（`kind=service` 的 app + 生态 manifest；mcp/runner 在 M08 提供内置 manifest 条目，物理上属 core）
- 每个 manifest app 生成 `WorkerInfo`：args=[python, -m, entry_module]（或 entry 脚本）+ env + health_url（`http://127.0.0.1:<port><health>`）

## 4. 执行任务

### 任务 7.1 文件迁移
- `git mv` §3 文件；建 `topoone/supervisor/`（含 `__main__.py`：`from topoone.supervisor.cli import main; main()`）
- 更新内部 import（`supervisor` ← cli；`tui` 引用；`main.py`/`engine/__main__.py` 的 distributed 模式引用改 `topoone.supervisor`）
- **验证**：G1；`python -m topoone.supervisor.cli --help` 输出正常

### 任务 7.2 manifest 驱动的进程注册
- cli.py `serve` 路径：`discover_apps()` → 为 `kind=service` app 注册 supervisor 进程（args/env/health 由 manifest 生成）
- 固定核心 4 进程 + mcp/runner（M08 manifest 或固定表）
- `topo status` 输出扩展 manifest app 状态（label 含 app 名）
- **验证**：`bash scripts/serve.sh foreground` 9 进程健康（G6）；kill 1 个 manifest app 进程 → 自动重启（重启限制内）

### 任务 7.3 脚本与入口切换
- `scripts/serve.sh`：`cd "$BACKEND_DIR"` + `python main_cli.py` → `python -m topoone.supervisor.cli`（PYTHON 选择逻辑保留）
- `plugin_manager` 插件根切换后回归：核心进程启动发现 `community/parsers/llm-provider-*`（installer 在 M08 前仍属旧目录？——installer 目录本步随 plugin_manager 迁入 `topoone/plugins/installer`，见 7.4）
- **验证**：`topo serve` + `topo status` + `topo doctor` 全过；5 SPA 冒烟（G7）

### 任务 7.4 本地插件目录收尾
- `git mv plugins/installer → packages/core/topoone/plugins/installer`
- `plugins/` 目录此时仅剩 `architect`（M13）、`mcp_server`/`coding_agent_runner`（M08）、`chat_service`/`arch_kernel`（仅 pycache，M14 清理）
- 更新 `engine/__main__.py` 的 `PluginManager()` 调用（默认根已随 manager 迁移生效，验证日志 `Discovered plugins: [...]` 含 community/parsers/llm-provider-*/installer）
- **验证**：G2+G3+G6 全过

## 5. 验收标准

1. `python -m topoone.supervisor.cli serve/status/doctor/tui` 全部可用
2. 进程注册表 manifest 驱动：`apps/docs/manifest.toml` 的 port 改变 → `topo status` 显示新端口（单测/手工各 1 次）
3. G2/G3/G6 全过；崩溃重启行为与迁移前一致（kill 1 进程验证）
4. `backend-core/` 仅剩 M08 的 mcp/runner 引用与 M14 清理项（`Bn`、`main.db`、空目录）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| CLI 814 行含大量 DB 直读逻辑（community/arch 离线查询） | 纯 import 路径更新，逻辑零改动；`topo community/arch` 离线查询各抽查 1 次 |
| TUI 在伪终端的回归 | 沿用 P6 验收方式（伪终端启动 + 标题/三标签/Footer 断言，test_tui.py 迁移后覆盖） |
| serve.sh 被 systemd/Docker 模板引用 | grep 全仓 `main_cli` 引用（含 .github/、release/、docs/），同步更新 |
| distributed 模式（TOPO_MODE=distributed）引用 db_service/agent_worker 模块名 | `python -m db_service` → `python -m topoone.engine.db_service`（M03 已迁），agent_worker 已并入 agent 服务（确认 _run_distributed 注册列表更新） |
