# M08 生态组件（P2⑦）

> 阶段：P2 第 7 步 | 预估：0.5 d | 前置：M07 | 后续：M09（可并行）、M10–M13
> 状态：✅ 完成（2026-08-20）
> 本模块为 P2 收尾，完成 `packages/core` 全量成包。
>
> 实施说明：
> - **T8.1 迁移**：`plugins/mcp_server/server.py`→`topoone/plugins/mcp/server.py`、`plugins/coding_agent_runner/server.py`→`topoone/plugins/runner/server.py`（git mv）；补 `__init__.py` + `__main__.py`（转发 `server.main`）；删 backend-core sys.path hack（topoone 已 editable 安装，`from topoone.http_logging import` 直接可用）。
> - **T8.2 注册**：cli.py `_FIXED_SERVICES` 移除 mcp/runner 的 `script` 键，`_make_cmd` 改 `-m topoone.plugins.{mcp,runner}`（与 kb/llm/agent/gateway 一致）；engine/app.py 两处 mcp 引用（monolith standalone spawn + `_run_distributed` 注册）同步为 `-m topoone.plugins.mcp`。删 `plugins/{mcp_server,coding_agent_runner}/`。
> - **插件发现无冲突**：manager 仅扫含 `plugin.json` 的目录，mcp/runner（无 plugin.json）被跳过，不污染插件列表。
> - **T8.3 收尾**：
>   - `backend-core/` 盘点：P2 业务代码（mcp/runner）已清空；残留 `doc_service_app.py`/`chat_service_app.py`（**M11/M12**，manifest 注释「M11/M12 后改 `topoone_app_*:main`」）、`pytest.ini`/`requirements*.txt`/`Bn`/`main.db`（M14 清理）。architect 在 `plugins/`（**M13**）。
>   - pyproject 依赖收敛：与 `requirements.txt` diff，运行时依赖全齐（`pytest` 在 `[optional-dependencies].test`，`httpx`/`websockets` 为 M06 新增）；**fresh venv `pip install -e packages/core` 全量安装成功**（69 包；topoone + fastapi/zmq/networkx/duckdb/tree_sitter/uvicorn/httpx/websockets/textual 等 + M08 迁移的 mcp/runner + 全进程入口均可导入；P2 出口硬要求达成。注：首次因 `files.pythonhosted.org` read timeout 中断，`--timeout 120 --retries 5` 重试成功）。
>   - 全量回归：G2 204 / G3 107 / G6 9 进程（mcp/runner 进程命令确为 `-m topoone.plugins.*`）/ G8 ws/events（token 鉴权 + 心跳流）/ doctor 新路径 / E2E（`project.import`→`createTask`→`runTask`→done，`getResults` 含 ast_data/call_chain/dependencies/dataflow/summary）。
> - **验收对照**：#3（G2/G3/G6/G8 + E2E）✓；#4（doctor 新路径）✓；#1「7 入口来自 core/apps」与 #2「backend-core 无业务 .py」为**前瞻门禁**——app 服务（docs/chat/architect）按 manifest 过渡态在 M11/M12/M13 迁入 apps/ 后满足；当前 6 核心进程（kb/gateway/llm/agent/mcp/runner）入口均来自 `packages/core`。

## 1. 改造目标

把两个生态组件（MCP Server :3460、Coding Agent Runner :3458）迁入 `packages/core/topoone/plugins/`，作为 core 内置服务由 supervisor 纳管；至此 `backend-core/` 业务代码清空（仅余 M14 清理项）。

## 2. 功能边界

**包含（In）**
- `mcp_server`：外部 agent/工具访问 KB/agent/llm 能力的 MCP 通道（stdio/HTTP）
- `coding_agent_runner`：第三方 coding agent（opencode/codex/claude-code 等）子进程管理
- 两者的 supervisor 注册（manifest 或固定表条目）

**不包含（Out）**
- MCP 协议扩展（加挂 llm/agent 面属后续功能需求，不在本次拆分范围）
- installer 插件（已随 M07 迁入 `topoone/plugins/installer`）

**依赖方向**：mcp → 内核 + engine 数据（读 project.db）+ llm/agent 服务（HTTP）；runner → 内核（进程管理）；被 supervisor 拉起，被 mcp 反向调用（agent 面）。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 | 说明 |
|---|---|---|
| `plugins/mcp_server/server.py`（98 行） | `packages/core/topoone/plugins/mcp/server.py` | 进程入口 `python -m topoone.plugins.mcp`（补 `__main__.py`） |
| `plugins/coding_agent_runner/server.py`（69 行） | `packages/core/topoone/plugins/runner/server.py` | 进程入口 `python -m topoone.plugins.runner`（补 `__main__.py`） |
| `plugins/{mcp_server,coding_agent_runner}/` 目录 | **删除**（迁移后） | |

**supervisor 注册**：mcp/runner 属 core 内置服务，采用固定表条目（非 app manifest），script 更新为 `-m topoone.plugins.mcp` / `-m topoone.plugins.runner`。

## 4. 执行任务

### 任务 8.1 迁移
- `git mv` 两个 server.py；建 `topoone/plugins/{mcp,runner}/` 包（`__init__.py` + `__main__.py`）
- 更新内部 import（DB 访问 → `topoone.db`；agent/llm 调用保持 HTTP）
- **验证**：G1；两进程手动启动 `GET /health` 200

### 任务 8.2 注册与回归
- cli.py 固定表 script 路径更新
- `topo serve` 9 进程健康（G6）；mcp 通道冒烟（1 次 tools/list 或 tools/call）；runner 冒烟（`GET /health` + 状态查询，不真实拉起 coding agent）
- **验证**：G2+G3+G6 全过

### 任务 8.3 P2 收尾确认
- `backend-core/` 内容盘点：应仅剩 `Bn`、`main.db`、`requirements*.txt`（pyproject 已吸收，待 M14 删）、`__pycache__`、空目录
- `packages/core/pyproject.toml` 依赖收敛检查：与 `backend-core/requirements.txt` diff，补齐遗漏（fastapi/uvicorn/httpx/websockets/textual/tree-sitter*/networkx/python-louvain/leidenalg/igraph/duckdb 等）
- 全量回归：`topo serve` + 8 项中 G2/G3/G6/G8 四项 + 一次端到端任务（导入→解析→社区→LLM 摘要，经 `/api/rpc/analysis.runTask`）
- **验证**：P2 出口门禁全过后提交，README §7 更新 M02–M08 状态为 ✅

## 5. 验收标准

1. `topo serve` 9 进程全健康，其中 7 个（kb/gateway/llm/agent/mcp/runner + 3 app 服务之一以上）入口均来自 `packages/core` 或 apps
2. `backend-core/` 无业务 .py 文件残留
3. G2/G3/G6/G8 全过 + 端到端任务成功
4. `topo doctor` 输出新路径诊断正确

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| mcp server 被外部 agent 以固定路径/命令配置（用户环境） | MCP 接入方式若暴露命令路径（如 `python plugins/mcp_server/server.py`），在 README（M14）更新新命令；stdio 模式由客户端配置，属用户侧变更，需 changelog 说明 |
| runner 拉起的外部 agent 工作目录假设 | runner 逻辑零改动，仅入口迁移；冒烟验证 |
| pyproject 依赖遗漏导致新环境安装失败 | 任务 8.3 用**全新 venv** 安装 `pip install -e packages/core` 冒烟一次（P2 出口硬要求） |
