# M04 llm 服务（P2③）

> 阶段：P2 第 3 步 | 预估：1 d | 前置：M02、M03 | 后续：M05
> 状态：✅ 完成（2026-08-20）

## 0. 完成记录与计划偏差（2026-08-20）

**验收结果**：
- G1：`topoone.llm.{service,prompt_manager,instruction_manager,providers,context}` 全部可导入，
  8 个内置 provider 正常注册。
- G2：RPC 基线 204 方法一致（kb 进程经 `engine/app.py → topoone.llm.service` 注册 llm.* 不变）。
- G3：`pytest packages/core/tests backend-core/tests` 98/98（含新增 test_llm_service.py 3 项：
  session CRUD / mock provider llm.chat 流式（chunk→done→assistant 消息落库）/ 参数与模型校验）。
- G6：`topo serve` 9 进程 /health 全 200；llm 以 `python3 -m topoone.llm --data-dir … --port 3484
  --pub-port 5682` 运行。
- G8 抽查：网关 `/api/rpc/llm.chat` 路由至 llm 服务（"Model not found" 域错误来自
  `topoone.llm.service`）；`session.delete` 经真实网关成功（验证下方 FK 修复）。
  注：本环境无可用本地模型（ollama 未运行），真实模型流式未跑，chunk→PUB 路径由 mock 单测覆盖。
- 独立启动：`python -m topoone.llm --data-dir <tmp> --port 3499 --pub-port 5699` → /health 200，
  `/zmq/session.list` 返回 `{"sessions":[]}`，`/zmq/llm.chat` 参数校验生效。
- `backend-core/` 不再含 llm 相关文件与 `context/`、`templates/`、`providers/`、`config/` ✓。
- api_key 面（验收 #4）：`topoone/` 内除 `llm/` 外仅 `engine/service/settings.py` 的模型配置 CRUD
  （保存写入 + 列表返回时 `hasApiKey` 掩码后删除原值），无新增读取/使用凭据路径（存量设计，记录在案）。

**与 §3 的偏差/补充**：
- `llm_service_app.py` 原为**未纳入版本控制**的文件 → 以普通 `mv` 迁入 `llm/__main__.py`（git 中为新增文件）。
- `backend-core/templates/` 为空目录（无文件）→ 直接删除，无迁移内容。
- `llm/__main__.py` 顶部保留 backend-core sys.path 自举（过渡期：`service.py` 内 2 处惰性
  `from tools_executor import …`，M05 迁出后移除；已标 TODO）。
- provider 插件（llm-provider-*）迁入 `topoone/plugins/` 后，`plugin_entry.py` 的
  `from providers.*` → `from topoone.llm.providers.*` 绝对导入。
- `main_cli.py`：llm spawn 改 `[sys.executable, "-m", "topoone.llm", …]`（独立分支，agent 仍走脚本路径）；
  `_SERVICES["llm"]["script"]` 置 None。
- `engine/app.py` 的 `from llm_service import register_llm_methods`（M03 TODO 标记）→
  `from topoone.llm.service import register_llm_methods`。

**顺带修复的存量生产 bug（非 M04 引入）**：
- `session.delete` 对 sessions.db 路由的会话**必然失败**：`delete_session` 开
  `PRAGMA foreign_keys = ON` 后，sessions.db 内 `analysis_sessions` 的跨库 FK
  （`task_id→analysis_tasks` / `project_id→projects`，两表在 topoone.db）无法在 sessions 连接解析，
  任何 DELETE 触发约束解析即报 `no such table: main.projects`（生产库复现确认）。
  修复：`delete_session` 不再开 FK pragma，改为显式级联
  `analysis_sessions → llm_messages → llm_sessions`。生产库 create+delete 探测通过。
  （`clear_all_sessions` 走 chat.db 无 analysis_sessions，不受影响；跨库 FK 的 DDL 根治留 M14。）

## 1. 改造目标

把 llm 服务（模型网关 :3484）全部代码迁入 `packages/core/topoone/llm/`，形成独立可启动的基础服务包：`python -m topoone.llm` 等价原 `python llm_service_app.py`。保持"唯一持 provider 凭据、唯一 LLM 客户端"的边界不变。

## 2. 功能边界

**包含（In）**
- LLM 方法：`llm.chat`（流式）/ `llm.abortChat` / `llm.sync`、模型管理（列表/默认/locale）
- 会话：`session.*` / `analysisSession.*`（sessions.db 唯一主写方）
- 模板：`promptTemplate.*` / prompt_manager / instruction_manager / templates/ / config/prompt_templates.json
- 上下文装配系统：`context/`（assembly/ingredient/registry/recipes/ingredients）
- Providers：`providers/`（base/openai_compat/ollama）+ provider 插件包 `plugins/llm-provider-{openai,ollama,lm-studio}`

