# M12 子项目·AI Chat chat（P3③）

> 阶段：P3 第 3 步 | 预估：2 d | 前置：M01–M11 | 后续：M13
> 状态：⬜ 未开始

## 1. 改造目标

把 AI Chat（门户卡片"AI CHAT"）切为独立子项目 `apps/chat/`：
- **前端**：chat SPA 从 `web/` 迁入，独立 vite 工程（5175，单 entry）
- **后端**：chat 服务（:3483）= `chat.py` 26 路由迁入 `apps/chat/server/`（包名 `topoone-app-chat`，独立进程）

**范围声明**：本模块为**纯组织拆分，代码原样迁移**。现状 chat 服务仍保留内置 LLM 客户端（直连 `/v1/chat/completions`，chat.py:205/680–722）与 `skills.py`/`web_tools.py` 作为 fallback（remove-electron 文档 P3d"LLM 客户端删除待定"状态）——**完成瘦身（流式改经 llm 服务 `llm.chat` + SUB 5682、删除内置客户端/skills/web_tools）是独立功能任务**，列为任务 12.6（可选、独立验收、可回退），不阻塞拆分主流程。

## 2. 功能边界

**包含（In）**
- 前端：`/chat` SPA（会话列表·流式对话·技能/模型选择·草稿·笔记·归档）
- 后端 26 路由（全部挂 chat 服务 :3483，gateway 反代）：
  - 页面：`/chat`
  - 会话：`/api/chat/sessions`（GET/POST）· `/api/chat/sessions/{id}`（GET/DELETE）· `/auto-title` · `/stream/abort` · `/messages`（GET/POST/DELETE）· `/messages/batch`
  - 上下文：`/api/chat/autocomplete` · `/api/chat/context/project/{id}` · `/api/chat/context/task/{id}`
  - 模型/技能/模板：`/api/models` · `/api/skills` · `/api/template-locale`
  - 草稿：`/api/drafts`（GET/POST）· `/api/drafts/{id}`（GET/DELETE）· `/send` · `/batch-send` · `/execute-draft`
  - 归档/笔记：`/api/chat/archives`（GET/POST/DELETE）· `/api/notes`（GET/POST）· `/api/notes/{id}`（GET/DELETE）
- 数据：topoone.db `chat_drafts`/`chat_archives` **主写**；会话/消息经 llm 服务 `session.*`（sessions.db）或现状内置路径（12.6 前）
- SSE 流式：现状（内置客户端直连 或 llm 服务，按 12.6 状态）

**不包含（Out）**
- LLM 推理/providers（core 的 llm 服务）；harness/agent 编排（core 的 agent 服务）
- 文档渲染域组件（viewer 域 → M11）；workbench 内嵌 AI 面板（→ M10，双实现后置整合）

**依赖方向**：chat server → topoone-core（service_app + db + service_common）+ llm 服务（HTTP `session.*`/`llm.chat`）；chat FE → @topo/web-core。

## 3. 源码归属（文件映射）

### 3.1 前端

| 现有路径 | 目标路径 |
|---|---|
| `web/chat.html`、`web/AppChat.vue`、`web/entry-chat.ts` | `apps/chat/src/{chat.html,AppChat.vue,main.ts}` |
| `web/pages/ChatSession.vue` | `apps/chat/src/pages/` |
| `web/components/{ChatInput,ChatMessage,ChatSidebar,ChatToolbar}.vue` | `apps/chat/src/components/` |
| `web/env.d.ts`（chat 相关） | `apps/chat/src/env.d.ts` |
| `vite.web.config.ts`（chat entry 部分） | `apps/chat/vite.config.ts`（root=apps/chat/src；outDir=`apps/chat/dist`；dev 5175 + 代理 `/api`→3456） |
| —（新建） | `apps/chat/package.json`（deps 按 import 扫描）、`manifest.toml` 校正 |

共享件（api.ts/i18n/domain types/MermaidViewer/PlantUmlViewer/AppDialog/useDialog/useToast/StarLogoMark）M09 已上提，本步仅确认 import。

### 3.2 后端（→ `apps/chat/server/`，包 `topoone_app_chat`）

