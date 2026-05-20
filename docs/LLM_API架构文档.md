# LLM API 请求架构文档

> 创建日期: 2026-05-18 | 状态: 当前实现

---

## 1. 总体架构

系统存在**两条并行的 LLM 通路**，各司其职：

| 通路 | 用途 | 协议 | 终端 |
|------|------|------|------|
| **A. Web Worker 直连**（主） | LLM 推理（Chat/Streaming/Embedding） | HTTP → Ollama/OpenAI API | LLM Provider |
| **B. IPC → ZeroMQ → Python**（辅） | 模型配置 CRUD + Chat 会话管理 | Electron IPC → ZeroMQ RPC | Python 后端 → SQLite |

```
┌──────────────────────────────────────────────────────────────────┐
│                     前端 (Electron + Vue)                       │
│                                                                  │
│  ┌─────────────────┐     ┌──────────────────────────────┐       │
│  │  Chat Store      │     │  Report Cards                │       │
│  │  (聊天面板)      │     │  (AI 解释按钮)               │       │
│  └───┬─────────┬───┘     └──────────┬───────────────────┘       │
│      │         │                    │                            │
│      │  会话管理                    │  llmClient.ts              │
│      ▼         │                    ▼                            │
│  window.api    │           llm.worker.instance.ts                │
│  .chat.*       │           (Worker 单例桥接)                    │
│      │         │                    │                            │
│      │         │           llm.worker.ts                        │
│      │         │           (Web Worker 线程)                    │
│      │         │           ┌──────────────────┐                 │
│      │         │           │ HTTP fetch()     │◄──── LLM 推理   │
│      │         │           │ Ollama / OpenAI  │     直接 HTTP    │
│      │         │           │ Streaming + SSE  │                 │
│      │         │           └──────────────────┘                 │
│      ▼         │                                                 │
│  IPC bridge    │                                                 │
│  (preload.ts) │                                                  │
└──────┬─────────┘────────────────────────────────────────────────┘
       │
       │  Electron main.ts
       │  zmqRouter.call()
       ▼
┌──────────────────────────────────────────────────────────────────┐
│                    后端 (Python)                                 │
│                                                                  │
│  ZeroMQ DEALER (5671)                                           │
│       │                                                          │
│       ▼                                                          │
│  ZMQServer.methods 注册表                                       │
│       │                                                          │
│       ├── chat.listSessions    ──┐                               │
│       ├── chat.createSession   ──┤  内存 session_store (⚠️ 易失)│
│       ├── chat.deleteSession   ──┤                               │
│       ├── chat.saveMessage     ──┘                               │
│       │                                                          │
│       ├── llm.summarizeCode      ──┐  ⚠️ 已注册但前端未调用     │
│       ├── llm.explainSymbol      ──┤  requests.post()            │
│       └── llm.summarizeCommunity  ──┘  → Ollama/OpenAI API       │
│                                                                  │
│  settings.* (core_service.py)                                   │
│       ├── settings.getModels        model_configs CRUD           │
│       ├── settings.addModel                                     │
│       ├── settings.updateModel                                  │
│       ├── settings.removeModel                                  │
│       ├── settings.testModel                                     │
│       ├── settings.getBindings      task_model_bindings          │
│       └── settings.updateBindings                               │
└──────────────────────────────────────────────────────────────────┘
```

---

## 2. 前端实现

### 2.1 Worker 层（核心推理引擎）

```
src/workers/
├── llm.worker.ts           # Worker 本体：HTTP fetch + SSE 流式解析 + 请求队列
├── llm.worker.instance.ts  # Worker 单例桥接：postMessage ↔ Promise
└── types.ts                # 渲染 Worker 类型（与 LLM 无关）
```

#### llm.worker.ts — Web Worker 逻辑

**线程隔离**: 所有 HTTP fetch 到 LLM Provider 的调用在独立 Worker 线程执行，不阻塞 UI 主线程。

**Provider 支持**:

| Provider | API 端点 | 认证 | 流式格式 |
|----------|---------|------|---------|
| Ollama | `{url}/api/chat` | 无 | 逐行 JSON |
| OpenAI | `{url}/v1/chat/completions` | `Bearer {apiKey}` | SSE (`data:` 前缀 + `[DONE]`) |
| LM-Studio | `{url}/v1/chat/completions` | 无 | SSE |
| Custom | `{url}/v1/chat/completions` | `Bearer {apiKey}`（可选） | SSE |

