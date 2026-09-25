# TopoCode

> **English** · [English](README.en.md)

<p align="center">
  <picture>
    <source srcset="assets/star-logo-zh.svg" type="image/svg+xml">
    <img src="docs/logo-zh.png" alt="TopoCode" width="660">
  </picture>
</p>

> 源码架构深度分析工具 —— 面向「深度代码学习」场景的「分析显微镜」，提升人的架构认知水平。

TopoCode 不是一句提示词生成架构图的效率工具，而是帮助你逐层理解项目架构、**提升架构认知能力**的分析平台。通过静态代码解析、依赖图计算、社区发现算法和 AI 辅助分析，挖掘代码背后的设计逻辑与模块关系，帮助开发者真正理解陌生项目的架构设计。

---

> **隐私说明**：除用户自行配置的云端 LLM API 外，TopoCode 的代码解析、图计算、架构分析、Web 文档服务等所有功能均在**本地运行**，项目源码和解析数据不会上传至任何外部服务器，确保用户数据隐私安全。

## 功能特性

- **项目导入与管理** — 支持本地目录导入、文件树浏览、分组管理
- **多语言代码解析** — 基于 Tree-sitter 的 AST 解析，支持 18+ 编程语言
- **架构可视化** — 依赖图/调用图/社区结构图（D3.js / Cytoscape），支持交互式浏览
- **社区发现** — Louvain / Leiden 算法自动识别代码模块（社区）结构
- **AI 架构分析** — LLM 驱动的工作流，自动分析组件功能、生成架构概览文档
- **交互式 AI 助手** — 基于项目上下文的智能问答，支持工具调用（符号搜索、文件读取等），通过本地 Web 端口提供浏览器端对话界面
- **知识库** — 分析文档持久化存储（分类管理待实现）。知识库是迭代重点，目标是成为与用户认知高度契合的**外脑知识库**，不仅静态存储，未来还将支持通过多种对接方式，帮助用户指挥驾驭其他 Agent 工具，实现知识的**存储 → 分析 → 使用**闭环
- **Web 文档服务** — 本地 HTTP 服务（默认 3456 端口），浏览器中浏览架构文档和使用 AI 对话
- **多语言支持** — 中文 / English 界面与 AI 分析输出

> **补充说明 — 代码生成项目**：TopoCode 直接解析磁盘上的源码文件，不依赖完整编译环境。如果项目包含代码生成步骤（如 protobuf、graphql-codegen、`go generate` 等），生成的源码不在原始代码中，直接导入不会包含这些生成文件。**如需更全面的分析**，可在导入前手动执行代码生成命令，使生成的源码纳入分析范围。请按需分析，不必强求覆盖所有生成代码。
>
> 常见代码生成命令示例：
>
> | 语言 | 典型代码生成场景 | 导入前可执行 |
> |---|---|---|
> | C / C++ | autoconf 生成 config.h / yacc / bison / flex / Qt MOC / protobuf | `./configure` / `bison -d parser.y` / `moc header.h` / `protoc --cpp_out=.` |
> | Go | stringer / mockgen / protobuf | `go generate ./...` / `protoc --go_out=.` |
> | TypeScript | graphql-codegen / protobuf-ts / openapi-generator | `npx graphql-codegen` / `protoc --ts_out=.` |
> | Dart | freezed / json_serializable / drift / protobuf | `dart run build_runner build` / `protoc --dart_out=.` |
> | Java | protobuf / Dagger / MapStruct 等注解处理器 | `protoc --java_out=.` |
> | Kotlin | protobuf / KSP | `protoc --kotlin_out=.` |
> | Swift | protobuf / Sourcery | `protoc --swift_out=.` / `sourcery --sources ...` |
> | C# | protobuf / T4 模板 | `protoc --csharp_out=.` |
> | Python | protobuf / Cython | `protoc --python_out=.` |
> | 其他语言 | protobuf / thrift / gRPC 等代码生成器 | 对应语言代码生成命令 |

