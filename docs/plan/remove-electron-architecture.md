# 去 Electron 化架构方案：web-ui + tui + cli + 后台 Python 微服务

> **后续**：本方案的落地已由工程拆分接管，执行总纲见 `docs/plan/split/`（M01–M14，核心基础框架 + 4 独立子项目 Monorepo）。本文件的 9 进程拓扑与 §Phase 3 的 8 项验收门已作为拆分 P0–P6 的验收基线沿用。

> 版本 v1.1（草案）| 日期 2026-08-16 | 状态：讨论结论，待落地（v1.1 经全仓代码核实修订，见 §8 修订记录）
> 关联：`docs/plan/restructure-plan.md`、`docs/plan/architect-design.md`
> v1.1 变更要点：进程拓扑唯一化（D8）、双 origin 决策（D6）、鉴权同相位（D7）、pickDirectory 方案、TUI ZMQ 直连（D9）、验收门 5→8 项

## 1. 结论

移除 Electron，将应用整体转为 **web-ui（浏览器）+ tui（Python Textual）+ cli + 后台 Python 异步进程微服务**。**可行，风险低于直觉预期**，支撑事实：

1. **Python 后端已可无 Electron 独立运行**：`python3 backend-core/main.py <data_dir> --http-port 3456` 拉起完整 monolith（core ZMQ + reports + architect + mcp + data-api）；另有 `--stdio` JSON-lines 模式。
2. **浏览器↔后端 RPC 桥已半成品**：`data_api.py` 已有 `POST /zmq/{method}` 直通 ZMQ 方法注册表（architect `KbGateway` 已在用）；architect 子进程已实现 ZMQ-SUB→WebSocket 桥（`arch_routes/zmq_stream.py` + `/ws/kb-analysis`）。
3. **读/可视化路径已 web 就绪**（图、热力图、文档、chat SSE、PlantUML、导入/导出/校验、architect）；缺口集中在写/执行路径与进程管理。

## 2. 目标架构

> v1.1 修订：双 origin（D6）+ 进程拓扑唯一化（D8）。图例：【新】= 本次新建 ·【修正】= 修现有问题 · 无标记 = 原样复用。

