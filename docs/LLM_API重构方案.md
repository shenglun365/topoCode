# LLM API 架构重构方案

> 2026-05-18 | 全部 19 项已确认 (Q1-Q8 + A-K)

---

## 一、已确认决策 (Q1-Q8 架构基础)

| # | 决策 | 方向 |
|---|------|------|
| Q1 | 批处理位置 | **后端 Python 100ms 汇聚后 PUB** |
| Q2 | API Key 安全 | **modelId 模式**，apiKey 不出后端 |
| Q3 | 数据迁移 | **删除旧表** `coder_sessions` + `chat_messages` |
| Q4 | 流式超时 | 可配置，默认 **300000ms** (5min，适配 100K+ 上下文) |
| Q5 | project_resource UI | 后端先支撑，UI **本次不开发** |
| Q6 | Coder 脱 mock | 只改通道，mock UI **后续独立迭代** |
| Q7 | ZMQ PUB → Renderer | **webContents.send()** 推送 |
| Q8 | llm.chat 请求体 | `{sessionId, messages, modelId}` |

## 一(b). 已确认决策 (A-K 实现细节)

| # | 决策 | 方向 |
|---|------|------|
| A | Worker 去留 | **移除** Worker，用 composable (~50行) |
| B | preload 事件 API | **按 requestId 订阅** `window.api.llm.subscribe(requestId, callback)`，返回 unsubscribe |
| C | llmClient 兼容性 | **保持流式签名**，内部改为 `subscribe` + `onChunk` 回调；注意 `onUnmounted` 清理订阅防内存泄漏 |
| D | 消息保存时机 | 前端 session.addMessage(user) → llm.chat → done 后**一次性**保存 assistant+tool messages；支持会话删除和单条删除 |
| E | Prompt 模板渲染 | **统一后端渲染**，前端传 `templateId + variables`；`promptTemplates.ts` 改为 RPC 客户端 |
| F | 结构化校验失败 | 返回 `{raw, validationError, retries, success:false}` 结构化错误对象 |
| G | summarizeCommunityName | **删除旧 RPC**，统一走 `llm.chat({mode:'structured', templateId:'community_name'})` |
| H | Agent vs Tools Calling | **独立子系统**。Tools Calling 在后端完成（内部 DB 工具）；Agent 是前端驱动外部 CLI。本次不涉及 Agent |
| I | 多窗口流式广播 | 事件按 requestId 推送**发起窗口**；其他窗口切回时调用 `session.getMessages` 刷新 |
| J | sqlite_ctx.py 旧表 | **彻底替换**：`DROP TABLE coder_sessions; DROP TABLE chat_messages;` + 新建 llm_* 表 |
| K | promptTemplates.ts | **改为 RPC 客户端**，从后端表读取。原 7 个模板内容迁移为内置 INSERT |

---

## 二、新增需求：三模式交互体系

### 2.1 模式定义

| 模式 | 标识 | 输出形式 | 典型场景 |
|------|------|---------|---------|
| **对话模式** | `chat` | 完整文本，流式输出 | 知识库问答、源码→伪码、程序功能概要 |
| **Tools Calling 模式** | `tools` | 模型调用工具→后端执行→结果反馈→模型继续→最终文本 | 架构解析（先给出项目概要+节点/边名称，模型按需调用工具获取详情） |
| **结构化输出模式** | `structured` | JSON 格式（按 schema 校验） | 社区命名、语法单元摘要、代码/文档关键词摘要 |

### 2.2 三模式架构差异

```
对话模式 (chat):
  前端 → llm.chat({mode:'chat', messages}) 
       → 后端直接 stream → PUB chunks → 前端渲染文本

Tools Calling 模式 (tools):
  前端 → llm.chat({mode:'tools', messages, tools})
       → 后端 loop:
            stream → 检测 tool_call → 
              后端自己执行 tool (db/system) → 
                构造 tool_result message → 
                  追加到 messages → 
                    继续 stream → 
                      检测 tool_call → ... → 
                        最终文本 → PUB done
       → 前端收到完整结果

结构化输出模式 (structured):
  前端 → llm.chat({mode:'structured', messages, outputSchema})
       → 后端 stream → 全量 → JSON.parse → schema 校验 → 
            ✓ 通过 → 返回结构化对象
            ✗ 失败 → 重试 (max 2) 或返回 raw + validation_error
```

