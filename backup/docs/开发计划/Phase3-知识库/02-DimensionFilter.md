# DimensionFilter 组件设计

> 四维折叠筛选栏，按四个维度筛选知识文档

---

## 1. 组件职责

- 展示四个分类维度
- 支持展开/折叠每个维度
- 提供标签复选筛选

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ 🔄 开发生命周期 [7]  [▼]                │
│ ☑需求 ☑设计 ☑编码 ☑测试 ☑部署 ☑运维 ☑重构│
├─────────────────────────────────────────┤
│ 🛠 技术栈工具链 [6]     [▶]             │
├─────────────────────────────────────────┤
│ 📐 抽象层级 [6]         [▶]             │
├─────────────────────────────────────────┤
│ 🎯 知识属性 [6]         [▶]             │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `dimensions` | `Dimension[]` | `[]` | 维度数据 |
| `selectedTags` | `Record<string, string[]>` | `{}` | 已选标签 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `toggle-dimension` | `{ dimension: string }` | 展开/折叠维度 |
| `toggle-tag` | `{ dimension: string, tag: string }` | 切换标签选择 |
| `clear` | `void` | 清除所有筛选 |

### 数据结构

```typescript
interface Dimension {
  key: string;
  icon: string;
  name: string;
  tags: string[];
}

interface SelectedTags {
  [dimension: string]: string[];
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `DimensionItem` | 单个维度 |
| `TagChip` | 标签芯片 |

## 5. 交互逻辑

- 点击维度标题 → 展开/折叠标签列表
- 点击标签 → 切换选中状态
- 选中标签 → 过滤知识文档列表
- 点击"清除" → 取消所有筛选

## 6. 样式规范

- 维度标题：11px，加粗，大写
- 标签芯片：小型，圆角，颜色根据维度区分
- 展开/折叠箭头：▶ / ▼
- 选中标签：高亮背景色

## 7. 文件结构

```
src/components/knowledge/
├── DimensionFilter.vue
├── DimensionItem.vue
└── TagChip.vue
```
