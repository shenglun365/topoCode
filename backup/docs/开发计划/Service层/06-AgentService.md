# AgentService 设计

> Agent 调度服务，负责外部 CLI Agent 工具调度和任务监控

---

## 1. 组件职责

- Agent 配置管理
- Agent 任务调度
- 任务状态监控
- 任务日志收集
- 任务结果处理

## 2. API 接口

### 2.1 获取 Agent 列表

```
GET /api/agent/list
```

**响应:**
```json
{
  "code": 0,
  "data": [
    {
      "id": "agent_001",
      "name": "qwen-code",
      "path": "/usr/local/bin/qwen-code",
      "args": ["--model", "qwen2.5-coder:7b"],
      "isDefault": true,
      "status": "available"
    }
  ]
}
```

### 2.2 添加 Agent

```
POST /api/agent
```

**请求:**
```json
{
  "name": "qwen-code",
  "path": "/usr/local/bin/qwen-code",
  "args": ["--model", "qwen2.5-coder:7b"]
}
```

### 2.3 更新 Agent

```
PUT /api/agent/{agentId}
```

### 2.4 删除 Agent

```
DELETE /api/agent/{agentId}
```

### 2.5 设置默认 Agent

```
POST /api/agent/{agentId}/set-default
```

### 2.6 测试 Agent

```
POST /api/agent/{agentId}/test
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "status": "available",
    "version": "1.0.0"
  }
}
```

### 2.7 创建 Agent 任务

```
POST /api/agent/task
```

**请求:**
```json
{
  "agentId": "agent_001",
  "name": "代码生成任务",
  "prompt": "请为这个项目生成用户认证模块",
  "context": {
    "projectId": "proj_001",
    "specDocId": "spec_001"
  }
}
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "taskId": "task_001",
    "status": "pending"
  }
}
```

### 2.8 获取任务状态

```
GET /api/agent/task/{taskId}
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "id": "task_001",
    "name": "代码生成任务",
    "agent": "qwen-code",
    "status": "running",
    "progress": 65,
    "currentStep": 13,
    "totalSteps": 20,
    "startTime": "2026-05-01T10:30:00Z",
    "estimatedRemaining": "2min"
  }
}
```

### 2.9 停止任务

```
POST /api/agent/task/{taskId}/stop
```

### 2.10 获取任务日志

```
GET /api/agent/task/{taskId}/logs
```

## 3. 数据结构

```python
class AgentConfig(BaseModel):
    id: str
    name: str
    path: str
    args: List[str]
    is_default: bool
    status: str  # available/not-found/error
    created_at: datetime
    updated_at: datetime

class AgentTask(BaseModel):
    id: str
    agent_id: str
    name: str
    prompt: str
    context: dict
    status: str  # pending/running/done/failed/stopped
    progress: int
    current_step: int
    total_steps: int
    start_time: Optional[datetime]
    end_time: Optional[datetime]
    estimated_remaining: Optional[str]
    logs: List[str]
    result: Optional[dict]
    created_at: datetime
    updated_at: datetime
```

## 4. 业务逻辑

### 4.1 Agent 任务执行流程

```
1. 接收任务创建请求
2. 验证 Agent 可用性
3. 创建任务记录 (状态: pending)
4. 异步执行任务
5. 启动 subprocess 调用 Agent
6. 实时收集 stdout/stderr
7. 解析任务进度
8. 更新任务状态
9. 任务完成/失败后保存结果
```

### 4.2 Subprocess 管理

```python
import asyncio
import subprocess

class AgentExecutor:
    async def execute(self, task: AgentTask) -> AgentTask:
        agent = await self.get_agent(task.agent_id)
        
        # 构建命令
        cmd = [agent.path] + agent.args + [
            "--prompt", task.prompt,
            "--context", json.dumps(task.context)
        ]
        
        # 启动进程
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        # 实时收集输出
        async for line in process.stdout:
            log = line.decode().strip()
            await self.append_log(task.id, log)
            await self.parse_progress(log, task.id)
        
        # 等待进程完成
        await process.wait()
        
        # 更新任务状态
        if process.returncode == 0:
            await self.update_task_status(task.id, "done")
        else:
            await self.update_task_status(task.id, "failed")
        
        return task
```

### 4.3 任务进度解析

```python
def parse_progress(log: str, task_id: str) -> dict:
    # 解析 Agent 输出的进度信息
    # 格式: [PROGRESS] step: 13/20, remaining: 2min
    import re
    
    match = re.match(r'\[PROGRESS\] step: (\d+)/(\d+), remaining: (.+)', log)
    if match:
        current_step = int(match.group(1))
        total_steps = int(match.group(2))
        remaining = match.group(3)
        
        progress = int((current_step / total_steps) * 100)
        
        return {
            "progress": progress,
            "current_step": current_step,
            "total_steps": total_steps,
            "estimated_remaining": remaining
        }
    
    return None
```

### 4.4 任务监控

```python
class TaskMonitor:
    def __init__(self):
        self.active_tasks: Dict[str, asyncio.Task] = {}
    
    async def start_monitoring(self, task_id: str):
        # 定期检查任务状态
        while True:
            task = await self.get_task(task_id)
            if task.status in ["done", "failed", "stopped"]:
                break
            
            # 推送状态更新到前端 (WebSocket)
            await self.push_status_update(task_id, task)
            
            await asyncio.sleep(1)
    
    async def push_status_update(self, task_id: str, task: AgentTask):
        # 通过 WebSocket 推送任务状态到前端
        pass
```

## 5. Agent 协议规范

Agent 工具需要遵循以下协议:

### 5.1 命令行参数

```
<agent> --prompt <prompt> --context <context_json> [其他参数]
```

### 5.2 输出格式

```
[PROGRESS] step: 1/10, remaining: 5min
[LOG] 正在分析项目结构...
[LOG] 生成用户认证模块...
[RESULT] { "files": [...], "summary": "..." }
```

### 5.3 退出码

| 退出码 | 说明 |
|--------|------|
| 0 | 成功 |
| 1 | 通用错误 |
| 2 | 参数错误 |
| 3 | 模型错误 |

## 6. WebSocket 实时推送

```python
class AgentWebSocket(WebSocketEndpoint):
    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_clients.add(websocket)
    
    async def push_task_update(self, task_id: str, task: AgentTask):
        message = {
            "type": "task_update",
            "taskId": task_id,
            "data": task.dict()
        }
        
        for websocket in self.active_clients:
            await websocket.send_json(message)
```

## 7. 错误处理

| 错误码 | 说明 |
|--------|------|
| 2501 | Agent 不存在 |
| 2502 | Agent 不可用 |
| 2503 | 任务创建失败 |
| 2504 | 任务执行失败 |
| 2505 | 任务已停止 |

## 8. 文件结构

```
backend/
├── api/
│   └── agent.py
├── services/
│   └── agent_service.py
├── repositories/
│   └── agent_repo.py
├── executors/
│   ├── __init__.py
│   ├── base.py
│   └── subprocess_executor.py
├── websocket/
│   └── agent_ws.py
└── models/
    └── agent.py
```