### 2.3 Tools Calling 模式的核心工具集

架构解析场景下，后端预注册以下工具供 LLM 调用：

| 工具名 | 参数 | 返回 | 说明 |
|--------|------|------|------|
| `get_file_content` | `fileId: string` | 文件完整源码 (截断 >10000 字符) | 获取源码文件内容 |
| `get_symbol_detail` | `symbolId: string` | 符号完整信息 (类型/签名/代码片段/所在文件) | 获取符号详情 |
| `get_community_subgraph` | `taskId, commId, depth=2` | 子图节点+边列表 | 获取社区子图结构 |
| `get_edge_detail` | `edgeId: string` | 边的调用/依赖/数据流详情 | 获取边详情 |
| `search_symbols` | `query: string, limit=20` | 匹配的符号列表 | 按名称搜索符号 |
| `get_call_chain` | `fromId, toId, maxDepth=5` | 调用链路 (路径+中间节点) | 获取两点间调用路径 |

**工具执行在后端**：LLM 返回 tool_call → 后端 `tool_executor` 解析并执行 → 构造 `role: 'tool'` message → 追加到 messages → 继续 stream。

### 2.4 结构化输出 Schema 示例

```json
// summarize_community: 社区命名
{
  "type": "object",
  "properties": {
    "name": { "type": "string", "maxLength": 10, "description": "社区中文名称" },
    "category": { "enum": ["核心逻辑", "数据访问", "接口定义", "配置管理", "测试", "工具类"] }
  },
  "required": ["name", "category"]
}

// summarize_symbol: 语法单元摘要
{
  "type": "object",
  "properties": {
    "summary": { "type": "string", "maxLength": 80, "description": "功能摘要" },
    "purpose": { "type": "string", "maxLength": 40, "description": "场景用途" },
    "logic": { "type": "string", "maxLength": 60, "description": "实现逻辑关键词" }
  },
  "required": ["summary", "purpose"]
}
```

---

## 三、Prompt 模板管理系统

### 3.1 模板存储（新增表）

```sql
-- 主库 topoone.db
CREATE TABLE IF NOT EXISTS llm_prompt_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mode TEXT NOT NULL CHECK(mode IN ('chat', 'tools', 'structured')),
    module_type TEXT CHECK(module_type IN ('project_resource', 'project_analysis', 'knowledge_base', 'ai_assistant')),
    category TEXT DEFAULT 'general',       -- 分类标签
    is_builtin INTEGER DEFAULT 0,          -- 1=内置(不可删) 0=用户自定义
    
    -- 对话模式专用
    system_prompt TEXT,
    user_prompt_template TEXT,             -- 含 {variable} 占位符
    
    -- Tools Calling 模式专用
    tools_json TEXT,                        -- 可用工具列表 JSON (引用工具ID)
    tool_strategy TEXT DEFAULT 'auto',      -- auto|sequential|manual
    
    -- 结构化输出模式专用
    output_schema_json TEXT,                -- JSON Schema
    output_example TEXT,                    -- 输出样例
    
    -- 通用
    variables_json TEXT,                    -- 变量定义 [{name, type, description, required}]
    metadata TEXT,                          -- JSON 扩展
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);
```

### 3.2 内置模板清单

| 模板ID | 名称 | 模式 | 模块 | 用途 |
|--------|------|------|------|------|
| `src_to_pseudocode` | 源码转伪码 | chat | project_resource | 长代码压缩为伪码 |
| `func_summary` | 程序功能概要 | chat | project_resource | 概述文件/模块功能 |
| `arch_analysis` | 架构深度解析 | **tools** | project_analysis | 按需获取详情，控制上下文容量 |
| `community_name` | 社区命名 | **structured** | project_analysis | JSON 输出名称+分类 |
| `symbol_summary` | 符号摘要 | **structured** | project_analysis | JSON 输出功能/场景/逻辑摘要 |
| `doc_qa` | 文档问答 | chat | knowledge_base | 基于知识文档的问答 |
| `doc_organize` | 文档梳理 | chat | knowledge_base | 整理文档结构 |
| `doc_parse` | 文档解析 | chat | knowledge_base | 提取文档关键词/摘要 |
| `agent_chat` | Agent 对话 | chat | ai_assistant | 通用 Agent 交互 |
| `code_keywords` | 代码关键词摘要 | **structured** | project_analysis | JSON 输出场景/功能/实现关键词 |

