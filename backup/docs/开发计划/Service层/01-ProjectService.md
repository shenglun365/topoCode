# ProjectService 设计

> 项目管理服务，负责项目导入、同步和元数据管理

---

## 1. 组件职责

- 项目导入 (文件夹扫描/语言识别)
- 项目同步 (文件变更检测)
- 项目元数据管理
- 项目删除/清理

## 2. API 接口

### 2.1 导入项目

```
POST /api/project/import
```

**请求:**
```json
{
  "path": "/home/user/projects/topoOne-ui"
}
```

**响应:**
```json
{
  "code": 0,
  "data": {
    "id": "proj_001",
    "name": "topoOne-ui",
    "language": "Python",
    "fileCount": 128,
    "syncStatus": "synced",
    "analysisProgress": 0
  }
}
```

### 2.2 获取项目列表

```
GET /api/projects
```

**响应:**
```json
{
  "code": 0,
  "data": [
    {
      "id": "proj_001",
      "name": "topoOne-ui",
      "path": "/home/user/projects/topoOne-ui",
      "language": "Python",
      "fileCount": 128,
      "lastModified": "2026-05-01T09:30:00Z",
      "syncStatus": "synced",
      "analysisProgress": 100
    }
  ]
}
```

### 2.3 获取项目详情

```
GET /api/project/{projectId}
```

### 2.4 同步项目

```
POST /api/project/{projectId}/sync
```

### 2.5 删除项目

```
DELETE /api/project/{projectId}
```

## 3. 数据结构

```python
class ProjectMeta(BaseModel):
    id: str
    name: str
    path: str
    language: str
    file_count: int
    last_modified: datetime
    sync_status: str  # synced/changed/error
    analysis_progress: int  # 0-100
    created_at: datetime
    updated_at: datetime
```

## 4. 业务逻辑

### 4.1 项目导入流程

```
1. 验证路径合法性
2. 扫描项目文件
3. 识别项目语言 (根据文件扩展名/配置文件)
4. 统计文件数量
5. 创建项目元数据
6. 初始化 AST 缓存
7. 返回项目 ID
```

### 4.2 语言识别规则

| 语言 | 标识文件 | 扩展名 |
|------|---------|--------|
| Python | requirements.txt, setup.py, pyproject.toml | .py |
| Go | go.mod | .go |
| JavaScript | package.json | .js, .jsx, .ts, .tsx |
| Java | pom.xml, build.gradle | .java |

### 4.3 文件同步流程

```
1. 扫描文件变更 (watchdog)
2. 对比文件哈希
3. 更新变更文件
4. 增量更新 AST 缓存
5. 更新同步状态
```

## 5. 数据访问

```python
class ProjectRepository:
    def create(self, project: ProjectMeta) -> str
    def get_by_id(self, project_id: str) -> ProjectMeta
    def get_all(self) -> List[ProjectMeta]
    def update(self, project_id: str, updates: dict)
    def delete(self, project_id: str)
```

## 6. 错误处理

| 错误码 | 说明 |
|--------|------|
| 2001 | 路径不存在 |
| 2002 | 路径不是目录 |
| 2003 | 项目已存在 |
| 2004 | 不支持的语言 |
| 2005 | 扫描失败 |

## 7. 文件结构

```
backend/
├── api/
│   └── project.py              # 路由
├── services/
│   └── project_service.py      # 业务逻辑
├── repositories/
│   └── project_repo.py         # 数据访问
└── models/
    └── project.py              # 数据模型
```
