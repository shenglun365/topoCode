# CONV-03 子项目开发规约（apps/*）

> 适用：4 个现有子项目（workbench/docs/chat/architect）+ 未来新增子项目。
> 核心原则：**子项目 = `apps/<name>/` 下一个自包含目录**；manifest 声明一切；对核心零改动。

## 1. 标准目录结构（模板）

```
apps/<name>/
├── manifest.toml            # 注册元数据（§2，唯一注册点）
├── package.json             # 前端工程（npm workspace 成员 @topo/app-<name>）
├── vite.config.ts           # 独立 vite 工程（root=src，独立 dev 端口与 base）
├── tsconfig.json            # 独立 TS 工程
├── tailwind.config.js       # Tailwind（ctp 色 + 插件，从模板复制）
├── postcss.config.js        # tailwindcss + autoprefixer
├── vitest.config.ts         # （可选）前端单测
├── src/                     # 前端源码（<name>.html 入口 + vue/ts）
├── topoone_app_<name>/      # 后端包（kind=service 时）
│   ├── __init__.py          #   main()：FastAPI + uvicorn
│   ├── __main__.py          #   python -m topoone_app_<name>
│   ├── server.py            #   路由 + 静态自托管（可选）
│   └── static/              #   前端构建产物（architect 模式：服务自托管）
├── pyproject.toml           # topoone-app-<name>，deps 必含 topoone-core
├── tests/                   # pytest（后端）
└── dist/                    # 前端构建产物（gitignore；gateway 挂载模式）
```

## 2. manifest.toml 字段表（权威：`topoone/manifest.py:AppManifest`）

| 字段 | 必填 | 语义 |
|---|---|---|
| `name` | ✓ | 子项目名（唯一；冲突即 ManifestError） |
| `kind` | ✓ | `core`=薄层注册进 kb 进程（无独立进程）；`service`=独立进程（gateway 反代） |
| `python_entry` | ✓ | `module:func`（kind=core，如 `topoone_app_workbench.server:register_methods`）或 `module`（kind=service，supervisor 以 `python -m module` 拉起） |
| `static_dir` | ✓ | 前端产物目录（相对仓库根或绝对） |
| `static_mount` | 可选 | gateway 目录型资产挂载点（如 `["/app"]`）；服务自托管时为空 `[]` |
| `api_prefixes` | kind=service 必填 | REST 前缀列表，gateway 反代至 `service_url` 并统一鉴权 |
| `rpc_namespaces` | 可选 | 子项目注册进核心 RPC 总线的方法前缀（如 `["knowledge"]`） |
| `port` / `pub_port` | kind=service 必填 port | HTTP 端口 / ZMQ PUB 端口（事件流） |
| `host` / `health` | 可选 | 默认 `127.0.0.1` / `/health` |
| `env` | 可选 | supervisor 注入该进程的环境变量 |

**冲突检测**：`api_prefixes`/端口与其他 app 或核心保留前缀（`/api/rpc`、`/ws/`、`/api/architect` 等）重叠 → `validate_registry` 启动失败。

## 3. kind=core 与 kind=service 对比

| 维度 | kind=core（workbench） | kind=service（docs/chat/architect） |
|---|---|---|
| 进程 | 无独立进程，薄层注册进 kb | 独立进程（manifest port） |
| 后端代码 | `server.py:register_methods`（注册 RPC） | `__main__.py:main()`（独立 FastAPI 服务） |
| 业务 API | RPC（rpc_namespaces 前缀） | REST（api_prefixes）+ 可选 RPC |
| 静态托管 | gateway 挂载（static_mount） | gateway 挂载 **或** 服务自托管（architect：static_dir 指向包内 static，static_mount=[]） |
| 适用 | 与核心数据强耦合、无独立状态的薄层 | 有独立业务/独立 DB/独立团队演进 |

### 3.1 kind=core 薄层档准入标准（C2 合法化，MS7-W6 定案）

kind=core 是正式「薄层档」（0905 C2 kb god-process 维持现状+文档化裁决）。**准入**（三条同时满足）：

1. 注册方法 **≤ 20 个**（当前 workbench 7 个 knowledge.*）；
2. **无独立 DB**（数据全部落主库，读经进程内 multi_db）；
3. **无长阻塞任务**（无独立生命周期/后台轮询进程）。

**升级触发线**（任一命中 → 升级 kind=service，对齐 docs/chat 模式）：方法数 > 20；或出现长阻塞/独立生命周期任务；或需要独立 DB。

## 4. 后端包规约（topoone_app_*）

