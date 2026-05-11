# TaskStatusCard 组件设计

> 任务状态卡片，展示 AI 调度的任务执行状态

---

## 1. 组件职责

- 展示任务执行状态
- 提供任务操作入口
- 展示任务进度

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ 🔧 代码生成任务            [执行中]      │
│                                         │
│ Agent: qwen-code                        │
│ 状态: 执行中  ·  进度: 65%              │
│ ████████████████░░░░░░  13/20          │
│                                         │
│ 开始时间: 10:30  ·  预计剩余: 2min      │
│                                         │
│ [查看日志] [停止]                       │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task` | `AgentTask` | - | 任务数据 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `view-log` | `{ taskId: string }` | 查看日志 |
| `stop` | `{ taskId: string }` | 停止任务 |

### 数据结构

```typescript
interface AgentTask {
  id: string;
  name: string;
  agent: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  progress: number;       // 0-100
  currentStep: number;
  totalSteps: number;
  startTime?: Date;
  endTime?: Date;
  estimatedRemaining?: string;
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `TaskHeader` | 任务标题栏 |
| `TaskProgress` | 进度条 (复用) |
| `TaskMeta` | 任务元信息 |
| `TaskActions` | 操作按钮 |

## 5. 交互逻辑

- 状态实时更新 (WebSocket 推送)
- 点击"查看日志" → 打开日志面板
- 点击"停止" → 终止任务执行
- 状态颜色：执行中=黄色，完成=绿色，失败=红色

## 6. 样式规范

- 卡片圆角：8px
- 进度条：4px 高度
- 状态标签：小型 badge

## 7. 文件结构

```
src/components/coder/
├── TaskStatusCard.vue
├── TaskHeader.vue
├── TaskMeta.vue
└── TaskActions.vue
```
