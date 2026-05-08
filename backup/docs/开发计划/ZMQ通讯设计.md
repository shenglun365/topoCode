# ZeroMQ 通讯设计 (v2.0)

> ZeroMQ 消息队列 + SQLite 上下文管理

---

## 一、架构总览

```
┌──────────────────────────────────────────────────────────────────┐
│  Renderer Process (Vue 3)                                       │
│  window.api.* → Electron IPC → Main Process                     │
└──────────────────────────────────────────────────────────────────┘
                              │
                              │ ZeroMQ (TCP/IPC)
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│  Main Process (ZMQ ROUTER)                                      │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  ROUTER Socket (tcp://*:5670)                              │  │
│  │  ┌──────────────────────────────────────────────────────┐  │  │
│  │  │  Message Router                                      │  │  │
│  │  │  - 根据 identity 路由到不同后端                       │  │  │
│  │  │  - 请求/响应匹配                                      │  │  │
│  │  │  - 超时管理                                           │  │  │
│  │  └──────────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  SUB Socket (tcp://127.0.0.1:5680)                         │  │
│  │  - 订阅 Core Service 事件                                  │  │
│  │  - 转发到 Renderer (IPC)                                   │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
         │                    │                    │
         │ DEALER             │ DEALER            │ DEALER
         │ tcp:5671           │ tcp:5672          │ tcp:5673
         ▼                    ▼                   ▼
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│  Core Service  │  │  Agent-1       │  │  Agent-N       │
│  (Python)      │  │  (qwen-code)   │  │  (cline)       │
│  ┌──────────┐  │  │                │  │                │
│  │ DEALER   │  │  │  DEALER        │  │  DEALER        │
│  └──────────┘  │  └────────────────┘  └────────────────┘
│  ┌──────────┐  │
│  │ PUB      │  │
│  └──────────┘  │
│  ┌──────────┐  │
│  │ SQLite3  │  │
│  └──────────┘  │
└────────────────┘
```

---

## 二、ZeroMQ 模式选择

### 2.1 ROUTER/DEALER - RPC 调用

**用途**: 项目/分析/知识库/设置的请求/响应

**消息格式**:
```
[IDENTITY] [REQUEST_ID] [METHOD] [PARAMS_JSON]
```

**请求示例**:
```
["core"] ["req-001"] ["project.list"] ["{}"]
```

**响应示例**:
```
["core"] ["req-001"] [{"id":"proj-1","name":"topoOne-ui",...}]
```

**错误示例**:
```
["core"] ["req-001"] [null] [{"code":-32001,"message":"项目不存在"}]
```

### 2.2 PUB/SUB - 事件推送

**用途**: 任务进度、项目同步、后端状态

**消息格式**:
```
[TOPIC] [EVENT_TYPE] [DATA_JSON]
```

**示例**:
```
["task"] ["progress"] [{"taskId":"task-1","progress":45}]
["task"] ["complete"] [{"taskId":"task-1","status":"done"}]
["project"] ["synced"] [{"projectId":"proj-1","fileCount":158}]
```

### 2.3 PUSH/PULL - 任务分发

**用途**: Agent 任务负载均衡

**消息格式**:
```
[TASK_ID] [TASK_TYPE] [TASK_DATA_JSON]
```

**示例**:
```
["task-001"] ["code-gen"] [{"files":["src/auth.ts"],"spec":"..."}]
```

---

## 三、消息协议

### 3.1 请求消息 (Request)

```typescript
interface ZMQRequest {
  requestId: string           // 唯一请求 ID (UUID)
  method: string              // 方法名 (模块.操作)
  params: Record<string, any> // 参数
  timestamp: number           // 时间戳
}
```

**帧结构**:
```
Frame 0: IDENTITY (后端标识)
Frame 1: REQUEST_ID
Frame 2: METHOD
Frame 3: PARAMS_JSON
```

### 3.2 响应消息 (Response)

```typescript
interface ZMQResponse {
  requestId: string           // 对应请求 ID
  result: any | null          // 成功结果 (null 表示无结果)
  error: ZMQError | null      // 错误信息 (null 表示成功)
}

interface ZMQError {
  code: number                // 错误码
  message: string             // 错误消息
  data?: any                  // 额外信息
}
```

**帧结构**:
```
Frame 0: IDENTITY (请求方标识)
Frame 1: REQUEST_ID
Frame 2: RESULT_JSON (或 null)
Frame 3: ERROR_JSON (或 null)
```

### 3.3 事件消息 (Event)

```typescript
interface ZMQEvent {
  topic: string               // 主题 (task/project/backend)
  eventType: string           // 事件类型 (progress/complete/error)
  data: Record<string, any>   // 事件数据
  timestamp: number           // 时间戳
}
```