**请求队列**: FIFO 队列，最大并发 3，`setConfig` / `chat` / `embed` / `test` 四种消息类型。

**流式批处理**: 16ms 定时器 + 500 字符兜底 — 将 SSE 字节流以对齐浏览器刷新帧率的粒度批量投递回主线程。

**消息路由**: `requestId` 机制 — 每个 `postMessage` 带 `requestId`，Worker 桥接层根据 `requestId` resolve 对应 Promise。

#### llm.worker.instance.ts — Worker 单例桥接

`LlmWorkerClient` 类（单例 `llmWorker`）：

```typescript
class LlmWorkerClient {
  setConfig(config: ModelConfig): void
  chat(messages, onChunk): Promise<string>     // 流式 Chat
  embed(text): Promise<number[]>               // 文本向量化
  testConnection(): Promise<{status, latency}> // 连接性测试
}
```

- 通过 Vite `?worker` 导入创建 Worker 实例
- `postMessage` 发送请求，`onmessage` 监听响应
- 每个 `chat()` 调用创建独立 `requestId`，在 `onmessage` 中路由 chunk/done/error

### 2.2 Service 层

#### llmClient.ts — 业务级 LLM API

封装 Worker 调用，为 Report 组件提供便捷方法：

| 方法 | 用途 | 使用方 |
|------|------|--------|
| `explainSymbol(params, onChunk)` | 解释代码符号 | SymbolDetailCard |
| `explainEdge(params, onChunk)` | 解释调用/依赖边 | EdgeDetailCard |
| `explainCommunity(params, onChunk)` | 解释社区分组 | CommunityNodeCard |
| `summarizeCode(code, onChunk)` | 长代码压缩为伪码 | SymbolDetailCard |
| `summarizeCommunityName(params, onChunk)` | 生成社区名称 | 分析报告 |
| `chat(options)` | 通用流式对话 | LLMChatFlow |

内部流程: `ensureConfig()` → 从 `settingsStore` 同步配置到 `llmWorker` → 构建 system/user prompt → `llmWorker.chat()`

#### promptTemplates.ts — Prompt 模板注册表

```
7 个内置模板:

社区类 (mode=community):
  ├── community_explain       — 解释社区功能
  ├── community_architecture  — 分析架构模式
  ├── community_business      — 梳理业务逻辑
  └── community_pseudocode    — 生成伪码

源码类 (mode=source_code):
  ├── source_explain          — 解释代码片段
  ├── source_summary          — 概述代码功能
  └── source_pseudocode       — 转换为伪码
```

每个模板包含: `id`, `name`, `mode`, `outputFormat` (markdown/structured/tool_call), `systemPrompt`, `userPrompt` (含 `{variable}` 占位符), `variables[]`

`renderPrompt(template, variables)` 方法负责填充占位符。

### 2.3 Store 层

#### chat.ts — useChatStore (Pinia)

聊天面板的状态管理中心:

- **State**: `sessions[]`, `activeSessionId`, `inputMode`, `inputText`, `isTyping`
- **核心方法 `sendMessage()`**:
  1. 从 `settingsStore` 读取默认模型
  2. 调用 `llmWorker.setConfig()` 同步配置
  3. 从 session 历史构建 `messages[]`
  4. 调用 `llmWorker.chat(messages, onChunk)` 流式对话
  5. `onChunk` 回调实时追加 `aiMessage.content`（响应式更新 UI）
- **会话持久化**: 通过 `window.api.chat.*` → IPC → ZeroMQ → Python 后端同步

#### settings.ts — useSettingsStore (Pinia)

模型与 Agent 配置管理中心:

- **State**: `models[]`, `agents[]`, `skills[]`, `bindings[]`
- **CRUD**: `addModel`, `updateModel`, `removeModel`, `testModel` — 全部走 IPC → ZeroMQ → Python → SQLite
- **初始化**: `loadSettings()` 启动时从后端加载所有配置

### 2.4 Components 层

#### Coder 组件（聊天面板 — 右侧栏）

| 组件 | 状态 | 职责 |
|------|------|------|
| ChatFlow.vue | mock 驱动 | 聊天容器：消息列表、模式切换、输入框 |
| ChatInput.vue | mock 驱动 | 备用输入组件 |
| ChatMessage.vue | mock 驱动 | 消息气泡渲染（文本/ContextCards/Spec/TaskStatus） |
| ContextCards.vue | mock 驱动 | 上下文卡片（知识库/代码/分析） |
| SessionTabBar.vue | ✅ 生产 | 多会话标签栏 |
| SpecCard.vue | mock 驱动 | 规格文档卡片 |
| TaskStatusCard.vue | mock 驱动 | Agent 任务执行状态卡片 |

