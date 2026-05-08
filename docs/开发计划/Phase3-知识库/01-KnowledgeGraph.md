# KnowledgeGraph 组件设计

> 知识图谱，可视化展示代码节点和知识点的关联关系

---

## 1. 组件职责

- 渲染知识图谱 (节点/边)
- 支持图谱交互 (拖拽/缩放/点击)
- 提供图例和搜索功能

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ [适配] [放大] [缩小] [重置] [导出 PNG]  │ ← 工具栏
│ [搜索节点...]                    [图例] │
├─────────────────────────────────────────┤
│                                         │
│         [SVG 画布]                       │
│                                         │
│         ● 模块                           │
│         □ 类                             │
│         △ 函数                           │
│         ◇ 知识点                         │
│                                         │
│         ●────● 依赖关系                  │
│         ·····  引用关系                  │
│                                         │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `nodes` | `GraphNode[]` | `[]` | 节点数据 |
| `edges` | `GraphEdge[]` | `[]` | 边数据 |
| `selectedNode` | `string` | `null` | 选中节点 ID |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `node-click` | `{ nodeId: string }` | 点击节点 |
| `zoom` | `{ level: number }` | 缩放变化 |

### 数据结构

```typescript
interface GraphNode {
  id: string;
  type: 'module' | 'class' | 'function' | 'knowledge';
  label: string;
  x: number;
  y: number;
  metadata?: Record<string, any>;
}

interface GraphEdge {
  from: string;
  to: string;
  type: 'dependency' | 'reference';
  label?: string;
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `GraphToolbar` | 工具栏 |
| `GraphCanvas` | SVG 画布 |
| `GraphNode` | 单个节点 |
| `GraphEdge` | 单个边 |
| `GraphLegend` | 图例 |
| `GraphSearch` | 节点搜索 |

## 5. 交互逻辑

- 拖拽节点：鼠标拖拽移动节点位置
- 缩放：滚轮缩放，工具栏按钮缩放
- 点击节点：高亮选中，右面板显示详情
- 搜索节点：输入过滤，高亮匹配节点
- 导出 PNG：将 SVG 导出为图片

## 6. 样式规范

- 节点形状：模块=圆形，类=方形，函数=三角形，知识点=菱形
- 节点大小：24px-40px 根据类型
- 边样式：依赖=实线箭头，引用=虚线箭头
- 颜色：根据节点类型区分

## 7. 文件结构

```
src/components/knowledge/
├── KnowledgeGraph.vue
├── GraphToolbar.vue
├── GraphCanvas.vue
├── GraphNode.vue
├── GraphEdge.vue
├── GraphLegend.vue
└── GraphSearch.vue
```