**帧结构**:
```
Frame 0: TOPIC
Frame 1: EVENT_TYPE
Frame 2: DATA_JSON
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
| `backend.start` | `-` | `{ status, pid }` | 启动后端 |
| `backend.stop` | `-` | `{ status }` | 停止后端 |
| `backend.restart` | `-` | `{ status }` | 重启后端 |
| `backend.getStatus` | `-` | `BackendStatus` | 获取状态 |
| `backend.ping` | `-` | `{ pong: true }` | 心跳检测 |

---

## 五、事件推送

### 5.1 任务事件

| 主题 | 事件类型 | 数据 | 说明 |
|------|----------|------|------|
| `task` | `progress` | `{ taskId, progress, total, current }` | 任务进度 |
| `task` | `complete` | `{ taskId, status, results }` | 任务完成 |
| `task` | `error` | `{ taskId, error }` | 任务失败 |
| `task` | `terminal` | `{ taskId, line, type }` | 终端输出 |
| `task` | `validation` | `{ taskId, label, passed }` | 校验结果 |

### 5.2 项目事件

| 主题 | 事件类型 | 数据 | 说明 |
|------|----------|------|------|
| `project` | `synced` | `{ projectId, fileCount }` | 同步完成 |
| `project` | `syncing` | `{ projectId, progress }` | 同步中 |

### 5.3 后端事件

| 主题 | 事件类型 | 数据 | 说明 |
|------|----------|------|------|
| `backend` | `status` | `{ status, pid, port }` | 状态变化 |
| `backend` | `error` | `{ error }` | 后端错误 |

---

## 六、Python 后端实现

### 6.1 Core Service (ZMQ DEALER + PUB)

```python
# backend/core_service.py
import zmq
import zmq.asyncio
import asyncio
import json
import sqlite3
from typing import Dict, Callable

class CoreService:
    def __init__(self, context: zmq.Context):
        self.context = context
        self.dealer = context.dealer()
        self.dealer.bind("tcp://127.0.0.1:5671")
        
        self.pub = context.pub()
        self.pub.bind("tcp://127.0.0.1:5680")
        
        self.methods: Dict[str, Callable] = {}
        self.db = sqlite3.connect("topoone.db")
    
    def register(self, name: str):
        def decorator(func: Callable):
            self.methods[name] = func
            return func
        return decorator
    
    async def run(self):
        poller = zmq.asyncio.Poller()
        poller.register(self.dealer, zmq.POLLIN)
        
        while True:
            events = await poller.poll()
            for socket, event in events:
                if socket == self.dealer:
                    await self.handle_request()
    
    async def handle_request(self):
        # 接收多帧消息
        frames = await self.dealer.recv_multipart()
        
        identity = frames[0]
        request_id = frames[1].decode()
        method = frames[2].decode()
        params = json.loads(frames[3])
        
        # 调用方法
        if method in self.methods:
            try:
                result = await self.methods[method](**params)
                error = None
            except Exception as e:
                result = None
                error = {"code": -32003, "message": str(e)}
        else:
            result = None
            error = {"code": -32601, "message": f"Method not found: {method}"}
        
        # 发送响应
        self.dealer.send_multipart([
            identity,
            request_id.encode(),
            json.dumps(result).encode(),
            json.dumps(error).encode(),
        ])
    
    def publish(self, topic: str, event_type: str, data: dict):
        self.pub.send_multipart([
            topic.encode(),
            event_type.encode(),
            json.dumps(data).encode(),
        ])

# 使用示例
service = CoreService(zmq.Context())

@service.register("project.list")
async def list_projects():
    cursor = service.db.execute("SELECT * FROM projects")
    return [dict(row) for row in cursor.fetchall()]

@service.register("analysis.runTask")
async def run_task(task_id: str):
    # 异步执行任务
    async def execute():
        for i in range(100):
            service.publish("task", "progress", {
                "taskId": task_id,
                "progress": i,
                "total": 100,
                "current": i,
            })
            await asyncio.sleep(0.1)
        service.publish("task", "complete", {
            "taskId": task_id,
            "status": "done",
        })
    
    asyncio.create_task(execute())
    return {"taskId": task_id, "status": "running"}

if __name__ == "__main__":
    asyncio.run(service.run())
```

### 6.2 SQLite 上下文管理

```python
# backend/sqlite_ctx.py
import sqlite3
from typing import Optional

