# Electron 架构设计 (v3.0 - ZeroMQ)

> 进程模型、ZeroMQ 消息队列、窗口管理、Agent 调度

---

## 1. 进程模型

```
┌──────────────────────────────────────────────────────────────────┐
│  Electron Main Process                                           │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  BrowserWindow 管理  │  ZMQ Router (消息路由中枢)           │  │
│  │  IPC 中枢             │  Agent 进程生命周期管理              │  │
│  │  系统托盘 / 菜单       │  SQLite 上下文管理                  │  │
│  │  自动更新             │  本地文件存储 (electron-store)       │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │ Electron IPC                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Preload Script                                             │  │
│  │  contextBridge.exposeInMainWorld('api', { ... })            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                          │                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Renderer Process (Vue 3 App)                               │  │
│  │  Vue 3 │ Pinia │ Router │ window.api.* (IPC调用)            │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │ ZeroMQ (TCP/IPC)   │ ZeroMQ            │ ZeroMQ
         │ ROUTER/DEALER      │ PUB/SUB           │ PUSH/PULL
         ▼                    ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  Core Service  │  │  Agent-1       │  │  Agent-N       │
│  (Python)      │  │  (qwen-code)   │  │  (cline)       │
│  ┌──────────┐  │  │  CLI Process   │  │  CLI Process   │
│  │ ZMQ      │  │  │                │  │                │
│  │ Dealer   │  │  └────────────────┘  └────────────────┘
│  └──────────┘  │
│  ┌──────────┐  │
│  │ SQLite3  │  │
│  │ 上下文   │  │
│  └──────────┘  │
│  ┌──────────┐  │
│  │Tree-sitter│ │
│  │代码解析  │  │
│  └──────────┘  │
└────────────────┘
         │
         │ HTTP (外部 API)
         ▼
┌──────────────────────────────────────────────────────────────────┐
│  LLM API (外部服务) - Renderer 直接调用                           │
│  Ollama │ OpenAI │ LM-Studio │ 其他兼容 OpenAI 的 API            │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 进程职责划分

| 进程 | 职责 | 不负责 |
|------|------|--------|
| **Main** | 窗口生命周期、ZMQ Router、Agent 调度、SQLite 上下文、原生菜单、系统托盘 | UI 渲染、业务逻辑 |
| **Preload** | 暴露安全 API 给 Renderer (contextBridge) | 业务数据处理 |
| **Renderer** | Vue 组件渲染、用户交互、Pinia 状态管理、路由、LLM HTTP 调用 | 文件系统直接访问、子进程管理 |
| **Core Service** | ZMQ Dealer、代码解析 (Tree-sitter)、知识库 (SQLite)、项目扫描 | UI、Electron 功能、LLM 调用 |
| **Agent-N** | 独立 CLI 进程、代码生成、任务执行、校验 | 消息路由、状态管理 |

---

## 3. ZeroMQ 拓扑设计

### 3.1 核心拓扑 - ROUTER/DEALER (RPC)

```
Main Process (ROUTER)
    │
    ├── DEALER ──→ Core Service (Python)
    │                - 项目管理
    │                - 代码分析
    │                - 知识库
    │                - 设置配置
    │
    ├── DEALER ──→ Agent-1 (qwen-code)
    │                - 代码生成
    │                - 任务执行
    │
    └── DEALER ──→ Agent-N (cline)
                     - 代码生成
                     - 任务执行
```

**特点**:
- Main Process 作为消息路由中枢，通过 identity 识别不同后端
- 支持多 Agent 并行执行
- 请求/响应模式，适合 RPC 调用

### 3.2 事件推送 - PUB/SUB

```
Core Service (PUB)
    │
    ├── SUB ──→ Main Process ──→ Renderer (任务进度)
    ├── SUB ──→ Main Process ──→ Renderer (项目同步)
    └── SUB ──→ Main Process ──→ Renderer (后端状态)
```

**特点**:
- 一对多广播
- 适合实时推送任务进度、状态变更
- Renderer 通过 IPC 订阅，Main 通过 ZMQ 订阅

### 3.3 任务分发 - PUSH/PULL

```
Main Process (PUSH)
    │
    ├── PULL ──→ Agent-1
    ├── PULL ──→ Agent-2
    └── PULL ──→ Agent-N