### 3.3 Tools Calling 模式的工具定义

```json
{
  "id": "tool-get_symbol_detail",
  "name": "get_symbol_detail",
  "description": "获取指定符号的详细信息（类型、签名、代码片段、所在文件）",
  "parameters": {
    "type": "object",
    "properties": {
      "symbolId": { "type": "string", "description": "符号ID" }
    },
    "required": ["symbolId"]
  }
}
```

```json
{
  "id": "tool-get_community_subgraph",
  "name": "get_community_subgraph",
  "description": "获取社区分析的子图结构（节点列表 + 边列表），支持指定展开深度",
  "parameters": {
    "type": "object",
    "properties": {
      "taskId": { "type": "string", "description": "分析任务ID" },
      "commId": { "type": "string", "description": "社区分组ID" },
      "depth": { "type": "integer", "default": 2, "description": "展开深度 (1-4)" }
    },
    "required": ["taskId", "commId"]
  }
}
```

### 3.4 模板 RPC 方法

```
promptTemplate.list      -- 列出模板 (可按 mode/module_type 过滤)
promptTemplate.get       -- 获取模板详情
promptTemplate.create    -- 创建用户自定义模板
promptTemplate.update    -- 更新模板
promptTemplate.delete    -- 删除模板 (内置模板不可删)
promptTemplate.render    -- 预览：渲染模板 (传入 variables)
```

---

## 四、Streaming 通道 (最终设计)

```
┌─ Renderer ─────────────────────────────────────────────────────────┐
│                                                                     │
│  llmChat.send({sessionId, messages, modelId, mode, templateId?})   │
│    ↓ IPC 'ipc:call'                                                 │
│                                                                     │
│  main → zmqRouter.call('llm.chat', params)                         │
│    ↓ ZMQ DEALER (5671)                                              │
│    ← { requestId, status: 'streaming' }                             │
│                                                                     │
│  ┌─ ZMQ PUB (5680) 流式事件 ───────────────────────────────────┐   │
│  │ [llm, chunk, {requestId, index, text}]      ← 100ms批量      │   │
│  │ [llm, tool_call, {requestId, name, args}]   ← 工具调用       │   │
│  │ [llm, tool_result, {requestId, result}]     ← 工具执行结果   │   │
│  │ [llm, done, {requestId, content, usage}]    ← 完成           │   │
│  │ [llm, error, {requestId, message}]          ← 错误           │   │
│  └──────────────────────────────────────────────────────────────┘   │
│    ↓                                                                │
│  main process SUB → webContents.send('zmq:event', ...)              │
│    ↓                                                                │
│  preload: ipcRenderer.on('zmq:event') →                             │
│    按 requestId 路由到 subscribe 注册的回调                          │
│    ↓                                                                │
│  composable useLlmChat(): requestId 订阅 + text 累积 + UI 更新      │
│    (替代旧 Worker，不再有 HTTP fetch / postMessage)                 │
└─────────────────────────────────────────────────────────────────────┘
```

### preload API (按 B 设计)

```typescript
// electron/preload.ts 暴露
window.api.llm = {
  // 发起流式 LLM 请求
  chat: (params: {
    sessionId: string
    messages: ChatMessage[]
    modelId: string
    mode: 'chat' | 'tools' | 'structured'
    templateId?: string
    variables?: Record<string, string>
    tools?: string[]            // tools 模式: 可用工具名列表
    outputSchema?: object       // structured 模式: JSON Schema
  }) => Promise<{ requestId: string; status: 'streaming' }>,

  // 中止流式调用
  abortChat: (requestId: string) => Promise<void>,

  // 订阅流式事件 (返回 unsubscribe 函数)
  subscribe: (
    requestId: string,
    callbacks: {
      onChunk?: (data: { index: number; text: string }) => void
      onToolCall?: (data: { toolName: string; args: object }) => void
      onToolResult?: (data: { toolName: string; result: object }) => void
      onDone?: (data: { content: string; usage: object }) => void
      onError?: (data: { message: string; code: string }) => void
    }
  ) => () => void  // unsubscribe
}
```

