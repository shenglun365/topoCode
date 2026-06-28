# Web 端 AI 对话 & Agent 能力拓展

## 1. 背景与目标

### 1.1 现状

- Electron 应用内的 `AIAssistantPanel` 同时处理**任务命令**（`/analyze` `/presummary` 等）和**自由对话**
- 任务命令用于触发社区分析、文件预摘要等操作，已形成完整体系
- 自由对话走 `llmClient.chat()`，注入图上下文后调用 LLM
- 文档查看器（`SubDocViewer`）和结构图（`CommunityGraphView`）与 AI 无直接交互

### 1.2 目标

| 目标 | 说明 |
|------|------|
| **范围分离** | In-App AI 只处理任务命令 + 使用帮助，自由对话引导到 Web |
| **Web 独立聊天** | 独立浏览器 Tab，多会话管理，自由定义和切换 |
| **模型自选** | 问答用 API 模型（DeepSeek V4 Pro/Flash, MiniMax3），代码分析时推荐本地 14B~9B |
| **上下文引用** | 文档和结构图一键引用到 Web 聊天，自动注入上下文 |
| **Agent 能力** | 具备 function calling + tool 执行能力，可查询项目架构、源码、社区数据 |
| **知识沉淀** | 对话内容持久化到 SQLite，关联项目/任务/标签，作为知识库数据源 |
| **可扩展** | 未来可增加爬虫、第三方文档阅读等能力，跟随 harness skills/tools 体系 |

### 1.3 原则

- 不在文档和结构图页面嵌入聊天框，只加「引用到 AI 会话」按钮
- Web 聊天独立 Tab，不干扰现有文档 + 图的交互闭环
- In-App AI 自由对话直接显示引导消息，不调 LLM
- 会话上下文通过 URL `?ref=` 参数传递，服务端注入 system message

---

## 2. 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                      main.py（同进程）                                │
│  ┌──────────────────────┐  ┌──────────────────────────────────────┐  │
│  │   ZMQ Server          │  │   Web Server (FastAPI :3456)         │  │
│  │   ├─ DEALER :5671     │  │   ├─ GET  /chat                     │  │
│  │   ├─ PUB    :5680     │  │   ├─ GET  /api/chat/sessions        │  │
│  │   └─ RPC 方法注册     │  │   ├─ POST /api/chat/sessions        │  │
│  │                       │  │   ├─ POST /api/chat/send (SSE)      │  │
│  │  ┌──────────────────┐ │  │   ├─ GET  /api/models               │  │
│  │  │   LLMService      │ │  │   └─ 静态文件 /static/             │  │
│  │  │   ├─ streaming    │ │  │        └─ chat.html                │  │
│  │  │   ├─ chat_sse()   │◄┼──┤                                    │  │
│  │  │   └─ ToolExecutor │ │  │                                    │  │
│  │  └──────────────────┘ │  └──────────────────────────────────────┘  │
│  │                       │                                           │
│  │  SQLite ─── multi_db  │─────────────────────── model_configs     │
│  │                       │                       llm_sessions        │
│  │                       │                       llm_messages        │
│  └───────────────────────┘                                           │
└─────────────────────────────────────────────────────────────────────┘
           │ ZMQ DEALER                           │ HTTP
           ▼                                       ▼