```

**特点**:
- 负载均衡，自动分发任务
- 适合批量代码分析、批量生成

---

## 4. 通讯方式划分

### 4.1 ZeroMQ 通道 (本地服务)

| 模块 | 模式 | 说明 |
|------|------|------|
| **project** | ROUTER/DEALER | 项目导入/列表/同步/文件树 |
| **analysis** | ROUTER/DEALER | 任务创建/执行/结果 |
| **knowledge** | ROUTER/DEALER | 文档 CRUD/图谱/分类 |
| **settings** | ROUTER/DEALER | 模型/Agent/SKILL 配置 |
| **task progress** | PUB/SUB | 任务进度/完成/错误推送 |
| **agent dispatch** | PUSH/PULL | Agent 任务分发 |

### 4.2 HTTP 通道 (LLM 请求)

| 模块 | 方式 | 说明 |
|------|------|------|
| **LLM Chat** | Renderer → HTTP (SSE) | 流式对话 |
| **LLM Completion** | Renderer → HTTP | 代码补全 |
| **LLM Embedding** | Renderer → HTTP | 文本向量化 |

---

## 5. ZeroMQ 端口/端点设计

| 端点 | 类型 | 说明 |
|------|------|------|
| `tcp://127.0.0.1:5670` | ROUTER (Main) | 主路由端点 |
| `tcp://127.0.0.1:5671` | DEALER (Core) | 核心服务 |
| `tcp://127.0.0.1:5672` | DEALER (Agent-1) | Agent 1 |
| `tcp://127.0.0.1:5673` | DEALER (Agent-N) | Agent N |
| `tcp://127.0.0.1:5680` | PUB (Core) | 事件发布 |
| `tcp://127.0.0.1:5681` | SUB (Main) | 事件订阅 |
| `tcp://127.0.0.1:5690` | PUSH (Main) | 任务分发 |
| `tcp://127.0.0.1:5691` | PULL (Agent) | 任务接收 |

---

## 6. 窗口管理

| 窗口类型 | 说明 |
|----------|------|
| **主窗口** | 1200×800px (最小 800×600)，可最大化，记住位置/大小 |
| **启动加载窗口** | 无边框 splash，显示后端启动进度 |
| **对话框** | 原生 dialog (导入文件夹/确认/错误) |

窗口配置:
```typescript
const mainWindow = new BrowserWindow({
  width: 1200,
  height: 800,
  minWidth: 800,
  minHeight: 600,
  frame: false,
  titleBarStyle: 'hidden',
  webPreferences: {
    preload: path.join(__dirname, '../preload/index.js'),
    contextIsolation: true,
    nodeIntegration: false,
  },
});
```

---

## 7. Renderer ↔ LLM API 通信

Renderer 进程**直接**通过 HTTP 调用外部 LLM API：

```
Renderer (Vue)
    │
    ├── LLM Chat:   fetch(config.url + '/api/chat')     → Ollama
    │                fetch(config.url + '/v1/chat/...')  → OpenAI
    │                封装在 src/services/llm.ts
    │
    └── LLM Embed:  fetch(config.url + '/api/embeddings') → 向量化
```

---

## 8. 目录结构

```
src/
├── main/                    # Electron Main Process
│   ├── index.ts             # 入口: app.whenReady()
│   ├── window.ts            # BrowserWindow 创建与管理
│   ├── ipc.ts               # IPC 处理器注册
│   ├── zmq-router.ts        # ZeroMQ ROUTER (消息路由)
│   ├── zmq-sub.ts           # ZeroMQ SUB (事件订阅)
│   ├── agent-manager.ts     # Agent 进程管理
│   ├── sqlite.ts            # SQLite 上下文管理
│   ├── menu.ts              # 原生菜单模板
│   ├── updater.ts           # 自动更新
│   └── store.ts             # electron-store 初始化
│
├── preload/                 # Preload Scripts
│   └── index.ts             # contextBridge API
│
├── renderer/                # Vue 3 应用
│   ├── App.vue
│   ├── main.ts              # createApp + router + pinia
│   ├── components/          # 组件
│   ├── stores/              # Pinia stores
│   ├── services/            # 服务层
│   │   ├── zmq.ts           # ZeroMQ 客户端 (通过 IPC 代理)
│   │   └── llm.ts           # LLM HTTP 调用封装
│   ├── router/              # Vue Router 配置
│   └── styles/              # 全局样式 + CSS 变量
│
backend/                     # Python 后端
├── core_service.py          # ZMQ DEALER + SQLite
├── zmq_server.py            # ZeroMQ 服务端
├── sqlite_ctx.py            # SQLite 上下文管理
└── handlers/                # 方法处理器
    ├── project.py
    ├── analysis.py
    ├── knowledge.py
    └── settings.py
```

---

## 9. SQLite 上下文管理

### 9.1 存储内容

| 表 | 说明 |
|----|------|
| `projects` | 项目元数据 |
| `analysis_tasks` | 分析任务 |
| `knowledge_docs` | 知识文档 |
| `chat_sessions` | 聊天会话 |
| `chat_messages` | 聊天消息 |
| `model_configs` | 模型配置 |
| `agent_configs` | Agent 配置 |
| `skill_configs` | SKILL 配置 |
| `context_store` | 通用上下文 (key-value) |

### 9.2 访问方式

- **Core Service**: 直接读写 SQLite
- **Main Process**: 通过 ZMQ 请求 Core Service 查询
- **Renderer**: 通过 IPC → Main → ZMQ → Core → SQLite