---

## 技术栈

| 层级 | 技术 |
|---|---|
| **前端框架** | Vue 3 + TypeScript + Pinia + Vue Router |
| **UI 样式** | Tailwind CSS + SCSS + Heroicons |
| **可视化** | D3.js + Cytoscape + Mermaid + PlantUML + PixiJS |
| **交付形态** | Web 应用（浏览器访问，本地 Web 服务 :3456） |
| **后端语言** | Python 3.10+ |
| **IPC 通信** | ZeroMQ (pyzmq) |
| **代码解析** | Tree-sitter (18+ 语言) |
| **符号索引（外部工具）** | codegraph CLI —— architect 语义资产的符号源（目标项目 `.codegraph/codegraph.db`）；缺失时自动降级为轻量文件扫描（`topo doctor` 可检测） |
| **图计算** | NetworkX + python-louvain + leidenalg + python-igraph |
| **Web 服务** | FastAPI + Uvicorn |
| **AI 推理** | OpenAI / Ollama / LM Studio 兼容接口 |
| **数据库** | SQLite + DuckDB |

---

## 使用教程

详细使用流程文档编写中。当前请参考上方「安装与运行」「配置 LLM」「Web 服务 & AI 助手」「开发」章节。

---

## 目录结构

> Monorepo（npm workspaces + pip editable）：1 个核心基础框架 + 4 个独立子项目。

```
topoOne-ui/
├── packages/
│   ├── core/                     # 核心基础框架（topoone-core，editable 安装）
│   │   └── topoone/
│   │       ├── engine/           # 引擎（app/service/task_manager/report_service/diagram_ir_docs）
│       ├── diagram/          # 统一图内核（DiagramSchema IR + validation/capabilities + builder + plantuml sidecar + 无头渲染池）
│   │       ├── gateway/          # 网关（:3456 反代 + RPC 路由 + 鉴权 + SPA 静态）
│   │       ├── supervisor/       # 进程治理（topo serve 拉起 9 进程）
│   │       ├── rpc/              # ZeroMQ RPC 服务
│   │       ├── db/               # SQLite 多数据库管理
│   │       ├── agent/            # AI Agent 工作流
│   │       ├── llm/              # LLM 推理服务
│   │       ├── plugins/          # 核心插件（parsers/community/mcp/runner/llm-provider-*）
│   │       └── manifest.py       # 子项目 manifest 驱动注册
│   └── web-core/                 # 前端共享内核（@topo/web-core：组件/服务/门户 dist-portal）
├── apps/                         # 独立子项目（各自 vite 工程 + Python 后端包）
│   ├── workbench/                # ① 主工作台（topoone_app_workbench + @topo/app-workbench）
│   ├── docs/                     # ② 文档浏览（topoone_app_docs :3481 + @topo/app-docs）
│   ├── chat/                     # ③ AI 对话（topoone_app_chat :3483 + @topo/app-chat）
│   └── architect/                # ④ Architect 工作台（topoone_app_architect :3470 + @topo/app-architect）
├── build/                        # 构建脚本（bundle-worker/plugin/module）
├── scripts/                      # 开发脚本（serve.sh / setup.sh / rpc-baseline）
└── docs/                         # 工程规约（conventions/CONV-00~04）+ 数据库设计
```

### 子项目说明

| 子项目 | 前端 | 后端 | 端口 | 职责 |
|---|---|---|---|---|
| **workbench** | `@topo/app-workbench` | `topoone_app_workbench` | `/app` | 主工作台（导入/分析/可视化/知识库） |
| **docs** | `@topo/app-docs` | `topoone_app_docs` | `:3481` | 文档浏览（viewer/web-root，render.* RPC） |
| **chat** | `@topo/app-chat` | `topoone_app_chat` | `:3483` | AI 对话（会话/技能/草稿） |
| **architect** | `@topo/app-architect` | `topoone_app_architect` | `:3470` | Architect 工作台（语义资产/需求/设计/Coding Agent） |