┌──────────────────────┐              ┌──────────────────────────┐
│   Electron App       │              │   浏览器 Tab              │
│   ├─ AI Assistant    │              │   ├─ chat.html           │
│   │  (任务命令)       │              │   ├─ 会话列表             │
│   ├─ SubDocViewer    │              │   ├─ 模型选择器            │
│   │  [引用到AI]      │              │   └─ SSE 流式消息          │
│   └─ GraphView       │              └──────────────────────────┘
│      [导出到AI]       │
└──────────────────────┘
```

### 2.1 关键架构决策

| 决策 | 选择 | 理由 |
|------|------|------|
| Web Server 形式 | 扩展现有 `plugins/reports/web_server.py` | 与 main.py 同进程，共享 `multi_db`，无需额外部署 |
| SSE 流式方案 | `chat_sse()` 使用独立 `asyncio.Queue` | 不走 ZMQ PUB，与 Electron 路径隔离，不阻塞现有 API |
| 会话持久化 | SQLite `llm_sessions` + `llm_messages` | 复用后端已有表结构，通过 `module_type='web_chat'` 区分 |
| 模型选择 | 会话级固定（创建时选择） | 用户清楚会话目的，避免同会话切换带来的不一致 |
| Agent 工具 | 复用 `ToolExecutor` + MCP `tools.py` | 现有 7 个工具可直接使用，新增工具注册到 `_handlers` 即可 |

---

## 3. 详细设计

### 3.1 In-App AI 助手收紧

**文件**: `src/components/ai/AIAssistantPanel.vue`

处理流程改为：

```
用户输入
  ├─ 以 / 开头 → 按现有命令路由（task + help），不变
  │
  └─ 非 / 开头 → 显示引导消息，不调用 LLM
```

引导消息：

> 这是一个通用知识问题。请使用 **Web AI 助手** 进行深入探讨，它支持多会话、持久化存储，并能引用项目文档和架构图作为上下文。
>
> 🔗 [打开 Web AI 助手 →](http://127.0.0.1:3456/chat)

### 3.2 数据库层

#### 3.2.1 `llm_sessions` 表扩展

```sql
CREATE TABLE IF NOT EXISTS llm_sessions (
  id TEXT PRIMARY KEY,
  module_type TEXT NOT NULL DEFAULT 'web_chat',  -- 'web_chat' | 'ai_assistant'
  title TEXT NOT NULL DEFAULT '',
  project_id TEXT,                    -- 可选关联项目（避免碎片化）
  task_id TEXT,                       -- 可选关联任务
  ref_type TEXT,                      -- 'doc' | 'graph' | 'free' | null
  ref_id TEXT,                        -- 具体引用 ID
  model_id TEXT,                      -- 会话使用的模型 ID
  status TEXT DEFAULT 'active',       -- 'active' | 'archived'
  metadata TEXT DEFAULT '{}',         -- JSON: tags, source, created_from
  created_at TEXT,
  updated_at TEXT
);

CREATE INDEX idx_sessions_project ON llm_sessions(project_id);
CREATE INDEX idx_sessions_module ON llm_sessions(module_type);
```

#### 3.2.2 `llm_messages` 表扩展

```sql
CREATE TABLE IF NOT EXISTS llm_messages (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES llm_sessions(id),
  role TEXT NOT NULL,                 -- 'user' | 'assistant' | 'system' | 'tool'
  content TEXT,
  tool_calls TEXT,                    -- JSON: [{name, arguments}]
  tool_results TEXT,                  -- JSON: [{name, result}]
  metadata TEXT DEFAULT '{}',         -- JSON: token_count, model_id, latency_ms
  sequence_num INTEGER NOT NULL,
  created_at TEXT
);

CREATE INDEX idx_messages_session ON llm_messages(session_id, sequence_num);
```

#### 3.2.3 设计要点

- `project_id` / `task_id` 可选——避免强制关联导致碎片化
- `ref_type` / `ref_id` 记录来源，Web 服务端在创建 session 时自动填充
- `metadata.tags` 用于后续知识库筛选（如 `["架构", "知识点"]`）
- 与 `ai_assistant` 类型共存于同一表，通过 `module_type` 区分
- 对话内容完整存储，是知识库的重要数据来源

### 3.3 Web Server 新增路由

**文件**: `plugins/reports/web_server.py`

#### 3.3.1 页面路由

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/chat` | 返回聊天页面 `static/chat.html` |

