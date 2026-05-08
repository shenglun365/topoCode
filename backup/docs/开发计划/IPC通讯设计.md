# IPC 通讯架构设计

> 前端 UI 与本地后台服务通过 IPC 通信，LLM 请求保持 HTTP Web API

---

## 一、架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│  Renderer Process (Vue 3)                                       │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  Pinia Stores                                              │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐      │  │
│  │  │ project  │ │ analysis │ │knowledge │ │  chat    │      │  │
│  │  │settings  │ │  status  │ │          │ │          │      │  │
│  │  └────┬─────┘ └────┬─────┘ └────┬─────┘ └────┬─────┘      │  │
│  └───────┼────────────┼────────────┼────────────┼─────────────┘  │
│          │            │            │            │                 │
│  ┌───────┴────────────┴────────────┴────────────┴─────────────┐  │
│  │  IPC Service Layer (src/services/ipc.ts)                   │  │
│  │  window.api.* 统一封装                                      │  │
│  └───────┬───────────────────────────────────────────────────┘  │
│          │ window.api (contextBridge)                           │
├──────────┼──────────────────────────────────────────────────────┤
│  Preload │  (src/preload/index.ts)                              │
│  ┌───────┴───────────────────────────────────────────────────┐  │
│  │  contextBridge.exposeInMainWorld('api', {                 │  │
│  │    project, analysis, knowledge, chat, settings, backend  │  │
│  │  })                                                       │  │
│  └───────┬───────────────────────────────────────────────────┘  │
├──────────┼──────────────────────────────────────────────────────┤
│  Main Process (Electron)                                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  IPC Handler (src/main/ipc.ts)                           │   │
│  │  ┌────────────────────────────────────────────────────┐  │   │
│  │  │  PythonBridge (src/main/python-bridge.ts)          │  │   │
│  │  │  JSON-RPC 2.0 over stdio                           │  │   │
│  │  │  ┌──────────────────────────────────────────────┐  │  │   │
│  │  │  │  Python Subprocess (child_process.fork)      │  │  │   │
│  │  │  │  FastAPI + Tree-sitter + SQLite              │  │  │   │
│  │  │  └──────────────────────────────────────────────┘  │  │   │
│  │  └────────────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘

