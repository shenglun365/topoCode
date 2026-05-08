# ModelService 设计

> 模型路由服务，负责 LLM 模型管理和请求路由

---

## 1. 组件职责

- 模型配置管理 (本地/云端)
- 模型请求路由
- 模型健康检查
- 负载均衡 (多模型场景)
- 请求重试/降级

## 2. API 接口

### 2.1 获取模型列表

```
GET /api/model/list
```

**响应:**
```json
{
  "code": 0,
  "data": [
    {
      "id": "model_001",
      "name": "Ollama (本地)",
      "type": "ollama",
      "model": "qwen2.5-coder:7b",
      "endpoint": "http://localhost:11434",
      "isDefault": true,
      "status": "online"
    }
  ]
}
```

### 2.2 添加模型

```
POST /api/model
```

**请求:**
```json
{
  "name": "OpenAI",
  "type": "openai",
  "model": "gpt-4o",
  "endpoint": "https://api.openai.com",
  "apiKey": "sk-xxx"
}
```

### 2.3 更新模型

```
PUT /api/model/{modelId}
```

### 2.4 删除模型

```
DELETE /api/model/{modelId}
```

### 2.5 设置默认模型

```
POST /api/model/{modelId}/set-default
```

### 2.6 测试模型连接

```
POST /api/model/{modelId}/test
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "status": "online",
    "latency": 120,
    "model": "qwen2.5-coder:7b"
  }
}
```

### 2.7 生成文本 (内部接口)

```
POST /api/model/generate
```

**请求:**
```json
{
  "modelId": "model_001",
  "prompt": "请分析这个项目的架构",
  "stream": true,
  "maxTokens": 2000,
  "temperature": 0.7
}
```

## 3. 数据结构

```python
class ModelConfig(BaseModel):
    id: str
    name: str
    type: str  # ollama/openai/custom
    model: str
    endpoint: str
    api_key: Optional[str]
    is_default: bool
    status: str  # online/offline/error
    config: Optional[dict]  # 额外配置
    created_at: datetime
    updated_at: datetime

class GenerateRequest(BaseModel):
    model_id: Optional[str]  # None 表示使用默认模型
    prompt: str
    stream: bool = False
    max_tokens: int = 2000
    temperature: float = 0.7
    top_p: float = 0.9

class GenerateResponse(BaseModel):
    id: str
    model: str
    content: str
    usage: dict
    finish_reason: str
```

## 4. 业务逻辑

### 4.1 模型路由流程

```
1. 接收生成请求
2. 如果指定 modelId，使用该模型
3. 否则使用默认模型
4. 检查模型状态
5. 根据模型类型选择适配器
6. 发送请求到模型端点
7. 返回响应
```

### 4.2 模型适配器模式

```python
class ModelAdapter(ABC):
    @abstractmethod
    async def generate(self, prompt: str, config: dict) -> GenerateResponse:
        pass
    
    @abstractmethod
    async def test_connection(self) -> dict:
        pass

class OllamaAdapter(ModelAdapter):
    async def generate(self, prompt: str, config: dict) -> GenerateResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config['endpoint']}/api/generate",
                json={
                    "model": config["model"],
                    "prompt": prompt,
                    "stream": config.get("stream", False)
                }
            )
            return response.json()
    
    async def test_connection(self) -> dict:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{endpoint}/api/tags")
            return {"status": "online" if response.status_code == 200 else "offline"}

class OpenAIAdapter(ModelAdapter):
    async def generate(self, prompt: str, config: dict) -> GenerateResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config['endpoint']}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {config['api_key']}",
                    "Content-Type": "application/json"
                },
                json={
                    "model": config["model"],
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": config.get("stream", False)
                }
            )
            return response.json()
```

### 4.3 健康检查流程

```python
async def health_check(model_id: str) -> str:
    model = await get_model_config(model_id)
    adapter = get_adapter(model.type)
    
    try:
        result = await adapter.test_connection(model)
        if result["status"] == "online":
            await update_model_status(model_id, "online")
        else:
            await update_model_status(model_id, "offline")
    except Exception as e:
        await update_model_status(model_id, "error")
    
    return await get_model_status(model_id)
```

### 4.4 请求重试/降级

```python
async def generate_with_retry(
    prompt: str,
    model_id: Optional[str],
    max_retries: int = 3
) -> GenerateResponse:
    models = await get_available_models()
    
    for attempt in range(max_retries):
        current_model = models[0] if not model_id else get_model(model_id)
        
        try:
            response = await self.generate(current_model, prompt)
            return response
        except Exception as e:
            if attempt < max_retries - 1:
                # 尝试下一个可用模型
                current_model = models[(attempt + 1) % len(models)]
                continue
            else:
                raise e
```

## 5. 模型类型支持

| 类型 | 端点格式 | 认证方式 | 备注 |
|------|---------|---------|------|
| ollama | http://localhost:11434 | 无 | 本地模型 |
| openai | https://api.openai.com | API Key | OpenAI 兼容 |
| custom | 自定义 | 自定义 | 用户自定义 |

## 6. 配置持久化

```python
class ModelRepository:
    async def create(self, model: ModelConfig) -> str
    async def get_by_id(self, model_id: str) -> ModelConfig
    async def get_all(self) -> List[ModelConfig]
    async def get_default(self) -> ModelConfig
    async def update(self, model_id: str, updates: dict)
    async def delete(self, model_id: str)
    async def set_default(self, model_id: str)
```

## 7. 错误处理

| 错误码 | 说明 |
|--------|------|
| 2401 | 模型不存在 |
| 2402 | 模型配置无效 |
| 2403 | 模型连接失败 |
| 2404 | 模型请求超时 |
| 2405 | 模型响应错误 |

## 8. 文件结构

```
backend/
├── api/
│   └── model.py
├── services/
│   └── model_service.py
├── repositories/
│   └── model_repo.py
├── adapters/
│   ├── __init__.py
│   ├── base.py
│   ├── ollama.py
│   ├── openai.py
│   └── custom.py
└── models/
    └── model.py
```