#### 3.3.2 API 路由

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/models` | 获取可用模型列表 |
| `GET` | `/api/chat/sessions` | 按 `project_id` / `status` 列出会话 |
| `POST` | `/api/chat/sessions` | 创建会话 `{title, project_id?, task_id?, model_id?, ref_type?, ref_id?}` |
| `DELETE` | `/api/chat/sessions/{id}` | 删除会话 |
| `PUT` | `/api/chat/sessions/{id}` | 更新会话（重命名/切换模型/归档） |
| `GET` | `/api/chat/sessions/{id}/messages` | 分页获取消息 |
| `POST` | `/api/chat/send` | 发送消息，返回 SSE 流 |

#### 3.3.3 SSE 流式端点

```python
@router.post("/api/chat/send")
async def chat_send(request: ChatSendRequest):
    """发送消息，返回 SSE 流式响应"""
    session_id = request.sessionId
    message = request.message
    model_id = request.modelId

    # 1. 保存用户消息
    save_message(session_id, role='user', content=message)

    # 2. 获取历史消息 + 系统上下文
    messages = load_session_messages(session_id)

    # 3. 创建 asyncio.Queue 作为 chunk 通道
    output_queue: asyncio.Queue = asyncio.Queue()

    # 4. 启动后台流式任务
    asyncio.create_task(
        llm_service.chat_sse(
            session_id=session_id,
            messages=messages,
            model_id=model_id,
            mode='tools',          # 启用 function calling
            output_queue=output_queue,
        )
    )

    # 5. 返回 SSE
    async def event_stream():
        while True:
            event = await output_queue.get()
            if event['type'] == 'done':
                yield f"event: done\ndata: {json.dumps(event)}\n\n"
                break
            elif event['type'] == 'error':
                yield f"event: error\ndata: {json.dumps(event)}\n\n"
                break
            elif event['type'] == 'chunk':
                yield f"event: chunk\ndata: {json.dumps(event)}\n\n"
            elif event['type'] == 'tool_call':
                yield f"event: tool_call\ndata: {json.dumps(event)}\n\n"
            elif event['type'] == 'tool_result':
                yield f"event: tool_result\ndata: {json.dumps(event)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
```

### 3.4 SSE 流式实现（后端核心）

**文件**: `backend-core/llm_service.py`

新增 `chat_sse()` 方法：

```python
async def chat_sse(
    self,
    session_id: str,
    messages: List[Dict],
    model_id: str,
    mode: str = 'tools',
    tools: Optional[List[str]] = None,
    output_queue: asyncio.Queue,
) -> None:
    """SSE 模式的流式 LLM 调用，chunk 写入 output_queue

    与 streaming_chat() 共享 _execute_streaming 的核心逻辑，
    但 chunk 输出目标从 ZMQ PUB 改为 asyncio.Queue。
    """
    request_id = _make_id()
    model = _get_model_by_id(self.multi_db, model_id)
    if not model:
        await output_queue.put({'type': 'error', 'message': f'Model not found: {model_id}'})
        return

    try:
        # 流式调用 + tool calling 循环（复用 _execute_streaming 核心逻辑）
        # 区别：self._publish → output_queue.put
        await self._execute_sse(
            request_id, session_id, messages, model,
            mode, tools, None, None, None,
            output_queue=output_queue,
        )
    except Exception as e:
        await output_queue.put({'type': 'error', 'message': str(e)})
    finally:
        await output_queue.put({'type': 'done'})
```

`_execute_sse` 从 `_execute_streaming` 复制核心循环，但：
- 将 `self._publish('llm', 'chunk', data)` 替换为 `output_queue.put({'type': 'chunk', ...})`
- `tool_call` / `tool_result` / `done` / `error` 同理
- 工具执行沿用 `ToolExecutor.execute()`，无需改动

这样 ZMQ PUB 路径与 SSE 路径完全隔离，互不影响。

### 3.5 模型选择

#### 3.5.1 API 端点

```python
@router.get("/api/models")
async def list_models():
    """列出所有已配置的模型，标注能力类型"""
    rows = multi_db.main_db.fetchall(
        "SELECT id, name, provider, model, is_default, capabilities FROM model_configs WHERE enabled = 1"
    )
    result = []
    for r in rows:
        badge = '本地' if r['provider'] == 'ollama' else 'API'
        result.append({
            'id': r['id'],
            'name': r['name'] or r['model'],
            'provider': r['provider'],
            'model': r['model'],
            'isDefault': bool(r['is_default']),
            'badge': badge,
        })
    return result
