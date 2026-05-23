# LLM API 请求架构文档

> 创建日期: 2026-05-18 | 最后更新: 2026-05-21 | 状态: 当前实现 (重构已完成)

---

## 1. 总体架构

系统采用**单一 IPC → ZeroMQ → Python 通路**，所有 LLM 调用均经过 Electron IPC 由 Python 后端统一处理：

| 通路 | 用途 | 协议 | 终端 |
|------|------|------|------|
| **IPC → ZeroMQ → Python**（唯一） | LLM 推理（Chat/Streaming/Tools/Structured）+ 会话管理 + Prompt 模板管理 | Electron IPC → ZeroMQ RPC + PUB | Python 后端 → SQLite |

```
┌──────────────────────────────────────────────────────────────────┐
│                     前端 (Electron + Vue)                       │
│                                                                  │
│  ┌─────────────────┐     ┌──────────────────────────────┐       │
│  │  Chat Store      │     │  Report Cards                │       │
│  │  (聊天面板)      │     │  (AI 解释按钮)               │       │
│  └───┬─────────┬───┘     └──────────┬───────────────────┘       │
│      │         │                    │                            │
│      │  session.* IPC              │  llmClient.ts               │
│      ▼         │                    ▼                            │
│  window.api    │           window.api.llm.chat()                 │
│  .session.*    │           window.api.llm.subscribe()            │
│      │         │           (IPC 订阅模式)                       │
│      │         │                                                 │
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
│       ├── llm.chat             ──┐  LLMService.streaming_chat() │
│       ├── llm.abortChat        ──┤  三模式: chat/tools/structured│
│       ├── llm.summarizeCode    ──┤  Tools Calling + 结构化校验   │
│       ├── llm.explainSymbol    ──┤  ZMQ PUB 推送 chunk/工具事件   │
│       │                          └→ Ollama/OpenAI API            │
│       │                                                          │
│       ├── session.list          ──┐  SQLite 持久化               │
│       ├── session.create         ──┤  llm_sessions/llm_messages  │
│       ├── session.delete         ──┤  表 CRUD                    │
│       ├── session.getMessages    ──┤                              │
│       ├── session.addMessage     ──┘                              │
│       ├── session.deleteMessage                                   │
│       ├── session.saveMessages                                    │
│       ├── session.updateMeta                                      │
│       │                                                          │
│       ├── promptTemplate.list    ──┐  PromptManager              │
│       ├── promptTemplate.get     ──┤  14 个内置模板              │
│       ├── promptTemplate.create  ──┤  chat/tools/structured 三类 │
│       ├── promptTemplate.update  ──┘                              │
│       ├── promptTemplate.delete                                    │
│       ├── promptTemplate.render                                    │
│       │                                                          │
│       ├── group.* (7 方法)       ──┐  functional groups          │
│       │                            └→ 项目功能分组管理             │
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

### 2.1 Composable 层（流式订阅模式）

> ⚠️ 原 Worker 层 (`llm.worker.ts` / `llm.worker.instance.ts`) 已移除。所有 LLM 调用统一走 IPC → ZMQ → Python 后端。

```
src/composables/
├── useLlmChat.ts            # LLM 流式对话 composable（替代旧 Worker）
├── useMermaidRender.ts       # Mermaid 渲染
├── useD3Graph.ts            # D3 力导向图
├── usePlantUmlRender.ts     # PlantUML 渲染
├── usePixiCanvas.ts         # PIXI.js WebGL
└── useAnimation.ts          # TopoScript 动画引擎
```

#### useLlmChat.ts — LLM 流式对话 Composable

替代旧的 Web Worker 方案，通过 `window.api.llm.subscribe()` 订阅后端流式事件：

```typescript
// useLlmChat.ts 核心逻辑
const { send, abort, isStreaming } = useLlmChat()

