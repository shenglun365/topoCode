# ActivityBar 组件设计

> 活动栏：模块导航入口

---

## 1. 组件定位

UI Shell 左侧固定导航栏，驱动页面切换。

```
┌──────────┐
│          │
│  📁      │  ← home (项目导入)
│  📊      │  ← analysis (代码分析)
│  🧠      │  ← knowledge (知识库)
│  🤖      │  ← coder (AI 助手)
│          │
│  ⚙️      │  ← user (设置)
│          │
└──────────┘
  48px wide
```

---

## 2. 子组件结构

```
ActivityBar
├── ActivitySection (top)
│   └── ActivityItem × 4  ← home / analysis / knowledge / coder
├── ActivitySpacer         ← 弹性间隔
└── ActivitySection (bottom)
    └── ActivityItem × 1  ← user (设置)
```

---

## 3. Props / Emits / Slots

### ActivityBar

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| `activePage` | `string` | `'home'` | 当前激活页面 |
| `items` | `ActivityItemConfig[]` | 内置 5 项 | 导航项配置 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `switch` | `{ page: string }` | 切换页面 |

### ActivityItem

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| `page` | `string` | - | 页面对应标识 |
| `icon` | `string` | - | 图标 (emoji 或 SVG) |
| `title` | `string` | - | 悬停提示 |
| `active` | `boolean` | `false` | 是否激活 |
| `badge` | `string \| number` | - | 角标 (可选) |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `click` | `{ page: string }` | 点击导航 |

---

## 4. 数据模型

```typescript
interface ActivityItemConfig {
  page: string;       // 页面标识
  icon: string;       // 图标
  title: string;      // 提示文本
  section: 'top' | 'bottom';  // 分区
  badge?: string | number;    // 角标 (可选)
}

// 默认配置
const defaultItems: ActivityItemConfig[] = [
  { page: 'home', icon: '📁', title: '项目导入', section: 'top' },
  { page: 'analysis', icon: '📊', title: '代码分析', section: 'top' },
  { page: 'knowledge', icon: '🧠', title: '知识库', section: 'top' },
  { page: 'coder', icon: '🤖', title: 'AI 助手', section: 'top' },
  { page: 'user', icon: '⚙️', title: '设置', section: 'bottom' },
];
```

---

## 5. 状态管理 (Pinia)

```typescript
// stores/navigation.ts
interface NavigationState {
  activePage: string;
  pageHistory: string[];  // 页面历史 (用于返回)
}

// Actions
defineActions({
  switchPage(page: string) {
    this.activePage = page;
    this.pageHistory.push(page);
    // 触发页面加载
  },
});
```

---

## 6. 交互逻辑

### 6.1 页面切换

- 点击导航项 → emit `switch` → Pinia `switchPage` → Vue Router 导航
- 激活态: 左侧指示条 + 高亮颜色 (`var(--accent)`)
- 非激活态: 灰色图标，hover 变亮

### 6.2 角标 (扩展)

- 可选显示未读/计数角标
- 如: AI 助手有执行中任务时显示 "●"

### 6.3 悬停提示

- 使用原生 `title` 属性或自定义 Tooltip 组件
- 显示模块名称

---

## 7. 样式规范

| 元素 | 宽度 | 背景 | 激活态 |
|------|------|------|--------|
| ActivityBar | 48px | `var(--bg-secondary)` | 右侧 `1px solid var(--border)` |
| ActivityItem | 48×48px | 透明 | 左侧 `3px solid var(--accent)` + 图标高亮 |
| 指示条 | 3px | `var(--accent)` | 激活时显示 |
| 角标 | 最小 16px×16px | `var(--accent)` | 圆角，白色文字 |

---

## 8. 文件结构

```
src/components/shell/
├── ActivityBar.vue       ← 根组件
├── ActivityItem.vue      ← 导航项
└── index.ts              ← 导出
```

---

## 9. 与原型对照

| 原型实现 | Vue 组件方案 |
|----------|-------------|
| `data-page` 属性 + JS 切换 | Props + emit + Vue Router |
| 内联 `title` 属性 | 同 (或自定义 Tooltip) |
| CSS `.active` 类 | 响应式 `:class="{ active: active }"` |