```

#### 3.5.2 模型推荐场景

| 使用场景 | 推荐模型 | 原因 |
|----------|----------|------|
| Web 知识问答 | DeepSeek V4 Pro/Flash, MiniMax3 等 API 模型 | 质量高，上下文窗口大，适合多轮对话 |
| 代码/架构分析（Web） | DeepSeek V4 Flash, Qwen 2.5 14B | 平衡质量与速度 |
| 代码/架构分析（In-App 预摘要/组件分析） | 本地模型 14B~9B | 数据量大，本地推理性价比高 |
| 简单查询 | 本地模型或轻量 API | 响应快 |

#### 3.5.3 会话级模型管理

- 创建会话时从下拉列表选择模型
- 会话详情中可切换模型（写入 `session.metadata.current_model_id`）
- 切换后后续消息使用新模型，不追溯已有消息
- 模型配置在 Electron 设置页统一管理，Web 端只读展示

### 3.6 Agent 能力（Tool 体系）

#### 3.6.1 现有工具清单

| 工具 | 来源 | 用途 |
|------|------|------|
| `topocode_community` | `mcp_server/tools.py` | 查询社区架构（按边类型+层级） |
| `topocode_community_detail` | `mcp_server/tools.py` | 查询特定社区详情 |
| `topocode_architecture_overview` | `mcp_server/tools.py` | 架构整体概览 |
| `topocode_diff` | `mcp_server/tools.py` | 版本间架构差异 |
| `topocode_quality_inspect` | `mcp_server/tools.py` | 架构风险检测 |
| `get_file_content` | `tools_executor.py` | 读取源码文件 |
| `get_symbol_detail` | `tools_executor.py` | 符号详情 |
| `get_community_subgraph` | `tools_executor.py` | 社区子图数据 |
| `search_symbols` | `tools_executor.py` | 搜索符号 |
| `get_call_chain` | `tools_executor.py` | 调用链查询 |

#### 3.6.2 Web Chat Agent 流程

```
用户提问："这个项目的核心模块有哪些？"
  │
  ├─ 1. LLM 判断需要工具 → tool_calls
  │    topocode_community(edge_type="INCLUDE", level=0)
  │
  ├─ 2. ToolExecutor.execute("topocode_community", args)
  │   → 返回社区列表
  │
  ├─ 3. tool_result → SSE 推送给前端（前端可展示「AI 正在查数据…」）
  │
  ├─ 4. LLM 继续生成（结合工具结果）
  │
  └─ 5. SSE 流式输出最终回答
```

- Tool calling 循环沿用现有 `_execute_streaming` 的 max 5 轮机制
- 工具结果自动截断（`MAX_RESULT_LENGTH = 10000`）
- 前端可监听 `tool_call` / `tool_result` 事件，展示中间状态

#### 3.6.3 未来扩展

通过注册新 tool 到 `ToolExecutor._handlers` 添加能力：

| 能力 | Tool 名 | 说明 |
|------|---------|------|
| 第三方文档阅读 | `fetch_web_doc` | 读取外部 URL 文档内容作为上下文 |
| 爬虫搜索 | `web_search` | 搜索外部知识 |
| 知识库查询 | `search_knowledge_base` | 检索已有对话记录/知识条目 |

遵循 MCP `ToolDefinition` 规范定义输入 schema，LLM 自动通过 function calling 发现并调用。

### 3.7 引用上下文（`?ref=` 参数）

#### 3.7.1 引用格式

```
/chat?ref=doc:{taskId}:{docId}
/chat?ref=graph:{taskId}:{edgeType}:{commLv}:{commId}
```

#### 3.7.2 服务端处理

```
GET /chat?ref=doc:task_xxx:doc_abc123
  │
  ├─ 解析 ref → ref_type='doc', ref_id='doc_abc123'
  ├─ 查询文档内容（通过 multi_db 获取社区结果）
  ├─ 自动创建 session：
  │   ├─ title = "引用: {文档标题}"
  │   ├─ project_id = 从 taskId 查出
  │   ├─ task_id = task_xxx
  │   ├─ ref_type = 'doc'
  │   ├─ ref_id = 'doc_abc123'
  │   └─ model_id = 用户默认模型或上次使用
  ├─ 写入一条 system message：
  │   "用户引用了社区文档「CoreModule（L1/INCLUDE）」：
  │    [文档内容摘要或关键内容]
  │    请基于此上下文回答用户的问题。"
  │
  └─ 返回 chat.html，前端 SSE 就绪
