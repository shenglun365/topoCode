# CoderService 设计

> AI 助手服务，负责对话管理、Session 管理、上下文检索

---

## 1. 组件职责

- Session 管理 (创建/切换/删除)
- 对话消息管理
- 上下文检索 (代码/知识库)
- AI 回复生成 (协调 ModelService)
- Spec 文档管理

## 2. API 接口

### 2.1 创建 Session

```
POST /api/coder/session
```

**请求:**
```json
{
  "name": "当前项目",
  "type": "project",
  "projectId": "proj_001"
}
```

### 2.2 获取 Session 列表

```
GET /api/coder/sessions
```

### 2.3 获取 Session 详情

```
GET /api/coder/session/{sessionId}
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "id": "session_001",
    "name": "当前项目",
    "messages": [
      {
        "id": "msg_001",
        "role": "user",
        "content": "请分析这个项目的架构",
        "timestamp": "2026-05-01T10:30:00Z"
      },
      {
        "id": "msg_002",
        "role": "assistant",
        "content": "根据分析，该项目采用...",
        "type": "text",
        "timestamp": "2026-05-01T10:30:05Z"
      }
    ]
  }
}
```

### 2.4 发送消息

```
POST /api/coder/session/{sessionId}/message
```

**请求:**
```json
{
  "content": "请分析这个项目的架构",
  "context": {
    "includeCode": true,
    "includeKnowledge": true,
    "knowledgeLimit": 5
  }
}
```

**响应 (SSE 流式):**
```
data: {"type": "chunk", "content": "根据"}
data: {"type": "chunk", "content": "分析"}
data: {"type": "done", "messageId": "msg_003"}
```

### 2.5 删除 Session

```
DELETE /api/coder/session/{sessionId}
```

### 2.6 获取上下文

```
GET /api/coder/session/{sessionId}/context
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "code": [ /* 相关代码片段 */ ],
    "knowledge": [ /* 相关知识文档 */ ],
    "spec": [ /* 相关 Spec 文档 */ ]
  }
}
```

## 3. 数据结构

```python
class Session(BaseModel):
    id: str
    name: str
    type: str  # project/general/history
    project_id: Optional[str]
    messages: List[ChatMessage]
    created_at: datetime
    updated_at: datetime
    status: str  # active/idle/error

class ChatMessage(BaseModel):
    id: str
    session_id: str
    role: str  # user/assistant
    content: str
    type: str  # text/context/spec/task/error
    timestamp: datetime
    metadata: Optional[dict]

class SpecDoc(BaseModel):
    id: str
    session_id: str
    title: str
    status: str  # draft/reviewed/approved
    content: str
    sections: List[str]
    created_at: datetime
    updated_at: datetime
```

## 4. 业务逻辑

### 4.1 消息发送流程

```
1. 接收用户消息
2. 保存用户消息到数据库
3. 检索相关上下文 (代码/知识库)
4. 构建 Prompt (系统提示 + 上下文 + 用户消息)
5. 调用 ModelService 生成回复
6. 流式返回 AI 回复
7. 保存 AI 回复到数据库
```

### 4.2 上下文检索流程

```
1. 分析用户消息意图
2. 检索相关代码片段 (从 AST 缓存)
3. 检索相关知识文档 (从 ChromaDB)
4. 检索相关 Spec 文档
5. 合并上下文，按相关度排序
6. 返回上下文数据
```

### 4.3 Session 管理流程

```
1. 创建 Session 时生成唯一 ID
2. Session 类型决定左面板显示
3. 切换 Session 时加载历史消息
4. 删除 Session 时清理相关数据
```

## 5. WebSocket 实时通信

```python
class CoderWebSocket(WebSocketEndpoint):
    async def on_connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_sessions.add(websocket)
    
    async def on_receive(self, websocket: WebSocket, data: dict):
        if data["type"] == "message":
            response = await self.process_message(data)
            await websocket.send_json(response)
    
    async def on_disconnect(self, websocket: WebSocket):
        self.active_sessions.discard(websocket)
    
    async def process_message(self, data: dict) -> dict:
        session_id = data["sessionId"]
        content = data["content"]
        
        # 检索上下文
        context = await self.retrieve_context(session_id, content)
        
        # 生成 AI 回复
        response = await self.model_service.generate(
            prompt=content,
            context=context,
            stream=True
        )
        
        return response
```

## 6. Prompt 构建

```python
def build_prompt(user_message: str, context: dict) -> str:
    system_prompt = """你是一个专业的代码分析助手，帮助用户理解项目架构和代码逻辑。"""
    
    context_prompt = ""
    if context["code"]:
        context_prompt += "\n\n## 相关代码\n"
        for code in context["code"]:
            context_prompt += f"\n```{code['language']}\n{code['content']}\n```\n"
    
    if context["knowledge"]:
        context_prompt += "\n\n## 相关知识\n"
        for doc in context["knowledge"]:
            context_prompt += f"\n### {doc['title']}\n{doc['content']}\n"
    
    full_prompt = f"{system_prompt}\n\n{context_prompt}\n\n用户: {user_message}\n\n助手:"
    
    return full_prompt
```

## 7. 错误处理

| 错误码 | 说明 |
|--------|------|
| 2301 | Session 不存在 |
| 2302 | 消息发送失败 |
| 2303 | AI 生成失败 |
| 2304 | 上下文检索失败 |
| 2305 | 模型不可用 |

## 8. 文件结构

```
backend/
├── api/
│   └── coder.py
├── services/
│   └── coder_service.py
├── repositories/
│   └── session_repo.py
├── websocket/
│   └── coder_ws.py
└── models/
    └── session.py
```