> 核心框架（`packages/core`）提供网关、RPC、DB、Agent、LLM、插件与进程治理；子项目经 manifest 驱动注册，独立进程运行，由 `topo serve` 统一拉起（9 进程：核心 kb/gateway/llm/agent + 生态 mcp/runner + manifest 服务 docs/chat/architect；拓扑以 `supervisor/cli.py` 注册表为准——原 agent-bus broker 已随生命周期重构 v2 退役，消息面由会话单流 + 事件泵承载）。

### Coding Agent 执行器（runner :3458）

architect 实施作业经 runner 执行，支持三类执行器（`agent/executors` 注册表可配，**cline 为默认**）：

| 执行器 | 机制 | 会话/多回合 | 审批 | 检查点 | 备注 |
|---|---|---|---|---|---|
| **cline**（默认） | `@cline/core` ClineCore 会话宿主（Node ≥22 sidecar） | ✓ 常驻多回合（sessionRef 复活） | ✓ toolPolicies 白名单 + 越界审批桥（`/approve` `/deny` 或 UI 按钮） | ✓ git 快照 restore/compare | 自定义协议工具 `report_turn_outcome`（done/need_input 结构化收口）、MCP server 注入（单失败降级）、Teams、steer 直达、会话内换模；存储隔离 `~/.topocode/cline/` |
| **opencode** | `opencode serve` HTTP + SSE | ✓（serve 重启自动重建会话） | 权限一律 allow 白名单（无头防挂起），readOnly 靠协议约束+验收把关 | ✗ | 权限/经 `OPENCODE_CONFIG_CONTENT` 内联注入；实例空闲自动回收 |
| **codex** | `codex app-server` stdio JSON-RPC | ✓ thread 续 | approvalPolicy=never + sandbox（readOnly→read-only 沙箱） | ✗ | 完成信号为文本标记契约（无自定义工具）；错误退避 2s/4s |

runner 作业面：`POST /api/implement`（worktree+分支，支持 `workspaceFiles` 规约/规则/agent 配置落盘）；作业内省 `GET /api/implement/{id}/messages|usage|pending`、`/checkpoints?runCount=N`、`POST /{id}/restore|model|approval|proceed|steer(input)`。执行器能力差异由 runner 能力分派自动降级（不支持时明确报"不支持"）。

---

## 安装与运行

### 推荐运行环境

- **CPU**: 4 核心及以上
- **内存**: 16 GB 及以上
- **系统**: Linux / macOS / Windows（物理机或虚拟机均可）
- **硬盘**: 至少 10 GB 可用空间（用于存储解析数据和知识库）

> **本地模型硬件要求**：运行 Qwen3.6-9B-Q4 量化等本地模型建议 **NVIDIA RTX 4060 Ti 16GB 或以上** 显卡。如果没有独立 GPU，本地模型将使用 CPU 推理，速度会慢得多。如果仅使用云端模型（如 DeepSeek V4 Flash），4 核 8G 配置也可满足基本使用。

> **运行形态**：本软件为 Web 应用（浏览器访问），无桌面端依赖，服务器/虚拟机/容器均可直接运行，无需虚拟显示（xvfb）。

### LLM 分析效率预估

架构分析各阶段耗时受**代码规模**、**LLM 性能**和**并发配置**影响。以下为典型预估（单并发，50 tokens/s）：

| 阶段 | 预估耗时 | 说明 |
|---|---|---|
| **语法解析 + 组件关系分析** | 2~5 分钟 | 纯静态分析，不依赖 LLM |
| **5000 源码文件分析** | 10~20 分钟 | 文件遍历与基础元数据提取 |
| **文件预摘要** | ~1 分钟 / 个 | 数百文件需数小时，LLM 密集阶段 |
| **组件分析** | 1~5 分钟 / 个 | 受组件规模影响，需多轮 LLM 对话 |
| **整体架构生成** | 1~5 分钟 | 综合摘要生成架构概览 |