1. `pyproject.toml`：`name = "topoone-app-<name>"`，`dependencies` 必含 `topoone-core`；独立服务加 `fastapi`/`uvicorn`。
2. 进程入口 `python -m topoone_app_<name>`：读 env 端口（supervisor 注入）、绑 `127.0.0.1`（安全默认）、暴露 `/health`。
3. **DB 归属**：子项目新建表只建在**自己的库**（CONV-04 §5）；读核心数据走 RPC/HTTP（architect 经 HTTP 只读 project.db 是范本）；**禁止直连 topoone.db/project.db 写**。
4. LLM 调用走 llm 服务（`llm.chat`），不得自持 provider 客户端（遗留例外见 CONV-01 §4）。
5. 静态自托管模式（architect）：vite `outDir` 指向 `topoone_app_<name>/static`，`server.py` 挂 `/web/<name>`（资产）+ 页面路由；**该目录须 gitignore**（构建产物）。

## 5. 前端工程规约

1. 独立 vite 工程：`root=src`，独立 dev 端口（已用 5173–5176，新 app 顺延 5177+），独立 `base`（`/app` 用 `./`+trailing-slash 重定向模式；其余用绝对 base 如 `/docs/`）。
2. 资产路径唯一：`/<name>/assets/*` 或 `./assets/*`（root 应用），不得与他 app 重叠。
3. **鉴权客户端必须存在**（CONV-02 §2 token 行为）：
   - 复用 web-core：`installBrowserAPI`（workbench/docs/chat）；
   - 自包含 app：内嵌等价 `readToken()`（`#token=` 首粘 → localStorage `topocode:token`）+ 所有 fetch 带 Bearer + WS 带 `?token=`（architect 模式：`api-client.ts`/`ws-client.ts`/裸 fetch 三处都要带）。
4. 路由：hash 或 history 均可；SPA 页面路由由 gateway `vue_routes` serve HTML（或自托管），资产由挂载 serve。
5. 构建产物路径写入 manifest `static_dir`；`npm run build` 全量包含该 app。
6. **主题统一（明/暗切换）**：
   - 机制：`<html data-theme="dark|light">` + 共享 Catppuccin 变量（`@topo/web-core/styles/variables.scss`，别名 `--bg`/`--accent`/`--bubble-ai` 等已映射）。
   - 状态：`localStorage['topoone-theme-<appKey>']`，**每页独立记忆**（同域不互串）。
   - 复用 web-core：`useTheme(appKey)` / `initTheme(appKey)`（挂载前调用防闪烁）+ `<ThemeToggle app-key>` 组件。
   - 自包含 app（architect）：内嵌等价 composable + 入口 HTML 内联 bootstrap 脚本（读 `topoone-theme-<appKey>` 设 data-theme）。
   - 图表渲染须跟随主题（Mermaid/PlantUML 读取当前 `data-theme`，如 architect `useDiagramRenderer`/`diagram-gen.ts` 的 `currentDiagramPalette()`）。

## 6. 新子项目工程清单（防"architect 式"缺件，逐项打勾）