┌──────────────────────────────────────────────────────────────────┐
│  External LLM API (HTTP)                                         │
│  Renderer ──fetch──→ http://localhost:11434 (Ollama)             │
│  Renderer ──fetch──→ https://api.openai.com (OpenAI)             │
│  Renderer ──fetch──→ http://localhost:1234 (LM-Studio)           │
└──────────────────────────────────────────────────────────────────┘
```

---

## 二、通讯方式划分

### 2.1 IPC 通道 (本地服务)

| 模块 | 方法 | 说明 |
|------|------|------|
| **project** | `list`, `import`, `get`, `remove`, `sync`, `getFileTree` | 项目管理 |
| **analysis** | `listTasks`, `createTask`, `runTask`, `getTask`, `getResults`, `updateTask`, `deleteTask` | 代码分析 |
| **knowledge** | `listDocs`, `createDoc`, `getDoc`, `updateDoc`, `deleteDoc`, `getGraph`, `getDimensions` | 知识库 |
| **settings** | `getModels`, `addModel`, `updateModel`, `removeModel`, `testModel`, `getAgents`, `addAgent`, `updateAgent`, `removeAgent`, `detectAgent`, `getSkills`, `updateSkill`, `getBindings`, `updateBindings` | 设置配置 |
| **backend** | `start`, `stop`, `restart`, `getStatus`, `ping` | 后端进程管理 |

### 2.2 HTTP 通道 (LLM 请求)

| 模块 | 方式 | 说明 |
|------|------|------|
| **LLM Chat** | `POST /api/chat` | 流式对话 (SSE) |
| **LLM Completion** | `POST /api/completions` | 代码补全 |
| **LLM Embedding** | `POST /api/embeddings` | 文本向量化 |

---

## 三、JSON-RPC 2.0 协议

Python 后端通过 stdio 接收 JSON-RPC 2.0 请求，Main Process 作为桥接层。

### 3.1 请求格式

```jsonc
{
  "jsonrpc": "2.0",
  "id": 1,                          // 请求 ID (number/string)
  "method": "project.list",         // 方法名 (模块.操作)
  "params": {                        // 参数对象 (可选)
    "projectId": "proj-1"
  }
}
```

### 3.2 响应格式

```jsonc
{
  "jsonrpc": "2.0",
  "id": 1,                          // 对应请求 ID
  "result": {                        // 成功结果
    "projects": [...]
  }
}
```

### 3.3 错误格式

```jsonc
{
  "jsonrpc": "2.0",
  "id": 1,
  "error": {
    "code": -32601,                  // JSON-RPC 标准错误码
    "message": "Method not found",
    "data": {                        // 额外信息
      "method": "project.unknown"
    }
  }
}
```

### 3.4 通知 (无 ID)

```jsonc
{
  "jsonrpc": "2.0",
  "method": "task.progress",
  "params": {
    "taskId": "task-1",
    "progress": 45,
    "status": "running"
  }
}
```

---

## 四、方法注册表

### 4.1 project 模块

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `project.list` | `-` | `Project[]` | 获取项目列表 |
| `project.import` | `{ path: string }` | `Project` | 导入新项目 |
| `project.get` | `{ id: string }` | `Project` | 获取项目详情 |
| `project.remove` | `{ id: string }` | `void` | 移除项目 |
| `project.sync` | `{ id: string }` | `Project` | 触发同步 |
| `project.getFileTree` | `{ id: string }` | `FileTreeNode[]` | 获取文件树 |

### 4.2 analysis 模块

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `analysis.listTasks` | `{ projectId: string }` | `AnalysisTask[]` | 获取任务列表 |
| `analysis.createTask` | `{ projectId, type, name }` | `AnalysisTask` | 创建任务 |
| `analysis.runTask` | `{ taskId: string }` | `{ taskId, status }` | 启动执行 |
| `analysis.getTask` | `{ taskId: string }` | `AnalysisTask` | 获取任务详情 |
| `analysis.getResults` | `{ taskId: string }` | `AnalysisResult` | 获取分析结果 |
| `analysis.updateTask` | `{ taskId, favorite, pinned, tags }` | `AnalysisTask` | 更新元数据 |
| `analysis.deleteTask` | `{ taskId: string }` | `void` | 删除任务 |

### 4.3 knowledge 模块

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `knowledge.listDocs` | `{ search, dimensions, sortBy }` | `KnowledgeDoc[]` | 获取文档列表 |
| `knowledge.createDoc` | `{ title, content, ... }` | `KnowledgeDoc` | 创建文档 |
| `knowledge.getDoc` | `{ id: string }` | `KnowledgeDoc` | 获取文档详情 |
| `knowledge.updateDoc` | `{ id, content, tags, ... }` | `KnowledgeDoc` | 更新文档 |
| `knowledge.deleteDoc` | `{ id: string }` | `void` | 删除文档 |
| `knowledge.getGraph` | `{ projectId?: string }` | `{ nodes, edges }` | 获取知识图谱 |
| `knowledge.getDimensions` | `-` | `Dimensions` | 获取分类标签 |

### 4.4 settings 模块

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `settings.getModels` | `-` | `ModelConfigItem[]` | 获取模型列表 |
| `settings.addModel` | `{ name, provider, ... }` | `ModelConfigItem` | 添加模型 |
| `settings.updateModel` | `{ id, ... }` | `ModelConfigItem` | 更新模型 |
| `settings.removeModel` | `{ id: string }` | `void` | 删除模型 |
| `settings.testModel` | `{ id: string }` | `{ status, latency }` | 测试连接 |
| `settings.getAgents` | `-` | `AgentConfigItem[]` | 获取 Agent 列表 |
| `settings.addAgent` | `{ name, path, args }` | `AgentConfigItem` | 添加 Agent |
| `settings.updateAgent` | `{ id, ... }` | `AgentConfigItem` | 更新 Agent |
| `settings.removeAgent` | `{ id: string }` | `void` | 删除 Agent |
| `settings.detectAgent` | `{ id: string }` | `{ status, version }` | 检测 Agent |
| `settings.getSkills` | `-` | `SkillConfigItem[]` | 获取技能列表 |
| `settings.updateSkill` | `{ id, enabled }` | `SkillConfigItem` | 更新技能 |
| `settings.getBindings` | `-` | `Record<string, string>` | 获取绑定 |
| `settings.updateBindings` | `{ bindings }` | `Record<string, string>` | 更新绑定 |

### 4.5 backend 模块

| 方法 | 参数 | 返回 | 说明 |
|------|------|------|------|
| `backend.start` | `-` | `{ status, pid, port }` | 启动后端 |
| `backend.stop` | `-` | `{ status }` | 停止后端 |
| `backend.restart` | `-` | `{ status }` | 重启后端 |
| `backend.getStatus` | `-` | `BackendStatus` | 获取状态 |
| `backend.ping` | `-` | `{ pong: true }` | 心跳检测 |

---

## 五、事件推送 (Main→Renderer)

Python 后端通过 stdio 发送通知，Main Process 转发到 Renderer：

| 事件 | 参数 | 说明 |
|------|------|------|
| `task:progress` | `{ taskId, progress, status }` | 任务进度更新 |
| `task:complete` | `{ taskId, status, results }` | 任务完成 |
| `task:error` | `{ taskId, error }` | 任务失败 |
| `project:synced` | `{ projectId, fileCount }` | 项目同步完成 |
| `backend:status` | `{ status, pid, port }` | 后端状态变化 |

---

## 六、Python 后端实现

### 6.1 JSON-RPC Server (stdio)

```python
# backend/rpc_server.py
import json
import sys
from typing import Dict, Callable, Any

