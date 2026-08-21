# M13 子项目·Architect 工作台 architect（P3④）

> 阶段：P3 第 4 步 | 预估：2 d | 前置：M01–M12 | 后续：M14
> 状态：⬜ 未开始
> architect 是现状独立性最强的子项目（独立进程 :3470 + 独立 architect.db + 自带 SPA 托管），迁移风险最低。

## 1. 改造目标

把 Architect 工作台（门户卡片"Architect 工作台"：需求驱动 + 架构驱动 Coding Agent）切为独立子项目 `apps/architect/`：
- **前端**：`web/architect-src/`（63 vue）整体迁入，独立 vite 工程（5176）
- **后端**：`plugins/architect/`（server + 36 个 arch_routes 路由模块 + tests）整体迁入 `apps/architect/server/`（包名 `topoone-app-architect`，独立进程 :3470 不变）

## 2. 功能边界

**包含（In）**
- 前端：`/architect` SPA（语义资产·需求/设计/greenfield·执行·单元测试·MCP 协作·资产图/蓝图）
- 后端：`/api/arch/*` + `/ws/kb-analysis`（WS）+ 自有静态托管；语义资产提取 agent（经 llm 服务 `llm.chat` + SUB 5682）；KbGateway（经 kb 服务/网关访问 KB）；MCP 协作
- 数据：**architect.db 唯一主写方**（`arch_*` 全部表）；project.db/topoone.db 只读（经 HTTP/KbGateway，不直连——现状已满足）

**不包含（Out）**
- llm 推理（core 的 llm 服务）；KB 数据（core 的引擎/kb 服务）；coding agent 子进程管理（core 的 runner，architect 经 agent 服务/runner 使用）

**依赖方向**：architect server → topoone-core（db 句柄仅 architect.db 自建、service_common 可选）+ llm 服务（HTTP）+ kb 服务（HTTP KbGateway）+ mcp（HTTP）；architect FE → @topo/web-core（M09 已上提的共享件；architect-src 目前自带 i18n/services，共享件引用面小）。

## 3. 源码归属（文件映射）

### 3.1 前端

| 现有路径 | 目标路径 |
|---|---|
| `web/architect-src/`（整目录：App.vue/pages 13/components 9 域/services/stores 14/i18n/config/utils/types/styles/assets） | `apps/architect/src/` |
| `web/architect.html` | `apps/architect/src/architect.html` |
| `web/entry-architect.ts` | `apps/architect/src/main.ts` |
| `vite.architect.config.ts` | `apps/architect/vite.config.ts`（root=apps/architect/src；dev 5176 + 代理 `/api/architect`→3470；build outDir=`apps/architect/server/static`（服务自托管），entryFileNames 保持 `web/architect/assets/...` 相对结构或扁平化（与 server.py 静态路由对齐后定）） |
| `web/{architect.tsconfig.json,architect.eslintrc.cjs}` | `apps/architect/{tsconfig.json,.eslintrc.cjs}` |
| `web/main.ts.bak` | **删除**（bak 文件） |
| —（新建） | `apps/architect/package.json`（deps 按 import 扫描：vue/pinia/vue-router/cytoscape/cytoscape-cose-bilkent/marked/marked-highlight/highlight.js/mermaid 等）、`manifest.toml` 校正 |

### 3.2 后端（→ `apps/architect/server/`，包 `topoone_app_architect`）

| 现有路径 | 目标路径 |
|---|---|
| `plugins/architect/{server,ctx,common,dirs,git,store}.py`（server.py + arch_routes 顶层工具模块） | `apps/architect/server/`（server.py）+ `apps/architect/server/arch_routes/`（common/ctx/dirs/git/store 归 arch_routes 或 server 包，按 import 关系就近） |
| `plugins/architect/arch_routes/`（36 文件：agent_adapters/agent_config/agent/agent_server/arch_change/arch_git/asset_*/design/diagram/docs/execution/greenfield/kb_gateway/knowledge/mcp_collab/overview/project/req_agent/requirements/semantic_assets/tags/unit_test/websocket/zmq_stream/db_schema/__init__） | `apps/architect/server/arch_routes/`（整目录） |
| `plugins/architect/__main__.py` | `apps/architect/server/__main__.py`（`python -m topoone_app_architect`；sys.path 引导逻辑删除——editable 安装后 `topoone.*` 全局可见） |
| `plugins/architect/{plugin.json,plugin_entry.py}` | **删除**（plugin_entry 为 no-op 占位；architect 不再是插件） |
| `plugins/architect/static/`（构建产物） | `apps/architect/server/static/`（gitignore 产物；vite build 目标同步改） |
| `plugins/architect/tests/` | `apps/architect/tests/` |
| —（新建） | `apps/architect/server/{__init__.py,pyproject.toml}`（name=`topoone-app-architect`，deps: `topoone-core` + fastapi/uvicorn/websockets） |
| `apps/architect/manifest.toml` | 校正：`kind="service"`、`python_entry="topoone_app_architect:main"`（`__main__.py` 内 main 函数）、`static_dir="apps/architect/server/static"`、`static_mount=["/architect"]`、`api_prefixes=["/api/architect","/api/arch","/ws/kb-analysis"]`、`port=3470`、`pub_port=null`、env 增加 `KB_API_URL`/`LLM_API_URL`/`MCP_URL`（默认值同现状） |

