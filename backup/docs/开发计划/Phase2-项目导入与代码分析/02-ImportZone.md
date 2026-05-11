# ImportZone 组件设计

> 项目导入区域，支持拖拽和文件夹选择

---

## 1. 组件职责

- 提供拖拽导入入口
- 提供文件夹选择按钮
- 展示支持的语言列表

## 2. 布局结构

```
┌─────────────────────────────────────┐
│                                     │
│           拖拽项目文件夹到此处        │
│                                     │
│           或  [选择文件夹]           │
│                                     │
│  支持: Python / Go / JavaScript / Java│
│                                     │
└─────────────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `supportedLangs` | `string[]` | `['Python','Go','JS','Java']` | 支持的语言 |
| `disabled` | `boolean` | `false` | 是否禁用 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `import` | `{ path: string }` | 导入项目 |
| `drag-over` | `boolean` | 拖拽状态变化 |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `LangBadge` | 语言标签 |

## 5. 数据结构

```typescript
// 导入事件载荷
interface ImportPayload {
  path: string;                    // 项目文件夹路径
}

// 拖拽状态
type DragState = 'idle' | 'dragover' | 'processing';
```

## 6. 交互逻辑

- 拖拽文件/文件夹到区域 → 高亮边框 → 释放触发 import
- 点击"选择文件夹" → 调用 Electron dialog → 获取路径 → emit import
- 拖拽离开时重置高亮

## 7. 样式规范

- 虚线边框：2px dashed `var(--border)`
- 拖拽高亮：边框变 `var(--accent)`，背景变浅
- 居中布局，最小高度 120px

## 8. 文件结构

```
src/components/project/
├── ImportZone.vue
└── LangBadge.vue
```
