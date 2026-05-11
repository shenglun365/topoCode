# Phase 3: 知识库 —— 集成总览

> 组件间协作流程、数据流、路由映射、Service 对接

---

## 1. Phase 目标

管理从代码分析中提取的结构化知识，支持四维分类检索、知识图谱可视化、Markdown 文档编辑/预览，以及代码执行流程动画播放。

---

## 2. 组件清单与职责

| 编号 | 组件 | 设计文档 | 职责 |
|------|------|----------|------|
| 01 | **KnowledgeGraph** | [01-KnowledgeGraph.md](01-KnowledgeGraph.md) | SVG 力导向图谱，展示知识节点与关系 |
| 02 | **DimensionFilter** | [02-DimensionFilter.md](02-DimensionFilter.md) | 四维折叠筛选栏 (生命周期/技术栈/抽象层级/知识属性) |
| 03 | **KnowledgeCard** | [03-KnowledgeCard.md](03-KnowledgeCard.md) | 知识文档卡片，展示标题/描述/标签/状态 |
| 04 | **DocEditor** | [04-DocEditor.md](04-DocEditor.md) | Markdown 编辑器 (Monaco)，edit/view/preview 三模式 |
| 05 | **AnimationPlayer** | [05-AnimationPlayer.md](05-AnimationPlayer.md) | 代码执行流程动画播放器 |
| 06 | **CategoryManager** | [06-CategoryManager.md](06-CategoryManager.md) | 四维分类管理 Tab，展示和管理各维度标签 |

---

## 3. 组件协作流程

```
用户操作                    组件响应                         Service
──────────                ──────────                      ──────────
进入 /knowledge 页面
    │
    ├── LeftPanel: DimensionFilter + KnowledgeCard 列表
    │       │
    │       ├── KnowledgeService.list({ dimensions, page })
    │       │       └── 返回分页列表 → 渲染 KnowledgeCard[]
    │       │
    │       └── 点击筛选标签
    │               └── DimensionFilter 发出 toggle-tag
    │                       └── 重新请求列表 → 更新 KnowledgeCard[]
    │
    ├── MainContent: 知识图谱 / 文档编辑器
    │       │
    │       ├── KnowledgeGraph (默认视图)
    │       │       │
    │       │       ├── KnowledgeService.getGraph()
    │       │       │       └── 返回 nodes[] + edges[] → D3 渲染 SVG
    │       │       │
    │       │       └── 点击节点
    │       │               └── emit node-click → RightPanel 显示详情
    │       │
    │       └── DocEditor (打开文档后)
    │               │
    │               ├── KnowledgeService.getDetail(docId)
    │               │       └── 加载 markdown 内容
    │               │
    │               ├── 编辑模式下 save → KnowledgeService.update()
    │               └── 预览模式下切换 mode='preview'
    │
    └── RightPanel: 知识点详情 / 动画播放
            │
            ├── 知识点详情 (从 KnowledgeCard 或 Graph 选中)
            │       └── 展示四维标签 + 关联关系 + 来源分析
            │
            └── AnimationPlayer (从 DocEditor 触发)
                    └── 播放代码执行步骤动画
```

---

## 4. 数据流

```
┌─────────────────────────────────────────────────────────────┐
│  Pinia stores                                              │
│                                                             │
│  stores/knowledge.ts                                        │
│    docs: KnowledgeDoc[]             ← KnowledgeService.list()│
│    selectedDoc: KnowledgeDoc                                │
│    graph: { nodes[], edges[] }     ← KnowledgeService.getGraph│
│    filter: { selectedTags }        ← DimensionFilter emit   │
│    docMode: 'edit' | 'view' | 'preview'                     │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Service 对接点

| 组件 | 调用 Service | API |
|------|-------------|-----|
| KnowledgeCard (列表) | KnowledgeService | `GET /api/v1/knowledge/docs` |
| DimensionFilter | KnowledgeService | `GET /api/v1/knowledge/docs?dimensions=` |
| KnowledgeGraph | KnowledgeService | `GET /api/v1/knowledge/graph` |
| DocEditor (打开) | KnowledgeService | `GET /api/v1/knowledge/docs/{id}` |
| DocEditor (保存) | KnowledgeService | `PUT /api/v1/knowledge/docs/{id}` |

---

## 6. 路由映射

```
/knowledge                      → 默认：图谱视图 + 左侧筛选 + 右侧详情
/knowledge/graph                → 图谱全屏
/knowledge/docs                 → 文档列表模式
/knowledge/docs/:docId          → 文档编辑器 (DocEditor)
/knowledge/docs/:docId/animate  → 动画播放器 (从文档进入)
```

---

## 7. 依赖关系

```
Phase 1 (AppShell + LeftPanel + RightPanel)
    │
    └── Phase 3 组件挂载:
              ├── LeftPanel:   DimensionFilter + KnowledgeCard 列表
              ├── MainContent: KnowledgeGraph 或 DocEditor
              └── RightPanel:  知识点详情 或 AnimationPlayer

Phase 2 (ExtractDialog → KnowledgeService)
    │
    └── 提取的知识点直接写入知识库，Phase 3 可立即检索
```
