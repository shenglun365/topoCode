# KnowledgeService 设计

> 知识库服务，负责知识文档管理、分类、检索

---

## 1. 组件职责

- 知识文档 CRUD
- 四维分类管理
- 知识检索 (全文/向量)
- 知识图谱数据提供
- 知识点提取

## 2. API 接口

### 2.1 创建知识文档

```
POST /api/knowledge/doc
```

**请求:**
```json
{
  "title": "JWT认证规范",
  "type": "document",
  "content": "# JWT认证规范\n\n...",
  "dimensions": {
    "lifecycle": "设计",
    "techStack": "Python",
    "abstraction": "模块",
    "attribute": "最佳实践"
  },
  "sourceTaskId": "task_001"
}
```

### 2.2 获取文档列表

```
GET /api/knowledge/docs?lifecycle={lifecycle}&techStack={techStack}
```

### 2.3 获取文档详情

```
GET /api/knowledge/doc/{docId}
```

### 2.4 更新文档

```
PUT /api/knowledge/doc/{docId}
```

### 2.5 删除文档

```
DELETE /api/knowledge/doc/{docId}
```

### 2.6 搜索文档

```
POST /api/knowledge/search
```

**请求:**
```json
{
  "query": "JWT 认证",
  "dimensions": {
    "lifecycle": ["设计", "编码"]
  },
  "limit": 10
}
```

**响应:**
```json
{
  "code": 0,
  "data": [
    {
      "id": "doc_001",
      "title": "JWT认证规范",
      "relevance": 95.5,
      "dimensions": { /* ... */ }
    }
  ]
}
```

### 2.7 获取知识图谱数据

```
GET /api/knowledge/graph
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "nodes": [
      {
        "id": "doc_001",
        "type": "knowledge",
        "label": "JWT认证规范",
        "x": 100,
        "y": 200
      }
    ],
    "edges": [
      {
        "from": "doc_001",
        "to": "doc_002",
        "type": "reference"
      }
    ]
  }
}
```

## 3. 数据结构

```python
class KnowledgeDoc(BaseModel):
    id: str
    title: str
    type: str  # project/document
    status: str  # draft/pending/reviewed
    content: str
    dimensions: dict
    favorite: bool
    pinned: bool
    source_task_id: Optional[str]
    created_at: datetime
    updated_at: datetime

class DimensionConfig(BaseModel):
    key: str
    icon: str
    name: str
    tags: List[str]

class GraphNode(BaseModel):
    id: str
    type: str  # module/class/function/knowledge
    label: str
    x: float
    y: float
    metadata: Optional[dict]

class GraphEdge(BaseModel):
    from_id: str
    to_id: str
    type: str  # dependency/reference
    label: Optional[str]
```

## 4. 业务逻辑

### 4.1 文档创建流程

```
1. 验证文档内容
2. 生成文档 ID
3. 保存文档到 SQLite
4. 提取文档向量 (embedding)
5. 存储向量到 ChromaDB
6. 更新知识图谱
7. 返回文档 ID
```

### 4.2 向量检索流程

```
1. 将查询文本转换为向量
2. 在 ChromaDB 中搜索相似向量
3. 根据相关度排序
4. 应用维度过滤
5. 返回搜索结果
```

### 4.3 知识图谱构建流程

```
1. 获取所有知识文档
2. 分析文档间引用关系
3. 构建图结构 (NetworkX)
4. 计算节点布局 (力导向算法)
5. 返回图谱数据
```

### 4.4 知识点提取流程

```
1. 从分析任务获取报告数据
2. 根据用户选择的维度标签
3. 生成知识文档模板
4. 填充报告内容
5. 创建知识文档
```

## 5. ChromaDB 集成

```python
class ChromaDBManager:
    def __init__(self, collection_name: str = "knowledge"):
        self.client = chromadb.Client()
        self.collection = self.client.get_or_create_collection(collection_name)
    
    def add_document(self, doc_id: str, content: str, metadata: dict):
        embedding = self.get_embedding(content)
        self.collection.add(
            ids=[doc_id],
            embeddings=[embedding],
            metadatas=[metadata],
            documents=[content]
        )
    
    def search(self, query: str, limit: int = 10) -> List[dict]:
        query_embedding = self.get_embedding(query)
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit
        )
        return results
    
    def get_embedding(self, text: str) -> List[float]:
        # 使用简单的 embedding 模型或调用外部 API
        return embedding_model.encode(text)
```

## 6. 四维分类配置

```python
DIMENSIONS = {
    "lifecycle": {
        "icon": "🔄",
        "name": "开发生命周期",
        "tags": ["需求", "设计", "编码", "测试", "部署", "运维", "重构"]
    },
    "techStack": {
        "icon": "🛠",
        "name": "技术栈工具链",
        "tags": ["Python", "Go", "JavaScript", "Java", "Rust", "数据库", "DevOps"]
    },
    "abstraction": {
        "icon": "📐",
        "name": "抽象层级",
        "tags": ["系统", "模块", "类", "函数", "算法", "配置"]
    },
    "attribute": {
        "icon": "🎯",
        "name": "知识属性",
        "tags": ["最佳实践", "规范", "教程", "案例", "问题排查", "性能优化"]
    }
}
```

## 7. 错误处理

| 错误码 | 说明 |
|--------|------|
| 2201 | 文档不存在 |
| 2202 | 文档已存在 |
| 2203 | 维度标签无效 |
| 2204 | 搜索失败 |
| 2205 | 向量存储失败 |

## 8. 文件结构

```
backend/
├── api/
│   └── knowledge.py
├── services/
│   └── knowledge_service.py
├── repositories/
│   └── knowledge_repo.py
├── utils/
│   └── chromadb.py
└── models/
    └── knowledge.py
```