**进程组装**：`__main__.py` 的 main() 逻辑不变（argparse --port/--host/--data-dir/--kb-url/--mcp-url + env 加载 + uvicorn server.app）；仅 import 路径更新（`sqlite_ctx`→`topoone.db`（若 architect 直接开库——现状经 self 建的 MultiDBManager 读共享库，改 `topoone.db.manager`）、`plugins.installer.targets`→`topoone.plugins.installer.targets`（M07 已迁）等，grep 全量确认）。

## 4. 执行任务

### 任务 13.1 后端迁移
- `git mv` §3.2 全部文件/目录；建包 + pyproject；`pip install -e apps/architect/server`
- import 更新：arch_routes 内部相对 import 不变；顶层 import 改 `topoone.*`；删除 sys.path 引导
- **验证**：`python -m topoone_app_architect --data-dir <dir>` 独立启动 :3470，`GET /health` 200，`GET /api/architect/projects`（或等价列表接口）冒烟

### 任务 13.2 前端迁移
- `git mv` §3.1 前端项；`apps/architect/vite.config.ts`
- architect-src 内对 web 共享件的引用（若有 `@web/` import——grep 确认，预期为 0，architect-src 自包含）→ 有则改 `@topo/web-core`
- G4（vue-tsc，app 内 tsconfig）+ G5（build → `apps/architect/server/static`，产物结构与 server.py 静态路由对齐验证）
- **验证**：全绿

### 任务 13.3 注册/路由/回归
- supervisor `_SERVICE_DEFS` architect 条目 script → `-m topoone_app_architect`
- gateway：`/architect` 静态（manifest static_mount）+ `/api/architect`、`/ws/kb-analysis` 反代（含 WS upgrade）确认
- PluginManager 不再发现 architect 插件（plugin.json 已删）；核心进程启动日志无 architect 相关 warning
- G2（合并方法集基线不变）+G3（apps/architect/tests 迁移后全绿）+G6+G7（/architect 深度 smoke：项目概览·语义资产页·1 次提取 agent 流式（经 llm 服务）·`/ws/kb-analysis` 流式正常）+G8
- dev 端口切换：architect dev 5175→5176；web-core 门户端口感知集合（M09 已含 5176）核对
- **验证**：全绿后提交；README §7 更新 M13 状态

## 5. 验收标准

1. `apps/architect/` 自包含（拆仓库能力验证：拷出 + core 包 + web-core 可独立构建/启动/测试）
2. G2–G8 全过；`/architect` 全部 URL 与功能现状不变（重点：WS 提取流式经网关 upgrade）
3. `plugins/architect/` 目录删除
4. architect 进程独立启停：kill 后 supervisor 重启，architect.db 数据无损

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| arch_routes 36 文件 import 面大（互引 + 引 backend-core 符号） | 整目录 `git mv` 保持相对 import；顶层 import 用 grep 清单逐一替换后跑 pytest（apps/architect/tests 覆盖 semantic_assets 等） |
| vite build 产物路径与 server.py 静态路由耦合（`web/architect/assets/...`） | 任务 13.2 显式对齐验证：构建后 `GET /architect` 200 + assets 加载无 404；若扁平化需同步改 server.py 路由 |
| `--kb-url`/`--mcp-url` 默认值依赖拓扑 | manifest env 显式声明默认值（127.0.0.1:3459/3460/3484），与 `_SERVICE_URLS` 一致 |
| architect 直接读共享 project.db（KbGateway 之外的路径） | grep `MultiDBManager`/`project.db` 直连点；若存在，保持只读语义不变（WAL），列入 13.1 验证清单（不直写 architect 之外库） |
