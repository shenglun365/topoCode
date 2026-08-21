# CONV-01 核心框架规约（topoone-core）

> 源码根：`packages/core/`（pip 包名 `topoone-core`，editable 安装）
> 修改方：核心组。任何子项目不得直接修改本模块；需要核心新能力时按 CONV-00 §5 提需求。

## 1. 源码范围与模块职责

| 目录/文件 | 职责 | 对应进程 |
|---|---|---|
| `topoone/engine/` | 分析引擎：project/analysis/report 服务、task_manager、ingest、store、plantuml、report_tree | kb :3459（`python -m topoone.engine`） |
| `topoone/gateway/` | 网关：`server.py`（装配+静态挂载）、`gateway.py`（反代+RPC 命名空间路由+鉴权+WS 事件桥）、`vue_routes.py`（SPA 页面路由）、`static_sources.py`（manifest 驱动静态源） | gateway :3456 |
| `topoone/supervisor/` | 进程治理：`cli.py`（`topo serve/status/doctor`，固定进程表）、`manager.py`（插件发现） | 无独立进程（launcher） |
| `topoone/rpc/` | ZeroMQ RPC 服务框架（`/zmq/{method}` 端点） | 各进程内嵌 |
| `topoone/db/` | 多库管理：`manager.py`（MultiDBManager：topoone.db/project.db/knowledge/sessions/chat 各库 schema + 建表 + LRU 连接池）、`connection.py` | 各进程内嵌 |
| `topoone/messaging/` | 内部消息总线（ZMQ PUB/SUB：5680/5682/5683/5684） | 各进程内嵌 |
| `topoone/llm/` | LLM 推理服务 + prompt/instruction 管理 + providers | llm :3484（`python -m topoone.llm`，PUB 5682） |
| `topoone/agent/` | Agent 工作流（workflows/toolkits/sandbox）+ worker + tools_executor | agent :3482（`python -m topoone.agent`，PUB 5684） |
| `topoone/plugins/` | 核心插件：`parsers/`（tree-sitter）、`community/`（社区算法）、`mcp/`（MCP Server :3460）、`runner/`（Coding Agent 执行 :3458）、`installer/`（Agent 配置安装）、`llm-provider-{openai,ollama,lm-studio}/` | mcp/runner 独立进程；其余进程内嵌 |
| `topoone/manifest.py` | AppManifest 数据类 + `discover_apps`/`validate_registry`（冲突即 ManifestError） | 被 gateway/supervisor 调用 |
| `topoone/config.py` / `logging_config.py` / `http_logging.py` / `service_common.py` | 全局配置/日志/HTTP 日志/服务公共件 | — |
| `packages/core/tests/`（16 文件） | 核心 pytest | — |
| `packages/core/rpc-method-baseline.json` | **RPC 204 方法冻结基线**（`scripts/rpc-baseline.py` 生成） | — |

## 2. 冻结契约（破坏 = 事故，须核心组评审）

### 2.1 RPC 方法基线（204）
- 基线文件：`packages/core/rpc-method-baseline.json`；生成：`python3 scripts/rpc-baseline.py`；比对：`python3 scripts/check-rpc-parity.py`。
- **只增不删不改语义**：新增方法允许（须更新基线 + 全量回归）；删除/改名/改参数语义禁止（需两个大版本过渡期 + 所有调用方迁移）。

### 2.2 进程拓扑与端口（9 进程，supervisor 固定表 `cli.py:_SERVICE_META`）
| 进程 | 端口 | PUB | 入口 |
|---|---|---|---|
| kb | 3459 | — | `python -m topoone.engine` |
| gateway | 3456 | — | `python -m topoone.gateway` |
| llm | 3484 | 5682 | `python -m topoone.llm` |
| agent | 3482 | 5684 | `python -m topoone.agent` |
| docs | 3481 | 5683 | `python -m topoone_app_docs`（manifest） |
| chat | 3483 | — | `python -m topoone_app_chat`（manifest） |
| architect | 3470 | — | `python -m topoone_app_architect`（manifest） |
| mcp | 3460 | — | `python -m topoone.plugins.mcp` |
| runner | 3458 | — | `python -m topoone.plugins.runner` |

- 端口表变更 = 核心契约变更（影响用户环境/外部 MCP 配置），须评审。

### 2.3 URL 布局（gateway）
`/`·`/home`（门户）、`/app`（workbench）、`/projects`·`/viewer`·`/web-root`（docs）、`/chat`（chat）、`/architect`（architect）、`/api/rpc/{method}`（RPC）、`/ws/events`（事件桥）、`/api/{app}/*`（子项目 REST，见 CONV-04 §1）。

### 2.4 数据布局（`~/.topocode`，零迁移承诺）
DB 文件位置与表归属见 CONV-04 §5。**任何模块不得移动/改名已有 DB 文件**。

## 3. 修改规则

| 允许 | 规则 |
|---|---|
| 新增 RPC 方法 | 注册进对应服务 → `rpc-baseline.py` 重生成基线 → 全量回归（G2+G3+G6）→ 提交说明列明新增方法 |
| 新增核心插件 | `topoone/plugins/<name>/` + `plugin.json`（如需分发）→ 不占固定端口（除非评审） |
| 修 bug | 行为不变的前提下修复；补测试 |
| 重构 | 方法签名/端口/URL/表结构不变；全量回归 |

| 禁止 | 原因 |
|---|---|
| core import `topoone_app_*` | 破坏依赖单向（CONV-00 §4.1） |
| 删除/改名基线内 RPC 方法 | 冻结契约 |
| 改动 `~/.topocode` 既有文件布局 | 零数据迁移承诺 |
| 在 gateway 硬编码 app 专属逻辑 | 新 app 必须 manifest 驱动零改 gateway |
| 子进程直连他进程 DB 文件 | 进程=数据边界 |

## 4. 核心对外接口（子项目调用方式）

| 接口 | 方式 | 说明 |
|---|---|---|
| RPC 方法 | 前端 `POST /api/rpc/{method}`（body=params）；进程内 `HttpAgentManager`/ZMQ | 204 方法基线 |
| 事件流 | WS `/ws/events?token=`（ZMQ SUB 5680 转发） | 任务/导入/LLM 流式 |
| 子项目 RPC 命名空间 | app 在 `python_entry` 中注册（如 `knowledge.*`/`render.*`/`doc.*`），经 gateway 命名空间路由到 owner 进程 | 见 CONV-04 §1 |
| LLM 调用 | llm 服务 `llm.chat`（ZMQ/HTTP，PUB 5682 流式） | 子项目不得自持 LLM 客户端直连 provider（chat 内置客户端为遗留，M12 任务 12.6 待瘦身） |
| Coding Agent | runner :3458 + agent :3482 管线 | MCP 工具调用经 mcp :3460 转发 architect |

## 5. 核心组提交前检查清单

- [ ] `python3 scripts/check-rpc-parity.py`（基线一致）
- [ ] `npm run test:py`（core 16 文件 + 各 app pytest 全绿）
- [ ] `topo serve` 后 `topo status` 9 进程全 OK
- [ ] 动 gateway：5 SPA URL 全 200 + `/ws/events` 101 + 无 token 401
- [ ] 动 schema：`~/.topocode` 旧数据可启动（向后兼容建表 `IF NOT EXISTS`）
- [ ] 提交说明：列出新增/变更 RPC 方法与影响面