```
╔════════════════════════════════════════════════════════════════════════════════════════╗
║ 客户端层（与 daemon 同机）                                                                ║
║                                                                                          ║
║  浏览器                               TUI (Python Textual)            CLI (topo)            ║
║  ┌────────────────────────────────┐   ┌─────────────────────────┐   ┌─────────────────────────┐
║  │ ① http://127.0.0.1:3456        │   │ HTTP /api/rpc (3456)    │   │ daemon 模式: /api/rpc    ║
║  │    web-ui 主工作台 (src/ 迁移)  │   │ ZMQ-SUB 5680 直连【新】 │   │   (复用 Phase1 客户端层) ║
║  │    /app 静态 · /api/rpc ·      │   │  (llm/task 流式, 同语言)│   │ offline 模式: 直读 DB    ║
║  │    /ws/events · /api/file ·    │   └─────────────────────────┘   │  【修正】主库 topoone.db ║
║  │    SSE chat                    │                                 │  解析 + task 选择        ║
║  │ ② http://127.0.0.1:3470        │                                 └─────────────────────────┘
║  │    architect workbench         │
║  │    (双 origin; 反向代理为后置选项)│
║  └───────────────┬────────────────┘
╚══════════════════╪═══════════════════════════════════════════════════════════════════════╝
                   │ HTTP/WS · 默认 127.0.0.1【修正: 现状默认 0.0.0.0】
                   │ 鉴权: ~/.topocode/token【新, 与 /api/rpc 同相位】
                   ▼
╔════════════════════════════════════════════════════════════════════════════════════════╗
║ reports 网关 :3456 —— 主工作台唯一入口                                                    ║
║  静态托管: /app=web-ui 产物【新挂载】 · /web=存量 SPA · /static                           ║
║  /api/rpc/{method} ──→ 3459 /zmq/{method}                                              ║
║      【新】method 黑名单: backend.* 进程控制 / plugin 装卸 等命名空间(服务端拦截)           ║
║  WS /ws/events ← ZMQ-SUB 5680【新, ~200行, 复用 architect zmq_stream 先例】              ║
║      转发 4 topic 全集: task · project · backend · llm; per-conn 队列+丢旧+心跳          ║
║  既有读路径(不动): /api/file(路径守卫) · /api/file-graph · /api/community-files · SSE chat║
║  聚合 GET /api/health【新】: 全服务状态                                                   ║
╚══════════════════════════════════╤═══════════════════════════════════════════════════════╝
                                   │ HTTP localhost (KbGateway 代理模式)
╔══════════════════════════════════▼═══════════════════════════════════════════════════════╗
║ core (主进程, 进程内 ZMQ)                                                                  ║
║  ZMQ ROUTER :5671 (请求/响应)       ZMQ PUB :5680 (事件广播)                              ║
║  ZMQ 方法注册表: project/analysis/llm/report/settings/knowledge/version…(写路径全在此)     ║
║  + system.pickDirectory【新】服务端目录选择器(zenity/osascript; headless 降级手动输路径)    ║
║  + backend.* 拆分【修正】: 进程控制→仅 CLI/TUI; 配置类→settings.* 等价 RPC                 ║
║  llm_service → PUB 5680 (llm.chunk/tool_call/tool_result/done/error)【producer 零改动】   ║
║  data-api 线程 :3459 (127.0.0.1): /zmq/{method} · /sql/execute · /health                 ║
║  SQLite: ~/.topocode/{topoone.db · <project>/.topocode/data/project.db · knowledge.db ·   ║
║           sessions.db · cache/}                                                           ║
╚═══════╤══════════════════════════════╤════════════════════════════════════════════════════╝
        │ HTTP /zmq (KbGateway :3459)  │ HTTP :3470/api/architect
        │ + ZMQ-SUB 5680 (llm 流)      │
        ▼                              ▼
╔═══════════════════════════════╗  ╔═══════════════════════════╗  ╔════════════════════════════╗
║ architect :3470 (127.0.0.1)   ║  ║ mcp :3460                 ║  ║ coding_agent_runner :3458  ║
║  /architect SPA (浏览器第二origin)║║  外部 agent/工具 KB 通道  ║  ║  agent 执行 (FastAPI+WS)   ║
║  /ws/kb-analysis: SUB 5680→WS ║  ║  (代理 architect)         ║  ║  claude/codex/cursor…      ║
║  (提取流式, 已存在)            ║  ╚═══════════════════════════╝  ╚════════════════════════════╝
╚═══════════════════════════════╝

  ┌────────────────────────────────────────────────────────────────────────────────────┐
  │ 进程治理: 5 个进程 (core·reports·architect·mcp·coding_agent_runner) 由               │
  │ `topo serve` (supervisor) 统一 spawn/监控/重启 —— 唯一 owner【拓扑唯一化, D8】       │
  │  【修正】现状三条 spawn 路径互不一致: monolith 漏跑 runner(3458)、mcp 双 spawn 撞     │
  │  3460、start_http_server 与 main.py 各管一摊 → 删除其余 spawn 点                     │
  │  ├─ 每服务独立日志 → ~/.topocode/logs/<service>.log【新, 现状 stdout 继承父进程】     │
  │  ├─ PID + 单实例 lock; 配置 ~/.topocode/config.toml (端口保留 env 覆盖, 测试隔离)     │
  │  └─ 部署: systemd user unit · Dockerfile · scripts/serve.sh; 保留 --stdio 模式      │
  └────────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 事件流（producer 零改动的依据）

```
core (producer, 全部已存在)
  task_manager → PUB 5680  task.progress / task.complete / task.error / task.stopped
  llm_service  → PUB 5680  llm.chunk / llm.tool_call / llm.tool_result / llm.done / llm.error
  (backend.status / project.* …)
                          │  ZMQ PUB/SUB 扇出
      ┌───────────────────┼───────────────────────────────┐
      ▼                   ▼                               ▼
 reports 进程          architect 进程                   TUI 进程
  SUB 5680              SUB 5680                        SUB 5680【新, 直连】
  → WS /ws/events       → WS /ws/kb-analysis            → 终端渲染
  → 浏览器 web-ui       → architect 前端(提取流式)        (llm chat / task 进度 / log tail)
