# TopoOne-UI 代码重构计划

> 版本: v1.0 | 日期: 2026-07-25

---

## 目录

1. [总体目标](#1-总体目标)
2. [当前问题分析](#2-当前问题分析)
3. [新架构概览](#3-新架构概览)
4. [目录结构](#4-目录结构)
5. [4 大子系统划分](#5-4-大子系统划分)
6. [分层执行计划](#6-分层执行计划)
7. [构建指令适配](#7-构建指令适配)
8. [验证与切换策略](#8-验证与切换策略)
9. [附录: 关键设计决策](#9-附录-关键设计决策)

---

## 1. 总体目标

将当前单体结构拆分为 4 个职责清晰、可独立演化的子系统:

| # | 子系统 | 状态 | 核心职责 |
|---|--------|------|----------|
| 1 | **核心引擎** (Core Engine) | 已有，需重构 | 项目导入、代码解析、符号图、社区检测、分析报告 |
| 2 | **知识库** (Knowledge Base) | 已有，需重构 | Web Viewer、Web AI Chat、架构分析 Agent、知识文档管理 |
| 3 | **Coding Agent** | 新建 | 基于知识库提供上下文，调用第三方 coding agent（opencode/cline/codex/qwen-code） |
| 4 | **统一管理层** (Tools/Skills/MCP/Harness) | 已有+新建 | 统一工具注册、技能编排、MCP Server/Client、工作流编排 |

### 核心原则

- **零 LLM 依赖的核心引擎**: `core/` 不依赖任何 LLM/Agent 代码
- **同一虚拟环境，彻底隔离源码**: 新代码在 `next/` 目录下，不触碰旧文件
- **按依赖层级分批重写**: 写完一层 → 测试通过 → 继续下一层
- **Monorepo Workspace**: 前端通过 npm workspaces 共享 node_modules，Python 通过 editable install 共享 venv

---

## 2. 当前问题分析

### 后端 (`backend-core/`) 问题

| 问题 | 表现 | 影响 |
|------|------|------|
| 单目录 50+ 模块 | 核心引擎 + Agent + LLM + 插件 + Context 全部混在 `backend-core/` | 难以独立演化，修改 Agent 可能影响核心 |
| 职责交织 | `task_manager.py` 同时管理 RPC 注册和任务调度 | 单一文件 >800 行，多个关注点 |
| 无统一工具管理层 | 工具定义在 `tools.py` + `toolkits/` + `tool_calling/` 三处 | 工具发现困难，无法统一审计 |
| 无 MCP 支持 | 无 Model Context Protocol 实现 | 无法接入第三方工具生态 |
| 知识库作为插件 | `plugins/reports/` 承担 Web Viewer + Web Chat | 与前端知识库页面逻辑割裂 |

### 前端 (`src/`) 问题

| 问题 | 表现 | 影响 |
|------|------|------|
| 无域分包 | 所有组件平铺在 `components/` | 无法独立部署，跨域引用混乱 |
| 双重 Chat 实现 | `AIAssistantPanel.vue` + `ChatView.vue` + `chat.html` 三套 | 维护成本高，特性不一致 |
| Web Viewer 非工程化 | `viewer.html` 单文件 3432 行，Vue CDN | 无法 TypeScript、模块化、测试 |
| Store 交叉引用 | project → analysis → community → report 相互引用 | 状态变更难以追踪 |

---

## 3. 新架构概览

### 分层依赖关系

```
Phase 1: core/          ← 无外部依赖（零 LLM）
    ↓
Phase 2: tools/ + mcp/  ← 依赖 core/db（数据存取层）
    ↓
Phase 3: llm/           ← 依赖 core, tools
    ↓
Phase 4: agent/ + knowledge/  ← 依赖 core, tools, llm
    ↓
Phase 5: coder/         ← 依赖 core, knowledge, agent, tools
                         
Phase 6: frontend/      ← 与 Phase 1-5 并行（前端 Vue + Electron）
Phase 7: web/           ← 依赖 Phase 4（Web 知识库子项目）
```

### 通信架构

```
next/frontend (Vue 3 + Electron)
    │ ZMQ RPC (DEALER/SUB)
    ▼
next/backend/topoone/ (Python)
    ├── core/       → process RPC, 数据库读写
    ├── llm/        → LLM streaming chat
    ├── agent/      → agent workflow execution
    ├── knowledge/  → knowledge CRUD
    ├── tools/      → tool registry
    ├── mcp/        → MCP Server/Client
    └── coder/      → coding agent orchestration
```

---

## 4. 目录结构

### 根目录

```
topoOne-ui/
├── next/                              # ★ 新架构（与旧代码完全隔离）
│   ├── backend/                       # Python 后端（独立 package）
│   ├── frontend/                      # Vue + Electron（独立 Vite 项目）
│   └── web/                           # Web 知识库（纯 Vite，无 Electron）
├── backend-core/                      # ❌ 旧系统 - 不动
├── electron/                          # ❌ 旧系统 - 不动
├── src/                               # ❌ 旧系统 - 不动
├── plugins/                           # ❌ 旧系统 - 不动
├── package.json                       # 根 workspace + 脚本
├── docs/
│   ├── plan/                          # 计划文档
│   └── ...
└── ...
```

### `next/backend/` — Python 后端

```
next/backend/
├── pyproject.toml                     # 构建配置 + 依赖声明
├── tests/                             # 测试
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_import.py
│   ├── core/
│   │   ├── test_db.py
│   │   ├── test_import_service.py
│   │   └── test_symbol_graph.py
│   ├── tools/
│   │   └── test_registry.py
│   ├── llm/
│   │   └── test_service.py
│   ├── agent/
│   │   └── test_runtime.py
│   ├── knowledge/
│   │   └── test_service.py
│   └── coder/
│       └── test_orchestrator.py
│
└── topoone/                           # 包名: topoone（pip install -e 后可 import）
    ├── __init__.py
    │
    ├── core/                          # Phase 1: 核心引擎（零 LLM 依赖）
    │   ├── __init__.py
    │   ├── db/
    │   │   ├── __init__.py
    │   │   ├── manager.py             # MultiDBManager（从 sqlite_ctx.py 移入）
    │   │   ├── connection.py          # SQLiteContext
    │   │   └── pragmas.py             # PRAGMA 常量
    │   ├── project/
    │   │   ├── __init__.py
    │   │   ├── service.py             # import/export/verify
    │   │   ├── scanner.py             # 文件扫描 + gitignore
    │   │   └── git.py                 # Git info
    │   ├── parser/
    │   │   ├── __init__.py
    │   │   ├── symbol_graph.py
    │   │   ├── stack_graphs_service.py
    │   │   └── ast_worker.py
    │   ├── analysis/
    │   │   ├── __init__.py
    │   │   ├── community.py           # community_data.py
    │   │   ├── report.py              # report_tree_service.py
    │   │   └── task.py                # 原 task_manager.py 无 LLM 部分
    │   └── store/
    │       ├── __init__.py
    │       ├── task_store.py
    │       ├── analysis_store.py
    │       ├── write_queue.py
    │       └── duckdb_reader.py
    │
    ├── tools/                         # Phase 2: 统一工具管理
    │   ├── __init__.py
    │   ├── registry.py                # 全局工具注册表
    │   ├── schema.py                  # ToolDef, ToolParam, ToolResult
    │   ├── executor.py                # 工具执行器
    │   └── builtin/
    │       ├── __init__.py
    │       ├── file_tools.py
    │       ├── symbol_tools.py
    │       ├── graph_tools.py
    │       ├── edge_tools.py
    │       └── knowledge_tools.py
    │
    ├── mcp/                           # Phase 2: MCP Server + Client
    │   ├── __init__.py
    │   ├── server.py                  # 暴露内建工具为 MCP 资源
    │   ├── client.py                  # 发现/调用第三方 MCP Server
    │   ├── transport.py               # stdio / TCP
    │   └── schema.py                  # MCP 协议适配
    │
    ├── llm/                           # Phase 3: LLM 服务
    │   ├── __init__.py
    │   ├── service.py                 # LLMService（session, streaming, tool calling）
    │   ├── providers/
    │   │   ├── __init__.py
    │   │   ├── base.py
    │   │   ├── ollama.py
    │   │   └── openai_compat.py
    │   ├── context/                   # 上下文装配系统
    │   │   ├── __init__.py
    │   │   ├── assembly.py
    │   │   ├── ingredient.py
    │   │   ├── registry.py
    │   │   ├── recipes/
    │   │   │   └── __init__.py
    │   │   └── ingredients/
    │   │       └── __init__.py
    │   └── prompt_manager.py
    │
    ├── agent/                         # Phase 4: 代理系统
    │   ├── __init__.py
    │   ├── runtime.py                 # AgentRuntime
    │   ├── memory.py                  # AgentMemory
    │   ├── sandbox.py                 # AgentSandbox
    │   ├── router.py                  # RouterHarness（增强: 支持 MCP 注入）
    │   ├── queue.py                   # AgentTaskManager
    │   ├── sub_agent.py
    │   ├── workflows/
    │   │   ├── __init__.py
    │   │   ├── base.py
    │   │   ├── overview.py
    │   │   ├── component_analyst.py
    │   │   ├── agentic_component_analyst.py
    │   │   ├── pre_summary.py
    │   │   └── pipeline.py
    │   ├── skills/
    │   │   ├── __init__.py
    │   │   ├── registry.py
    │   │   └── builtin.py
    │   └── toolkits/
    │       ├── __init__.py
    │       └── adapters.py            # 包装 tools/builtin/ 为 AgentTool
    │
    ├── knowledge/                     # Phase 4: 知识库
    │   ├── __init__.py
    │   ├── service.py                 # CRUD + 检索
    │   ├── graph.py                   # 知识图谱
    │   └── dimensions.py              # 维度系统
    │
    └── coder/                         # Phase 5: Coding Agent
        ├── __init__.py
        ├── orchestrator.py            # 协调器
        ├── parser.py                  # 需求解析
        ├── context.py                 # 上下文装配
        ├── spec_builder.py            # 规约生成
        ├── workspace.py               # 工作区管理
        ├── reviewer.py                # diff 审查
        └── adapters/
            ├── __init__.py
            ├── base.py                # BaseCodingAdapter 抽象
            ├── opencode.py
            ├── cline.py
            ├── codex.py
            └── qwen_code.py
```

### `next/frontend/` — Vue + Electron 前端

```
next/frontend/
├── package.json                       # 独立依赖 + scripts
├── vite.config.ts                     # Vite + Electron 插件
├── tsconfig.json
├── tsconfig.electron.json
├── index.html
├── electron/                          # Electron main process
│   ├── main.ts
│   ├── preload.ts
│   ├── python-bridge.ts
│   ├── zmq-router.ts
│   └── window-manager.ts
└── src/
    ├── main.ts
    ├── App.vue
    ├── router/
    │   └── index.ts
    ├── core/                          # 核心引擎前端
    │   ├── pages/
    │   │   ├── HomePage.vue
    │   │   ├── CodePage.vue
    │   │   └── AnalysisPage.vue
    │   ├── components/
    │   │   ├── project/
    │   │   ├── analysis/
    │   │   └── report/
    │   ├── stores/
    │   │   ├── project.ts
    │   │   ├── analysis.ts
    │   │   └── community-store.ts
    │   └── services/
    │       ├── ipc.ts
    │       └── llmClient.ts
    ├── knowledge/                     # 知识库
    │   ├── pages/
    │   │   └── KnowledgePage.vue
    │   ├── components/
    │   ├── stores/
    │   │   └── knowledge.ts
    │   └── services/
    ├── agent/                         # 代理系统
    │   ├── components/
    │   │   ├── AIAssistantPanel.vue
    │   │   ├── ChatView.vue
    │   │   └── AgentTaskList.vue
    │   ├── stores/
    │   │   └── agent-usage-store.ts
    │   └── services/
    ├── coder/                         # Coding Agent
    │   ├── pages/
    │   │   └── CoderPage.vue
    │   ├── components/
    │   │   ├── TaskCreateForm.vue
    │   │   ├── TaskList.vue
    │   │   ├── DiffViewer.vue
    │   │   └── AgentSelector.vue
    │   ├── stores/
    │   │   └── coder-store.ts
    │   └── services/
    ├── shell/                         # App 外壳
    │   ├── AppShell.vue
    │   ├── ActivityBar.vue
    │   ├── TopBar.vue
    │   ├── StatusBar.vue
    │   ├── LeftPanel.vue
    │   └── RightPanel.vue
    ├── settings/                      # 设置
    │   ├── GeneralSettings.vue
    │   ├── ModelConfig.vue
    │   ├── AgentConfigManager.vue
    │   └── ...
    └── shared/                        # 跨域共享
        ├── components/
        ├── composables/
        ├── utils/
        ├── types/
        ├── i18n/
        └── styles/
```

### `next/web/` — Web 知识库（纯浏览器）

```
next/web/
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
└── src/
    ├── main.ts
    ├── viewer/                        # 文档查看器
    │   ├── App.vue
    │   ├── components/
    │   └── stores/
    └── chat/                          # AI Chat
        ├── App.vue
        ├── components/
        └── stores/
```

---

## 5. 4 大子系统划分

### 5.1 核心引擎 (Core Engine) — `topoone/core/`

**职责**:
- 项目导入/导出/同步
- 文件扫描 + GitIgnore
- AST 解析 + 符号图生成
- Stack Graph 分析
- 社区检测 (Leiden/Louvain)
- 数据存取层 (SQLite + DuckDB)

**零 LLM 依赖**: 不 import 任何 LLM/Agent/MCP 模块。

**RPC 命名空间**:
- `project.*` — 项目管理
- `analysis.task.*` — 任务管理（无 Agent）
- `analysis.graph.*` — 图数据查询
- `report.*` — 文档生成

### 5.2 知识库 (Knowledge Base) — `topoone/knowledge/` + `next/web/` + `next/frontend/knowledge/`

**职责**:
- 知识文档 CRUD + 检索
- 知识图谱管理
- 维度系统 (lifecycle / techStack / abstraction / purpose)
- Web Viewer（浏览器查看架构文档）
- Web AI Chat（浏览器内架构分析对话）
- 架构分析 Agent（生成 overview / 组件分析 / 质量检查）

**双模架构**:
- Electron 内: `next/frontend/knowledge/` 使用 Vue 组件嵌入主界面
- 浏览器内: `next/web/` 独立 Vite 项目，共享 API 和类型

### 5.3 Coding Agent — `topoone/coder/` + `next/frontend/coder/`

**职责**:
- 理解自然语言需求 → 解析意图
- 从知识库 + 项目分析获取精确上下文
- 生成规约描述（文件列表、接口签名、约束条件）
- 通过 Adapter 调用第三方 coding agent
- 审查返回的 diff

**Adapter 抽象**:

```python
class BaseCodingAdapter(ABC):
    name: str                           # "opencode" / "cline" / "codex"
    capabilities: dict                  # 多轮对话? 上下文窗口? 工具支持?

    @abstractmethod
    def invoke(self, context: CodingContext) -> CodingResult:
        """首次/单次调用"""

    @abstractmethod
    def continue_(self, session_id: str, feedback: str) -> CodingResult:
        """多轮对话推进"""

    @abstractmethod
    def cancel(self, session_id: str):
        """取消任务"""

    def get_status(self, session_id: str) -> str: ...
    def get_result(self, session_id: str) -> CodingResult: ...
```

**Orchestrator 流程**:

```
User Request
    → parser 解析意图 + 提取关键实体
    → context 从知识库 + 社区分析检索精确上下文
    → spec_builder 生成规约（文件路径、接口签名、约束）
    → adapter.invoke(context) 启动第三方 agent
    → 多轮 adapter.continue_(feedback)
    → reviewer 审查 diff → 通过则写入 workspace
```

### 5.4 统一管理层 (Tools/Skills/MCP/Harness)

```
                    ┌─────────────────────────────┐
                    │   tools/registry.py          │
                    │   全局工具注册表              │
                    └────────────┬────────────────┘
                                 │
        ┌────────────────────────┼────────────────────────┐
        │                        │                        │
        ▼                        ▼                        ▼
┌───────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  skills/      │    │  mcp/server.py   │    │  mcp/client.py   │
│  技能编排     │    │  暴露内建工具    │    │  接入第三方 MCP  │
│  多步工作流   │    │  支持动态发现    │    │  discover/list   │
└───────┬───────┘    └────────┬─────────┘    └────────┬─────────┘
        │                     │                        │
        ▼                     ▼                        ▼
┌──────────────────────────────────────────────────────────┐
│              agent/router.py (RouterHarness)              │
│  Action → Workflow 路由 + 工具组合 + 沙箱 + MCP 注入     │
└──────────────────────────────────────────────────────────┘
```

**MCP 实现要点**:
- Server: 将 `tools/builtin/*` 注册的工具通过 MCP 协议暴露
- Client: 发现/连接第三方 MCP Server，注入到 Agent Runtime
- 支持 stdio 和 TCP transport

---

## 6. 分层执行计划

### Phase 0: 基础设施 + 目录骨架（1 天）

**目标**: 建好空包结构，验证可导入、可构建

**产出**:
- `next/backend/` 完整空包 + `pyproject.toml`
- `next/frontend/` 最小 Vite + Electron 可启动项目
- `next/web/` 最小 Vite 可启动项目
- 根 `package.json` 增加 workspaces 和新脚本

**验证**:
```bash
pip install -e next/backend/                    # 成功
python -c "from topoone.core import *"          # 无报错
cd next/frontend && npm install && npm run dev  # Vite 启动
cd next/web && npm install && npm run dev       # Vite 启动
npm run next:setup                              # 一键脚本
```

---

### Phase 1: 核心引擎 `topoone/core/`（3 天）

**目标**: 完成无 LLM 依赖的核心引擎重写

**子模块**:

| 子模块 | 源文件 | 目标文件 | 说明 |
|--------|--------|----------|------|
| db/ | `sqlite_ctx.py` | `core/db/manager.py` + `connection.py` | MultiDBManager, SQLiteContext |
| project/ | `core_service.py`, `import_service.py`, `export_service.py`, `verify_service.py` | `core/project/` | 保留非 LLM 部分 |
| parser/ | `symbol_graph.py`, `stack_graphs_service.py` | `core/parser/` | AST + 符号图 |
| analysis/ | `community_data.py`, `task_manager.py` (部分) | `core/analysis/` | 社区检测, 任务状态管理 |
| store/ | `store/`, `data_layer/` | `core/store/` | 数据存取 |

**验证**:
```bash
cd next/backend && pytest tests/ -v           # 全部通过
python -c "from topoone.core.project import *" # 可导入
```

**不移入 Phase 1 的内容**:
- LLM 调用的任何部分 (`llm_service.py`, `providers/`)
- Agent 工作流 (`agent_workflow/`)
- Context Assembly (`context/`)
- Plugin Manager (`plugin_manager.py`)
- Knowledge (`knowledge.*` RPC)

---

### Phase 2: 工具/Skills/MCP 管理层（3-4 天）

**目标**: 统一工具注册表 + MCP Server/Client

**2a. `topoone/tools/`**
- 定义 `ToolDef`, `ToolParam`, `ToolResult` 标准 schema
- 实现全局 `ToolRegistry`
- 从旧 `agent_workflow/toolkits/` 迁移 5 个工具集到 `tools/builtin/`

**2b. `topoone/mcp/`**
- 实现 MCP Server: `tools/list`, `tools/call`
- 实现 MCP Client: `discover()`, `connect()`, 远程调用
- `ToolRegistry` 提供内建工具列表给 MCP Server

**2c. `topoone/agent/skills/`**
- 迁移 `@register_skill` 装饰器
- 从旧 `agent_workflow/workflows/` 提取技能定义

**验证**:
```bash
# 工具注册
python -c "
from topoone.tools import registry
registry.register_builtins()
tools = registry.list_tools()
print(f'{len(tools)} tools registered')
"

# MCP Server 启动
python -c "from topoone.mcp.server import MCPServer; print('MCP OK')"
```

---

### Phase 3: LLM 服务 `topoone/llm/`（2 天）

**目标**: 独立的 LLM 服务层

- 迁移 `llm_service.py` → `llm/service.py`
- 迁移 `providers/` → `llm/providers/`
- 迁移 `context/` → `llm/context/`
- 依赖 `topoone/core`（数据存取）、`topoone/tools`（工具调用）

**验证**: LLM streaming chat 可通过单元测试验证（mock provider）

---

### Phase 4: Agent 工作流 + 知识库（3 天）

**目标**: 完整的代理系统和知识库服务

**Agent**:
- 迁移 `agent_workflow/runtime.py` → `agent/runtime.py`
- 迁移 `agent_workflow/router.py` → `agent/router.py`（增强 MCP 注入）
- 迁移 `agent_workflow/workflows/` → `agent/workflows/`
- `agent/toolkits/adapters.py` 包装 `tools/builtin/` 为 AgentTool

**知识库**:
- 迁移 `knowledge.*` RPC 到 `knowledge/service.py`
- 实现 `knowledge/graph.py`
- 实现 `knowledge/dimensions.py`

**验证**: Agent 工作流端到端测试通过

---

### Phase 5: Coding Agent `topoone/coder/`（5-7 天）

**目标**: 新建编码代理子系统

- `orchestrator.py` — 需求→上下文→分派→结果协调
- `parser.py` — 自然语言→结构化任务
- `context.py` — 知识库 + 项目分析 → 精确上下文
- `spec_builder.py` — 规约文件生成
- `adapters/base.py` — 抽象基类
- `adapters/opencode.py` — opencode CLI 适配
- `adapters/cline.py` — cline 适配
- `adapters/codex.py` — codex API 适配
- `adapters/qwen_code.py` — qwen-code 适配
- `workspace.py` — 临时工作区管理
- `reviewer.py` — diff 审查

---

### Phase 6: 前端 `next/frontend/`（3 天）

**目标**: 按域分包的前端项目

- 创建 `core/`, `knowledge/`, `agent/`, `coder/`, `shell/`, `settings/`, `shared/` 目录
- 逐步从旧 `src/` 移入对应组件
- 每个子包独立路由 + store + 服务

---

### Phase 7: Web 子项目 `next/web/`（3 天）

**目标**: 浏览器端知识库

- `viewer/` — 架构文档查看器（从 `plugins/reports/static/viewer.html` 迁移）
- `chat/` — AI Chat（从 `plugins/reports/static/chat.html` 迁移）
- 共享 `shared/types/`, `shared/i18n/`
- 构建产出独立部署

---

## 7. 构建指令适配

### 根 `package.json` 新脚本

```json
{
  "workspaces": ["next/frontend", "next/web"],
  "scripts": {
    "dev": "concurrently ...",             // 旧系统 - 保留
    "build": "...",                        // 旧系统 - 保留

    "next:setup": "cd next/frontend && npm install && cd ../web && npm install && pip install -e next/backend/",
    "next:setup:pip": "pip install -e next/backend/",
    "next:frontend:install": "cd next/frontend && npm install",
    "next:web:install": "cd next/web && npm install",

    "next:frontend:dev": "cd next/frontend && npx vite",
    "next:frontend:electron": "cd next/frontend && npx electron .",
    "next:web:dev": "cd next/web && npx vite",

    "next:backend:test": "cd next/backend && python -m pytest -v",
    "next:backend:shell": "cd next/backend && python -c \"from topoone import *; print('OK')\"",
    "next:backend:lint": "cd next/backend && ruff check topoone/",
    "next:frontend:typecheck": "cd next/frontend && vue-tsc --noEmit",

    "next:build:frontend": "cd next/frontend && npx vite build",
    "next:build:web": "cd next/web && npx vite build",
    "next:build": "npm run next:build:frontend && npm run next:build:web",
    "next:dev": "concurrently \"npm run next:frontend:dev\" \"npm run next:backend:test -- --watch\""
  }
}
```

### Python 入口

```python
# next/backend/main.py (新系统入口)
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from topoone.core.db.manager import MultiDBManager
from topoone.core.project.service import ProjectService
# ...
```

### 数据库路径

新系统可通过环境变量切换数据目录:
```bash
DATA_DIR=~/.topoone-v2 next/backend/main.py
```

---

## 8. 验证与切换策略

### 每 Phase 验证标准

| 检查项 | 命令 | 预期 |
|--------|------|------|
| Python 包可导入 | `python -c "from topoone.xxx import *"` | 无 ImportError |
| 单元测试通过 | `cd next/backend && pytest -v` | 全部 green |
| 类型检查 | `cd next/frontend && vue-tsc --noEmit` | 无 error |
| 构建 | `npm run next:build` | 产出 dist/ |

### 渐进切换策略

```
Phase 0-5: 纯后端开发，不影响旧系统
           └── 旧系统继续运行，用户无感知

Phase 6:   前端 next/frontend/ 可独立开发
           └── 可通过 npm run next:frontend:dev 单独启动

切换点:    新系统稳定后，修改根 entry
           └── package.json 的 "dev" 脚本切到 next/
           └── 移入 electron/main.py 指向 topoone package

最终:      旧 backend-core/ + src/ + electron/ 归档为 legacy/
```

### 回滚策略

- 旧系统代码 **不动**，直到确认新系统稳定
- 回滚只需将切换开关改回旧入口
- 数据库：新系统使用 `DATA_DIR` 环境变量隔离，旧数据不受影响

---

## 9. 附录: 关键设计决策

### 决策记录

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| D1 | 重构位置 | 独立 `next/` 目录 | 与旧代码零冲突，可并行开发 |
| D2 | Python 包管理 | `pip install -e next/backend/` | 标准做法，IDE 自动识别，依赖自动解析 |
| D3 | 前端形态 | 需要 Electron | 保留桌面端能力（文件系统、窗口管理） |
| D4 | Web 工程化 | 独立 Vite 子项目 | 支持 TypeScript、模块化、测试 |
| D5 | 迁移策略 | 一次性重写，按依赖层级分批 | 每层写完即测试，无长期过渡负担 |
| D6 | Coding Agent 适配器 | 通用架构，同时支持多个 | 不同第三方 agent 的多轮对话模式有差异，各自独立保持上下文 |
| D7 | MCP | 内置 Server + Client | 同时支持暴露内建工具和接入第三方 |
| D8 | 核心引擎 | 零 LLM 依赖 | 确保核心可独立演化、测试、部署 |

### 不放入 Phase 1（核心引擎）的内容

- LLM 调用 (`llm_service.py`)
- LLM Providers (`providers/`)
- Agent 工作流 (`agent_workflow/`)
- Context Assembly (`context/`)
- Plugin Manager (`plugin_manager.py`)
- Knowledge RPC (`knowledge.*`)
- 技能注册 (`skill_registry.py`)

这些模块依赖 LLM 或 Agent 系统，将在 Phase 3-5 中处理。

---

> 本文档将随重构进展持续更新。

## 各 Phase 详细设计文档

| 阶段 | 文档 | 内容 |
|------|------|------|
| Phase 1 | `docs/plan/phase1-core-engine.md` | 核心引擎 `topoone/core/` — 36 个文件规格, 模块依赖, 测试规划 |
| Phase 2 | `docs/plan/phase2-tools-skills-mcp.md` | 工具管理层 `topoone/tools/` + `mcp/` + `agent/skills/` — MCP 协议规格 |
| Phase 3 | `docs/plan/phase3-llm-service.md` | LLM 服务 `topoone/llm/` — 服务/Provider/会话/上下文 |
| Phase 4 | `docs/plan/phase4-agent-knowledge.md` | Agent 工作流 `topoone/agent/` + 知识库 `topoone/knowledge/` |
| Phase 5 | `docs/plan/phase5-coding-agent.md` | Coding Agent `topoone/coder/` — 适配器/编排器/审查 |
| Phase 6+7 | `docs/plan/phase6-frontend-web.md` | 前端 `next/frontend/` + Web 子项目 `next/web/` |
| 补充 | `docs/plan/supplement-electron-web.md` | Electron IPC 层完整规格、Pinia Store 接口、Coding Agent 前端设计、Web HTTP API 规格、Reports 插件迁移、渲染管线、TopoScript 动画引擎 |

> **更新 2026-07-25**: 前端侧取消重构。旧 `src/` + `electron/` 保持不动，直接复用。`next/frontend/` 和 `next/web/` 目录已删除。后端 `next/backend/` 重构继续。

> 本文档将随重构进展持续更新。
