# TopoOne UI - 后端接口文档 (v3.0 - ZeroMQ)

> 本文档定义了前端 UI 组件依赖的所有后端接口，包含 ZeroMQ 消息队列和 HTTP Web API 两种通信协议。
> 
> **后端技术栈**: Python (ZeroMQ Dealer) + Tree-sitter + SQLite3
> **前端技术栈**: Vue 3.5 + Pinia + TypeScript + Electron 33
> **通信协议**: 
> - **ZeroMQ**: ROUTER/DEALER (本地服务: 项目/分析/知识库/设置)
> - **ZeroMQ**: PUB/SUB (事件推送: 任务进度/项目同步/后端状态)
> - **ZeroMQ**: PUSH/PULL (Agent 任务分发)
> - **HTTP**: REST API + SSE (外部 LLM: Ollama/OpenAI/LM-Studio)

---

## 目录

- [一、接口总览](#一接口总览)
- [二、IPC 接口 - 项目模块](#二ipc-接口---项目模块)
- [三、IPC 接口 - 代码分析模块](#三ipc-接口---代码分析模块)
- [四、IPC 接口 - 知识库模块](#四ipc-接口---知识库模块)
- [五、IPC 接口 - 设置配置模块](#五ipc-接口---设置配置模块)
- [六、IPC 接口 - 后端状态](#六ipc-接口---后端状态)
- [七、HTTP 接口 - LLM 服务](#七http-接口---llm-服务)
- [八、事件推送协议](#八事件推送协议)
- [九、错误码定义](#九错误码定义)
- [十、类型定义](#十类型定义)

---

## 一、接口总览

### 1.1 IPC 接口 (本地服务)

| 模块 | 方法数 | 说明 |
|------|--------|------|
| **项目模块** | 6 | 项目导入、列表、同步、文件树 |
| **代码分析** | 7 | 任务创建、执行、结果查询 |
| **知识库** | 7 | 文档 CRUD、图谱、分类 |
| **设置配置** | 14 | 模型/Agent/SKILL 管理 |
| **后端状态** | 5 | 进程管理、健康检查 |
| **小计** | **39** | |

### 1.2 HTTP 接口 (LLM 服务)

| 模块 | 接口数 | 说明 |
|------|--------|------|
| **LLM Chat** | 1 | 流式对话 (SSE) |
| **LLM Completion** | 1 | 代码补全 |
| **LLM Embedding** | 1 | 文本向量化 |
| **小计** | **3** | |

### 1.3 通讯方式对比

| 维度 | ZeroMQ (ROUTER/DEALER) | ZeroMQ (PUB/SUB) | HTTP (REST/SSE) |
|------|------------------------|-------------------|-----------------|
| **适用场景** | 本地服务 RPC | 事件推送 | 外部 LLM 调用 |
| **延迟** | ~0.01-0.1ms | ~0.01ms | ~5-200ms |
| **传输** | TCP/IPC | TCP/IPC | TCP/HTTP |
| **序列化** | 多帧消息 (JSON) | 多帧消息 (JSON) | JSON over HTTP |
| **模式** | 请求/响应 | 发布/订阅 | 请求/流式响应 |
| **调用方** | Renderer → Main → Core | Core → Main → Renderer | Renderer → 外部 API |

---

## 二、ZeroMQ 接口 - 项目模块

**Store**: `src/stores/project.ts`  
**调用方式**: `window.api.project.*` → Electron IPC → ZeroMQ ROUTER/DEALER

### 2.1 project.list - 获取项目列表

**请求帧**:
```
Frame 0: "core"              # 后端标识
Frame 1: "req-001"           # 请求 ID
Frame 2: "project.list"      # 方法名
Frame 3: "{}"                # 参数 JSON
```

**响应帧**:
```
Frame 0: "main"              # 请求方标识
Frame 1: "req-001"           # 对应请求 ID
Frame 2: [{"id":"proj-1","name":"topoOne-ui","path":"/home/user/projects/topoOne-ui","language":"TypeScript","fileCount":156,"status":"synced","lastSync":"2026-05-04T10:30:00Z","createdAt":"2026-04-20T08:00:00Z"}]
Frame 3: null                # 无错误
```

### 2.2 project.import - 导入新项目

**请求帧**: `["core", "req-002", "project.import", '{"path":"/home/user/projects/new-project"}']`

**响应帧**: `["main", "req-002", {"id":"proj-2","name":"new-project","path":"/home/user/projects/new-project","language":"Python","fileCount":89,"status":"syncing"}, null]`

### 2.3 project.get - 获取项目详情

**请求帧**: `["core", "req-003", "project.get", '{"id":"proj-1"}']`

**响应帧**: `["main", "req-003", {"id":"proj-1","name":"topoOne-ui","fileTree":[...]}, null]`

### 2.4 project.remove - 移除项目

**请求帧**: `["core", "req-004", "project.remove", '{"id":"proj-1"}']`

**响应帧**: `["main", "req-004", null, null]`

### 2.5 project.sync - 触发项目同步

**请求帧**: `["core", "req-005", "project.sync", '{"id":"proj-1"}']`

**响应帧**: `["main", "req-005", {"id":"proj-1","status":"syncing","fileCount":158}, null]`

### 2.6 project.getFileTree - 获取文件树

**请求帧**: `["core", "req-006", "project.getFileTree", '{"id":"proj-1"}']`

**响应帧**: `["main", "req-006", [{"name":"src","type":"directory","children":[...]}], null]`

---

## 三、ZeroMQ 接口 - 代码分析模块

**Store**: `src/stores/analysis.ts`  
**调用方式**: `window.api.analysis.*` → Electron IPC → ZeroMQ ROUTER/DEALER

> **注**: 所有 ZeroMQ 接口遵循统一的消息帧格式:
> - **请求**: `[IDENTITY, REQUEST_ID, METHOD, PARAMS_JSON]`
> - **响应**: `[IDENTITY, REQUEST_ID, RESULT_JSON, ERROR_JSON]`
> 
> 以下为简化表示，完整格式参考 [ZMQ通讯设计.md](./ZMQ通讯设计.md)

### 3.1 analysis.listTasks - 获取任务列表

**请求**:
```json
{"jsonrpc":"2.0","id":1,"method":"analysis.listTasks","params":{"projectId":"proj-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":1,"result":[{"id":"task-1","projectId":"proj-1","type":"full-parse","name":"全量代码解析","status":"done","progress":100,"total":156,"current":156,"error":null,"createdAt":"2026-05-04T09:00:00Z","updatedAt":"2026-05-04T09:05:00Z","favorite":true,"pinned":false,"tags":["v1.0"]}]}
```

### 3.2 analysis.createTask - 创建任务

**请求**:
```json
{"jsonrpc":"2.0","id":2,"method":"analysis.createTask","params":{"projectId":"proj-1","type":"full-parse","name":"全量代码解析"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":2,"result":{"id":"task-2","projectId":"proj-1","type":"full-parse","name":"全量代码解析","status":"pending","progress":0}}
```

### 3.3 analysis.runTask - 启动执行

**请求**:
```json
{"jsonrpc":"2.0","id":3,"method":"analysis.runTask","params":{"taskId":"task-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":3,"result":{"taskId":"task-1","status":"running"}}
```

### 3.4 analysis.getTask - 获取任务详情

**请求**:
```json
{"jsonrpc":"2.0","id":4,"method":"analysis.getTask","params":{"taskId":"task-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":4,"result":{"id":"task-1","projectId":"proj-1","type":"full-parse","name":"全量代码解析","status":"done","progress":100,"total":156,"current":156}}
```

### 3.5 analysis.getResults - 获取分析结果

**请求**:
```json
{"jsonrpc":"2.0","id":5,"method":"analysis.getResults","params":{"taskId":"task-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":5,"result":{"ast":{"type":"Program","body":[]},"callChain":[{"from":"main.ts:10","to":"utils.ts:25","function":"processData"}],"dependencies":{"modules":["@vue/runtime-core"],"files":["src/main.ts"]}}}
```

### 3.6 analysis.updateTask - 更新元数据

**请求**:
```json
{"jsonrpc":"2.0","id":6,"method":"analysis.updateTask","params":{"taskId":"task-1","favorite":true,"pinned":true}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":6,"result":{"id":"task-1","favorite":true,"pinned":true}}
```

### 3.7 analysis.deleteTask - 删除任务

**请求**:
```json
{"jsonrpc":"2.0","id":7,"method":"analysis.deleteTask","params":{"taskId":"task-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":7,"result":null}
```

---

## 四、IPC 接口 - 知识库模块

**Store**: `src/stores/knowledge.ts`  
**调用方式**: `window.api.knowledge.*` → IPC → JSON-RPC

### 4.1 knowledge.listDocs - 获取文档列表

**请求**:
```json
{"jsonrpc":"2.0","id":1,"method":"knowledge.listDocs","params":{"search":"认证","dimensions":{"lifecycle":"设计文档"},"sortBy":"updatedAt"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":1,"result":[{"id":"doc-1","title":"用户认证模块设计","type":"document","description":"JWT 认证流程设计文档","content":"# 用户认证模块设计\n...","projectId":"proj-1","tags":{"lifecycle":["设计文档"],"techStack":["Vue"],"abstraction":["架构设计"],"purpose":["安全规范"]},"status":"reviewed","favorite":true,"pinned":false}]}
```

### 4.2 knowledge.createDoc - 创建文档

**请求**:
```json
{"jsonrpc":"2.0","id":2,"method":"knowledge.createDoc","params":{"title":"新文档","content":"# 内容","projectId":"proj-1","tags":{"lifecycle":["设计文档"]}}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":2,"result":{"id":"doc-8","title":"新文档","status":"draft"}}
```

### 4.3 knowledge.getDoc - 获取文档详情

**请求**:
```json
{"jsonrpc":"2.0","id":3,"method":"knowledge.getDoc","params":{"id":"doc-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":3,"result":{"id":"doc-1","title":"用户认证模块设计","content":"# 用户认证模块设计\n...","tags":{"lifecycle":["设计文档"]}}}
```

### 4.4 knowledge.updateDoc - 更新文档

**请求**:
```json
{"jsonrpc":"2.0","id":4,"method":"knowledge.updateDoc","params":{"id":"doc-1","content":"# 更新后内容","favorite":true}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":4,"result":{"id":"doc-1","updatedAt":"2026-05-04T10:00:00Z"}}
```

### 4.5 knowledge.deleteDoc - 删除文档

**请求**:
```json
{"jsonrpc":"2.0","id":5,"method":"knowledge.deleteDoc","params":{"id":"doc-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":5,"result":null}
```

### 4.6 knowledge.getGraph - 获取知识图谱

**请求**:
```json
{"jsonrpc":"2.0","id":6,"method":"knowledge.getGraph","params":{"projectId":"proj-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":6,"result":{"nodes":[{"id":"node-1","label":"用户模块","type":"module","x":100,"y":150,"color":"#89b4fa"}],"edges":[{"from":"node-1","to":"node-2","type":"dependency"}]}}
```

### 4.7 knowledge.getDimensions - 获取分类标签

**请求**:
```json
{"jsonrpc":"2.0","id":7,"method":"knowledge.getDimensions","params":{}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":7,"result":{"lifecycle":["需求文档","设计文档","实现文档"],"techStack":["Vue","Node.js","Python"],"abstraction":["架构设计","模块设计"],"purpose":["安全规范","性能优化"]}}
```

---

## 五、IPC 接口 - 设置配置模块

**Store**: `src/stores/settings.ts`  
**调用方式**: `window.api.settings.*` → IPC → JSON-RPC

### 5.1 settings.getModels - 获取模型列表

**请求**:
```json
{"jsonrpc":"2.0","id":1,"method":"settings.getModels","params":{}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":1,"result":[{"id":"model-1","name":"Ollama - qwen2.5-coder:7b","provider":"ollama","model":"qwen2.5-coder:7b","url":"http://localhost:11434","type":"local","status":"connected","isDefault":true,"temperature":0.7,"maxTokens":4096}]}
```

### 5.2 settings.addModel - 添加模型

**请求**:
```json
{"jsonrpc":"2.0","id":2,"method":"settings.addModel","params":{"name":"自定义模型","provider":"ollama","model":"llama3-8b","url":"http://localhost:11434","type":"local"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":2,"result":{"id":"model-4","name":"自定义模型","status":"offline"}}
```

### 5.3 settings.updateModel - 更新模型

**请求**:
```json
{"jsonrpc":"2.0","id":3,"method":"settings.updateModel","params":{"id":"model-1","temperature":0.5,"maxTokens":8192}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":3,"result":{"id":"model-1","temperature":0.5,"maxTokens":8192}}
```

### 5.4 settings.removeModel - 删除模型

**请求**:
```json
{"jsonrpc":"2.0","id":4,"method":"settings.removeModel","params":{"id":"model-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":4,"result":null}
```

### 5.5 settings.testModel - 测试连接

**请求**:
```json
{"jsonrpc":"2.0","id":5,"method":"settings.testModel","params":{"id":"model-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":5,"result":{"status":"connected","latency":12,"model":"qwen2.5-coder:7b"}}
```

### 5.6 settings.getAgents - 获取 Agent 列表

**请求**:
```json
{"jsonrpc":"2.0","id":6,"method":"settings.getAgents","params":{}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":6,"result":[{"id":"agent-1","name":"qwen-code","path":"/usr/local/bin/qwen-code","args":"--workspace {project_root}","status":"online","version":"v1.2.3","isDefault":true}]}
```

### 5.7 settings.addAgent - 添加 Agent

**请求**:
```json
{"jsonrpc":"2.0","id":7,"method":"settings.addAgent","params":{"name":"cline","path":"~/.cline/bin/cline","args":"--mode agent"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":7,"result":{"id":"agent-4","name":"cline","status":"not-detected"}}
```

### 5.8 settings.updateAgent - 更新 Agent

**请求**:
```json
{"jsonrpc":"2.0","id":8,"method":"settings.updateAgent","params":{"id":"agent-1","path":"/new/path","args":"--verbose"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":8,"result":{"id":"agent-1","path":"/new/path"}}
```

### 5.9 settings.removeAgent - 删除 Agent

**请求**:
```json
{"jsonrpc":"2.0","id":9,"method":"settings.removeAgent","params":{"id":"agent-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":9,"result":null}
```

### 5.10 settings.detectAgent - 检测 Agent

**请求**:
```json
{"jsonrpc":"2.0","id":10,"method":"settings.detectAgent","params":{"id":"agent-1"}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":10,"result":{"status":"online","version":"v1.2.3"}}
```

### 5.11 settings.getSkills - 获取技能列表

**请求**:
```json
{"jsonrpc":"2.0","id":11,"method":"settings.getSkills","params":{}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":11,"result":[{"id":"skill-1","name":"严格函数签名校验","description":"校验生成代码的函数签名是否与 Spec 定义一致","enabled":true}]}
```

### 5.12 settings.updateSkill - 更新技能

**请求**:
```json
{"jsonrpc":"2.0","id":12,"method":"settings.updateSkill","params":{"id":"skill-1","enabled":true}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":12,"result":{"id":"skill-1","enabled":true}}
```

### 5.13 settings.getBindings - 获取绑定

**请求**:
```json
{"jsonrpc":"2.0","id":13,"method":"settings.getBindings","params":{}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":13,"result":{"syntax-analysis":"model-1","function-analysis":"model-2","ai-chat":"model-1"}}
```

### 5.14 settings.updateBindings - 更新绑定

**请求**:
```json
{"jsonrpc":"2.0","id":14,"method":"settings.updateBindings","params":{"bindings":{"syntax-analysis":"model-1","ai-chat":"model-2"}}}
```

**响应**:
```json
{"jsonrpc":"2.0","id":14,"result":{"syntax-analysis":"model-1","ai-chat":"model-2"}}
```

---

## 六、IPC 接口 - 后端状态

**Store**: `src/stores/status.ts`  
**调用方式**: `window.api.backend.*` → IPC

### 6.1 backend.start - 启动后端

**请求**: `ipcRenderer.invoke('backend:start')`

**响应**: `{status:"running", pid:12345}`

### 6.2 backend.stop - 停止后端

**请求**: `ipcRenderer.invoke('backend:stop')`

**响应**: `{status:"stopped"}`

### 6.3 backend.restart - 重启后端

**请求**: `ipcRenderer.invoke('backend:restart')`

**响应**: `{status:"restarting"}`

### 6.4 backend.getStatus - 获取状态

**请求**: `ipcRenderer.invoke('backend:status')`

**响应**: `{status:"running", pid:12345, port:8000}`

### 6.5 backend.onStatusChange - 状态变更监听

**请求**: `ipcRenderer.on('backend:status-changed', callback)`

**推送**: `{status:"running", pid:12345}`

---

## 七、HTTP 接口 - LLM 服务

**调用方**: Renderer (Vue) → 外部 LLM API  
**封装**: `src/services/llm.ts`

### 7.1 Ollama - 流式对话

**端点**: `POST {config.url}/api/chat`

**请求**:
```json
{
  "model": "qwen2.5-coder:7b",
  "messages": [
    {"role": "user", "content": "请帮我设计用户认证模块"}
  ],
  "stream": true,
  "options": {
    "temperature": 0.7,
    "num_predict": 4096
  }
}
```

**响应** (SSE 流式):
```
{"model":"qwen2.5-coder:7b","message":{"content":"好的"},"done":false}
{"model":"qwen2.5-coder:7b","message":{"content","我来"},"done":false}
{"model":"qwen2.5-coder:7b","message":{"content","为你设计"},"done":false}
{"model":"qwen2.5-coder:7b","message":{},"done":true}
```

### 7.2 OpenAI - 流式对话

**端点**: `POST {config.url}/v1/chat/completions`

**请求**:
```json
{
  "model": "gpt-4o",
  "messages": [
    {"role": "user", "content": "请帮我设计用户认证模块"}
  ],
  "stream": true,
  "temperature": 0.5,
  "max_tokens": 8192
}
```

**响应** (SSE 流式):
```
data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"好的"},"finish_reason":null}]}
data: {"id":"chatcmpl-1","choices":[{"delta":{"content":"我来"},"finish_reason":null}]}
data: {"id":"chatcmpl-1","choices":[{"delta":{},"finish_reason":"stop"}]}
data: [DONE]
```

### 7.3 Embedding - 文本向量化

**Ollama**: `POST {config.url}/api/embeddings`
```json
{"model":"nomic-embed-text","prompt":"用户认证模块"}
```

**OpenAI**: `POST {config.url}/v1/embeddings`
```json
{"model":"text-embedding-3-small","input":"用户认证模块"}
```

---

## 八、事件推送协议

Python 后端通过 stdio 发送通知，Main Process 转发到 Renderer：

### 8.1 任务进度推送

**事件**: `task:progress`

**参数**:
```json
{"taskId":"task-1","progress":45,"total":156,"current":70,"status":"running"}
```

### 8.2 任务完成推送

**事件**: `task:complete`

**参数**:
```json
{"taskId":"task-1","status":"done","progress":100}
```

### 8.3 任务失败推送

**事件**: `task:error`

**参数**:
```json
{"taskId":"task-1","status":"error","error":"解析失败: 语法错误"}
```

### 8.4 项目同步完成推送

**事件**: `project:synced`

**参数**:
```json
{"projectId":"proj-1","fileCount":158}
```

### 8.5 后端状态变化推送

**事件**: `backend:status-changed`

**参数**:
```json
{"status":"running","pid":12345,"port":8000}
```

---

## 七、后端状态 API

**Store**: `src/stores/status.ts`

### 7.1 健康检查

```
GET /api/health
```

**Response**:
```json
{
  "code": 0,
  "data": {
    "status": "running",
    "pid": 12345,
    "port": 8000,
    "error": null
  }
}
```

### 7.2 状态推送 (WebSocket)

```
WS /api/status/stream
```

**服务端推送**:
```json
{
  "type": "status_update",
  "data": {
    "status": "running",
    "pid": 12345,
    "port": 8000
  }
}
```

---

## 八、WebSocket 协议

### 8.1 任务进度推送

**连接**:
```
WS /api/tasks/:id/progress
```

**服务端推送**:
```json
{
  "type": "progress_update",
  "data": {
    "taskId": "task-1",
    "progress": 45,
    "total": 156,
    "current": 70,
    "status": "running"
  }
}
```

**任务完成**:
```json
{
  "type": "task_complete",
  "data": {
    "taskId": "task-1",
    "status": "done",
    "progress": 100,
    "total": 156,
    "current": 156
  }
}
```

**任务失败**:
```json
{
  "type": "task_error",
  "data": {
    "taskId": "task-1",
    "status": "error",
    "error": "解析失败: 语法错误"
  }
}
```

### 8.2 AI 消息流式推送

**连接**:
```
WS /api/chat/sessions/:id/stream
```

**服务端推送 (流式)**:
```json
{
  "type": "message_chunk",
  "data": {
    "messageId": "msg-3",
    "content": "根据分析，",
    "done": false
  }
}
```

**消息完成**:
```json
{
  "type": "message_complete",
  "data": {
    "messageId": "msg-3",
    "content": "根据分析，该模块的调用链如下：...",
    "done": true,
    "contextCards": [],
    "actions": ["生成设计文档"]
  }
}
```

### 8.3 Agent 执行日志推送

**连接**:
```
WS /api/chat/sessions/:id/task/:taskId/stream
```

**服务端推送**:
```json
{
  "type": "terminal_line",
  "data": {
    "taskId": "task-agent-1",
    "line": {
      "text": "[INFO] 正在生成 src/auth/index.ts...",
      "type": "info"
    }
  }
}
```

**校验结果**:
```json
{
  "type": "validation_result",
  "data": {
    "taskId": "task-agent-1",
    "validation": {
      "label": "函数签名校验",
      "passed": true
    }
  }
}
```

**任务完成**:
```json
{
  "type": "task_complete",
  "data": {
    "taskId": "task-agent-1",
    "status": "done",
    "filesGenerated": 5,
    "elapsed": "00:03:15"
  }
}
```

---

## 九、错误码定义

### 9.1 JSON-RPC 标准错误码

| 错误码 | 说明 |
|--------|------|
| `-32700` | Parse error |
| `-32600` | Invalid Request |
| `-32601` | Method not found |
| `-32602` | Invalid params |
| `-32603` | Internal error |
| `-32000 ~ -32099` | Server error (自定义) |

### 9.2 业务错误码

| 错误码 | 说明 |
|--------|------|
| `-32001` | 项目路径不存在 |
| `-32002` | 项目已存在 |
| `-32003` | 任务不存在 |
| `-32004` | 文档不存在 |
| `-32005` | 模型配置不存在 |
| `-32006` | Agent 未配置 |
| `-32007` | 模型服务不可用 |
| `-32008` | Agent 执行失败 |
| `-32009` | 请求超时 |

**错误响应格式**:
```json
{"jsonrpc":"2.0","id":1,"error":{"code":-32001,"message":"项目路径不存在"}}
```

---

## 十、类型定义

### 10.1 JSON-RPC 请求/响应

```typescript
interface JsonRpcRequest {
  jsonrpc: '2.0'
  id: number | string
  method: string
  params?: Record<string, any>
}

interface JsonRpcResponse<T = any> {
  jsonrpc: '2.0'
  id: number | string
  result?: T
  error?: {
    code: number
    message: string
    data?: any
  }
}

interface JsonRpcNotification {
  jsonrpc: '2.0'
  method: string
  params: Record<string, any>
}
```

### 10.2 文件树节点

```typescript
interface FileTreeNode {
  name: string
  type: 'file' | 'directory'
  language?: string
  size?: number
  children?: FileTreeNode[]
}
```

### 10.3 分析结果

```typescript
interface AnalysisResult {
  ast?: any
  callChain?: CallChainItem[]
  dependencies?: {
    modules: string[]
    files: string[]
  }
  dataflow?: DataFlowItem[]
}

interface CallChainItem {
  from: string
  to: string
  function: string
}

interface DataFlowItem {
  source: string
  target: string
  data: string
}
```

### 10.4 知识图谱

```typescript
interface KnowledgeGraphNode {
  id: string
  label: string
  type: 'module' | 'class' | 'function' | 'knowledge'
  x: number
  y: number
  color: string
}

interface KnowledgeGraphEdge {
  from: string
  to: string
  type: 'dependency' | 'reference'
}
```

---

## 附录：前端 Store 与 API 映射

| Store | 通讯方式 | 主要方法 |
|-------|---------|---------|
| `project.ts` | ZeroMQ | `api.project.list()`, `api.project.import()`, `api.project.sync()` |
| `analysis.ts` | ZeroMQ | `api.analysis.listTasks()`, `api.analysis.runTask()`, `api.analysis.getResults()` |
| `knowledge.ts` | ZeroMQ | `api.knowledge.listDocs()`, `api.knowledge.getGraph()`, `api.knowledge.updateDoc()` |
| `chat.ts` | HTTP | `llmService.chat()`, `llmService.embed()` |
| `settings.ts` | ZeroMQ | `api.settings.getModels()`, `api.settings.updateAgent()`, `api.settings.updateSkill()` |
| `status.ts` | ZeroMQ | `api.backend.getStatus()`, `api.backend.onStatusChange()` |

---

## 附录 B: ZeroMQ 端点配置

| 端点 | 类型 | 进程 | 说明 |
|------|------|------|------|
| `tcp://127.0.0.1:5670` | ROUTER | Main | 主路由 |
| `tcp://127.0.0.1:5671` | DEALER | Core | 核心服务 |
| `tcp://127.0.0.1:5672` | DEALER | Agent-1 | Agent 1 |
| `tcp://127.0.0.1:5680` | PUB | Core | 事件发布 |
| `tcp://127.0.0.1:5681` | SUB | Main | 事件订阅 |

---

> **文档版本**: v3.0.0 (ZeroMQ 重构)
> **最后更新**: 2026-05-04
> **维护者**: TopoOne Team