### ZMQ PUB 事件类型

| eventType | 数据字段 | 触发时机 |
|-----------|---------|---------|
| `chunk` | `{requestId, index, text}` | 每 100ms 或 200 字符 |
| `tool_call` | `{requestId, toolName, args}` | LLM 请求调用工具 |
| `tool_result` | `{requestId, toolName, result}` | 工具执行完毕 |
| `done` | `{requestId, content, usage}` | 流式完成 |
| `error` | `{requestId, message, code}` | 异常/超时/中止 |

---

## 五、数据库 Schema (最终版)

### 5.1 新增表（主库 topoone.db）

```sql
-- Prompt 模板
CREATE TABLE IF NOT EXISTS llm_prompt_templates (
    -- 见 §3.1
);

-- LLM 调用日志
CREATE TABLE IF NOT EXISTS llm_call_logs (
    id TEXT PRIMARY KEY,
    session_id TEXT,
    request_id TEXT NOT NULL,
    model_id TEXT,
    mode TEXT NOT NULL,            -- chat|tools|structured
    template_id TEXT,              -- 使用的模板ID（可空）
    messages_json TEXT,
    response_content TEXT,
    tool_calls_json TEXT,          -- 工具调用记录 [{name, args, result}]
    token_prompt INTEGER,
    token_completion INTEGER,
    token_total INTEGER,
    latency_ms INTEGER,
    status TEXT CHECK(status IN ('success', 'error', 'aborted')),
    error_message TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 5.2 新增表（会话库 sessions.db）

```sql
-- 统一会话表
CREATE TABLE IF NOT EXISTS llm_sessions (
    id TEXT PRIMARY KEY,
    module_type TEXT NOT NULL CHECK(module_type IN (
        'project_resource', 'project_analysis', 'knowledge_base', 'ai_assistant'
    )),
    project_id TEXT,
    title TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    metadata TEXT,            -- JSON
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 统一消息表
CREATE TABLE IF NOT EXISTS llm_messages (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES llm_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
    content TEXT NOT NULL,
    token_count INTEGER,
    metadata TEXT,            -- JSON: tool_call/tool_result/structured_output 等
    created_at TEXT DEFAULT (datetime('now'))
);
```

### 5.3 废弃表

```sql
DROP TABLE IF EXISTS coder_sessions;  -- 替换为 llm_sessions
DROP TABLE IF EXISTS chat_messages;   -- 替换为 llm_messages
```

---

## 六、后端 RPC 方法汇总

### 6.1 llm.* (LLM 推理)

```
llm.chat              -- 统一流式对话 {sessionId, messages, modelId, mode, templateId?, tools?, outputSchema?}
llm.abortChat         -- 中止流式调用 {requestId}
llm.getCallLogs       -- 查询调用历史 {sessionId?, limit?, offset?}
llm.summarizeCode     -- 源码压缩 {code, sessionId?, modelId?}
llm.explainSymbol     -- 符号解释 {symbolName, symbolType, codeSnippet, fileName?, sessionId?, modelId?}
```

### 6.2 session.* (会话管理)

```
session.list          -- 列举会话 {moduleType?, projectId?, status?}
session.create        -- 创建会话 {moduleType, projectId?, title, metadata?}
session.delete        -- 删除会话 {sessionId} (级联删除消息+日志)
session.getMessages   -- 获取消息 {sessionId, limit?, offset?}
session.updateMeta    -- 更新元数据 {sessionId, metadata} (merge 模式)
```

### 6.3 promptTemplate.* (模板管理)

```
promptTemplate.list      -- 列表 {mode?, moduleType?, category?}
promptTemplate.get       -- 详情 {templateId}
promptTemplate.create    -- 创建 {name, mode, moduleType?, systemPrompt?, userPromptTemplate?, ...}
promptTemplate.update    -- 更新 {templateId, ...}
promptTemplate.delete    -- 删除 {templateId} (内置模板拒绝)
promptTemplate.render    -- 预览 {templateId, variables}
```

### 6.4 移除项

```
chat.listSessions        → session.list
chat.createSession       → session.create
chat.deleteSession       → session.delete
chat.saveMessage         → 后端自动保存 (llm.chat 内部处理)
llm.summarizeCommunityName → 纳入结构化输出模式
```

---

## 七、后端 tools_executor 模块（新增）

### 7.1 模块结构

```python
# backend/tools_executor.py (新文件)

class ToolExecutor:
    """Tools Calling 模式下的工具执行器"""
    
    def __init__(self, multi_db: MultiDBManager):
        self.multi_db = multi_db
        self._register_tools()
    
    def _register_tools(self):
        self.tools = {
            'get_file_content': self._get_file_content,
            'get_symbol_detail': self._get_symbol_detail,
            'get_community_subgraph': self._get_community_subgraph,
            'get_edge_detail': self._get_edge_detail,
            'search_symbols': self._search_symbols,
            'get_call_chain': self._get_call_chain,
        }
    
    def get_tool_definitions(self, tool_names: List[str]) -> List[dict]:
        """返回 OpenAI 兼容的 tools 定义"""
        
    async def execute(self, tool_name: str, args: dict) -> dict:
        """执行工具并返回结果"""
```

### 7.2 工具执行流程

```
1. LLM 返回: { choices: [{ delta: { tool_calls: [{ function: { name, arguments } }] } }] }
2. 后端累积 tool_call arguments JSON
3. 累积完成后，ToolExecutor.execute(name, args)
   a. 对数据库工具: 直接查询 SQLite
   b. 对系统工具: 调用 core_service 方法
4. 结果作为 tool_result 追加到 messages
5. 继续 stream (模型基于新信息继续输出或结束)
6. 最大 tool_call 循环: 5 次 (防止死循环)
```

### 7.3 Tool Calling 的 PUB 事件序列

```
[llm, chunk, {text: "让我先查看项目中的类结构..."}]
[llm, tool_call, {toolName: "search_symbols", args: {query: "HttpRequest"}}]
[llm, tool_result, {toolName: "search_symbols", result: {count: 12, symbols: [...]}}]
[llm, chunk, {text: "找到了 12 个相关符号，其中..."}]
[llm, tool_call, {toolName: "get_symbol_detail", args: {symbolId: "sym-123"}}]
[llm, tool_result, {toolName: "get_symbol_detail", result: {...}}]
[llm, chunk, {text: "这个类是主要负责..."}]
[llm, done, {content: "完整文本", usage: {prompt: 4000, completion: 1200}}]
```

---

## 八、文件级变更清单（最终版）

### 8.1 后端

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/llm_service.py` | **重写** | LLMService 类：`streaming_chat()` + `abort()` + ZMQ PUB 推送 + tools loop + structured parse |
| `backend/tools_executor.py` | **新建** | ToolExecutor 类：工具注册、执行、结果构造 |
| `backend/prompt_manager.py` | **新建** | PromptManager 类：模板 CRUD + render |
| `backend/sqlite_ctx.py` | **修改** | 新增 llm_sessions/llm_messages/llm_call_logs/llm_prompt_templates 表 DDL；DROP coder_sessions/chat_messages |
| `backend/zmq_server.py` | **微调** | PUB 确保 'llm' topic 可订阅 |
| `backend/main.py` | **修改** | 注册 llm.* / session.* / promptTemplate.* 方法 |
| `backend/core_service.py` | **不变** | settings.* 保持不变 |
| `backend/task_manager.py` | **不变** | |

### 8.2 前端

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/composables/useLlmChat.ts` | **新建** | ~50 行：`subscribe` + text 累积 + `onUnmounted` 清理（替代 Worker） |
| `src/workers/llm.worker.ts` | **删除** | Worker 已移除 |
| `src/workers/llm.worker.instance.ts` | **删除** | Worker 单例已移除 |
| `src/services/llmClient.ts` | **修改** | explain* 等保持流式签名，内部改为 `window.api.llm.subscribe` + onChunk |
| `src/services/promptTemplates.ts` | **重写** | 改为 RPC 客户端，从 `promptTemplate.*` 读取后端模板 |
| `src/stores/chat.ts` | **重写** | 适配 session.* + llm.* IPC，模块类型感知，模板选择；useLlmChat composable |
| `src/stores/settings.ts` | **不变** | settings.* 保持不变 |
| `src/types/ipc.ts` | **修改** | 新增 session.* / llm.* / promptTemplate.* IPC 类型；移除 chat.*；新增 LlmMode |
| `src/types/index.ts` | **修改** | 统一 ChatMessage → LlmMessage；deprecate CoderSession → LlmSession |
| `src/utils/mock.ts` | **修改** | 移除 ChatSession/ChatMessage mock 类型 |
| `src/components/coder/` | **不变** | 本次不改 UI（通道改，mock 保留） |
| `electron/preload.ts` | **修改** | 新增 session.* + llm.* + promptTemplate.* 桥接；`window.api.llm.subscribe` |
| `electron/zmq-router.ts` | **修改** | SUB 新增 'llm' topic；`forwardToRenderer()` → webContents.send('zmq:event') |
| `electron/main.ts` | **修改** | zmq:event IPC 通道注册 + 多窗口 broadcast |

---

## 九、实施顺序（6 Phase）

```
Phase 1: 数据库 + 基础 RPC
  ├── sqlite_ctx.py: 建表 (llm_sessions / llm_messages / llm_call_logs / llm_prompt_templates)
  ├── sqlite_ctx.py: DROP coder_sessions / chat_messages
  ├── llm_service.py: LLMService 类骨架 + session.* RPC
  └── 单元测试

Phase 2: Streaming 通道 + Tools Calling
  ├── llm_service.py: streaming_chat() + ZMQ PUB 推送 + 100ms 批处理
  ├── tools_executor.py: ToolExecutor 完整实现
  ├── zmq_server.py: 'llm' topic 注册
  └── 集成测试 (模拟 tools loop)

Phase 3: Prompt 模板 + 结构化输出
  ├── prompt_manager.py: PromptManager CRUD + render
  ├── llm_service.py: 三模式路由 (chat/tools/structured)
  └── 集成测试

Phase 4: 前端 IPC 适配
  ├── electron/preload.ts: session.* + llm.*(含 subscribe) + promptTemplate.*
  ├── electron/zmq-router.ts: 'llm' SUB + forwardToRenderer → webContents.send
  ├── electron/main.ts: zmq:event IPC 通道
  ├── src/types/ipc.ts: 类型更新
  └── 手动 E2E 测试

Phase 5: 前端 Store + Composable 改造
  ├── src/composables/useLlmChat.ts: 新建 (subscribe + text累积 + onUnmounted清理)
  ├── src/stores/chat.ts: 适配 session.* + llm.* IPC，useLlmChat
  ├── src/services/llmClient.ts: 切换通道 (subscribe + onChunk)
  ├── src/services/promptTemplates.ts: 改为 RPC 客户端
  ├── src/types/index.ts: 类型统一
  ├── src/utils/mock.ts: 移除 LLM 类型
  └── 回归测试

Phase 6: 清理 + 文档
  ├── 删除 src/workers/llm.worker.ts + llm.worker.instance.ts
  ├── 构建验证 (vite build + tsc)
  └── 更新 前后端服务通讯协议.md
```

---

## 十、风险矩阵

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| ZMQ PUB 高负载 | 中 | 中 | 后端 100ms 批处理降频 |
| Tools loop 死循环 | 低 | 高 | 最大 5 次 tool_call 循环 |
| 结构化输出校验失败 | 中 | 低 | 重试 2 次，失败返回 raw+error |
| 多窗口事件广播遗漏 | 低 | 高 | BrowserWindow.getAllWindows().forEach |
| llm_call_logs 膨胀 | 中 | 低 | 定期清理 30 天 + 大文本(>10K)截断 |
| 迁移期间旧会话丢失 | 低 | 低 | 旧数据仅测试数据，可接受 |
| 300s 超时大上下文无响应 | 中 | 中 | abortChat 手动中止 + 心跳 PUB |