// 发送消息，自动处理 subscribe + onChunk + onDone + onError
await send({ sessionId, messages, modelId, mode, templateId, variables }, {
  onChunk: (text) => { /* 追加到响应式文本 */ },
  onDone: (content) => { /* 对话完成 */ },
  onError: (err) => { /* 错误处理 */ },
})
// onUnmounted 自动清理订阅，防止内存泄漏
```

**流式事件路由**: `requestId` 机制 — 每个 `llm.chat()` 返回唯一 `requestId`，`subscribe` 按 `requestId` 路由 EventEmitter 回调。

**Provider 支持**（后端处理，前端透明）:

| Provider | 后端处理方法 |
|----------|-------------|
| Ollama | `POST /api/chat` (stream: true) |
| OpenAI / LM-Studio / Custom | `POST /v1/chat/completions` (SSE) |

**流式批处理**（后端侧）: 100ms 定时器 + 200 字符兜底 — Python 后端通过 ZMQ PUB 推送批量 chunk 事件。**流式超时**: 300s (5分钟)，可通过 `abortChat` 手动中止。

### 2.2 Service 层

#### llmClient.ts — 业务级 LLM API

封装 IPC 调用，为 Report 组件提供便捷方法：

| 方法 | 用途 | 使用方 |
|------|------|--------|
| `explainSymbol(params, onChunk)` | 解释代码符号 | SymbolDetailCard |
| `explainEdge(params, onChunk)` | 解释调用/依赖边 | EdgeDetailCard |
| `explainCommunity(params, onChunk)` | 解释社区分组 | CommunityNodeCard |
| `summarizeCode(code, onChunk)` | 长代码压缩为伪码 | SymbolDetailCard |
| `summarizeCommunityName(params, onChunk)` | 生成社区名称 | 分析报告 |
| `chat(options)` | 通用流式对话 | LLMChatFlow |

内部流程: `ensureConfig()` → 从 `settingsStore` 获取默认模型 → 构建 system/user prompt → `window.api.llm.chat() + subscribe()`

#### Prompt 模板

> ⚠️ `promptTemplates.ts` 已移除，改为后端管理。14 个内置模板存储在 `llm_prompt_templates` 表中。

**后端模板管理**: 通过 `promptTemplate.*` RPC 方法操作（`list`, `get`, `create`, `update`, `delete`, `render`）。

**模板分类**:

| 模块 | 模板数 | 说明 |
|------|--------|------|
| project_resource | 2 | 源码转伪码、功能概要 (chat) |
| project_analysis | 5 | 架构解析(tools)、社区命名(structured)、符号摘要、关键词摘要(channel) |
| knowledge_base | 3 | 文档问答/梳理/解析 (chat) |
| ai_assistant | 1 | Agent 对话 (chat) |

**三种模式模板**:

| 模式 | 数量 | 说明 |
|------|------|------|
| `chat` | 10 | 完整文本流式输出 |
| `tools` | 1 | LLM 按需调用后端工具 (get_file_content, get_symbol_detail 等) |
| `structured` | 3 | JSON Schema 校验输出

### 2.3 Store 层

#### chat.ts — useChatStore (Pinia)

聊天面板的状态管理中心:

- **State**: `sessions[]`, `activeSessionId`, `inputMode`, `inputText`, `isTyping`
- **核心方法 `sendMessage()`**:
  1. 从 `settingsStore` 读取默认模型
  2. 从 session 历史构建 `messages[]`
  3. 调用 `useLlmChat().send()` → `window.api.llm.chat()` IPC 调用
  4. `subscribe` 回调实时追加 `aiMessage.content`（响应式更新 UI）
  5. 完成后通过 `session.saveMessages` 持久化
- **会话持久化**: 通过 `window.api.session.*` → IPC → ZeroMQ → Python 后端 → SQLite (`llm_sessions`/`llm_messages` 表)

#### settings.ts — useSettingsStore (Pinia)

模型与 Agent 配置管理中心:

- **State**: `models[]`, `agents[]`, `skills[]`, `bindings[]`
- **CRUD**: `addModel`, `updateModel`, `removeModel`, `testModel` — 全部走 IPC → ZeroMQ → Python → SQLite
- **初始化**: `loadSettings()` 启动时从后端加载所有配置

### 2.4 Components 层

#### Coder 组件（聊天面板 — 右侧栏）

| 组件 | 状态 | 职责 |
|------|------|------|
| ChatFlow.vue | ✅ 生产 (IPC) | 聊天容器：消息列表、模式切换、输入框 |
| ChatInput.vue | mock 驱动 | 备用输入组件 |
| ChatMessage.vue | mock 驱动 | 消息气泡渲染（文本/ContextCards/Spec/TaskStatus） |
| ContextCards.vue | mock 驱动 | 上下文卡片（知识库/代码/分析） |
| SessionTabBar.vue | ✅ 生产 | 多会话标签栏、IPC session.* 操作 |
| SpecCard.vue | mock 驱动 | 规格文档卡片 |
| TaskStatusCard.vue | mock 驱动 | Agent 任务执行状态卡片 |

> ⚠️ ChatFlow 通道已改为 IPC (`window.api.llm.chat` + `subscribe`)，但 contextCards/specSummary/taskStatus 等 UI 卡片仍来自 mock 数据，待后续迭代。

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

**流式事件推送通道**（新增 `llm` topic）:

```
Vue → window.api.llm.chat(params)
  → preload.ts → ipcRenderer.invoke('ipc:call', 'llm.chat', params)
    → main.ts → zmqRouter.call('llm.chat', params)
      → zmq-router.ts (DEALER) → Python backend
        ← zmq-router.ts (SUB) ← ZMQ PUB 流式事件