class SQLiteContext:
    def __init__(self, db_path: str = "topoone.db"):
        self.db_path = db_path
        self.db = sqlite3.connect(db_path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.init_tables()
    
    def init_tables(self):
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                language TEXT,
                file_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'synced',
                last_sync TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            );
            
            CREATE TABLE IF NOT EXISTS analysis_tasks (
                id TEXT PRIMARY KEY,
                project_id TEXT,
                type TEXT NOT NULL,
                name TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                progress INTEGER DEFAULT 0,
                total INTEGER,
                current INTEGER,
                error TEXT,
                favorite INTEGER DEFAULT 0,
                pinned INTEGER DEFAULT 0,
                tags TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            
            CREATE TABLE IF NOT EXISTS knowledge_docs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                type TEXT DEFAULT 'document',
                description TEXT,
                content TEXT,
                project_id TEXT,
                tags TEXT,
                status TEXT DEFAULT 'draft',
                favorite INTEGER DEFAULT 0,
                pinned INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (project_id) REFERENCES projects(id)
            );
            
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                mode TEXT DEFAULT 'chat',
                status TEXT DEFAULT 'idle',
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );
            
            CREATE TABLE IF NOT EXISTS chat_messages (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now')),
                metadata TEXT,
                FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
            );
            
            CREATE TABLE IF NOT EXISTS model_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                url TEXT NOT NULL,
                type TEXT DEFAULT 'local',
                status TEXT DEFAULT 'offline',
                is_default INTEGER DEFAULT 0,
                temperature REAL,
                max_tokens INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            
            CREATE TABLE IF NOT EXISTS agent_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                path TEXT NOT NULL,
                args TEXT,
                status TEXT DEFAULT 'not-configured',
                version TEXT,
                is_default INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            
            CREATE TABLE IF NOT EXISTS skill_configs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                enabled INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
        """)
        self.db.commit()
    
    def execute(self, sql: str, params: tuple = ()):
        cursor = self.db.execute(sql, params)
        self.db.commit()
        return cursor
    
    def fetchall(self, sql: str, params: tuple = ()):
        cursor = self.db.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def fetchone(self, sql: str, params: tuple = ()):
        cursor = self.db.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None
    
    def close(self):
        self.db.close()
```

---

## 七、Main Process ZMQ Router

```typescript
// src/main/zmq-router.ts
import * as zmq from 'zeromq'
import { EventEmitter } from 'events'

export class ZMQRouter extends EventEmitter {
  private router: zmq.Router
  private sub: zmq.Sub
  private pendingRequests = new Map<string, { resolve: Function, reject: Function }>()
  private requestCounter = 0

  constructor() {
    super()
    this.router = new zmq.Router()
    this.router.bind('tcp://127.0.0.1:5670')
    
    this.sub = new zmq.Sub()
    this.sub.connect('tcp://127.0.0.1:5680')
    this.sub.subscribe('task')
    this.sub.subscribe('project')
    this.sub.subscribe('backend')
    
    this.startListening()
  }

  private async startListening() {
    // 监听 SUB 事件
    for await (const [topic, eventType, data] of this.sub) {
      this.emit(`event:${topic}.${eventType}`, JSON.parse(data.toString()))
    }
  }

  async call<T = any>(identity: string, method: string, params: Record<string, any> = {}): Promise<T> {
    const requestId = `req-${++this.requestCounter}`
    
    return new Promise((resolve, reject) => {
      this.pendingRequests.set(requestId, { resolve, reject })
      
      this.router.send(identity, [
        requestId,
        method,
        JSON.stringify(params),
      ])
      
      // 超时处理
      setTimeout(() => {
        if (this.pendingRequests.has(requestId)) {
          this.pendingRequests.delete(requestId)
          reject(new Error(`Request timeout: ${method}`))
        }
      }, 30000)
    })
  }

  handleResponse(): void {
    // 在 Main Process 中处理 ROUTER 响应
    // 通过 async iterator 接收
  }

  async *[Symbol.asyncIterator](): AsyncIterator<zmq.Message[]> {
    return this.router
  }

  close(): void {
    this.router.close()
    this.sub.close()
  }
}
```

---

## 八、Agent 管理

### 8.1 Agent 进程启动

```typescript
// src/main/agent-manager.ts
import { spawn } from 'child_process'
import * as zmq from 'zeromq'
import { EventEmitter } from 'events'

export class AgentManager extends EventEmitter {
  private agents = new Map<string, {
    process: ReturnType<typeof spawn>
    dealer: zmq.Dealer
    status: 'online' | 'offline' | 'not-detected'
  }>()

  async startAgent(name: string, path: string, args: string): Promise<void> {
    const process = spawn(path, this.parseArgs(args))
    
    const dealer = new zmq.Dealer()
    await dealer.connect('tcp://127.0.0.1:5670')
    
    this.agents.set(name, { process, dealer, status: 'online' })
    
    process.on('exit', () => {
      this.agents.get(name)!.status = 'offline'
      this.emit('agent:offline', name)
    })
  }

  async dispatchTask(agentName: string, task: any): Promise<void> {
    const agent = this.agents.get(agentName)
    if (!agent || agent.status !== 'online') {
      throw new Error(`Agent ${agentName} not available`)
    }
    
    agent.dealer.send([
      'task',
      JSON.stringify(task),
    ])
  }

  private parseArgs(args: string): string[] {
    return args.split(' ').filter(Boolean)
  }
}
```

---

## 九、对比总结

| 维度 | HTTP API (v1) | JSON-RPC stdio (v2) | ZeroMQ (v3) |
|------|---------------|---------------------|-------------|
| **延迟** | ~5-20ms | ~0.1-1ms | ~0.01-0.1ms |
| **多 Agent** | 不支持 | 复杂 | 原生支持 |
| **解耦** | 低 | 中 | 高 |
| **事件推送** | WebSocket/SSE | stdio 通知 | PUB/SUB |
| **负载均衡** | 手动 | 手动 | PUSH/PULL 自动 |
| **跨网络** | 是 | 否 | 是 (TCP) |
| **适用场景** | 外部服务 | 单进程 | 多 Agent 调度 |
