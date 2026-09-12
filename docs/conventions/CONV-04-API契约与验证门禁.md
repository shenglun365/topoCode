# CONV-04 API 契约与验证门禁

> 所有开发提交前必读。本文件是"接口归属 + 端口/URL 总表 + 数据归属 + 回归门禁"的单一权威。

## 1. API 归属总表（谁拥有哪段 API）

| API 段 | Owner | 传输 | 备注 |
|---|---|---|---|
| `POST /api/rpc/{method}`（218 核心方法：project.*·analysis.*·settings.*·llm.*·model.*·system.*·resource.*·architecture.*） | 核心组 | RPC（body=params，返回 `{result}`） | 冻结基线 `packages/core/rpc-method-baseline.json` |
| RPC `knowledge.*` | 工作台组 | RPC（gateway 命名空间路由 → kb） | workbench manifest `rpc_namespaces` |
| RPC `render.*`·`doc.*` | 文档组 | RPC（→ docs :3481） | docs manifest `rpc_namespaces` |
| REST `/api/chat`·`/api/models`·`/api/skills`·`/api/template-locale`·`/api/drafts`·`/api/notes` | 对话组 | REST（gateway 反代 → chat :3483） | 响应 `{code,message,data}` |
| REST `/doc`·`/code`·`/api/community-*`·`/api/file*`·`/api/plantuml*`·`/api/diagram*`·`/api/projects`·`/api/tasks`·`/api/docs`·`/api/export`·`/api/import`·`/api/verify`（27 前缀） | 文档组 | REST（→ docs :3481） | 见 docs manifest |
| REST `/api/architect/*`（171 路由）+ WS `/api/architect/ws/kb-analysis` | Architect 组 | REST/WS（→ architect :3470） | 含 `/api/architect/mcp/calls`（MCP 外部调用记录） |
| MCP 工具接口 `GET /v1/tools`·`POST /v1/tools/{name}/call`（:3460，外部 Agent 直连） | 核心组（mcp 插件） | HTTP | 工具调用转发 architect |
| WS `/ws/events`（任务/导入/LLM 流式事件桥） | 核心组 | WebSocket（ZMQ SUB 5681 转发） | 4 topic：task/project/backend/llm |
| SPA 页面路由 `/`·`/home`·`/app`·`/projects`·`/viewer`·`/web-root`·`/chat`·`/architect` | 核心组（gateway vue_routes）+ 各 app 提供 HTML | — | URL 布局冻结（CONV-01 §2.3） |

**新增 API 规则**：子项目新 REST 路由必须落在自己 manifest `api_prefixes` 内；新 RPC 方法必须带自己 `rpc_namespaces` 前缀（核心前缀归核心组）。**不得占用他人前缀**（冲突 = manifest 校验失败或线上串流）。

## 2. 调用格式契约

### 2.1 RPC（前端 → 网关）
```
POST /api/rpc/{method}
Headers: Authorization: Bearer <token>   （或 ?token=）
Body:    { ...params }                    （JSON，即方法参数）
200:     { "result": ... }
401:     { "detail": "unauthorized: ..." }
404:     { "detail": "Method xxx not found" }
```

### 2.2 子项目 REST（architect 示例）
```
GET/POST /api/architect/...
200: { "code": 0, "data": ... }        code≠0 → { "code": n, "message": "..." }
401: 无/错 token（网关层拦截）
```

### 2.3 鉴权（全局）
- token 生成于 `~/.topocode`（`topo serve` 首启打印）；未生成时放行（开发态），生成后强制。
- 载体：`Authorization: Bearer <token>` 或 `?token=<token>`（WS 同）。
- 前端：localStorage key `topocode:token`（同源共享）；首粘 `http://<host>:3456/#token=<token>`。
- 豁免路径：静态资产、`/health`、`/ws/`（事件桥除外）。

## 3. 端口总表（冻结）

| 用途 | 端口 |
|---|---|
| gateway（唯一对外入口） | 3456 |
| kb（引擎+数据） | 3459 |
| runner（Coding Agent 执行） | 3458 |
| mcp（MCP Server） | 3460 |
| architect | 3470 |
| agent | 3482 |
| chat | 3483 |
| llm | 3484 |
| docs | 3481 |
| ZMQ PUB：kb 事件 / llm 流式 / docs 事件 / agent 事件 | 5681（单一源 `config.KB_PUB_PORT`）/ 5682 / 5683 / 5684 |
| 前端 dev（vite）：workbench / docs / chat / architect | 5173 / 5174 / 5175 / 5176（新 app 顺延 5177+） |
| PlantUML 渲染服务（外部，建议自部署） | 8300（env `PLANTUML_SERVER`） |

## 4. URL 布局总表（冻结）

| URL | 说明 | 资产路径 |
|---|---|---|
| `/` · `/home` | 门户首页（web-core dist-portal） | `/assets/*` |
| `/app`（307→`/app/`） | workbench | `/app/assets/*` |
| `/projects` · `/viewer` · `/web-root` | docs 页面 | `/docs/*` |
| `/chat` | chat 页面 | `/chat/assets/*` |
| `/architect` | architect 页面（服务自托管） | `/web/architect/assets/*` |
| `/api/rpc/{method}` | RPC | — |
| `/ws/events` | 事件桥 | — |