class JSONRPCServer:
    def __init__(self):
        self.methods: Dict[str, Callable] = {}

    def register(self, name: str):
        def decorator(func: Callable):
            self.methods[name] = func
            return func
        return decorator

    def handle_request(self, raw: str) -> dict:
        request = json.loads(raw)
        method = request.get('method')
        params = request.get('params', {})
        req_id = request.get('id')

        if method not in self.methods:
            return {
                'jsonrpc': '2.0',
                'id': req_id,
                'error': {
                    'code': -32601,
                    'message': f'Method not found: {method}'
                }
            }

        try:
            result = self.methods[method](**params)
            return {
                'jsonrpc': '2.0',
                'id': req_id,
                'result': result
            }
        except Exception as e:
            return {
                'jsonrpc': '2.0',
                'id': req_id,
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }

    def run(self):
        for line in sys.stdin:
            response = self.handle_request(line.strip())
            sys.stdout.write(json.dumps(response) + '\n')
            sys.stdout.flush()

# 使用示例
server = JSONRPCServer()

@server.register('project.list')
def list_projects():
    return [{"id": "proj-1", "name": "topoOne-ui", ...}]

@server.register('analysis.runTask')
def run_task(task_id: str):
    # 异步执行，通过通知推送进度
    ...

if __name__ == '__main__':
    server.run()
```

### 6.2 方法注册

```python
# backend/main.py
from rpc_server import server
from handlers import project, analysis, knowledge, settings

# 注册所有方法
for method in [
    project.list, project.import_, project.get, project.remove, project.sync, project.get_file_tree,
    analysis.list_tasks, analysis.create_task, analysis.run_task, ...
]:
    server.register(method.__name__)(method)

if __name__ == '__main__':
    server.run()
```

---

## 七、Main Process 桥接层

```typescript
// src/main/python-bridge.ts
import { fork, ChildProcess } from 'child_process'
import { join } from 'path'
import { EventEmitter } from 'events'

export class PythonBridge extends EventEmitter {
  private process: ChildProcess | null = null
  private requestId = 0
  private pendingRequests = new Map<number, { resolve: Function, reject: Function }>()