> ⚠️ Coder 组件大量导入 `@/utils/mock` 类型，LLM 实际调用通过 `chatStore.sendMessage()` 进行，但 UI 中的 contextCards/specSummary/taskStatus 字段来自 mock 数据。

#### Report 组件（分析报告 AI 交互 — 分析页）

| 组件 | 状态 | 职责 |
|------|------|------|
| LLMChatFlow.vue | ✅ 生产 | 报告内嵌 LLM 对话：获取社区图 + 渲染 Prompt 模板 + 流式 Chat + 保存为子文档 |
| CommunityNodeCard.vue | ✅ 生产 | 社区节点 AI 解释按钮 → `llmClient.explainCommunity()` |
| SymbolDetailCard.vue | ✅ 生产 | 符号详情 AI 解释 → `llmClient.explainSymbol()` |
| EdgeDetailCard.vue | ✅ 生产 | 边详情 AI 解释 → `llmClient.explainEdge()` |

#### Settings 组件

| 组件 | 状态 | 职责 |
|------|------|------|
| ModelConfig.vue | ✅ 生产 | 模型配置 UI：增删改 + 测试连接 + 设置默认 + provider 选择 |

### 2.5 Electron IPC Bridge

```
preload.ts → ipcRenderer.invoke('ipc:call', {method, params})
  → main.ts → zmqRouter.call(method, params)
    → zmq-router.ts → ZeroMQ DEALER → tcp://127.0.0.1:5671
      → Python backend
```

`window.api` 暴露的 LLM 相关方法:
- `settings.getModels / addModel / updateModel / removeModel / testModel`
- `settings.getAgents / addAgent / updateAgent / removeAgent`
- `settings.getSkills / updateSkill`
- `settings.getBindings / updateBindings`
- `chat.listSessions / createSession / deleteSession / saveMessage`

---

## 3. 后端实现

### 3.1 llm_service.py — LLM 服务层

**文件**: `backend/llm_service.py`

#### 核心方法

| 函数 | 类型 | 说明 |
|------|------|------|
| `_call_llm(model_config, messages)` | 内部 | 根据 provider 路由到对应同步 HTTP 调用（使用 `asyncio.to_thread`） |
| `_sync_call_ollama_chat(config, messages)` | 内部 | Ollama `POST /api/chat`，`stream: false` |
| `_sync_call_openai_chat(config, messages)` | 内部 | OpenAI 兼容 `POST /v1/chat/completions`，支持 Bearer 认证 |

#### 注册的 RPC 方法

| RPC 方法 | 用途 | 前端调用情况 |
|----------|------|-------------|
| `llm.summarizeCode` | >500 字符代码压缩为伪码 | ⚠️ **未调用**（前端 Worker 直连） |
| `llm.explainSymbol` | 中文解释代码符号 | ⚠️ **未调用**（前端 Worker 直连） |
| `llm.summarizeCommunityName` | 生成社区分组名称（≤10字） | ⚠️ **未调用**（前端 Worker 直连） |
| `chat.listSessions` | 列出所有 Chat 会话 | ✅ 已调用 |
| `chat.createSession` | 创建 Chat 会话 | ✅ 已调用 |
| `chat.deleteSession` | 删除 Chat 会话 | ✅ 已调用 |
| `chat.saveMessage` | 保存消息到会话 | ✅ 已调用 |

#### Chat 会话存储

```python
# ⚠️ 内存存储，进程重启即丢失
session_store: Dict[str, Dict] = {}
```

`sessions.db` 数据库中有 `coder_sessions` 和 `chat_messages` 表，但 `llm_service.py` **未使用**。

### 3.2 core_service.py — 设置方法

在 `register_settings_methods()` 中注册的 LLM 相关 RPC 方法：

| RPC 方法 | 用途 |
|----------|------|
| `settings.getModels` | 列出全部模型配置（api_key 隐去，返回 hasApiKey 布尔值） |
| `settings.addModel` | 新增模型配置，设为默认时自动清除其他默认标记 |
| `settings.updateModel` | 更新模型配置 |
| `settings.removeModel` | 删除模型配置 |
| `settings.testModel` | 连接性测试（Ollama: `GET /api/tags`，OpenAI: `GET /v1/models`） |
| `settings.getBindings` | 获取 task_model_bindings |
| `settings.updateBindings` | 更新 task_model_bindings |

