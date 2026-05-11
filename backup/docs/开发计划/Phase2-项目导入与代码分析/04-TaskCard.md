# TaskCard 组件设计

> 分析任务卡片，展示任务状态和操作

---

## 1. 组件职责

- 展示任务基本信息 (名称/状态/进度)
- 提供任务操作入口 (运行/编辑/删除)
- 支持收藏/置顶标记

## 2. 布局结构

```
┌─────────────────────────────────┐
│ 全量解析          [完成] [★] [📌]│
│                                 │
│ topoOne-ui  ·  Python  ·  自动  │
│ ████████████████████  128/128   │
│ 2026-05-01 09:30  ·  2.3s      │
│                                 │
│ [运行] [编辑] [删除]            │
└─────────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task` | `AnalysisTask` | — | 任务数据 |
| `expanded` | `boolean` | `false` | 是否展开详情 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `run` | `{ taskId: string }` | 运行任务 |
| `edit` | `{ taskId: string }` | 编辑任务 |
| `delete` | `{ taskId: string }` | 删除任务 |
| `toggle-fav` | `{ taskId: string }` | 切换收藏 |
| `toggle-pin` | `{ taskId: string }` | 切换置顶 |
| `toggle-expand` | `{ taskId: string }` | 展开/折叠 |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `TaskHeader` | 任务标题栏 |
| `TaskProgress` | 进度条 |
| `TaskMeta` | 任务元信息 |
| `TaskActions` | 操作按钮组 |

## 5. 数据结构

```typescript
interface AnalysisTask {
  id: string;
  name: string;
  type: 'full-parse' | 'ast-gen' | 'call-chain' | 'dataflow' | 'dep-analysis';
  status: 'done' | 'running' | 'pending' | 'failed';
  project: string;
  language: string;
  trigger: 'auto' | 'manual';
  progress: number;       // 0–100
  filesParsed: number;
  filesTotal: number;
  lastRun?: Date;
  duration?: string;
  favorite: boolean;
  pinned: boolean;
  tags: string[];
}
```

## 6. 交互逻辑

- 点击卡片主体 → 展开/折叠详情
- 点击运行按钮 → emit run 事件
- 点击星标 → 切换收藏状态
- 点击图钉 → 切换置顶状态
- 悬停显示操作按钮

## 7. 样式规范

- 卡片圆角：8px
- 状态标签颜色：完成=绿色，执行中=黄色，等待=灰色，失败=红色
- 进度条：4px 高度
- 收藏/置顶图标：右上角，金色/蓝色

## 8. 文件结构

```
src/components/analysis/
├── TaskCard.vue
├── TaskHeader.vue
├── TaskProgress.vue
├── TaskMeta.vue
└── TaskActions.vue
```