> **加速建议**：您可以注册账户，通过 **用户中心 → 资源中心** 获取预分析好的架构内容，资源中心会定期更新热门项目的分析数据，免去本地等待时间。

### 前置要求

- **Node.js** >= 20.0.0
- **Python** >= 3.10
- **npm** 或 **pnpm**
- **pip**

### 1. 一键安装

```bash
# 创建 .venv + pip install -e（核心 + 4 子项目后端）+ npm install（workspaces）
npm run setup
```

> 手动分步（等价于 `npm run setup`）：
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -e packages/core -e apps/workbench -e apps/docs -e apps/architect -e apps/workbench/chat_service
> npm install
> ```

### 2. 运行

```bash
# 全栈开发（core 后端 + 4 前端 dev server 并发）
npm run dev

# 仅后端服务集（supervisor 拉起 9 进程，:3456）
npm run serve          # 等价于 topo serve

# 查看进程状态 / 停止
npm run status         # 等价于 topo status
bash scripts/serve.sh stop
```

> 亦可直接用 `topo` CLI（安装后即全局可用）：`topo serve` / `topo status` / `topo doctor` / `topo init` 等。

首次启动会生成访问 token（见终端输出）。浏览器访问: `http://localhost:3456/#token=<token>`

### 图表渲染（topo 内核）部署说明

图渲染统一走 `packages/core/topoone/diagram` 内核（DiagramSchema IR 单一事实源，mermaid/plantuml
引擎可插拔）。docs 服务 `:3481` 挂载 `/api/topo`（gateway 自动反代）：

- **PlantUML**：优先启动 sidecar（独立 JVM `:3491`）。需 plantuml jar，部署时复制到
  `~/.topocode/plantuml.jar`（与既有 `plantuml_service` 共用；可用 `TOPOONE_PLANTUML_JAR` 覆盖）。
  sidecar 未就绪时自动兜底：本地 jar → 远程 plantuml.com。