  async start(): Promise<void> {
    const scriptPath = join(__dirname, '../../backend/main.py')
    this.process = fork(scriptPath, [], {
      stdio: ['pipe', 'pipe', 'pipe', 'ipc'],
      env: { ...process.env, NODE_ENV: 'production' },
    })

    this.process?.stdout?.on('data', (data) => {
      const lines = data.toString().split('\n').filter(Boolean)
      for (const line of lines) {
        this.handleResponse(line)
      }
    })

    this.process?.on('error', (err) => {
      this.emit('error', err)
    })

    this.process?.on('exit', (code) => {
      this.emit('exit', code)
    })
  }

  async call<T = any>(method: string, params: Record<string, any> = {}): Promise<T> {
    return new Promise((resolve, reject) => {
      const id = ++this.requestId
      const request = JSON.stringify({
        jsonrpc: '2.0',
        id,
        method,
        params,
      }) + '\n'

      this.pendingRequests.set(id, { resolve, reject })
      this.process?.stdin?.write(request)
    })
  }

  private handleResponse(raw: string): void {
    let response: any
    try {
      response = JSON.parse(raw)
    } catch {
      return
    }

    if (response.error) {
      this.pendingRequests.get(response.id)?.reject(new Error(response.error.message))
    } else if (response.result !== undefined) {
      this.pendingRequests.get(response.id)?.resolve(response.result)
    } else {
      // Notification (no id)
      this.emit(response.method, response.params)
    }
    this.pendingRequests.delete(response.id)
  }

  stop(): void {
    this.process?.kill()
    this.process = null
  }
}
```

---

## 八、Preload API 暴露

```typescript
// src/preload/index.ts
const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('api', {
  // 项目管理
  project: {
    list: () => ipcRenderer.invoke('ipc:call', 'project.list'),
    import: (path: string) => ipcRenderer.invoke('ipc:call', 'project.import', { path }),
    get: (id: string) => ipcRenderer.invoke('ipc:call', 'project.get', { id }),
    remove: (id: string) => ipcRenderer.invoke('ipc:call', 'project.remove', { id }),
    sync: (id: string) => ipcRenderer.invoke('ipc:call', 'project.sync', { id }),
    getFileTree: (id: string) => ipcRenderer.invoke('ipc:call', 'project.getFileTree', { id }),
  },

  // 代码分析
  analysis: {
    listTasks: (projectId: string) => ipcRenderer.invoke('ipc:call', 'analysis.listTasks', { projectId }),
    createTask: (params: any) => ipcRenderer.invoke('ipc:call', 'analysis.createTask', params),
    runTask: (taskId: string) => ipcRenderer.invoke('ipc:call', 'analysis.runTask', { taskId }),
    getTask: (taskId: string) => ipcRenderer.invoke('ipc:call', 'analysis.getTask', { taskId }),
    getResults: (taskId: string) => ipcRenderer.invoke('ipc:call', 'analysis.getResults', { taskId }),
    updateTask: (params: any) => ipcRenderer.invoke('ipc:call', 'analysis.updateTask', params),
    deleteTask: (taskId: string) => ipcRenderer.invoke('ipc:call', 'analysis.deleteTask', { taskId }),
    onProgress: (cb: any) => ipcRenderer.on('task:progress', (_e, data) => cb(data)),
    onComplete: (cb: any) => ipcRenderer.on('task:complete', (_e, data) => cb(data)),
    onError: (cb: any) => ipcRenderer.on('task:error', (_e, data) => cb(data)),
  },

  // 知识库
  knowledge: {
    listDocs: (params: any) => ipcRenderer.invoke('ipc:call', 'knowledge.listDocs', params),
    createDoc: (params: any) => ipcRenderer.invoke('ipc:call', 'knowledge.createDoc', params),
    getDoc: (id: string) => ipcRenderer.invoke('ipc:call', 'knowledge.getDoc', { id }),
    updateDoc: (params: any) => ipcRenderer.invoke('ipc:call', 'knowledge.updateDoc', params),
    deleteDoc: (id: string) => ipcRenderer.invoke('ipc:call', 'knowledge.deleteDoc', { id }),
    getGraph: (params?: any) => ipcRenderer.invoke('ipc:call', 'knowledge.getGraph', params || {}),
    getDimensions: () => ipcRenderer.invoke('ipc:call', 'knowledge.getDimensions'),
  },

  // 设置配置
  settings: {
    getModels: () => ipcRenderer.invoke('ipc:call', 'settings.getModels'),
    addModel: (params: any) => ipcRenderer.invoke('ipc:call', 'settings.addModel', params),
    updateModel: (params: any) => ipcRenderer.invoke('ipc:call', 'settings.updateModel', params),
    removeModel: (id: string) => ipcRenderer.invoke('ipc:call', 'settings.removeModel', { id }),
    testModel: (id: string) => ipcRenderer.invoke('ipc:call', 'settings.testModel', { id }),
    getAgents: () => ipcRenderer.invoke('ipc:call', 'settings.getAgents'),
    addAgent: (params: any) => ipcRenderer.invoke('ipc:call', 'settings.addAgent', params),
    updateAgent: (params: any) => ipcRenderer.invoke('ipc:call', 'settings.updateAgent', params),
    removeAgent: (id: string) => ipcRenderer.invoke('ipc:call', 'settings.removeAgent', { id }),
    detectAgent: (id: string) => ipcRenderer.invoke('ipc:call', 'settings.detectAgent', { id }),
    getSkills: () => ipcRenderer.invoke('ipc:call', 'settings.getSkills'),
    updateSkill: (params: any) => ipcRenderer.invoke('ipc:call', 'settings.updateSkill', params),
    getBindings: () => ipcRenderer.invoke('ipc:call', 'settings.getBindings'),
    updateBindings: (params: any) => ipcRenderer.invoke('ipc:call', 'settings.updateBindings', params),
  },

  // 后端管理
  backend: {
    start: () => ipcRenderer.invoke('backend:start'),
    stop: () => ipcRenderer.invoke('backend:stop'),
    restart: () => ipcRenderer.invoke('backend:restart'),
    getStatus: () => ipcRenderer.invoke('backend:status'),
    onStatusChange: (cb: any) => ipcRenderer.on('backend:status-changed', (_e, data) => cb(data)),
  },

  // 系统
  system: {
    selectDirectory: () => ipcRenderer.invoke('dialog:open-directory'),
    getAppDataPath: () => ipcRenderer.invoke('app:data-path'),
    get: (key: string) => ipcRenderer.invoke('store:get', key),
    set: (key: string, val: any) => ipcRenderer.invoke('store:set', key, val),
  },
})
```

---

## 九、Renderer Service 层

```typescript
// src/services/ipc.ts
/// <reference types="electron-vite/node" />

