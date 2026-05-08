# TopBar 组件设计

> 顶部工具栏：菜单 + 面板切换 + 主题切换

---

## 1. 组件定位

UI Shell 的最顶层组件，提供全局操作入口。

```
┌────────────────────────────────────────────────────────────┐
│ TopBar (36px)                                              │
│  [◆ TopoOne] [文件▼] [编辑▼] [查看▼] [工具▼] [帮助▼]  [...] │
│                                              [◫] [◪] [🌙] │
└────────────────────────────────────────────────────────────┘
```

---

## 2. 子组件结构

```
TopBar
├── TopBarLogo        ← 产品 Logo + 名称
├── TopBarMenu        ← 菜单栏 (5 个下拉菜单)
│   └── MenuDropdown  ← 下拉菜单项 (可复用)
├── TopBarSpacer      ← 弹性间隔
└── TopBarActions     ← 右侧操作按钮
    ├── ToggleLeftPanelBtn
    ├── ToggleRightPanelBtn
    └── ThemeSwitchBtn
```

---

## 3. Props / Emits / Slots

### TopBar (根组件)

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| - | - | - | 无外部 Props |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `menu-action` | `{ action: string, payload?: any }` | 菜单项点击 |
| `toggle-left` | - | 切换左面板 |
| `toggle-right` | - | 切换右面板 |
| `toggle-theme` | - | 切换主题 |

### MenuDropdown

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| `items` | `MenuItem[]` | `[]` | 菜单项列表 |
| `trigger` | `'click' \| 'hover'` | `'click'` | 触发方式 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `select` | `{ item: MenuItem }` | 菜单项选中 |

---

## 4. 数据模型

```typescript
interface MenuItem {
  label: string;
  shortcut?: string;      // 快捷键提示
  action?: string;        // 动作标识
  divider?: boolean;      // 分隔线
  children?: MenuItem[];  // 子菜单
  disabled?: boolean;
  checked?: boolean;      // 勾选态
}

// 菜单数据 (由父组件注入)
const menuData: MenuItem[] = [
  {
    label: '文件',
    children: [
      { label: '导入项目', shortcut: 'Ctrl+O', action: 'import-project' },
      { label: '打开文件', shortcut: 'Ctrl+Shift+O', action: 'open-file' },
      { divider: true },
      { label: '退出', shortcut: 'Ctrl+Q', action: 'quit' },
    ],
  },
  {
    label: '编辑',
    children: [
      { label: '撤销', shortcut: 'Ctrl+Z', action: 'undo' },
      { label: '重做', shortcut: 'Ctrl+Shift+Z', action: 'redo' },
      { divider: true },
      { label: '查找', shortcut: 'Ctrl+F', action: 'find' },
    ],
  },
  {
    label: '查看',
    children: [
      { label: '左面板', shortcut: 'Ctrl+B', action: 'toggle-left', checked: true },
      { label: '右面板', shortcut: 'Ctrl+J', action: 'toggle-right', checked: true },
      { divider: true },
      { label: '深色主题', action: 'theme-dark' },
      { label: '浅色主题', action: 'theme-light' },
    ],
  },
  {
    label: '工具',
    children: [
      { label: '设置', shortcut: 'Ctrl+,', action: 'open-settings' },
      { label: '插件管理', action: 'open-plugins' },
    ],
  },
  {
    label: '帮助',
    children: [
      { label: '文档', action: 'open-docs' },
      { label: '关于', action: 'open-about' },
    ],
  },
];
```

---

## 5. 状态管理 (Pinia)

```typescript
// stores/theme.ts
interface ThemeState {
  mode: 'dark' | 'light' | 'system';
  current: 'dark' | 'light';  // 解析后的实际主题
}

// stores/panel.ts
interface PanelState {
  leftVisible: boolean;
  rightVisible: boolean;
}
```

---

## 6. 交互逻辑

### 6.1 菜单下拉

- 点击菜单项 → 展开/收起下拉面板
- 点击菜单项动作 → 触发 `menu-action` 事件 → 关闭下拉
- 点击页面其他区域 → 关闭下拉
- ESC → 关闭下拉

### 6.2 快捷键

- 通过 `keyboardjs` 或原生 `keydown` 监听
- 快捷键映射表由 `menuData` 中的 `shortcut` 字段驱动
- 触发后执行对应 `action`

### 6.3 主题切换

- 按钮循环切换: dark → light → system → dark
- 切换时更新 `html[data-theme]` 属性
- 通过 CSS 变量实现主题切换
- `system` 模式监听 `prefers-color-scheme` 媒体查询

### 6.4 面板切换

- 左面板按钮: 切换 `leftVisible`
- 右面板按钮: 切换 `rightVisible`
- 面板收起/展开带动画过渡 (200ms)

---

## 7. 样式规范

| 元素 | 高度 | 背景 | 边框 |
|------|------|------|------|
| TopBar | 36px | `var(--bg-secondary)` | 底部 `1px solid var(--border)` |
| Logo | 20px | 透明 | 无 |
| 菜单项 | 28px | 透明 → hover `var(--bg-hover)` | 无 |
| 下拉面板 | 自适应 | `var(--bg-secondary)` | `1px solid var(--border)` + shadow |
| 操作按钮 | 24px | 透明 → hover `var(--bg-hover)` | 圆角 4px |

---

## 8. 文件结构

```
src/components/shell/
├── TopBar.vue              ← 根组件
├── TopBarLogo.vue          ← Logo
├── TopBarMenu.vue          ← 菜单栏
├── MenuDropdown.vue        ← 下拉菜单 (可复用)
├── TopBarActions.vue       ← 右侧操作按钮
└── index.ts                ← 导出
```

---

## 9. 与原型对照

| 原型实现 | Vue 组件方案 |
|----------|-------------|
| 内联 HTML + JS 事件 | Vue 组件 + emit |
| 全局 `menuData` 变量 | Props 注入 |
| 内联样式 | scoped CSS + CSS 变量 |
| 手动 DOM 操作 | 响应式数据驱动 |