- **无头渲染池**（`/api/topo/render/mermaid`、`/render/schema`）：chromium 跑 web-core 的 IIFE bundle
  （`packages/web-core/dist-topoone/topo-one.js`，`npm run build:topoone-browser` 生成）。需
  `pip install -e "packages/core[diagrams]"` + `playwright install chromium`；未装则 render/* 返回 503。
- 浏览器端 mermaid 主线程渲染、plantuml 经 `/api/topo/plantuml/svg` 同源访问（见 web-core
  `useTopoRender` / `DiagramViewer`）。

| URL | 说明 |
|---|---|
| `/` · `/home` | 统一门户首页 |
| `/app` | 主工作台（workbench） |
| `/projects` · `/viewer` · `/web-root` | 文档浏览（docs） |
| `/chat` | AI 对话（chat） |
| `/architect` | Architect 工作台（architect） |

### 3. 构建

```bash
# core bundle（worker/plugin/module）+ portal + 4 子项目前端
npm run build
```

---

## 配置 LLM

启动应用后，在 **设置 → 模型配置** 中添加 LLM 模型。支持任何兼容 OpenAI API 格式的提供商。

### 模型选择建议

| 用途 | 推荐方案 | 说明 |
|---|---|---|
| **架构解析 (Agent 工作流)** | 本地模型 Qwen3.6-9B 及以上 (Ollama / LM Studio) | 架构解析需要大量 token，涉及多轮工具调用和文件摘要。**建议本地部署**，节省费用且保证响应速度 |
| **AI Chat 对话** | 云端高级模型，如 **DeepSeek V4 Flash** | 交互式对话对模型能力要求较高，DeepSeek V4 Flash 性价比优异。也可根据需求选择 GPT-4o / Claude 等 |

### 常见配置

- **Ollama 本地模型**: `http://localhost:11434`
- **OpenAI 协议兼容**（支持所有兼容 OpenAI API 格式的模型服务，如 DeepSeek、Qwen 等）: `https://api.openai.com`
- **DeepSeek**: `https://api.deepseek.com`
- **LM Studio**: `http://localhost:1234`

---

## Web 服务 & AI 助手

应用运行后，**所有界面均通过本地 Web 服务提供**，默认监听 `http://localhost:3456`（URL 布局见上方「运行」表格）。可通过 **设置 → 通用设置** 修改 HTTP 端口与绑定地址。

### PlantUML 渲染服务

Web 文档和 AI 对话中的 PlantUML 图表需要一个渲染服务。**建议自行部署本地 PlantUML 服务**，以确保数据安全、响应速度和稳定性。

前端统一通过后端代理 `/api/plantuml`（POST）转发，后端负责编码并请求 PlantUML 服务器，不受 URL 长度限制。

推荐使用 Docker 部署（国内用户可使用镜像加速）：

```bash
# 阿里云镜像
docker run -d --name plantuml -p 8300:8080 registry.cn-hangzhou.aliyuncs.com/dockerhub-mirror/plantuml/plantuml-server:jetty

# 官方镜像
docker run -d --name plantuml -p 8300:8080 plantuml/plantuml-server:jetty
```

部署后设置后端环境变量（如 `docker-compose.yml` 或 systemd）：

```bash
PLANTUML_SERVER=http://localhost:8300
```

默认值为 `http://www.plantuml.com/plantuml`，内网环境必须改为自建地址。

修改后重启 Python 后端服务生效。

### MCP Server

对外部 Agent/工具提供 Model Context Protocol（HTTP）接口，独立进程监听 `:3460`，工具调用转发至 architect 服务（`:3470`）。

```bash
# 独立启动（topo serve 会随 9 进程自动拉起，通常无需手动启动）
python -m topoone.plugins.mcp
```

外部 Agent 接入端点：

| 端点 | 说明 |
|---|---|
| `GET http://localhost:3460/v1/tools` | 列出可用工具（arch.read / arch.write / arch.invoke / arch.status） |
| `POST http://localhost:3460/v1/tools/{tool_name}/call` | 执行工具调用（转发至 architect） |

> MCP 接入路径变更（工程拆分 M08）：由旧 `python plugins/mcp_server/server.py` 变更为 `python -m topoone.plugins.mcp`；客户端为 HTTP 模式（非 stdio），仅需将接入地址指向 `http://localhost:3460`。

### 完整配置项

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `VITE_API_BASE` | API 基础地址 | `https://topocode.cn` |
| `VITE_DISABLE_MOCK` | 禁用 Mock 数据 | `true` |

---

## 开发

> **模块分工与边界规约**（分子系统/子模块开发前必读）：`docs/conventions/`
> CONV-00 总纲与分工矩阵 / CONV-01 核心框架 / CONV-02 前端共享内核 / CONV-03 子项目规约（含新子项目模板）/ CONV-04 API 契约与验证门禁

```bash
# 代码检查
npm run type-check    # 全 workspace TypeScript 类型检查
npm run lint          # ESLint 代码风格检查

# 测试
npm run test          # 后端 pytest（core + 4 子项目）+ 前端 vitest（workbench + web-core）
npm run test:py       # 仅后端
npm run test:fe       # 仅前端

# 单子项目（示例）
npm run dev -w @topo/app-architect    # architect 前端 dev
npm run build -w @topo/app-docs       # docs 前端构建
python -m pytest apps/architect/tests # architect 后端测试
```

---

## 许可证

[Apache License 2.0](LICENSE)

---

## 联系我们

- 开发者邮箱: **topocode@163.com**
- 项目地址: [https://github.com/topocode/topoone-ui](https://github.com/topocode/topoone-ui)
- 问题反馈: [https://github.com/topocode/topoone-ui/issues](https://github.com/topocode/topoone-ui/issues)
