# AppShell 组件设计

> 整体布局容器，管理活动栏、左面板、主内容区、右面板、状态栏

---

## 1. 组件职责

- 提供整体布局框架 (Flexbox)
- 管理面板折叠/展开状态
- 协调子组件间的通信
- 主题切换全局控制

## 2. 布局结构

```
┌─────────────────────────────────────────────────────────┐
│ AppShell (100vw × 100vh)                                │
│                                                         │
│  ┌──────────┬────────────┬──────────────┬────────┐     │
│  │ActivityBar│ LeftPanel  │ MainContent  │RightPanel│  │
│  │  (48px)  │ (240px)    │  (flex:1)    │(280px)  │  │
│  │          │            │              │        │  │
│  │ 📁       │ [列表]     │ [页面内容]   │ [详情] │  │
│  │ 📊       │            │              │        │  │
│  │ 🧠       │            │              │        │  │
│  │ 🤖       │            │              │        │  │
│  │          │            │              │        │  │
│  │ ⚙️       │            │              │        │  │
│  └──────────┴────────────┴──────────────┴────────┘     │
│                                                         │
│  ┌───────────────────────────────────────────────────┐  │
│  │ StatusBar (24px)                                  │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `theme` | `'dark' \| 'light'` | `'dark'` | 主题模式 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `toggle-left` | `void` | 切换左面板 |
| `toggle-right` | `void` | 切换右面板 |
| `theme-change` | `{ theme: string }` | 主题切换 |

### Slots

| 名称 | 说明 |
|------|------|
| `activity` | 活动栏内容 |
| `left` | 左面板内容 |
| `main` | 主内容区 |
| `right` | 右面板内容 |
| `status` | 状态栏内容 |

## 4. 子组件

| 组件 | 位置 | 说明 |
|------|------|------|
| `ActivityBar` | 左侧固定 | 导航入口 |
| `LeftPanel` | 左侧可变 | 上下文列表 |
| `MainContent` | 中间弹性 | 页面路由出口 |
| `RightPanel` | 右侧可变 | 详情面板 |
| `StatusBar` | 底部固定 | 状态指示 |

## 5. 状态管理

```typescript
interface ShellState {
  leftPanelVisible: boolean;
  rightPanelVisible: boolean;
  leftPanelWidth: number;
  rightPanelWidth: number;
  theme: 'dark' | 'light';
}
```

## 6. 交互逻辑

- 面板折叠：点击折叠按钮切换 visible 状态，CSS transition 动画
- 面板拖拽：鼠标拖拽面板边缘调整宽度，最小 180px，最大 600px
- 主题切换：切换 html 标签 data-theme 属性，CSS 变量响应

## 7. 样式规范

- 使用 CSS Grid 或 Flexbox 布局
- 面板宽度通过 CSS 变量控制：`--panel-left-width`, `--panel-right-width`
- 过渡动画：`transition: width 0.2s ease`

## 8. 文件结构

```
src/components/shell/
├── AppShell.vue
├── ActivityBar.vue
├── LeftPanel.vue
├── MainContent.vue
├── RightPanel.vue
└── StatusBar.vue
```