```

- 浏览器走**双 origin**（3456 主工作台 + 3470 architect workbench，均为 localhost）；
  reports→3470 反向代理（含 WS upgrade）为后置选项（D6）。
- **内部 ZMQ 保留**作为服务间 IPC（5671 请求/响应 + 5680 事件）。
- 现有端口固化：5671/5680/3456/3459/3460/3470/3458。

## 3. 现状差距分析

### 3.1 后端独立运行（已具备，需补齐"守护化" + 进程拓扑唯一化）
- 各服务已可独立进程启动；Data API(3459) 嵌在 core 进程内（无碍）。
- **进程 spawn 路径有三处且互不一致**（v1.1 核实，Phase 0 必须先统一）：
  1. `main.py` `_start_optional_services`（core 主进程侧，monolith 实际生效）：启动 reports + architect + mcp；
  2. `web_server.start_http_server`（独立 reports 模式入口）：启动 coding_agent_runner + mcp；
  3. `plugins/reports/__main__.py`（monolith 下 reports 子进程实际走的入口，由 1 拉起）：runner/mcp 都不启动。
  - 后果 A：**monolith 下 coding_agent_runner(3458) 实际未在运行**（agent 功能静默缺失）；
  - 后果 B：路径 1 与 2 都启 mcp，并存时撞 3460 端口。
- 缺失：monolith 下 reports/architect/mcp 崩溃不重启（supervisor 仅 distributed 用）；无聚合健康端点；子进程 stdout 继承父进程（无独立日志）；无配置/PID/lock；无 systemd/Docker。
- `main_cli.py` 存在但 `arch analyze/overview/export/diff/track` 为 stub（打印 "feature in development"），且 `serve` 命令仅存在于 docstring、无 parser 无 handler → CLI 当前实际不可用。
- query 数据布局：`<project>/.topocode/data/project.db` **路径本身正确**（与 `sqlite_ctx._project_db_path` 一致）；真正的 bug 是 ① 不查主库 `~/.topocode/topoone.db` 做 root_path↔project_id 解析 ② `SELECT DISTINCT task_id LIMIT 1` 取任意任务。

### 3.2 传输层（半具备，两块补丁）
| 能力 | Electron 现状 | Web 现状 | 缺口 |
|---|---|---|---|
| 请求/响应 | zmq-router DEALER→ROUTER | `POST /zmq/{method}` ✅ | 校验/错误契约统一 |
| LLM 流式 | ZMQ SUB llm | chat SSE ✅ / architect WS ✅ | 社区 LLM 流式接入 /ws/events |
| 任务/项目/导入/导出/校验推送 | ZMQ SUB | 仅轮询 | **缺 `/ws/events` 通用事件桥** |
| Agent 进度 | RPC 轮询 getAgentProgress | — | 经 /zmq 暴露即可 |

→ 补一个挂在 core/reports 进程的 `WS /ws/events`（转发 `{topic,eventType,data}`，契约与 `electron/zmq-router.ts` 一致）+ 复用 `ArchWs` 客户端模式，即可 1:1 复刻 Electron 事件面（约 200 行）。

### 3.3 功能面（读路径就绪，写路径缺暴露）
- 读/可视化（community-graph、file-graph、cascade、heatmap、external、docs、plantuml、export/import/verify）✅。
- session/llm/chat ✅（SSE）。
- 写路径（task CRUD/run/stop/logs、agent pipeline、pre-summary、report 写作、version sync/diff/materialize、group、model usage、settings CRUD）❌ 无 HTTP 等价——**但全部已在 ZMQ 注册表**，`POST /zmq/{method}` 天然覆盖，缺口本质是"暴露 + 前端 UI"而非重写后端。

### 3.4 Electron 专属能力 → 浏览器等价物
| 通道 | 替代 |
|---|---|
| dialog.openDirectory | **服务端 `system.pickDirectory` RPC**（Linux zenity/kdialog · macOS osascript · Windows PowerShell；headless 降级为手动输路径）+ 输入框兜底。⚠️ v1.1 修正：`webkitdirectory`/FS Access **不暴露绝对路径**，无法用于导入场景（`project.import(path)` 需要服务端绝对路径；4 处调用：ImportSourceDialog×2 / ProjectCard / GeneralSettings） |
| dialog.openFile | 同上（文件选择器 RPC 或手动输入） |
| fs.readFile | `GET /api/file`（已存在，服务端路径守卫：normpath + startswith 校验，viewer.py:409） |
| device.getId | localStorage + crypto.randomUUID |
| store.* | localStorage / IndexedDB |
| shell.openExternal | window.open |
| shell.openPath（打开文件管理器） | 无浏览器等价物 → 移除或降级为"显示路径"提示 |
| window.* / app.* | 移除（浏览器窗口管理无意义），TopBar 改浏览器模式 |
| backend.* | **拆分**（v1.1）：进程控制类（restart/quit/status）→ CLI/TUI/systemd，UI 只读；配置类（setHttpConfig/setMemoryLimit/setResourceDir，SettingsPage 在用）→ `settings.*` 等价 RPC |
| updater | 失效 → 脚本/系统包管理 / 托管实例自动更新 |

**window.api 迁移策略（v1.1 补充）**：全仓 81 处引用 / ~20 文件，其中 6+ 处**绕过 ipc.ts 直接调用**（useFileReader / ImportSourceDialog / ProjectCard / GeneralSettings / llmClient 等）。最低风险路径：浏览器模式 `window.api = createBrowserAPI()`（与 `IPCAPI` 同构），`ipc.ts` 的 `createRealIPC` 改为"存在 window.api 则直接用"——81 处引用零改动存活，避免逐文件改调用点。

## 4. 决策记录

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| D1 | Web-UI 来源 | **迁移现有 src/ 桌面 UI** | 78 Vue + 156 TS 全部复用，仅替换传输层，功能全对齐 |
| D2 | TUI 选型 | **Python Textual** | 与后端同语言，可 import topoone + 复用 /zmq 客户端 |
| D3 | 后台管理 | **topo serve + systemd 模板** | 跨平台可移植 + Linux 系统级托管 |
| D4 | 迁移节奏 | **直接切换** | 不长期双轨并行；以强制验收门 + 单 commit 回滚补偿风险 |
| D5 | 内部 IPC | **保留 ZMQ** | 现状已如此，改动最小；浏览器只走 HTTP/WS |
| D6 | 浏览器 origin | **双 origin**（3456 主工作台 + 3470 architect workbench） | 现状 `/architect` 本就是 302 跳 3470（web_server.py:70）；WS 反向代理成本高，代理为后置选项 |
| D7 | 鉴权时机 | **与 /api/rpc 同相位**（token + method 黑名单 + 默认 127.0.0.1） | reports 现状默认绑 0.0.0.0（main.py:80）；/api/rpc 在 P1 才真正扩大暴露面，缓解必须同相位落地 |
| D8 | 进程拓扑 | **`topo serve` 唯一 owner**，删除其余 spawn 点 | 现状三条 spawn 路径互不一致：monolith 漏跑 runner(3458)、mcp 双 spawn 撞 3460 |
| D9 | TUI 流式 | **TUI 直连 ZMQ-SUB 5680**（HTTP 走 /api/rpc） | 与后端同语言，少一跳，无需 WS |

## 5. 落地计划

### Phase 0 后端守护化（`topo serve`）—— 进程拓扑唯一化
- `main_cli.py` 新增可用 `serve/status/doctor`（现状 `serve` 仅存在于 docstring，无 parser 无 handler），兼容 `--http-port` 启动。
- **进程拓扑唯一化（关键，D8）**：定义唯一服务集（core·reports·architect·mcp·coding_agent_runner）+ 唯一 owner（`topo serve`/supervisor），删除其余 spawn 点：
  - `main.py` `_start_optional_services` 中的 mcp spawn（与 reports 路径重复，撞 3460）；
  - `web_server.start_http_server` 中的 runner/mcp spawn（monolith 实际走 `plugins/reports/__main__.py`，该路径不生效 → **runner 在 monolith 下漏跑**，agent 功能静默缺失）；
  - supervisor 扩展为 monolith 下全部 5 进程崩溃重启（backoff/limit 机制已有，复用）。
- 聚合 `GET /api/health`（reports）；每服务独立日志（`~/.topocode/logs/<service>.log`，现状 stdout 继承父进程）；配置规范化（`~/.topocode/config.toml`，端口保留 env 覆盖以保测试隔离）；PID/lock 单实例。
- systemd user unit + Dockerfile 模板 + `scripts/serve.sh`；保留 `--stdio`。

### Phase 1 通用 RPC + 事件桥 + 鉴权（同相位，硬性）
- `/api/rpc/{method}`（reports 3456）→ 转发 core data-api `/zmq/{method}`（复用 KbGateway 代理模式）；
  **method 黑名单（服务端拦截，不依赖前端禁用）**：`backend.*` 进程控制、plugin 装卸等命名空间不对 Web 暴露；校验/错误契约与 `/zmq/{method}` 对齐（结构化错误，不裸 500+string）。
- **鉴权（D7，不后置）**：reports 默认绑定由 0.0.0.0 改为 **127.0.0.1**（main.py:80 默认值）；生成 `~/.topocode/token`，前端/CLI/TUI 随请求携带并校验。
- `WS /ws/events`（reports 3456）→ ZMQ SUB 5680，转发 4 topic 全集（task/project/backend/llm，即 electron zmq-router 订阅集）；per-connection 队列 + 丢旧策略 + ping 心跳（llm chunk 高频、多 tab 各持一条连接）。
- 浏览器 `subscribe()` 客户端（复用 zmq_stream.py + ArchWs 先例）；`llm.subscribe(requestId)` 等价物 = WS 监听按 requestId+topic 过滤（preload 现有过滤逻辑 1:1 迁移）。
- 后端 producer 零改动（task_manager/analyst_runner/core_service 已在 publish）。

### Phase 2 web-ui 迁移（复用 src/）
- 新增 `src/services/browser-api.ts`（fetch `/api/rpc/{method}` + WS，接口与 `IPCAPI` 同构）；浏览器模式 `window.api = createBrowserAPI()`，`ipc.ts` 的 `createRealIPC` 改为"存在 window.api 则直接用"——81 处引用（6+ 处绕过 ipc.ts 直调）零改动存活（见 3.4 迁移策略）。
- 3.4 等价物替换；TopBar 浏览器化；`backend.*` 拆分处理（进程控制只读 / 配置类走 `settings.*` 等价）。
- **目录选择器（硬性项）**：新增 `system.pickDirectory` 服务端 RPC（zenity/kdialog · osascript · PowerShell；headless 降级手动输路径）+ 输入框兜底，替换 4 处 `dialog.openDirectory` 导入调用点。
- 写路径缺口经 /api/rpc 直通覆盖，**无需新增后端**。
- 构建：`vite build` 产物由 reports 网关静态托管（`/app` **新挂载**，现状 web_server 只挂 `/static` + `/web`）；`vite.config.ts` 加 dev 代理 `/api`+`/ws`→3456。可与 P1 并行。
- **architect workbench**：双 origin（3470）保持现状、不加代理（D6）；反向代理（含 WS upgrade）列为后置选项。

### Phase 3 直接切换（一次性翻转）
翻转前**强制验收门**（v1.1：5 → 8 项）：
1. `topo serve` 全 5 服务健康 ✓（**含 coding_agent_runner 3458** —— 现状 monolith 漏跑，必须确认拓扑唯一化后拉起）
2. `/api/rpc` 抽查 analysis.runTask 全链路（导入→解析→社区→LLM 摘要）✓
3. `/ws/events` 任务/导入进度推送 + llm 流式（浏览器端）✓
4. web-ui 手动 smoke（扩展 `tests/`）✓
5. 后端 pytest + 前端 vitest 全绿 ✓
6. architect workbench 浏览器可达（3470）+ `/ws/kb-analysis` 提取流式正常 ✓
7. coding agent 执行进度可见（runner 3458 可达、agent pipeline 可用）✓
8. 鉴权生效：非本机访问 3456 被拒（默认 127.0.0.1）；无 token → 401 ✓

**回滚演练**：切换前打 tag，验证 `git checkout` 后 Electron dev flow 完整可用（`npm run dev`），再执行切换 commit。

切换 commit：
- 删除 `electron/`、`tsconfig.electron.json`、`build/afterPack.cjs`、`electron-builder-*.json`、updater、preload、`window-manager/python-bridge/zmq-router`。
- `package.json`：`dev`=concurrently(vite + `topo serve`)；`build` 去 build:electron；移除 electron-builder 与 `main` 字段。
- `ipc.ts`/`window-api.ts` 清理 Electron 分支；`src/types/ipc.ts` 保留为**单一契约源**。
- 分发：前端静态产物本就嵌在 backend 仓（`plugins/reports/static` + src 构建输出）→ 实际为**一个后端包 + 一个 Dockerfile**。

### Phase 4 CLI
- `main_cli.py` 重构：`serve/status/import/analyze/tasks/export/verify/settings/doctor` + `--json`。
- 客户端连 daemon 走 `/api/rpc`；离线模式直读 DB。
- 修正 query 路径（v1.1 精确化）：项目库路径 `<project>/.topocode/data/project.db` 本身正确；真 bug = ① 不查主库 `~/.topocode/topoone.db` 解析 root_path↔project_id ② `SELECT DISTINCT task_id LIMIT 1` 取任意任务 → 补项目解析 + task 选择参数，并补测试。

### Phase 5 TUI（Python Textual）
- 新增依赖 `textual`（现状 requirements 未包含）。
- HTTP 请求/响应复用 Phase 4 RPC 客户端层；**流式（llm/task）直连 ZMQ-SUB 5680**（同语言，少一跳，D9）。
- 首期 = 服务状态、导入、任务进度、LLM chat、日志 tail。

## 6. 交叉关注点
- **本地鉴权（P1 硬性，不再后置，D7）**：reports 现状默认绑 0.0.0.0（main.py:80），`/api/rpc` 在 P1 暴露全部 ZMQ 方法 → 默认 127.0.0.1 + `~/.topocode/token` + 服务端 method 黑名单，与 `/api/rpc` 同相位落地。
- **单机关机假设（v1.1 显式声明）**：方案隐含"浏览器与 daemon 同机"（导入/文件语义全在服务端）。远程访问（浏览器在另一台机器）只能走服务端路径；headless 环境 pickDirectory 无 GUI → 手动路径输入。如需远程部署，后续评估反向代理 + 远端文件源。
- **web/ 存量 SPAs**：翻转后 viewer/chat/web-root 与 src/ 重叠，标记后置整合；architect SPA 保留为 workbench（双 origin 3470）。
- **契约对齐**：`/api/rpc` 封包与现有 `/zmq/{method}`、chat SSE 事件格式对齐，不发明新协议。

## 7. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 直接切换中途不可用 | 验收门前置（8 项）+ 切换前回滚演练 + 单 commit 可回滚 |
| 浏览器无法直读本地任意路径 | 能力不降（经 localhost 后端 `GET /api/file` 带路径守卫）；File System Access API 可选增强 |
| Web API 无鉴权 + daemon 化暴露面扩大（3456 现状默认 0.0.0.0） | **P1 同相位**（D7）：默认 127.0.0.1 + 本地 token + 服务端 method 黑名单；验收门 8 验证拒绝路径 |
| 进程拓扑混乱（3 条 spawn 路径不一致、runner 漏跑、mcp 端口冲突） | P0 拓扑唯一化（D8）：`topo serve` 唯一 owner + 删除其余 spawn 点；验收门 1/7 验证 |
| 导入场景丢失目录选择器（浏览器拿不到服务端绝对路径） | 服务端 `system.pickDirectory` RPC + 手动输入兜底（Phase 2 硬性项） |
| 切换后 architect workbench 不可达（静态/WS） | 双 origin 保持现状（D6）+ 验收门 6；反向代理为后置选项 |
| src/ 与 web/ 双前端职责模糊 | src/ 为主工作台，web/ 仅留 architect，其余后置整合 |
| src/ 全局 window.api 引用多（81 处 / 20+ 文件，6+ 处绕过 ipc.ts 直调） | 浏览器模式 `window.api = createBrowserAPI()`，引用零改动存活；契约以 `src/types/ipc.ts` 为单一源 |
| CLI 数据布局 bug 历史遗留 | Phase 4 修正（主库项目解析 + task 选择）并补测试 |

## 8. 修订记录

### v1.0 → v1.1（2026-08-16，基于全仓代码核实）
| # | 变更 | v1.0 | v1.1 | 依据 |
|---|------|------|------|------|
| 1 | 进程治理 | Phase 0 仅"supervisor 扩展崩溃重启" | **拓扑唯一化**：`topo serve` 唯一 owner，删除其余 spawn 点 | `main.py`/`web_server.start_http_server`/`plugins/reports/__main__.py` 三条 spawn 路径互不一致；monolith 实际漏跑 runner(3458)、mcp 双 spawn 撞 3460 |
| 2 | 浏览器 origin | "单一 origin :3456" | **双 origin**（3456 + 3470），代理后置 | `web_server.py:70` `/architect` 本就是 302 跳 3470；WS 反向代理成本高 |
| 3 | 鉴权时机 | "建议/可后置"交叉关注点 | **P1 硬性**（token + method 黑名单 + 默认 127.0.0.1） | reports 默认绑 0.0.0.0（`main.py:80`）；暴露面 P1 才真正扩大，缓解须同相位 |
| 4 | 目录选择器 | `webkitdirectory` / FS Access | **服务端 `system.pickDirectory` RPC** + 手动输入 | FS Access API 刻意不暴露绝对路径；4 处导入调用点均需服务端绝对路径 |
| 5 | TUI 流式 | 复用 Phase 4 RPC 层 | **ZMQ-SUB 5680 直连** + HTTP 走 RPC | 与后端同语言，少一跳（D9） |
| 6 | window.api 迁移 | ipc.ts 单点适配 | 浏览器模式 `window.api = createBrowserAPI()` | 81 处引用、6+ 处绕过 ipc.ts 直调，零改动存活风险最低 |
| 7 | CLI bug 描述 | "数据布局不符" | 项目库路径本身正确；真 bug = 缺主库解析 + 任意 task | `sqlite_ctx.py:1519-1525` vs `main_cli.py:156-177` |
| 8 | 验收门 | 5 项 | **8 项**（+ runner 健康 / architect 可达 / agent 进度 / 鉴权拒绝）+ 切换前回滚演练 | 防功能静默丢失（runner 漏跑已是现状事实） |
| 9 | backend.* 处理 | Web 面一律禁用 | **拆分**：进程控制只读 / 配置类走 `settings.*` 等价 | `backend:setHttpConfig` 等为 SettingsPage 配置读写，非进程控制 |
| 10 | 分发形态 | 后端包 + 前端静态包 + Docker | **一个后端包 + 一个 Dockerfile** | 前端静态产物本就嵌在 backend 仓（`plugins/reports/static` + 构建输出） |