```

### 3.8 前端聊天页面

**文件**: `plugins/reports/static/chat.html`

#### 3.8.1 布局

```
┌─────────────────────────────────────────────┐
│  TopoCode AI 助手    [+ 新建会话]  [≡]       │  ← 顶部栏
├────────────┬────────────────────────────────┤
│            │                                │
│  会话列表   │  消息区域                        │
│  (按项目    │  ┌─ system ────────────────┐   │
│   分组)     │  │ 引用: CoreModule 文档    │   │  ← 上下文芯片
│            │  └────────────────────────┘   │
│  📁 projA  │  ┌─ user ──────────────────┐  │
│  │  ├ 架构   │  │ 这个模块的职责是什么？   │  │
│  │  ├ 代码   │  └────────────────────────┘  │
│  │  └ 知识   │  ┌─ assistant ────────────┐  │
│  📁 projB   │  │ CoreModule 主要负责…    │  │  ← Markdown 渲染
│  │  └ 依赖   │  │ 📊 [正在查询社区数据…] │  │  ← tool_call 状态
│            │  └────────────────────────┘  │
│  标签筛选   │                                │
│  ┌──────┐  │  ┌─────────────────────────┐  │
│  │架构  │  │  │ 输入消息...    [发送]    │  │
│  │知识  │  │  │          [▼ 模型选择]    │  │  ← 当前会话模型
│  └──────┘  │  └─────────────────────────┘  │
└────────────┴────────────────────────────────┘
```

#### 3.8.2 功能要点

| 功能 | 说明 |
|------|------|
| 会话列表 | 按项目分组，显示会话名 + 模型标识 |
| 新建会话 | 弹出对话框：名称 + 关联项目（可选） + 选择模型（必选） |
| 标签筛选 | 按 `metadata.tags` 过滤会话 |
| Markdown 渲染 | 复用 `viewer.html` 的 marked + highlight.js 配置 |
| 流式渲染 | SSE 逐 chunk 追加到消息气泡，支持 `[CMD:]` 预留给图操作 |
| Tool 中间状态 | 显示「📊 正在查询社区数据…」等占位 |
| 上下文芯片 | 引用来源显示在输入框上方，辅助用户了解对话上下文 |
| 会话内模型切换 | 会话详情下拉可选，切换后写入 metadata |
| 自动滚动 | SSE 过程中自动跟随 |

#### 3.8.3 技术选型

- `marked` + `highlight.js` — 与现有 viewer.html 一致
- 原生 Fetch + `EventSource` 或 `fetch` 的 `ReadableStream` 接收 SSE
- 零构建工具，单 HTML 文件，inline CSS/JS

---

## 4. 引用按钮（Electron 侧）

### 4.1 SubDocViewer

**文件**: `src/components/report/SubDocViewer.vue`

工具栏新增按钮，复用「在浏览器打开」逻辑：

```
[🌐 在浏览器打开]  [🤖 引用到 AI 会话]
```

```typescript
function openWebChatRef() {
  const ref = `doc:${props.taskId}:${docId.value}`
  const url = `http://127.0.0.1:${httpPort}/chat?ref=${ref}`
  window.api.shell.openExternal(url)
}
```

### 4.2 CommunityGraphView

**文件**: `src/components/report/CommunityGraphView.vue`

替换现有「导出架构」占位：

```typescript
function exportToWebChat() {
  const state = {
    edgeType: currentEdgeType.value,
    level: currentLevel.value,
    commId: selectedNode?.data?.id || '',
    commLabel: selectedNode?.data?.label || '',
  }
  const ref = `graph:${props.taskId}:${state.edgeType}:${state.level}:${state.commId}`
  const url = `http://127.0.0.1:${httpPort}/chat?ref=${encodeURIComponent(ref)}`
  window.api.shell.openExternal(url)
}
```

### 4.3 图节点右键菜单

在右键菜单增加「引用该社区到 AI 会话」项。

---

## 5. 与现有系统的关系

### 5.1 模型配置共享

```
Electron 设置页（模型管理）
  → model_configs 表（SQLite）
    → GET /api/models（Web Server）
      → chat.html 模型选择器
