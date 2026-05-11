# AnalysisService 设计

> 代码分析服务，负责 AST 解析、调用链、依赖分析、数据流分析

---

## 1. 组件职责

- AST 解析 (全量/增量)
- 调用链分析
- 依赖关系分析
- 数据流分析
- 分析任务管理

## 2. API 接口

### 2.1 创建分析任务

```
POST /api/analysis/task
```

**请求:**
```json
{
  "projectId": "proj_001",
  "type": "full-parse",
  "scope": "src/**",
  "trigger": "manual"
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

### 2.2 获取任务列表

```
GET /api/analysis/tasks?projectId={projectId}
```

### 2.3 获取任务详情

```
GET /api/analysis/task/{taskId}
```

### 2.4 获取任务报告

```
GET /api/analysis/task/{taskId}/report
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "task": { /* 任务元数据 */ },
    "ast": { /* AST 树 */ },
    "callChain": [ /* 调用链 */ ],
    "dependencies": { /* 依赖图 */ },
    "dataFlow": { /* 数据流 */ },
    "logs": [ /* 执行日志 */ ]
  }
}
```

### 2.5 删除任务

```
DELETE /api/analysis/task/{taskId}
```

## 3. 数据结构

```python
class AnalysisTask(BaseModel):
    id: str
    project_id: str
    name: str
    type: str  # full-parse/ast-gen/call-chain/dataflow/dep-analysis
    status: str  # done/running/pending/failed
    scope: str
    trigger: str  # auto/manual
    progress: int
    files_parsed: int
    files_total: int
    last_run: Optional[datetime]
    duration: Optional[str]
    favorite: bool
    pinned: bool
    tags: List[str]
    created_at: datetime
    updated_at: datetime

class ASTNode(BaseModel):
    type: str
    name: str
    range: dict  # {start: {line, column}, end: {line, column}}
    children: List['ASTNode']

class CallChainNode(BaseModel):
    id: str
    name: str
    target: str
    callers: List[str]
    callees: List[str]

class DependencyGraph(BaseModel):
    nodes: List[dict]
    edges: List[dict]

class DataFlowGraph(BaseModel):
    nodes: List[dict]
    edges: List[dict]
```

## 4. 业务逻辑

### 4.1 AST 解析流程

```
1. 根据项目语言选择 Tree-sitter 解析器
2. 扫描项目文件 (根据 scope)
3. 逐个文件解析 AST
4. 缓存 AST 到 SQLite
5. 更新任务进度
6. 返回解析结果
```

### 4.2 增量解析流程

```
1. 获取变更文件列表
2. 对比文件哈希
3. 只重新解析变更文件
4. 更新 AST 缓存
5. 更新依赖关系
```

### 4.3 调用链分析流程

```
1. 从 AST 提取函数定义
2. 提取函数调用关系
3. 构建调用图 (NetworkX)
4. 分析调用路径
5. 返回调用链数据
```

### 4.4 依赖分析流程

```
1. 从 AST 提取 import/require 语句
2. 构建模块依赖图
3. 分析循环依赖
4. 返回依赖数据
```

## 5. Tree-sitter 集成

```python
class TreeSitterParser:
    def __init__(self, language: str):
        self.language = language
        self.parser = get_parser(language)
    
    def parse_file(self, file_path: str) -> ASTNode:
        source = read_file(file_path)
        tree = self.parser.parse(source)
        return ast_to_dict(tree.root_node)
    
    def parse_incremental(self, file_path: str, old_tree: Tree) -> ASTNode:
        source = read_file(file_path)
        new_tree = self.parser.parse(source, old_tree)
        return ast_to_dict(new_tree.root_node)
```

## 6. 任务执行策略

| 任务类型 | 执行方式 | 并发数 |
|---------|---------|--------|
| 全量解析 | 异步任务 (Celery) | CPU 核心数 |
| 增量解析 | 同步 | 1 |
| 调用链分析 | 异步任务 | 1 |
| 依赖分析 | 异步任务 | 1 |
| 数据流分析 | 异步任务 | 1 |

## 7. 错误处理

| 错误码 | 说明 |
|--------|------|
| 2101 | 项目不存在 |
| 2102 | 解析器不存在 |
| 2103 | 解析失败 |
| 2104 | 任务已存在 |
| 2105 | 任务执行失败 |

## 8. 文件结构

```
backend/
├── api/
│   └── analysis.py
├── services/
│   └── analysis_service.py
├── repositories/
│   └── task_repo.py
├── utils/
│   └── tree_sitter.py
└── models/
    └── task.py
```