| 现有路径 | 目标路径 |
|---|---|
| `plugins/reports/chat.py`（1777） | `apps/chat/server/chat.py` |
| `plugins/reports/skills.py`（232） | `apps/chat/server/skills.py`（12.6 删除） |
| `plugins/reports/web_tools.py`（1844） | `apps/chat/server/web_tools.py`（12.6 删除） |
| `backend-core/chat_service_app.py`（68） | `apps/chat/server/main.py`（+ `__main__.py`：`python -m topoone_app_chat`） |
| `plugins/reports/common.py` 残留（`_ensure_chat_tables` 等 chat 专属，M11 拆散后） | `apps/chat/server/chat_tables.py` |
| —（新建） | `apps/chat/server/{__init__.py,pyproject.toml}`（name=`topoone-app-chat`，deps: `topoone-core` + fastapi/uvicorn） |
| `apps/chat/manifest.toml` | 校正：`kind="service"`、`python_entry="topoone_app_chat:main"`、`static_dir="apps/chat/dist"`、`static_mount=["/chat"]`、`api_prefixes=["/chat","/api/chat","/api/drafts","/api/notes","/api/models","/api/skills","/api/template-locale"]`、`port=3483`、`pub_port=null` |

**chat 服务进程组装**（`main.py`，沿用现状 `chat_service_app.py` 结构）：`MultiDBManager` + `service_common.set_globals(..., executor=WebToolExecutor)` + `chat_tables.ensure()` + `include_router(chat.router)` + `/health`。

## 4. 执行任务

### 任务 12.1 后端迁移
- `git mv` §3.2 文件；建包 + pyproject；`pip install -e apps/chat/server`
- import 更新：`import common` → `topoone.service_common`（M11 已建）+ 包内 `chat_tables`；`web_tools`/`skills` 改包内 import
- **验证**：`python -m topoone_app_chat --data-dir <dir>` 独立启动 :3483，`GET /health` 200，`GET /api/models` + `GET /api/skills` 冒烟

### 任务 12.2 前端迁移
- `git mv` §3.1 前端项；`apps/chat/vite.config.ts` 单 entry
- 共享 import 复核；G4（vue-tsc）+ G5（`dist/chat/` 产物）
- **验证**：全绿

### 任务 12.3 注册/路由/回归
- supervisor `_SERVICE_DEFS` chat 条目 script → `-m topoone_app_chat`
- gateway 反代确认（现状 `_SERVICE_URLS.chat` 已指向 3483，manifest 驱动后由 `api_prefixes` 生成，行为不变）
- G2（合并方法集基线：chat 服务 methods 已含在 M11 升级后的基线采集内）+G3+G6+G7（/chat 深度 smoke：新建会话·1 轮流式对话·技能选择·草稿发送·笔记 CRUD）+G8
- **验证**：全绿后提交；README §7 更新 M12 状态

### 任务 12.4 chat 专属清理
- `plugins/reports/common.py` 删空（M11 拆通用部分、本步拆 chat 部分后，文件清零）
- `plugins/reports/` 此时仅剩 `static/`（过渡）+ `__init__.py`（M14 随目录删除）
- **验证**：`plugins/reports/` 盘点符合预期

### 任务 12.5（可选）完成 P3d 瘦身
> 独立 commit/分支，独立验收；**默认不在拆分主流程内执行**，建议拆分全部完成后作为独立任务评审。
- chat 流式改经 llm 服务 `llm.chat`（HTTP `/zmq/llm.chat`，requestId）+ SUB 5682 chunk 转发 SSE
- 删除内置 LLM 客户端（chat.py:205 `_req.post /v1/chat/completions` 非流式、680–722 `_llm_round` 流式）、`skills.py`、`web_tools.py`（refs 解析改经 agent 服务 `tool.*`/`skill.*` 或 core 等价 API）
- 会话 CRUD 全部经 llm 服务 `session.*`（sessions.db 主写方唯一化）
- 验收：chat 全功能 smoke（会话/流式/技能/工具调用/草稿）+ provider key 不出现在 chat 进程（grep + 运行时 env 断言）+ G3/G7
- 回退：本任务独立 commit，revert 即回到"内置 fallback"状态

## 5. 验收标准

1. `apps/chat/` 自包含（拆仓库能力验证）
2. G2/G3/G4/G5/G6/G7/G8 全过；`/chat` 全部 26 路由现状行为不变
3. `plugins/reports/` 业务代码清零（仅剩过渡 static）
4. chat 服务进程独立启停（kill 后 supervisor 重启，SSE 会话恢复语义与现状一致）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| 内置 LLM 客户端依赖 model_configs 直读（含 api_key） | 12.5 前保持现状（已知偏差，P3d pending）；12.5 完成后 key 仅 llm 进程持有 |
| SSE 长连接经 gateway 反代的超时/缓冲 | 现状已如此（3456 反代 3483），迁移不改链路；smoke 含长流（>60s）用例 |
| `web_tools.py`（1844 行）迁移后仍被 chat.py 动态 import（`from web_tools import ...` 函数内） | 改包内 import 时注意函数内延迟 import 也要替换（grep `web_tools` 全覆盖） |
| chat SPA 与 workbench 内嵌 AI 面板双实现 | 不消重（后置整合）；两者共享 web-core 组件，视觉一致性由 web-core 保障 |
