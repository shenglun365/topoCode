# M05 agent 服务（P2④）

> 阶段：P2 第 4 步 | 预估：1–2 d | 前置：M02–M04 | 后续：M06
> 状态：✅ 完成（2026-08-20）

## 0. 完成记录与计划偏差（2026-08-20）

**验收结果**：
- G1：`topoone.agent.{worker,tools_executor,agent_workflow.*}` 全部可导入；`topoone.agent` 包内
  0 处 `api_key`/`OPENAI_API_KEY`（验收 #4 ✓）。
- G2：RPC 基线 204 方法一致（agent.* 仍由独立进程注册，核心进程方法集不变）。
- G3：`pytest packages/core/tests backend-core/tests` 100/100（新增 test_agent_service.py 2 项：
  skill 注册表同步落库；mock LLM 通道下 `agent.dispatch(presummary_files)` 全链路跑通
  ——router→runtime→SummarizeFileTool→SubAgent→llm_adapter→LLMService→mock provider→
  FileSummaryCache，进度轮询至 completed）。
- G6：`topo serve` 9 进程 /health 全 200；agent 以 `python3 -m topoone.agent --data-dir … 
  --port 3482 --pub-port 5684` 运行。
- G8 抽查：网关 `agent.getConfig`（4 路由：overview/analyze_components/presummary_files/pipeline）
  与 `agent.listRunning` 均正常。
- `backend-core/` 不再含 `agent_workflow/`、`agent_worker.py`、`agent_service_app.py`、
  `tools_executor.py`（验收 #3 ✓）；`plugins/architect` 对 agent 无直接 import（grep 确认）。

**与 §3 的偏差/补充**：
- 子包名按 §6 保守方案**保留原名 `agent_workflow`**（`topoone/agent/agent_workflow/`），
  import 改写为 `topoone.agent.agent_workflow.*`，改动面最小。
- `agent_service_app.py` 原为**未纳入版本控制**的文件 → 普通 `mv` 迁入 `agent/__main__.py`。
- `agent/__main__.py` 无需 backend-core sys.path 自举（迁移后 agent 对 backend-core 零依赖，
  全部经 `topoone.*`）；`llm/__main__.py` 的过渡期自举（M04 为 tools_executor 保留）同步移除。
- `tools_executor.py` 迁入 `topoone/agent/` 后，`llm/service.py` 与 `llm/providers/openai_compat.py`
  的惰性 `from tools_executor import …` 改 `from topoone.agent.tools_executor import …`
  （llm→agent 方向，属工具定义复用，无凭据传递）。
- `main_cli.py`：agent spawn 改 `[sys.executable, "-m", "topoone.agent", …]`（独立分支）；
  `_SERVICES["agent"]["script"]` 置 None。
- `engine/app.py`：skill 同步 8 模块 import + `sync_skills_to_db` 改 `topoone.agent.agent_workflow.*`
  （import 顺序保持不变：先 skill 模块后 sync）；过渡期自举注释更新为仅剩 M07 依赖
  （plugin_manager/supervisor）。
- `engine/task_manager.py`（11 处惰性）与 `engine/service/report.py` 的 `agent_workflow.*`
  引用改 `topoone.agent.agent_workflow.*`——agent→engine 与 engine→agent 双向惰性 import
  为存量事实（文档理想边界"agent 不 import engine 业务模块"未达成，记录在案，M07/M08 收敛）。
- 测试：`test_agentic_workflow.py` 迁入 `packages/core/tests/`（import 已随全仓替换）；
  `packages/core/tests/test_service_app.py` 的 `from agent_service_app import` →
  `from topoone.agent.__main__ import`。

## 1. 改造目标

把 agent 服务（harness 引擎 :3482）全部代码迁入 `packages/core/topoone/agent/`：`agent_workflow/` 整体 + `agent_worker.py`（已并入本进程）+ `tools_executor.py`，形成 `python -m topoone.agent` 可启动的基础服务包。保持"唯一 harness + 唯一 skill/tool 注册表、不含 provider 凭据、LLM 交互经 llm 服务"的边界不变。

## 2. 功能边界

**包含（In）**
- Harness：`AgentRuntime`（顺序工作流 + agentic 循环：tool-call loop 检测 / rate-limit / cancel / pause / resume）
- 任务队列：`agent_queue.AgentTaskManager`（并发 1–10，状态持久化 jsonl，dispatch/progress/cancel/pause/resume）
- 子能力：`sub_agent` / `memory` / `sandbox` / `router`（RouterHarness）
- Skills：`skill_registry` + `skill_configs` 表同步（`@register_skill` 装饰器）
- Tools：`tools_executor`（KB 分析工具，读共享 project.db）+ `tool_factory` / `tools` / `tool_calling/` / `toolkits/`（file/symbol/graph/edge）
- 工作流：`workflows/`（overview / component_analyst / agentic_component_analyst / pipeline / pre_summary / base）
- 方法注册：`agent.*` / `skill.*` / `tool.*`（`agent_service_app.py` → `topoone/agent/__main__.py`）

