# Phase 4: AI 助手 —— 集成总览

> 组件间协作流程、数据流、路由映射、Service 对接

---

## 1. Phase 目标

提供 AI 对话界面，支持多 Session 管理、上下文检索、Spec 文档生成、Agent 任务调度与状态监控。

---

## 2. 组件清单与职责

| 编号 | 组件 | 设计文档 | 职责 |
|------|------|----------|------|
| 01 | **SessionTabBar** | [01-SessionTabBar.md](01-SessionTabBar.md) | 多 Tab Session 管理 (创建/切换/关闭/重命名) |
| 02 | **ChatFlow** | [02-ChatFlow.md](02-ChatFlow.md) | 对话消息流，SSE 流式显示，发送/停止 |
| 03 | **ChatMessage** | [03-ChatMessage.md](03-ChatMessage.md) | 单个消息气泡 (用户/助手两种样式) |
| 04 | **ContextCard** | [04-ContextCard.md](04-ContextCard.md) | AI 检索到的知识上下文卡片 |
| 05 | **SpecCard** | [05-SpecCard.md](05-SpecCard.md) | AI 生成的 Spec 设计文档摘要卡片 |
| 06 | **TaskStatusCard** | [06-TaskStatusCard.md](06-TaskStatusCard.md) | Agent 任务执行状态卡片 (进度/预估) |
| 07 | **RightPanelTabs** | [07-RightPanelTabs.md](07-RightPanelTabs.md) | 右面板 4 Tab: 代码解析/知识库/Spec/任务配置 |

---

## 3. 组件协作流程

### 3.1 AI 上下文展示策略

| 场景 | ContextCard/SpecCard 展示位置 |
|------|------------------------------|
| **AI 助手页 (/coder)** | 对话流内 inline 展示（AI 回复气泡中嵌入） |
| **知识库 AI 辅助解答** | 右面板展示 |
| **分析报告 AI 辅助解析** | 右面板展示 |

### 3.2 临时会话机制

知识库和分析报告的 AI 问答产生的对话，自动保存为**临时会话**，存放在 AI 助手的 Session 管理中的专用文件夹：

```
Session 列表
├── 当前项目
├── 架构设计
├── ...
├── 📁 会话日志/知识库        ← 知识库 AI 问答产生的临时会话
└── 📁 会话日志/分析报告      ← 分析报告 AI 问答产生的临时会话
```

## 3. 组件协作流程

```
用户操作                    组件响应                         Service
──────────                ──────────                      ──────────
进入 /coder 页面
    │
    ├── LeftPanel: SessionTabBar
    │       │
    │       ├── 初始化: CoderService.listSessions()
    │       │       └── 渲染 Session Tab 列表
    │       │
    │       ├── 新建 Session → CoderService.createSession()
    │       └── 切换 Session → 重新加载 ChatFlow 消息历史
    │
    ├── MainContent: ChatFlow
    │       │
    │       ├── 加载消息: CoderService.getSessionDetail(id)
    │       │       └── 渲染 ChatMessage[] 列表
    │       │
    │       ├── 发送消息
    │       │       │
    │       │       ├── CoderService.sendMessage(SSE 流式)
    │       │       │       │
    │       │       │       ├── 后端: 意图分析 → AST检索 → ChromaDB检索 → 构建Prompt
    │       │       │       │
    │       │       │       └── 流式返回 text/context/spec/task/error 五种消息类型
    │       │       │
    │       │       └── ChatFlow 实时追加消息流
    │       │               ├── text → 渲染文本气泡
    │       │               ├── context → 渲染 ContextCard
    │       │               ├── spec → 渲染 SpecCard
    │       │               └── task → 渲染 TaskStatusCard
    │       │
    │       └── 点击停止 → CoderService.stopGeneration()
    │
    └── RightPanel: RightPanelTabs
            │
            ├── 代码解析 Tab: 当前会话关联的 AST/文件信息
            ├── 知识库 Tab: 检索到的 ContextCard 列表
            ├── Spec Tab: 已生成的 SpecCard 列表
            └── 任务配置 Tab: Agent 任务状态 + 调度参数
```

---

## 4. 数据流

```
┌─────────────────────────────────────────────────────────────┐
│  Pinia stores                                              │
│                                                             │
│  stores/coder.ts                                            │
│    sessions: Session[]              ← CoderService.list()   │
│    activeSession: Session                                    │
│    messages: ChatMessage[]          ← SSE 流式累积          │
│    loading: boolean                                          │
│                                                             │
│  stores/agent.ts  (建议新增)                                 │
│    tasks: AgentTask[]              ← AgentService.list()    │
│    taskStatus: Map<id, AgentTask>  ← WebSocket 实时推送     │
└─────────────────────────────────────────────────────────────┘
```

---

## 5. Service 对接点

| 组件 | 调用 Service | API |
|------|-------------|-----|
| SessionTabBar (列表) | CoderService | `GET /api/v1/coder/sessions` |
| SessionTabBar (创建) | CoderService | `POST /api/v1/coder/sessions` |
| ChatFlow (加载) | CoderService | `GET /api/v1/coder/sessions/{id}` |
| ChatFlow (发送) | CoderService | `POST /api/v1/coder/sessions/{id}/messages` (SSE) |
| ChatFlow (停止) | CoderService | WebSocket `stop` 消息 |
| RightPanelTabs | CoderService | `GET /api/v1/coder/context?session=` |
| ContextCard | KnowledgeService | (间接：CoderService 已合并上下文) |
| TaskStatusCard | AgentService | `GET /api/v1/agent/tasks/{id}/status` + WebSocket |

---

## 6. 路由映射

```
/coder                          → 默认 Session (或空状态引导)
/coder/:sessionId               → 指定 Session 对话
```

---

## 7. 依赖关系

```
Phase 1 (AppShell + LeftPanel + RightPanel)
    │
    └── Phase 4 组件挂载:
              ├── LeftPanel:   SessionTabBar
              ├── MainContent: ChatFlow (ChatMessage[] + ContextCard/SpecCard/TaskStatusCard)
              └── RightPanel:  RightPanelTabs

Phase 3 (知识库)
    │
    └── CoderService 上下文检索依赖 KnowledgeService (ChromaDB 向量搜索)
        和 Phase 2 AnalysisService (AST 缓存)
```