- [ ] `vite.config.ts`（root/base/dev 端口/outDir）
- [ ] `tsconfig.json`（strict 策略与现有 app 一致）
- [ ] `tailwind.config.js`（ctp 色以 `rgb(var(--ctp-x) / <alpha-value>)` 变量化 + `@tailwindcss/forms` + `@tailwindcss/typography`，content 指向本工程 src；global.css 定义 `:root`(Mocha) + `[data-theme="light"]`(Latte) 的 `--ctp-*` 三元组）
- [ ] `postcss.config.js`（tailwindcss + autoprefixer）
- [ ] `package.json` devDeps：vite/@vitejs/plugin-vue/vue-tsc/typescript/**tailwindcss/postcss/autoprefixer/@tailwindcss/forms/@tailwindcss/typography**（+ 复用 web-core 时 `"@topo/web-core": "*"`）
- [ ] 入口 HTML + `main.ts`
- [ ] **token 客户端**（web-core 或内嵌；验收：无 token 401、带 token 200）
- [ ] **主题引导**（入口 HTML 内联 bootstrap 脚本 + `initTheme` + toggle 按钮；验收：明/暗可切、每页独立记忆、刷新保持、无白闪）
- [ ] `manifest.toml`（§2 字段齐全；前缀/端口不冲突）
- [ ] `pyproject.toml` + 后端包 + `tests/`
- [ ] 根 `package.json` workspaces 自动发现（`apps/*` 通配，无需改）；CI/构建自动包含（`build:apps`/`test` 遍历）
- [ ] 验证：`npm run build` 全量绿 + `topo status` 进程数 +1 全 OK + 页面 URL 200 + 资产 200 + API 带 token 200

## 7. 现有 4 子项目源码范围与分工（权威边界）

### 7.1 workbench（工作台组）
| 项 | 值 |
|---|---|
| 源码范围 | `apps/workbench/src/`（224 文件）、`apps/workbench/topoone_app_workbench/`、`apps/workbench/server/`、`apps/workbench/tests/`（vitest smoke+unit） |
| 形态 | kind=core（薄层 `register_methods` 进 kb 进程，无独立进程） |
| 前端 | dev :5173，base `./`，页面 `/app`（gateway 307→`/app/`），资产 `/app/assets/*` |
| API 归属 | RPC 命名空间 `knowledge.*`；页面路由 `/app` |
| 不得触碰 | 其他 app 目录、core 基线方法、`/app` 以外 URL |

### 7.2 docs（文档组）
| 项 | 值 |
|---|---|
| 源码范围 | `apps/docs/src/`（12 文件，viewer+web-root 双 entry）、`apps/docs/topoone_app_docs/`、`apps/docs/tests/`（当前 0 文件，新增功能须补） |
| 形态 | kind=service，独立进程 :3481（PUB 5683） |
| 前端 | dev :5174，base `/docs/`，页面 `/viewer`·`/web-root`·`/projects`（gateway vue_routes serve），资产 `/docs/*`（gateway 挂载） |
| API 归属 | REST 27 前缀（`/doc`·`/code`·`/api/community-*`·`/api/file*`·`/api/plantuml*`·`/api/diagram*`·`/api/projects`·`/api/tasks`·`/api/docs`·`/api/export`·`/api/import`·`/api/verify` 等，见 manifest）；RPC 命名空间 `render.*`·`doc.*` |
| 不得触碰 | 其他 app、core 基线、`/docs/` 资产路径 |

### 7.3 chat（对话组）
| 项 | 值 |
|---|---|
| 源码范围 | `apps/chat/src/`（9 文件）、`apps/chat/topoone_app_chat/`、`apps/chat/tests/`（当前 0 文件，新增功能须补） |
| 形态 | kind=service，独立进程 :3483 |
| 前端 | dev :5175，base `/chat/`，页面 `/chat`（gateway serve chat.html），资产 `/chat/assets/*` |
| API 归属 | REST 前缀 `/api/chat`·`/api/models`·`/api/skills`·`/api/template-locale`·`/api/drafts`·`/api/notes` |
| 遗留 | 内置 LLM 客户端/skills/web_tools fallback 待瘦身（M12 任务 12.6，流式改经 llm 服务）——瘦身前不得扩大直连 provider 范围 |
| 不得触碰 | 其他 app、core 基线、`/chat/` 资产路径 |

### 7.4 architect（Architect 组）
| 项 | 值 |
|---|---|
| 源码范围 | `apps/architect/src/`（129 文件，**自包含，不依赖 web-core**）、`apps/architect/topoone_app_architect/`（server.py + arch_routes/ 35 文件 + static/ 构建产物）、`apps/architect/tests/`（9 文件 145 用例） |
| 形态 | kind=service，独立进程 :3470，**静态自托管**（static_dir=包内 static，static_mount=[]） |
| 前端 | dev :5176，页面 `/architect`（服务自 serve architect.html），资产 `/web/architect/assets/*` |
| API 归属 | REST 前缀 `/api/architect`（171 路由）+ 页面 `/architect` + 资产 `/web/architect`；WS `/api/architect/ws/kb-analysis` |
| 数据 | **独立 `architect.db`**（arch_* 表主写）；project.db/topoone.db 经 HTTP 只读（禁止直连写） |
| 对外集成 | MCP Server（core mcp :3460 转发至 architect `/api/architect/mcp/calls`，记录 External Call 日志） |
| 不得触碰 | 其他 app、core 基线、project.db 写路径 |

## 8. 子项目提交前检查清单

- [ ] `npm run typecheck -w @topo/app-<name>` + `npm run build -w @topo/app-<name>` 绿
- [ ] `python -m pytest apps/<name>/tests` 绿（新功能有测试）
- [ ] 全量 `npm run build`（确认未破坏他 app）
- [ ] `topo serve` 后本 app 页面 URL 200 + 资产 200 + API 带 token 200 / 无 token 401
- [ ] 新增 REST 前缀/RPC 方法已写入 manifest（前缀冲突即启动失败，本地先验）
- [ ] 未 import 其他 app、未直连他库、未改 core
