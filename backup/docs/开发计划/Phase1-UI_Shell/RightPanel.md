# RightPanel 组件设计

> 右面板：页面详情/上下文面板

---

## 1. 组件定位

UI Shell 右侧可变内容面板，展示当前选中项的详情或提供上下文操作。

```
┌──────────────┐
│ 详情 [×]     │  ← Header
├──────────────┤
│              │
│ 动态内容区    │  ← Body (按页面注入)
│              │
└──────────────┘
  280px wide
```

---

## 2. 子组件结构

```
RightPanel
├── RightPanelHeader
│   ├── PanelTitle        ← 标题 (按页面变化)
│   └── CollapseBtn       ← 收起按钮
├── RightPanelBody        ← 动态内容容器
│   └── <slot />          ← 由页面组件注入
└── RightPanelResizeHandle ← 拖拽调整宽度 (可选)
```

---

## 3. Props / Emits / Slots

### RightPanel

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| `visible` | `boolean` | `true` | 面板可见性 |
| `width` | `number` | `280` | 面板宽度 |
| `minWidth` | `number` | `220` | 最小宽度 |
| `maxWidth` | `number` | `500` | 最大宽度 |
| `title` | `string` | `'详情'` | 面板标题 |
| `resizable` | `boolean` | `false` | 是否可拖拽调整宽度 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `toggle` | - | 切换面板可见性 |
| `resize` | `{ width: number }` | 宽度变化 |

| Slots | 说明 |
|-------|------|
| `default` | 面板内容 |
| `header-actions` | 标题栏额外按钮 |

---

## 4. 页面内容映射

| 页面 | 标题 | 内容 |
|------|------|------|
| home | 提示 | 项目使用说明 |
| analysis | 详情 | 任务详情 (状态/标签/操作) |
| knowledge | 过滤器 | 图谱统计 + 节点类型筛选 |
| coder | 上下文 | 4 Tab: 代码解析/知识库/Spec/任务配置 |
| user | - | 不使用右面板 |

---

## 5. 状态管理

复用 `stores/panel.ts` 中的 `right` 状态 (见 LeftPanel 文档)。

---

## 6. 交互逻辑

与 LeftPanel 对称:
- 页面切换时注入对应内容
- 收起/展开动画
- 可选拖拽调整宽度

---

## 7. 文件结构

```
src/components/shell/
├── RightPanel.vue          ← 根组件
├── RightPanelHeader.vue    ← 标题栏
└── index.ts
```

---

## 8. 与原型对照

| 原型实现 | Vue 组件方案 |
|----------|-------------|
| `rightPanelTemplates` 对象 | 独立 Vue 组件 |
| `updateRightPanel()` 注入 | `<component :is="">` 动态组件 |
| 固定 280px | 可配置 + 可选拖拽 |