```

- 模型新增/删除/修改在 Electron 设置页进行
- Web 端只读展示，不支持修改
- 两端使用同一 `model_configs` 表，配置即时生效

### 5.2 会话数据互通

```
llm_sessions 表（SQLite）
  ├─ module_type='web_chat'      → Web 聊天会话
  ├─ module_type='ai_assistant'   → Electron AI 助手会话
  └─ 可通过 project_id 关联筛选
```

- 两类会话共存，互不干扰
- 后续知识库模块可跨 `module_type` 检索全量对话记录
- In-App 的 `/analyze` 等任务日志仍然走 `agent_tasks` 表

### 5.3 工具体系复用

```
ToolExecutor._handlers
  ├─ 被 _execute_streaming 调用（Electron 路径）
  └─ 被 _execute_sse 调用（Web 路径）
     → 同一批工具，两种输出路径
```

- 无需为 Web 端重写工具
- 新增工具同时惠及两端

---

## 6. 实施路线

| 阶段 | 任务 | 预计工时 | 涉及文件 |
|------|------|----------|----------|
| **P1** | In-App AI 收紧：非命令消息改引导 | 1天 | `AIAssistantPanel.vue` |
| **P2.1** | 数据库扩展：`llm_sessions` 加关联字段 | 0.5天 | `llm_service.py`, 迁移脚本 |
| **P2.2** | 模型列表 API：`GET /api/models` | 0.5天 | `web_server.py` |
| **P2.3** | SSE 后端：`chat_sse()` + SSE 路由 + tool 集成 | 2天 | `llm_service.py`, `web_server.py` |
| **P2.4** | 聊天前端：`chat.html` + 会话管理 + 模型选择 | 2天 | `static/chat.html` |
| **P2.5** | 引用上下文：`?ref=` 解析 + system message 注入 | 0.5天 | `web_server.py` |
| **P3.1** | SubDocViewer 引用按钮 | 0.5天 | `SubDocViewer.vue` |
| **P3.2** | GraphView 引用按钮 + 右键菜单 | 0.5天 | `CommunityGraphView.vue` |
| **合计** | | **~7天** | |

---

## 7. 附录：SSE 协议格式

### 7.1 事件类型

```javascript
// chunk — LLM 输出片段
event: chunk
data: {"type":"chunk","text":"核心模块主要负责"}

// tool_call — LLM 请求调用工具
event: tool_call
data: {"type":"tool_call","name":"topocode_community","arguments":{"edge_type":"INCLUDE","level":0}}

// tool_result — 工具执行结果
event: tool_result
data: {"type":"tool_result","name":"topocode_community","result":{"communities":[...]}}

// done — 流结束
event: done
data: {"type":"done","content":"完整回复内容","tokenCount":1234,"latencyMs":5678}

// error — 错误
event: error
data: {"type":"error","message":"Model not found"}
```

### 7.2 前端接收示例

```javascript
const eventSource = new EventSource(`/api/chat/send?sessionId=${sessionId}&message=${encodeURIComponent(msg)}&modelId=${modelId}`)

eventSource.addEventListener('chunk', (e) => {
  const data = JSON.parse(e.data)
  appendToCurrentMessage(data.text)
})

eventSource.addEventListener('tool_call', (e) => {
  showToolStatus(data.name)  // 显示「正在查询社区数据…」
})

eventSource.addEventListener('tool_result', (e) => {
  updateToolStatus(data.name, 'done')
})

eventSource.addEventListener('done', (e) => {
  finalizeMessage(data.content)
  eventSource.close()
})

eventSource.addEventListener('error', (e) => {
  showError(data.message)
  eventSource.close()
})
```

---

> **文档状态**: 设计阶段 · 待评审
> **关联文档**: `docs/architecture-overview.md`, `backend-core/llm_service.py`, `plugins/reports/web_server.py`
