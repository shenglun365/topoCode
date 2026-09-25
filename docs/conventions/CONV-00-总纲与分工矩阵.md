# CONV-00 总纲与分工矩阵

> 版本 v1.0 | 2026-08-21 | 适用：所有参与 TopoOne 工程开发的团队/个人
> 本规约集共 5 篇：CONV-00 总纲 / CONV-01 核心框架 / CONV-02 前端共享内核 / CONV-03 子项目规约 / CONV-04 API 契约与门禁

## 1. 工程形态

Monorepo（npm workspaces + pip editable）：**1 个核心基础框架 + 1 个前端共享内核 + 4 个独立子项目**，运行时为 **9 个独立进程**（核心 kb/gateway/llm/agent + 生态 mcp/runner + manifest 服务 docs/chat/architect；拓扑以 `supervisor/cli.py` 注册表为准——原 agent-bus broker 已随生命周期重构 v2 退役，消息面由会话单流 + 事件泵承载），由 `topo serve`（supervisor）统一拉起，`gateway:3456` 是唯一对外入口。

> 口径注（MS1 D3，2026-09-24 核证）：agent-bus 退役后进程数**恒为 9**（`supervisor/cli.py` `_FIXED_SERVICES` 6 项 + manifest `kind=service` 3 项）；历史文档中「10 进程」均为退役前笔误。进程数变更必须过 G6 门禁并同步本节拓扑图。

```
                    浏览器（唯一入口 :3456）
                          │
                 ┌────────┴────────┐
                 │  gateway :3456  │  反代 / RPC 命名空间路由 / 鉴权 / SPA 静态
                 └────────┬────────┘
     ┌─────────┬──────────┼──────────┬──────────┬──────────┐
     │         │          │          │          │          │
  kb:3459  llm:3484   agent:3482  mcp:3460  runner:3458   （核心 6 进程）
  引擎+数据  LLM 推理   Agent 工作流  MCP 接口  Coding Agent 执行
     │
     │  apps（子项目 3 进程 + 1 薄层）
     ├── docs:3481     文档浏览
     ├── chat:3483     AI 对话
     ├── architect:3470 Architect 工作台（独立 architect.db）
     └── workbench（kind=core，无独立进程，薄层注册进 kb）
```

## 2. 代码归属总表

| 代码位置 | 包名 | 形态 | 职责 |
|---|---|---|---|
| `packages/core/` | `topoone-core`（pip editable） | Python | 核心框架：引擎/网关/进程治理/RPC/DB/LLM/Agent/核心插件 |
| `packages/web-core/` | `@topo/web-core`（npm workspace） | Vue3 | 前端共享内核：RPC 客户端/共享组件/i18n/门户首页 |
| `apps/workbench/` | `@topo/app-workbench` + `topoone_app_workbench` | Vue3 + Python | 主工作台（导入/分析/可视化/知识库） |
| `apps/docs/` | `@topo/app-docs` + `topoone_app_docs` | Vue3 + Python | 文档浏览（viewer/web-root + render.* RPC） |
| `apps/chat/` | —（FE 已并入 workbench，MS7-W3） | Python | chat 后端域托管（MS7-W4）：包体 `apps/workbench/chat_service/topoone_app_chat`，manifest 留 `apps/chat/`（gateway 发现约定），:3483 独立进程 |
| `apps/architect/` | `@topo/app-architect` + `topoone_app_architect` | Vue3 + Python | Architect 工作台（语义资产/需求/设计/Coding Agent） |
| `build/` | — | Node 脚本 | core bundle（render-worker / plugins / modules） |
| `scripts/` | — | Shell/Python | serve / setup / rpc-baseline 等开发脚本 |

## 3. 分工矩阵（模块 × 源码范围 × 可变性 × 验证）

| 模块 | 源码范围（owner） | 冻结契约（不得破坏） | 修改方 | 必跑门禁 |
|---|---|---|---|---|
| 核心框架 | `packages/core/topoone/{engine,gateway,supervisor,rpc,db,messaging,llm,agent,plugins,manifest.py}` | RPC 218 方法基线、9 进程拓扑与端口表、URL 布局、`~/.topocode` 数据布局 | 核心组 | G2+G3+G6（+G7/G8 若动 gateway） |
| 前端共享内核 | `packages/web-core/src/` + `dist-portal/`（构建产物） | 导出 API（index.ts）、token 客户端行为、门户 URL（/ · /home） | 前端基础组 | G4+G5+G7（type-check/build/5 SPA） |
| workbench | `apps/workbench/{src,topoone_app_workbench,server,tests}` + manifest | `/app` URL、`/app` 资产路径、`knowledge.*` RPC 命名空间 | 工作台组 | G3+G4+G5+G6+G7 |
| docs | `apps/docs/{src,topoone_app_docs,server,tests}` + manifest | `/docs/` 资产路径、`/viewer·/web-root·/projects` URL、`render.*·doc.*` RPC、`:3481` | 文档组 | 同上 |
| chat | `apps/workbench/chat_service/{topoone_app_chat,tests}` + `apps/chat/manifest.toml` | `/api/chat·/api/models·/api/skills·/api/template-locale·/api/drafts·/api/notes` 前缀、`:3483` | 对话组 | FE 页面 `/chat` 由 workbench SPA 客户端路由承载（MS7-W3） |
| architect | `apps/architect/{src,topoone_app_architect,tests}` + manifest | `/architect` 页面、`/web/architect/` 资产路径、`/api/architect` 前缀、`:3470`、`architect.db` 独立 | Architect 组 | 同上 + WS kb-analysis |