**不包含（Out）**
- coding_agent_runner（M08，独立子进程）
- 任何 provider 凭据读取（依赖方向：agent → llm 服务 HTTP + SUB 5682）

**依赖方向**：agent → 内核 + llm 包（`llm_adapter` 经 llm 服务通道）+ engine 数据（读 project.db，经 MultiDBManager，不 import engine 业务模块）。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 |
|---|---|
| `backend-core/agent_workflow/`（整目录：runtime/agent_queue/router/jsonl_store/llm_adapter/memory/sandbox/sub_agent/skill_registry/tool_factory/tools/tool_calling//toolkits//workflows//file_summary_cache/path_utils/shared_utils/__init__） | `packages/core/topoone/agent/workflow/`（同构，包名 agent_workflow → workflow） |
| `backend-core/agent_worker.py` | `topoone/agent/worker.py` |
| `backend-core/agent_service_app.py` | `topoone/agent/__main__.py` |
| `backend-core/tools_executor.py` | `topoone/agent/tools_executor.py` |
| `backend-core/tests/test_agentic_workflow.py` | `packages/core/tests/` |

**import 改写**：
- `from agent_workflow import ...` / `from agent_workflow.xxx import ...` → `from topoone.agent.workflow...`（受影响方：`engine/__main__.py` 的 skill 同步 import 块、`main_cli.py`、`plugins/architect`（grep 确认，若 architect 直接 import 则改经 HTTP 或更新 import））
- 包内相对 import 随目录整体移动自动保持；`llm_adapter` 对 llm 服务的引用改 `topoone.llm.*`
- `engine/__main__.py` 中 `sync_skills_to_db` 的 8 个 skill 模块 import（overview/component_analyst/agentic_component_analyst/file_tools/symbol_tools/graph_tools/edge_tools）改为 `topoone.agent.workflow.*` 新路径

## 4. 执行任务

### 任务 5.1 文件迁移
- `git mv` §3 全部文件/目录；建 `topoone/agent/` 包结构（含 `workflow/` 子包）
- 更新被迁文件 import（内核 → `topoone.*`；llm → `topoone.llm.*`；engine 数据访问保持 MultiDBManager 注入模式）
- 更新 `engine/__main__.py`：skill 同步 import 块 + `register_all` 中 agent 相关引用（agent.* 方法注册方现状在 `agent_service_app`，独立进程，无引擎侧注册依赖——确认 `main.py` 不注册 agent 方法）
- **验证**：G1；G2（方法集不变）

### 任务 5.2 服务进程入口验证
- `python -m topoone.agent --data-dir <dir>` 启动 :3482，`GET /health` 200
- `agent.getConfig` / `agent.listRunning` 经网关 `/api/rpc/agent.getConfig` 抽查（G8 抽查）
- `main_cli.py` `_SERVICE_DEFS` 的 agent 条目 script 路径更新为 `-m topoone.agent`
- **验证**：`topo serve` 9 进程健康（G6）

### 任务 5.3 测试与回归
- `test_agentic_workflow.py` 迁移 + import 更新
- 补 1 个 `packages/core/tests/test_agent_service.py`：mock llm 通道下 `agent.dispatch`（pre_summary 小工作流）跑通 + `skill.list` 返回已注册技能
- 全量 G2+G3+G6
- **验证**：全绿后提交

## 5. 验收标准

1. `python -m topoone.agent` 可独立启动（`topo serve` 与手动两种路径）
2. G2/G3/G6 全过；`/ws/events` 中 agent.* 进度事件正常（PUB 5684）
3. `backend-core/` 不再含 `agent_workflow/`、`agent_worker.py`、`agent_service_app.py`、`tools_executor.py`
4. grep 断言：`topoone/agent/` 内无 provider 凭据读取（`api_key`/`OPENAI_API_KEY` 仅出现在 llm 包）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| `agent_workflow` 包名较长，改名（workflow）引入 import 遗漏 | 机械替换 `agent_workflow` → `topoone.agent.workflow` 全仓 grep 复核；改名可选（保守方案：保留子包名 `workflow` 亦可改为 `agent_workflow`，**建议保留原名 `topoone/agent/agent_workflow/` 降低改动面**） |
| architect 服务对 agent_workflow 的直接 import（若有） | 迁移前 grep `plugins/architect` 内 `agent_workflow` 引用；有则改 `topoone.agent.*`（architect 进程与 core 同 venv，editable 安装可见） |
| skill 同步 import 顺序（engine 启动时触发装饰器注册） | `engine/__main__.py` 保持原有 import 顺序（先 skill 模块后 `sync_skills_to_db`），仅改路径 |
