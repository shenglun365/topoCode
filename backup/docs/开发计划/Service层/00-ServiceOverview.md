# Service 层概述

> 后端服务层，提供业务逻辑和数据持久化

---

## 1. 架构定位

```
┌─────────────────────────────────────────────────────────┐
│ 前端 (Electron + Vue 3)                                 │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │ 组件层   │  │ 组件层   │  │ 组件层   │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│        │             │             │                   │
│  ┌──────────────────────────────────────────┐          │
│  │        Pinia Store (状态管理)            │          │
│  └──────────────────────────────────────────┘          │
│        │                                               │
│  ┌──────────────────────────────────────────┐          │
│  │        API Client (HTTP/WebSocket)       │          │
│  └──────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────────────────────────────────┐
│ 后端 (Python 3.12 + FastAPI)                            │
│                                                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │Router层  │  │Service层 │  │  数据层   │             │
│  └──────────┘  └──────────┘  └──────────┘             │
│        │             │             │                   │
│  ┌──────────────────────────────────────────┐          │
│  │        外部依赖                           │          │
│  │  Tree-sitter / ChromaDB / SQLite / NetworkX│        │
│  └──────────────────────────────────────────┘          │
└─────────────────────────────────────────────────────────┘
```

## 2. Service 列表

| Service | 职责 | 对应 Phase |
|---------|------|-----------|
| ProjectService | 项目管理 (导入/同步/元数据) | Phase 2 |
| AnalysisService | 代码分析 (AST/调用链/依赖/数据流) | Phase 2 |
| KnowledgeService | 知识库管理 (文档/分类/检索) | Phase 3 |
| CoderService | AI 助手服务 (对话/Session/上下文) | Phase 4 |
| ModelService | 模型路由 (本地/云端/负载均衡) | Phase 5 |
| AgentService | Agent 调度 (CLI 工具/任务监控) | Phase 4/5 |

## 3. 技术栈

| 层级 | 技术 |
|------|------|
| 框架 | FastAPI + uvicorn |
| ORM | SQLAlchemy (SQLite) |
| 向量数据库 | ChromaDB |
| 解析器 | Tree-sitter |
| 图计算 | NetworkX |
| 任务队列 | Celery + Redis (可选) |
| 实时通信 | WebSocket |

## 4. API 设计规范

- RESTful API + WebSocket 混合
- 统一响应格式：
  ```json
  {
    "code": 0,
    "message": "success",
    "data": {}
  }
  ```
- 错误码规范：
  - 0: 成功
  - 1xxx: 参数错误
  - 2xxx: 业务错误
  - 3xxx: 系统错误

## 5. 文件结构

```
backend/
├── main.py                 # FastAPI 入口
├── api/                    # 路由层
│   ├── __init__.py
│   ├── project.py
│   ├── analysis.py
│   ├── knowledge.py
│   ├── coder.py
│   ├── model.py
│   └── agent.py
├── services/               # 服务层
│   ├── __init__.py
│   ├── project_service.py
│   ├── analysis_service.py
│   ├── knowledge_service.py
│   ├── coder_service.py
│   ├── model_service.py
│   └── agent_service.py
├── models/                 # 数据模型
│   ├── __init__.py
│   ├── project.py
│   ├── task.py
│   ├── knowledge.py
│   └── session.py
├── repositories/           # 数据访问层
│   ├── __init__.py
│   ├── project_repo.py
│   ├── task_repo.py
│   ├── knowledge_repo.py
│   └── session_repo.py
├── utils/                  # 工具函数
│   ├── tree_sitter.py
│   ├── chromadb.py
│   └── networkx.py
└── config/                 # 配置
    ├── __init__.py
    └── settings.py
```