## 4. 四大边界规则（所有模块共同遵守）

1. **依赖单向，禁止环**
   - 后端：`topoone_app_*` → `topoone-core` 允许；**core 永远不得 import 任何 `topoone_app_*`**。
   - 前端：apps → `@topo/web-core` 允许；**web-core 不得 import 任何 app**。
   - **app 之间禁止互相 import**（跨子系统通信只走 RPC/HTTP/WS）。
2. **进程边界 = 数据边界**
   - 每个进程独占自己的 DB（见 CONV-04 §5 数据归属表）。
   - 跨进程取数只许 RPC/HTTP，**禁止跨进程直连他库**（architect 经 HTTP 只读 project.db 是范本）。
3. **manifest = 唯一注册点**
   - 子项目的 `kind/port/api_prefixes/static_mount/python_entry` 全部声明在 `apps/<name>/manifest.toml`。
   - gateway/supervisor 经 `discover_apps` 自动发现；**前缀/端口冲突即启动失败**（fail-fast，不留静默冲突）。
   - 新增子项目对核心代码零改动。
4. **契约冻结，基线比对**
   - 核心 RPC 218 方法集冻结于 `packages/core/rpc-method-baseline.json`。
   - 动核心契约必须重生成基线 + 全量回归，并在提交说明中列出新增/变更方法。

## 5. 变更路径判定（先改哪里）

| 需求 | 改哪里 | 不动哪里 |
|---|---|---|
| 某子项目新功能（UI/业务） | `apps/<name>/src` + `apps/<name>/topoone_app_*` | core、web-core、其他 app |
| 子项目需要核心新能力（如新 RPC） | core 新增方法 + 更新基线 + 全量回归；app 侧调用 | 不改已有方法语义 |
| ≥2 个 app 复用同一前端组件 | 上提 `packages/web-core/src` | 各 app 删除本地副本 |
| 新增第 5 个子项目 | 按 CONV-03 §7 模板新建 `apps/<name>/` | core、gateway、supervisor 零改动 |
| 端口/URL 布局调整 | 属核心契约变更：supervisor 固定表 + manifest + gateway，走核心组评审 | — |

## 6. 角色建议（可合并兼任）

| 角色 | 拥有模块 | 主要职责 |
|---|---|---|
| 核心组 | topoone-core | 引擎/网关/进程治理/RPC/DB/LLM/Agent；维护 218 基线与 9 进程拓扑 |
| 前端基础组 | @topo/web-core | 共享组件/i18n/RPC+token 客户端/门户；执行上提/下沉 |
| 工作台组 | apps/workbench | 导入/分析/可视化/知识库 |
| 文档组 | apps/docs | viewer/web-root + render/doc RPC |
| 对话组 | apps/workbench/chat_service（chat） | 会话/技能/草稿 |
| Architect 组 | apps/architect | 语义资产/需求/设计/Coding Agent 集成 |

> 团队小于角色数时合并兼任即可；**分工矩阵（§3）的"修改方"列是边界权威**，与人数无关。

## 7. 术语表

| 术语 | 含义 |
|---|---|
| manifest | `apps/<name>/manifest.toml`，子项目注册元数据（字段见 CONV-03 §2） |
| kind=core | 子项目薄层注册进 kb 进程（无独立进程），如 workbench |
| kind=service | 子项目独立进程，gateway 反代其 api_prefixes，如 docs/chat/architect |
| RPC 基线 | `packages/core/rpc-method-baseline.json`，核心 218 方法冻结集 |
| api_prefixes | 子项目 REST 前缀，gateway 反代到子进程并统一鉴权 |
| rpc_namespaces | 子项目注册进核心 RPC 总线的方法前缀（如 `knowledge.*`、`render.*`） |
| 门禁 G1–G8 | 见 CONV-04 §6 |

## 8. 规约集索引

| 文档 | 内容 | 读者 |
|---|---|---|
| CONV-01 核心框架 | topoone-core 源码范围/冻结契约/修改规则 | 核心组 + 所有需调用核心者 |
| CONV-02 前端共享内核 | web-core 源码范围/上提下沉准则/使用方式 | 前端基础组 + 所有前端开发 |
| CONV-03 子项目规约 | 子项目目录模板/manifest 字段/工程清单/各 app 范围/新子项目步骤 | 各子项目组 |
| CONV-04 API 契约与门禁 | API 归属/调用格式/端口与 URL 总表/数据归属/G1–G8/测试命令 | 所有开发（提交前必读） |