// 类型声明
interface Window {
  api: {
    project: {
      list: () => Promise<Project[]>
      import: (path: string) => Promise<Project>
      get: (id: string) => Promise<Project>
      remove: (id: string) => Promise<void>
      sync: (id: string) => Promise<Project>
      getFileTree: (id: string) => Promise<FileTreeNode[]>
    }
    analysis: {
      listTasks: (projectId: string) => Promise<AnalysisTask[]>
      createTask: (params: CreateTaskParams) => Promise<AnalysisTask>
      runTask: (taskId: string) => Promise<{ taskId: string; status: string }>
      getTask: (taskId: string) => Promise<AnalysisTask>
      getResults: (taskId: string) => Promise<AnalysisResult>
      updateTask: (params: UpdateTaskParams) => Promise<AnalysisTask>
      deleteTask: (taskId: string) => Promise<void>
      onProgress: (cb: (data: any) => void) => void
      onComplete: (cb: (data: any) => void) => void
      onError: (cb: (data: any) => void) => void
    }
    knowledge: {
      listDocs: (params: any) => Promise<KnowledgeDoc[]>
      createDoc: (params: any) => Promise<KnowledgeDoc>
      getDoc: (id: string) => Promise<KnowledgeDoc>
      updateDoc: (params: any) => Promise<KnowledgeDoc>
      deleteDoc: (id: string) => Promise<void>
      getGraph: (params?: any) => Promise<{ nodes: any[]; edges: any[] }>
      getDimensions: () => Promise<Dimensions>
    }
    settings: {
      getModels: () => Promise<ModelConfigItem[]>
      addModel: (params: any) => Promise<ModelConfigItem>
      updateModel: (params: any) => Promise<ModelConfigItem>
      removeModel: (id: string) => Promise<void>
      testModel: (id: string) => Promise<{ status: string; latency: number }>
      getAgents: () => Promise<AgentConfigItem[]>
      addAgent: (params: any) => Promise<AgentConfigItem>
      updateAgent: (params: any) => Promise<AgentConfigItem>
      removeAgent: (id: string) => Promise<void>
      detectAgent: (id: string) => Promise<{ status: string; version?: string }>
      getSkills: () => Promise<SkillConfigItem[]>
      updateSkill: (params: any) => Promise<SkillConfigItem>
      getBindings: () => Promise<Record<string, string>>
      updateBindings: (params: any) => Promise<Record<string, string>>
    }
    backend: {
      start: () => Promise<void>
      stop: () => Promise<void>
      restart: () => Promise<void>
      getStatus: () => Promise<BackendStatus>
      onStatusChange: (cb: (data: any) => void) => void
    }
    system: {
      selectDirectory: () => Promise<string>
      getAppDataPath: () => Promise<string>
      get: (key: string) => Promise<any>
      set: (key: string, val: any) => Promise<void>
    }
  }
}