### 3.3 main.py — LLM 初始化

```python
from llm_service import register_llm_methods

class BackendApp:
    def register_all(self):
        # ...
        register_llm_methods(self.server, self.multi_db)  # 第 91 行
        # ...
```

LLM 方法与其他 6 个 register 函数并列注册到统一 ZMQServer。

### 3.4 task_manager.py — 分析任务中的 LLM 标记

`analysis.getSymbolDetail` 方法（约第 779 行）:
- 读取代码片段后，若 `len(code_snippet) > 500`，设置 `needs_summarize: true`
- 该标志发给前端，前端 **自行** 通过 Worker 调用 LLM 压缩
- 任务管理器本身 **不直接调用 LLM**

### 3.5 数据库表

**主库 `topoone.db` — `model_configs` 表**:

```sql
CREATE TABLE model_configs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    provider TEXT NOT NULL CHECK(provider IN ('ollama','openai','lm-studio','custom')),
    model TEXT NOT NULL,
    url TEXT NOT NULL,
    api_key TEXT DEFAULT '',
    type TEXT DEFAULT 'local' CHECK(type IN ('local','cloud')),
    status TEXT DEFAULT 'offline',
    is_default INTEGER DEFAULT 0,
    temperature REAL DEFAULT 0.7,
    max_tokens INTEGER DEFAULT 4096,
    timeout INTEGER DEFAULT 30000,
    extra_config TEXT,
    created_at, updated_at
);
```

**`task_model_bindings` 表**: 任务类型 → 模型 ID 映射。

**会话库 `sessions.db` — `coder_sessions` + `chat_messages`**: ⚠️ 存在但未被 `llm_service.py` 使用。

**`agent_configs` / `skill_configs` 表**: 用于 Qwen-Code / Cline 等外部 Agent 工具配置，与 LLM 推理调用分离。

### 3.6 依赖

`backend/requirements.txt`:
- `requests>=2.31.0` — HTTP 调用
- 无 `openai`、`anthropic`、`ollama` 等 SDK — 全部使用原始 `requests` 库

---

## 4. 数据流全景

### 路径 A: Coder 聊天面板 (ChatFlow)

```
用户输入
  → ChatFlow.vue emit('send')
    → chatStore.sendMessage()
      → llmWorker.setConfig({url, apiKey, provider, model, ...})
      → llmWorker.chat(messages, onChunk)
        → Worker: fetch() → Ollama/OpenAI API
          → ReadableStream → SSE 解析 → 16ms 批量
            → postMessage({type:'chunk', requestId, data})
              → onChunk 回调 → aiMessage.content += chunk (响应式渲染)
```

### 路径 B: 分析报告 AI 解释 (Report Cards)

```
用户点击 "AI 解释"
  → Component 调用 llmClient.explainSymbol/explainEdge/explainCommunity(params, onChunk)
    → llmClient.ensureConfig() → 同步 settingsStore → llmWorker
    → llmClient 构建 system/user prompt
      → llmWorker.chat([{role:'system',...}, {role:'user',...}], onChunk)
        → Worker: fetch() → Provider API (同上)
          → onChunk 回调 → aiContent.value += chunk (卡片内渲染)
```

### 路径 C: 报告内嵌 LLM 对话 (LLMChatFlow)

```
用户点击 "AI Analyze"
  → LLMChatFlow.vue onQuickParseCommunity()
    → window.api.analysis.getCommunityGraph() → IPC → ZeroMQ → Python → SQLite
    → renderPrompt(template, communityData) 渲染 Prompt
    → llmWorker.setConfig() + llmWorker.chat(messages, onChunk)
      → Worker: fetch() → Provider API
        → 流式结果渲染在报告底部对话区
          → 用户可 'save-subdoc' → window.api.report.createSubDoc() 持久化
```

### 路径 D: 模型配置 CRUD

```
ModelConfig.vue 表单提交
  → settingsStore.addModel(params)
    → ipc.settings.addModel(params)
      → window.api.settings.addModel(params)
        → preload.ts → ipcRenderer.invoke('ipc:call', {method, params})
          → main.ts → zmqRouter.call('settings.addModel', params)
            → ZeroMQ DEALER → tcp://127.0.0.1:5671
              → Python: core_service.py → SQLite INSERT
                → 返回 model_id
                  → settingsStore.models 更新
```