Python PUB 推送:
  [llm, chunk, {requestId, index, text}]        ← 100ms 批量
  [llm, tool_call, {requestId, name, args}]      ← 工具调用
  [llm, tool_result, {requestId, result}]        ← 工具执行结果
  [llm, done, {requestId, content, usage}]       ← 完成
  [llm, error, {requestId, message}]             ← 错误

main.ts → webContents.send('zmq:event', ...)
  → preload: 按 requestId 路由到 subscribe 注册的回调
```

`window.api` 暴露的 LLM 相关方法:
- `llm.chat` — 统一流式对话 (三模式: chat/tools/structured)
- `llm.abortChat` — 中止流式调用
- `session.*` — 会话管理 (`list / create / delete / getMessages / addMessage / deleteMessage / saveMessages / updateMeta`)
- `promptTemplate.*` — 模板管理 (`list / get / create / update / delete / render`)
- `settings.*` — 模型/Agent/SKILL/绑定配置 CRUD

---

## 3. 后端实现

### 3.1 llm_service.py — LLM 服务层

**文件**: `backend/llm_service.py` (重构后，含 LLMService 类 + PromptManager + ToolExecutor)

#### 核心方法

| 函数 | 类型 | 说明 |
|------|------|------|
| `LLMService.streaming_chat()` | 公开 | 统一流式入口，三模式路由 (chat/tools/structured) |
| `LLMService._stream_chat()` | 内部 | 对话模式：直接流式输出 |
| `LLMService._stream_tools()` | 内部 | Tools Calling：LLM → tool_call → 后端执行 → 继续流式（最多 5 轮） |
| `LLMService._stream_structured()` | 内部 | 结构化输出：全量 → JSON Schema 校验 → 重试最多 2 次 |
| `LLMService._call_llm()` | 内部 | 根据 provider 路由到对应 HTTP 调用 (`asyncio.to_thread`) |
| `LLMService.abort()` | 公开 | 通过 `requestId` 中止正在进行的流式调用 |

#### 注册的 RPC 方法

| RPC 方法 | 用途 | 前端调用情况 |
|----------|------|-------------|
| `llm.chat` | **统一流式对话** (三模式) | ✅ **主入口** |
| `llm.abortChat` | 中止流式调用 | ✅ 已调用 |
| `llm.summarizeCode` | >500 字符代码压缩为伪码 | ✅ 已调用（v1 兼容） |
| `llm.explainSymbol` | 中文解释代码符号 | ✅ 已调用（v1 兼容） |
| `session.*` (8 方法) | 会话管理 CRUD | ✅ 已调用 |
| `promptTemplate.*` (6 方法) | 模板管理 CRUD + Render | ✅ 已调用 |

#### Chat 会话存储

```python
# ✅ SQLite 持久化，进程重启不丢失
# 会话表: sessions.db → llm_sessions / llm_messages
# 日志表: topoone.db → llm_call_logs
```

`LLMService` 通过 `multi_db` 直接写入 SQLite，所有会话和消息持久化存储。

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

**会话库 `sessions.db` — `llm_sessions` + `llm_messages`**: ✅ `LLMService` 使用 SQLite 持久化（旧 `coder_sessions`/`chat_messages` 表已 DROP）。

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

## 5. 架构问题与修复状态

### 5.1 已修复问题

| # | 问题 | 修复 |
|---|------|------|
| 1 | **Chat 会话持久化** | ✅ `LLMService` 使用 SQLite `llm_sessions`/`llm_messages` 表持久化；旧 `coder_sessions`/`chat_messages` 已 DROP |
| 2 | **后端 LLM RPC 方法死代码** | ✅ 统一 `llm.chat` 为主入口；`llm.summarizeCode`/`explainSymbol` 保留为 v1 兼容方法并接入前端 |
| 3 | **双通道 LLM 调用路径** | ✅ 移除 Worker，统一走 IPC → ZMQ → Python 后端 |
| 4 | **API Key Worker 明文传输** | ✅ Worker 已移除，API Key 仅在后端处理 |
| 5 | **llm.summarizeCommunityName 死代码** | ✅ 已移除，统一走 `llm.chat` 结构化模式 |

### 5.2 剩余问题

| # | 问题 | 严重性 | 详情 |
|---|------|--------|------|
| 1 | **Coder 组件 mock 驱动** | 🟡 中等 | ChatFlow 通道已改 IPC，但 UI 卡片 (contextCards/specSummary/taskStatus) 仍来自 mock 数据 |
| 2 | **类型定义分散** | 🟢 低 | `src/types/ipc.ts`、`src/types/index.ts`、`src/utils/mock.ts` 三处存在相似类型 |
| 3 | **API Key 存储在 SQLite 明文** | 🟢 低 | `model_configs.api_key` 字段明文存储。Electron 本地应用可接受，但需注意 |

### 5.3 Coder 面板 vs Report 面板功能分裂 (待统一)

```
┌─────────────────────────────────────────────────┐
│  功能            Coder 面板    Report 面板       │
├─────────────────────────────────────────────────┤
│  LLM 流式对话    ✅ 可用       ✅ 可用          │
│  Prompt 模板     ❌ 无         ✅ 14 个模板     │
│  上下文卡片      ✅ (mock)     ❌ 无             │
│  规格文档卡片    ✅ (mock)     ❌ 无             │
│  任务状态卡片    ✅ (mock)     ❌ 无             │
│  社区图分析      ❌ 无         ✅ 可用          │
│  会话持久化      ✅ SQLite     ✅ (子文档)      │
│  多会话切换      ✅ 可用       ❌ 无             │
│  会话管理后端    ✅ IPC        ❌ 无             │
└─────────────────────────────────────────────────┘
```

---

## 6. 重构进度与后续建议

### 6.1 已完成重构 (2026-05-18~2026-05-20)

| 任务 | 状态 | 说明 |
|------|------|------|
| **Chat 会话持久化** | ✅ | 使用 `llm_sessions`/`llm_messages` 表，进程重启不丢失 |
| **Worker → IPC 迁移** | ✅ | 移除 `llm.worker.ts`/`llm.worker.instance.ts`，统一走 IPC |
| **三模式交互体系** | ✅ | chat/tools/structured 三种模式上线 |
| **Prompt 模板后端管理** | ✅ | `prompt_manager.py` + `promptTemplate.*` RPC，14 个内置模板 |
| **Tools Calling 执行器** | ✅ | `tools_executor.py`，6 个内置工具，最多 5 轮循环 |
| **结构化输出校验** | ✅ | JSON Schema 校验 + 2 次重试 |
| **ZMQ PUB llm 事件流** | ✅ | chunk/tool_call/tool_result/done/error 五种事件 |
| **流式超时配置** | ✅ | 默认 300s，支持手动 abort |

### 6.2 后续建议

| # | 建议 | 优先级 |
|---|------|--------|
| 1 | **Coder 组件脱 mock** — 将 ChatFlow/ChatMessage 类型从 `@/utils/mock` 切换到真实 IPC 响应结构 | P1 |
| 2 | **类型定义归一化** — 合并 `src/types/ipc.ts`、`src/types/index.ts`、`src/utils/mock.ts` 中重复的 LLM 类型 | P2 |
| 3 | **Coder → Report 能力对齐** — 为 Coder 面板添加 Prompt 模板选择，为 Report 面板添加会话历史 | P2 |
| 4 | **Prompt 模板管理 UI** — 允许用户通过设置页面自定义/编辑 Prompt 模板 | P3 |
| 5 | **LLM 调用日志/审计 UI** — 查看每次 LLM 请求的 token 用量、延迟等 | P3 |
| 6 | **多模型 Fallback** — 默认模型不可用时自动切换备用模型 | P3 |