export const api = window.api
```

---

## 十、LLM HTTP 服务

```typescript
// src/services/llm.ts
import type { ModelConfigItem } from '@/utils/mock'

export class LLMService {
  private config: ModelConfigItem | null = null

  setConfig(config: ModelConfigItem) {
    this.config = config
  }

  private getBaseUrl(): string {
    if (!this.config) throw new Error('No LLM config')
    return this.config.url
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    }
    if (this.config?.provider === 'openai') {
      headers['Authorization'] = `Bearer ${this.config.url}` // API key stored securely
    }
    return headers
  }

  async chat(messages: Array<{ role: string; content: string }>, onChunk?: (chunk: string) => void) {
    const baseUrl = this.getBaseUrl()
    const provider = this.config?.provider

    if (provider === 'ollama') {
      return this.ollamaChat(messages, onChunk)
    } else if (provider === 'openai') {
      return this.openAIChat(messages, onChunk)
    }
    // ... other providers
  }

  private async ollamaChat(messages: any[], onChunk?: (chunk: string) => void) {
    const response = await fetch(`${this.getBaseUrl()}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: this.config?.model,
        messages,
        stream: true,
        options: {
          temperature: this.config?.temperature,
          num_predict: this.config?.maxTokens,
        },
      }),
    })

    if (!response.body) throw new Error('No response body')

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let fullContent = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      const chunk = decoder.decode(value)
      for (const line of chunk.split('\n').filter(Boolean)) {
        const data = JSON.parse(line)
        const content = data.message?.content || ''
        fullContent += content
        onChunk?.(content)
      }
    }

    return fullContent
  }

  private async openAIChat(messages: any[], onChunk?: (chunk: string) => void) {
    const response = await fetch(`${this.getBaseUrl()}/v1/chat/completions`, {
      method: 'POST',
      headers: this.getHeaders(),
      body: JSON.stringify({
        model: this.config?.model,
        messages,
        stream: true,
        temperature: this.config?.temperature,
        max_tokens: this.config?.maxTokens,
      }),
    })

    // SSE parsing...
  }

  async embed(text: string): Promise<number[]> {
    // Similar implementation for embeddings
  }
}

export const llmService = new LLMService()
```

---

## 十一、对比总结

| 维度 | HTTP API (旧) | IPC (新) |
|------|---------------|----------|
| **延迟** | ~5-20ms (网络栈) | ~0.1-1ms (进程间) |
| **序列化** | JSON over HTTP | JSON over stdio |
| **流式推送** | WebSocket/SSE | stdio 通知 + IPC 事件 |
| **文件传输** | multipart/form-data | 文件路径引用 |
| **错误处理** | HTTP 状态码 | JSON-RPC 错误码 |
| **跨进程安全** | CORS | contextBridge 隔离 |
| **适用场景** | 外部服务 (LLM) | 本地服务 (分析/知识库) |
