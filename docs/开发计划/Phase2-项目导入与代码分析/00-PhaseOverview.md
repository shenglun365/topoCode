# Phase 2: 项目导入与代码分析 —— 集成总览

> 组件间协作流程、数据流、路由映射、Service 对接

---

## 1. Phase 目标

提供项目导入入口，管理已导入项目的文件树浏览，以及代码分析任务的创建、执行与结果查看。

---

## 2. 组件清单与职责

| 编号 | 组件 | 设计文档 | 职责 |
|------|------|----------|------|
| 01 | **ProjectCard** | [01-ProjectCard.md](01-ProjectCard.md) | 展示单个项目的名称/语言/文件数/同步状态/分析进度 |
| 02 | **ImportZone** | [02-ImportZone.md](02-ImportZone.md) | 拖拽/选择文件夹导入新项目 |
| 03 | **FileTree** | [03-FileTree.md](03-FileTree.md) | 展示项目目录结构，支持展开/选中文件 |
| 04 | **TaskCard** | [04-TaskCard.md](04-TaskCard.md) | 分析任务卡片，支持收藏/置顶/展开/执行/删除 |
| 05 | **TaskReport** | [05-TaskReport.md](05-TaskReport.md) | 多 Tab 报告视图 (AST/调用链/依赖/数据流/日志) |
| 06 | **ExtractDialog** | [06-ExtractDialog.md](06-ExtractDialog.md) | 从分析结果提取知识点的对话框 |
| 07 | **ProjectImport** | [07-ProjectImport.md](07-ProjectImport.md) | 根组件，管理默认视图 ↔ 项目视图切换 |
| 08 | **HomeTabBar** | [08-HomeTabBar.md](08-HomeTabBar.md) | 项目内多 Tab Card 栏 (文件/任务/报告切换) |

---

## 3. 组件协作流程

```
用户操作                    组件响应                         Service
──────────                ──────────                      ──────────
拖拽文件夹到 ImportZone
    │
    ├── ImportZone 发出 import 事件
    │       │
    │       └── ProjectImport 调用 ProjectService.import()
    │               │
    │               └── 后端解析项目结构 → 返回 ProjectMeta
    │                       │
    │                       └── 更新 Pinia stores/project.ts
    │                               │
    │                               ├── 刷新 ProjectCardGrid (项目列表)
    │                               └── 自动进入 ProjectView

点击 ProjectCard
    │
    ├── ProjectCard 发出 select 事件
    │       │
    │       └── ProjectImport 切换 viewMode
    │               │
    │               ├── FileTree 视图: 调用 ProjectService.getDetail()
    │               │       └── 加载文件树 → 渲染 FileTree
    │               │
    │               └── Task 列表视图: 调用 AnalysisService.list()
    │                       └── 加载任务列表 → 渲染 TaskCard[]

选中文件 → 右键创建分析任务
    │
    ├── 调用 AnalysisService.create({ type, files })
    │       │
    │       └── 后端异步执行 → WebSocket 推送进度
    │               │
    │               └── TaskCard 实时更新状态/进度
    │
    └── 点击任务卡片
            │
            └── ProjectImport 切换右侧为 TaskReport
                    │
                    ├── TaskReport 调用 AnalysisService.getReport(taskId)
                    │       └── 按 activeTab 渲染对应视图
                    │
                    └── 点击「提取知识点」
                            └── 打开 ExtractDialog
                                    └── 选择四维标签 → 调用 KnowledgeService.create()
```

---

## 4. 数据流

```
┌─────────────────────────────────────────────────────────────┐
│  Pinia stores                                              │
│                                                             │
│  stores/project.ts                                          │
│    projects: ProjectMeta[]        ← ProjectService.list()   │
│    selectedProject: ProjectMeta                             │
│    viewMode: 'files' | 'tasks'                              │
│                                                             │
│  stores/analysis.ts  (建议新增)                              │
│    tasks: AnalysisTask[]          ← AnalysisService.list()  │
│    selectedTask: AnalysisTask                                │
│    report: TaskReportData         ← AnalysisService.getReport│
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Service 对接点

| 组件 | 调用 Service | API |
|------|-------------|-----|
| ImportZone | ProjectService | `POST /api/v1/projects/import` |
| ProjectImport (default) | ProjectService | `GET /api/v1/projects` |
| FileTree | ProjectService | `GET /api/v1/projects/{id}` |
| TaskCard (列表) | AnalysisService | `GET /api/v1/tasks?project_id=` |
| TaskCard (操作) | AnalysisService | `POST /api/v1/tasks` (创建), `DELETE` |
| TaskReport | AnalysisService | `GET /api/v1/tasks/{id}/report` |
| ExtractDialog | KnowledgeService | `POST /api/v1/knowledge/docs` |

---

## 6. 路由映射

```
/home                           → 默认视图 (ProjectCardGrid + ImportZone)
/home/:projectId                → 项目视图 (FileTree / TaskList + TaskReport)
/home/:projectId/files          → 文件树视图
/home/:projectId/tasks          → 任务列表视图
/home/:projectId/tasks/:taskId  → 任务报告视图
```

---

## 7. 依赖关系

```
Phase 1 (AppShell + LeftPanel + RightPanel)
    │
    └── Phase 2 组件挂载在 LeftPanel / MainContent / RightPanel 区域
              │
              ├── LeftPanel:   FileTree 或 TaskCard 列表
              ├── MainContent: ProjectCardGrid (默认) 或 TaskReport
              └── RightPanel:  项目详情 (选中 ProjectCard 时)
```
