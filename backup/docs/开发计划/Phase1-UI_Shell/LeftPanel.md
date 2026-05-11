# LeftPanel 组件设计

> 左面板：页面上下文列表容器

---

## 1. 组件定位

UI Shell 左侧可变内容面板，由当前页面动态注入内容。

```
┌──────────────┐
│ 面板标题 [×] │  ← Header
├──────────────┤
│              │
│ 动态内容区    │  ← Body (按页面注入)
│              │
│              │
└──────────────┘
  240px wide
```

---

## 2. 子组件结构

```
LeftPanel
├── LeftPanelHeader
│   ├── PanelTitle        ← 标题 (按页面变化)
│   ├── PanelActions      ← 操作按钮 (刷新/折叠)
│   └── CollapseBtn       ← 收起按钮
├── LeftPanelBody         ← 动态内容容器
│   └── <slot />          ← 由页面组件注入
└── LeftPanelResizeHandle ← 拖拽调整宽度 (可选)
```

---

## 3. Props / Emits / Slots

### LeftPanel

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| `visible` | `boolean` | `true` | 面板可见性 |
| `width` | `number` | `240` | 面板宽度 (px) |
| `minWidth` | `number` | `180` | 最小宽度 |
| `maxWidth` | `number` | `400` | 最大宽度 |
| `title` | `string` | `''` | 面板标题 |
| `resizable` | `boolean` | `false` | 是否可拖拽调整宽度 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `toggle` | - | 切换面板可见性 |
| `resize` | `{ width: number }` | 宽度变化 |

| Slots | 说明 |
|-------|------|
| `default` | 面板内容 (由页面组件注入) |
| `actions` | 标题栏操作按钮 |

---

## 4. 页面内容模板

每个页面注入不同的左面板内容:

| 页面 | 标题 | 内容模板 |
|------|------|----------|
| home | 项目列表 | 项目卡片 + 搜索 |
| home-files | 文件树 | 文件树 (展开/折叠) |
| home-tasks | 任务列表 | 项目内任务卡片 |
| analysis | 任务筛选 | 收藏/置顶/分组/标签 |
| knowledge | 知识分类 | 置顶/收藏/项目/文档 |
| coder | AI 助手 | 对话分组 + 搜索 |
| user | 设置导航 | 设置项列表 |

---

## 5. 状态管理 (Pinia)

```typescript
// stores/panel.ts
interface PanelState {
  left: {
    visible: boolean;
    width: number;
  };
  right: {
    visible: boolean;
    width: number;
  };
}

defineActions({
  toggleLeft() {
    this.left.visible = !this.left.visible;
  },
  setLeftWidth(width: number) {
    this.left.width = clamp(width, 180, 400);
  },
});
```

---

## 6. 交互逻辑

### 6.1 内容切换

- 页面切换时，`updateLeftPanel(page)` 注入对应模板
- Vue 方案: 通过 `<component :is="currentLeftPanelComponent">` 动态渲染
- 内容组件由路由元数据指定

### 6.2 收起/展开

- 点击 Header 收起按钮 → toggle visible
- 点击 TopBar 面板切换按钮 → toggle visible
- 收起时面板宽度 → 0，内容隐藏，过渡动画 200ms

### 6.3 拖拽调整宽度 (可选)

- 面板右边缘 4px 拖拽区
- mousedown → 开始拖拽 → mousemove 更新宽度 → mouseup 结束
- 宽度限制: minWidth ~ maxWidth

---

## 7. 通用子组件

左面板内容中复用的通用组件:

### SearchBox (搜索框)

```vue
<!-- 各页面左面板顶部搜索 -->
<SearchBox placeholder="搜索..." v-model="query" />
```

| Props | 类型 | 说明 |
|-------|------|------|
| `modelValue` | `string` | 搜索文本 |
| `placeholder` | `string` | 占位符 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `update:modelValue` | `{ value: string }` | 文本变化 |
| `search` | `{ query: string }` | 搜索触发 |

### CollapsibleGroup (折叠分组)

```vue
<!-- 用于对话分组/任务分组 -->
<CollapsibleGroup title="当前项目" :defaultOpen="true">
  <ConvoItem ... />
</CollapsibleGroup>
```

| Props | 类型 | 说明 |
|-------|------|------|
| `title` | `string` | 分组标题 |
| `count` | `number` | 项数 (角标) |
| `defaultOpen` | `boolean` | 默认展开 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `toggle` | `{ open: boolean }` | 展开/折叠 |

---

## 8. 样式规范

| 元素 | 宽度 | 背景 | 边框 |
|------|------|------|------|
| LeftPanel | 240px (可变) | `var(--bg-primary)` | 右侧 `1px solid var(--border)` |
| Header | 全宽 × 32px | `var(--bg-secondary)` | 底部 `1px solid var(--border)` |
| Body | 全宽 | `var(--bg-primary)` | 无 |
| ResizeHandle | 4px | 透明 → hover `var(--accent)` | 无 |

---

## 9. 文件结构

```
src/components/shell/
├── LeftPanel.vue           ← 根组件
├── LeftPanelHeader.vue     ← 标题栏
└── index.ts

src/components/common/
├── SearchBox.vue           ← 搜索框 (通用)
├── CollapsibleGroup.vue    ← 折叠分组 (通用)
└── index.ts
```

---

## 10. 路由元数据配置

```typescript
// router/index.ts
const routes = [
  {
    path: '/home',
    component: () => import('@/pages/HomePage.vue'),
    meta: {
      leftPanel: '项目列表',
      leftComponent: () => import('@/components/pages/home/ProjectListPanel.vue'),
    },
  },
  {
    path: '/analysis',
    component: () => import('@/pages/AnalysisPage.vue'),
    meta: {
      leftPanel: '任务筛选',
      leftComponent: () => import('@/components/pages/analysis/TaskFilterPanel.vue'),
    },
  },
  // ...
];
```

---

## 11. 与原型对照

| 原型实现 | Vue 组件方案 |
|----------|-------------|
| `leftPanelTemplates` 对象 (HTML 字符串) | 独立 Vue 组件 + 路由元数据 |
| `updateLeftPanel()` 注入 innerHTML | `<component :is="">` 动态组件 |
| 克隆节点清除事件 | Vue 响应式 + 组件事件 |
| 固定 240px | 可配置 + 可选拖拽调整 |
