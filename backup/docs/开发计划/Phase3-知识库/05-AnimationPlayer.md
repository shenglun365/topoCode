# AnimationPlayer 组件设计

> 动画播放器，展示代码执行流程动画

---

## 1. 组件职责

- 播放代码执行流程动画
- 支持播放/暂停/单步/重置
- 高亮当前执行的代码行

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ [▶ 播放] [⏸ 暂停] [⏭ 单步] [⏮ 重置]   │
│ ████████████░░░░░░░░░░  45%            │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ 1  def foo():│  │  数据流图     │    │
│  │ 2    x = 1   │  │              │    │
│  │ 3    y = 2   │  │  [x=1] ──→   │    │
│  │ 4    return  │  │       [y=2]  │    │
│  │ 5            │  │              │    │
│  │ 6  result =  │  │  当前步骤: 3  │    │
│  │ 7  print()   │  │              │    │
│  └──────────────┘  └──────────────┘    │
│   ← 代码区         ← 可视化区           │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `animation` | `AnimationData` | - | 动画数据 |
| `speed` | `number` | `1` | 播放速度 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `play` | `void` | 播放 |
| `pause` | `void` | 暂停 |
| `step` | `void` | 单步执行 |
| `reset` | `void` | 重置 |
| `speed-change` | `{ speed: number }` | 速度变化 |

### 数据结构

```typescript
interface AnimationData {
  id: string;
  title: string;
  steps: AnimationStep[];
  code: string;
}

interface AnimationStep {
  id: number;
  line: number;        // 代码行号
  description: string; // 步骤描述
  state: Record<string, any>;  // 变量状态
  visualization: string;  // 可视化数据
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `PlayerControls` | 播放控制栏 |
| `CodeHighlighter` | 代码高亮区 |
| `VisualizationArea` | 可视化区 |
| `StepIndicator` | 步骤指示器 |

## 5. 交互逻辑

- 播放：自动按步骤执行动画
- 暂停：暂停在当前步骤
- 单步：执行下一步
- 重置：回到初始状态
- 速度调节：0.5x, 1x, 1.5x, 2x

## 6. 样式规范

- 控制栏：底部固定
- 代码高亮：当前行高亮背景
- 可视化区：SVG/Canvas 渲染
- 进度条：4px 高度

## 7. 文件结构

```
src/components/knowledge/
├── AnimationPlayer.vue
├── PlayerControls.vue
├── CodeHighlighter.vue
├── VisualizationArea.vue
└── StepIndicator.vue
```