**不包含（Out）**
- harness/agent 逻辑（M05）；chat 应用路由（M12）；任何 UI/静态资源

**依赖方向**：llm → 内核（db/rpc/messaging）+ engine（仅读 project.db 元数据，经 MultiDBManager，不 import engine 业务模块）；被 agent/chat/architect 经 HTTP（`/zmq/llm.*`）+ SUB 5682 依赖。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 |
|---|---|
| `backend-core/llm_service.py` | `packages/core/topoone/llm/service.py` |
| `backend-core/llm_service_app.py` | `packages/core/topoone/llm/__main__.py` |
| `backend-core/providers/{__init__,base,openai_compat,ollama}.py` | `topoone/llm/providers/`（同名） |
| `backend-core/prompt_manager.py` | `topoone/llm/prompt_manager.py` |
| `backend-core/instruction_manager.py` | `topoone/llm/instruction_manager.py` |
| `backend-core/templates/`（整目录） | `topoone/llm/templates/` |
| `backend-core/config/prompt_templates.json` | `topoone/llm/config/prompt_templates.json`（`backend-core/config/` 目录随之删除） |
| `backend-core/context/{__init__,assembly,ingredient,registry}.py` + `context/recipes/` + `context/ingredients/`（整目录） | `topoone/llm/context/`（同构） |
| `plugins/llm-provider-openai/`、`plugins/llm-provider-ollama/`、`plugins/llm-provider-lm-studio/`（各含 plugin.json + plugin_entry.py） | `packages/core/topoone/plugins/llm-provider-*/` |

**import 改写**：`from llm_service import register_llm_methods` → `from topoone.llm.service import register_llm_methods`（受影响方：`engine/__main__.py` 的 `register_all`、`agent_workflow/**`（M05 迁时再改）、`plugins/architect`（经 HTTP，无 import 影响））。

## 4. 执行任务

### 任务 4.1 文件迁移
- `git mv` §3 全部文件；建 `topoone/llm/` 包结构
- 更新被迁文件内部 import（内核 → `topoone.*`；providers/context 相对引用保持包内）
- 更新 `engine/__main__.py`：`register_llm_methods` 改从 `topoone.llm.service` 导入（llm.* 方法本步起由 llm 包注册，注册方仍为引擎进程入口——与现状一致）
- **验证**：G1；G2（方法集不变）

### 任务 4.2 服务进程入口验证
- `python -m topoone.llm --data-dir <dir>` 启动 :3484，`GET /health` 200，`llm.chat` 冒烟（mock 或本地模型 1 轮）
- `supervisor` 侧（main_cli.py 的 `_SERVICE_DEFS`）llm 条目 `script` 路径更新为 `-m topoone.llm`（此文件 M07 才整体迁移，本步仅改路径字符串 + 验证）
- **验证**：`topo serve` 9 进程健康（G6）；llm 流式事件经 PUB 5682 → `/ws/events` 可见（G8 抽查）

### 任务 4.3 测试与回归
- llm 无独立单测文件；补 1 个 `packages/core/tests/test_llm_service.py`：mock provider 下 `llm.chat` 流式 + `session.create/list` CRUD（用临时 data_dir）
- 全量 G2+G3+G6
- **验证**：全绿后提交

## 5. 验收标准

1. `python -m topoone.llm` 可独立启动（`topo serve` 与手动两种路径）
2. G2/G3/G6 全过；`/ws/events` 中 llm 流式正常
3. `backend-core/` 不再含 llm 相关文件与 `context/`、`templates/`、`providers/`、`config/`
4. provider api_key 仍仅 llm 进程读取（grep 断言：`topoone/` 内除 `llm/` 外无 `api_key` 读取逻辑）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| `context/` 装配系统被 agent_workflow 反向 import（若存在） | 迁移前 grep `from context` 引用面；若有 agent 侧引用，M05 迁 agent 时同步改 `topoone.llm.context`（依赖方向 agent→llm 合法） |
| prompt_templates.json 路径硬编码 | grep 全仓 `prompt_templates.json` 引用，统一改 `topoone.llm.config` 常量 |
| provider 插件 plugin.json 的 dependencies 安装目标 | 跟随插件目录（.deps 机制），目录迁移自动跟随 |
