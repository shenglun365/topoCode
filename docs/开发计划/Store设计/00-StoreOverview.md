# Pinia Store 设计总览

> 各 Phase 对应的 Pinia Store 定义，用于前端状态管理

---

## Store 清单

| Store 文件 | 归属 Phase | 用途 |
|-----------|-----------|------|
| `navigation.ts` | Phase 1 | 活动栏页面切换、页面历史 |
| `panel.ts` | Phase 1 | 左/右面板折叠、宽度、可见性 |
| `status.ts` | Phase 1 | 全局状态 (后端/AST/Git/AI/编码/缩放) |
| `theme.ts` | Phase 1 | 主题切换 (dark/light/system) |
| `project.ts` | Phase 2 | 项目列表、选中项目、视图模式、HomeTab 管理 |
| `analysis.ts` | Phase 2 | 分析任务列表、选中任务、报告、筛选 |
| `knowledge.ts` | Phase 3 | 知识文档、图谱数据、四维筛选、文档模式 |
| `coder.ts` | Phase 4 | Session 列表、消息流、加载状态 |
| `agent.ts` | Phase 4 | Agent 任务状态 (WebSocket 实时推送) |
| `settings.ts` | Phase 5 | 模型/Agent/SKILL/通用设置 |

---

## Store 文件结构

```
src/renderer/stores/
├── navigation.ts
├── panel.ts
├── status.ts
├── theme.ts
├── project.ts
├── analysis.ts
├── knowledge.ts
├── coder.ts
├── agent.ts
└── settings.ts
```