## 5. 数据归属表（`~/.topocode`，进程=数据边界）

| 数据 | Owner 进程 | 规则 |
|---|---|---|
| `topoone.db`（main：projects/analysis_tasks/model_configs/agent_* 等 24 表） | kb（核心） | 子项目**读**经 RPC/HTTP；写仅核心 |
| `projects/<pid>/project.db`（26 表：AST/社区/LLM 结果/agent_task_history 等） | kb（核心） | 同上（architect 经 HTTP 只读） |
| knowledge / sessions / chat 各库 | kb / llm / chat | 各 owner 独占 |
| `architect.db`（arch_* 表） | architect :3470 | architect 独占；其中 `arch_bus_messages`（非项目路由全局单表）由 agent-bus :3486 共享，broker 读写边界=仅该表（create/mark/pending/list） |
| docs 业务表（web_root 等） | docs :3481 | docs 独占 |
| `~/.topocode/token`、`logs/`、`source-cache/` | gateway/supervisor | 用户级，模块不得改动布局 |

**铁律**：跨进程取数走 RPC/HTTP；禁止打开他进程 DB 文件写；`~/.topocode` 文件布局零迁移（新增文件允许）。

## 6. 门禁定义（G1–G8）

| 门禁 | 内容 | 命令/判据 |
|---|---|---|
| G1 冷启动 | fresh venv `pip install -e packages/core` + `npm install && npm run build` | 安装/构建零错 |
| G2 RPC 基线 | 218 方法集一致 | `python3 scripts/check-rpc-parity.py` |
| G3 后端测试 | core + 4 app pytest 全绿 | `npm run test:py`（当前 252） |
| G4 前端类型 | 全 workspace type-check | `npm run type-check` |
| G5 前端构建 | 全量 build（core bundle + portal + 4 app） | `npm run build` |
| G6 进程拓扑 | `topo serve` 10 进程全 OK（kb/gateway/llm/agent/mcp/runner/docs/chat/architect/agent-bus） | `topo status` |
| G7 URL 布局 | 5 SPA 入口 HTML+资产 200 + 子项目 API 带 token 200 | curl 矩阵（见 §7） |
| G8 事件桥 | `/ws/events` 101 + 事件流 + 无 token 401 | WS 握手 + 鉴权抽查 |

## 7. 回归范围判定（改哪里跑什么）

| 改动范围 | 必跑 |
|---|---|
| 某 app 前端/后端（不动契约） | G3（该 app 部分）+ G4 + G5 + G6 + G7（该 app） |
| web-core | G4 + G5 + G7（全 5 SPA） |
| core 非契约模块（bug/重构） | G2 + G3 + G6 |
| core 契约（RPC/端口/URL/schema） | **全量 G1–G8** + 基线重生成 + 核心组评审 |
| gateway（路由/鉴权/静态） | G6 + G7 + G8 |
| 新增子项目 | G3 + G4 + G5 + G6（进程数+1）+ G7（新 URL/资产/API） |

## 8. 测试命令速查

```bash
# 一键
npm run setup                 # .venv + pip install -e(core+4apps) + npm install
npm run dev                   # 全栈（core + 4 前端 dev）
npm run serve / topo serve    # 仅后端 10 进程（:3456）
npm run status / topo status  # 进程状态
npm run build                 # core bundle + portal + 4 app
npm run test                  # test:py + test:fe

# 分项
npm run test:py               # pytest: packages/core/tests + apps/*/tests
npm run test:fe               # vitest: workbench + docs + chat + web-core
npm run type-check            # 全 workspace vue-tsc
npm run lint                  # eslint（存量 116 style error 非门禁）
python -m pytest apps/<name>/tests -v
npm run dev|build|typecheck -w @topo/app-<name>

# 契约
python3 scripts/rpc-baseline.py       # 重生成 RPC 基线（仅核心组）
python3 scripts/check-rpc-parity.py   # 基线比对

# G7/G8 抽查（TOKEN=~/​.topocode 或 topo serve 输出）
curl -s -o /dev/null -w "%{http_code}" localhost:3456/architect                      # 200
curl -s -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $TOKEN" \
     localhost:3456/api/rpc/project.list -d '{}' -X POST                             # 200
curl -s -o /dev/null -w "%{http_code}" localhost:3456/api/rpc/project.list -X POST   # 401
```

## 9. 提交纪律（配合 CONV-00 §4）

1. 每模块独立 commit 组，不跨模块混合提交。
2. commit 信息标注影响面（模块 + 门禁结果），契约变更须列新增/变更方法。
3. `git status` 干净（构建产物不入库：`dist/`、`topoone_app_architect/static/`、`render-worker-bundled.js` 等已在 .gitignore）。
4. 数据零迁移：任何提交不得移动/改名 `~/.topocode` 既有文件。