---

## 5. 架构问题总结

### 5.1 致命问题

| # | 问题 | 严重性 | 详情 |
|---|------|--------|------|
| 1 | **Chat 会话易失性存储** | 🔴 致命 | 后端 `session_store` 是内存 dict，进程重启全部丢失。`sessions.db` 中的 `coder_sessions`/`chat_messages` 表存在但未使用。 |
| 2 | **后端 LLM RPC 方法死代码** | 🟡 中等 | 后端注册了 `llm.summarizeCode`、`llm.explainSymbol`、`llm.summarizeCommunityName`，但 `window.api` 中没有对应绑定，前端完全绕过它们走 Worker。 |

### 5.2 架构层面

| # | 问题 | 严重性 | 详情 |
|---|------|--------|------|
| 3 | **双通道 LLM 调用路径** | 🟡 中等 | 前端 Worker 和后端 Python 各有一套 LLM HTTP 调用逻辑，代码重复、维护负担加倍。 |
| 4 | **Coder 组件 mock 驱动** | 🟡 中等 | ChatFlow/ChatMessage/ContextCards 等导入 `@/utils/mock` 类型，UI 展示的 contextCards/specSummary/taskStatus 来自 mock 数据，与真实 LLM 响应结构脱节。 |
| 5 | **类型定义分散** | 🟢 低 | `src/types/ipc.ts`、`src/types/index.ts`、`src/utils/mock.ts` 三处各自定义了 `ChatMessage`、`CoderSession`、`ChatSession` 等相似类型。 |

### 5.3 安全隐患

| # | 问题 | 严重性 | 详情 |
|---|------|--------|------|
| 6 | **API Key 在 Worker 中明文传输** | 🟡 中等 | `setConfig()` 将 `apiKey` 以明文通过 `postMessage` 发送到 Worker 线程，Worker 线程内存中可访问完整 key。 |
| 7 | **API Key 存储在 SQLite 明文** | 🟢 低 | `model_configs.api_key` 字段明文存储。Electron 本地应用可接受，但需注意。 |

### 5.4 Coder 面板 vs Report 面板功能分裂

```
┌─────────────────────────────────────────────────┐
│  功能            Coder 面板    Report 面板       │
├─────────────────────────────────────────────────┤
│  LLM 流式对话    ✅ 可用       ✅ 可用          │
│  Prompt 模板     ❌ 无         ✅ 7 个模板      │
│  上下文卡片      ✅ (mock)     ❌ 无             │
│  规格文档卡片    ✅ (mock)     ❌ 无             │
│  任务状态卡片    ✅ (mock)     ❌ 无             │
│  社区图分析      ❌ 无         ✅ 可用          │
│  会话持久化      ⚠️ 易失      ✅ (子文档)      │
│  多会话切换      ✅ 可用       ❌ 无             │
│  会话管理后端    ✅ IPC        ❌ 无             │
└─────────────────────────────────────────────────┘
```

两个面板共享同一个 `llmWorker` 单例，但功能互不相通。

---

## 6. 重构方向建议

### 6.1 短期（稳定性优先）

1. **Chat 会话持久化** — 将 `llm_service.py` 的 `session_store` 改为使用 `sessions.db` 的 `coder_sessions`/`chat_messages` 表，防止进程重启丢失
2. **清理死代码** — 移除或标记后端 `llm.summarizeCode` 等未被调用的 RPC 方法，降低维护负担
3. **Coder 组件脱 mock** — 将 ChatFlow/ChatMessage 的类型从 `@/utils/mock` 切换到 `src/types/index.ts`，对接真实 LLM 响应结构

### 6.2 中期（架构统一）

4. **统一 LLM 调用通道** — 二选一：全部走 Worker（推荐，保持 UI 响应）或全部走后端（支持服务端缓存/日志/审计）
5. **类型定义归一化** — 合并 `src/types/ipc.ts`、`src/types/index.ts`、`src/utils/mock.ts` 中重复的 LLM 相关类型
6. **Coder → Report 能力对齐** — 为 Coder 面板添加 Prompt 模板选择，为 Report 面板添加社区图数据引用能力

### 6.3 长期（体验优化）

7. **Prompt 模板管理 UI** — 允许用户自定义/编辑 Prompt 模板，存储到 SQLite
8. **LLM 调用日志/审计** — 记录每次 LLM 请求的 model, provider, token 用量, 延迟
9. **多模型 Fallback** — 默认模型不可用时自动切换备用模型
