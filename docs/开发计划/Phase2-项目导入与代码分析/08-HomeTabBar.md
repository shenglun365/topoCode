# HomeTabBar 组件设计

> 项目视图内的多 Tab Card 栏，管理文件/任务/报告的打开状态

---

## 1. 组件职责

- 在项目视图下管理多个打开的 Tab Card（文件/任务/报告）
- 支持 Tab 切换、关闭
- 作为 ProjectImport 组件内部的子组件

## 2. 布局结构

```
┌──────────────────────────────────────────────────────────┐
│ 📄 auth.py  │ ⭐ 全量解析  │ 📊 AST报告  │ 📋 调用链  │  │
│             │              │             │         [×] │  │
└──────────────────────────────────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `tabs` | `HomeTabCard[]` | `[]` | 当前打开的 Tab 列表 |
| `activeTabId` | `string \| null` | `null` | 当前激活 Tab |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `switch` | `{ tabId: string }` | 切换 Tab |
| `close` | `{ tabId: string }` | 关闭 Tab |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `TabItem` | 单个 Tab 项 (图标/标题/关闭按钮) |

## 5. 数据结构

```typescript
interface HomeTabCard {
  id: string;                      // 唯一标识
  type: 'file' | 'task-private' | 'task-shared' | 'report';
  title: string;                   // Tab 标题
  icon: string;                    // Tab 图标
  data: any;                       // 关联数据
  closable: boolean;               // 是否可关闭
}
```

### Tab 类型与图标

| 类型 | 图标 | 说明 |
|------|------|------|
| `file` | 📄 | 文件内容查看 |
| `task-private` | ⭐ | 任务详情 (本用户私有) |
| `task-shared` | 📋 | 任务详情 (共享) |
| `report` | 📊 | 分析报告查看 |

## 6. 交互逻辑

- 点击 Tab → emit `switch` → 切换 MainContent 内容区
- 点击关闭按钮 → emit `close` → 从 tabs 数组移除
- 如果关闭的是 activeTab → 自动激活左侧相邻 Tab
- 最大 Tab 数限制: 10 个 (超出时关闭最早的 Tab)
- 双击 Tab → 可重命名 (task-private 类型)

## 7. 样式规范

- 高度 32px
- 背景 `var(--bg-secondary)`
- Tab 项: padding 0 12px, gap 6px, 右侧 1px border 分隔
- 激活态底部 1px solid `var(--accent)`，背景 `var(--bg-primary)`
- 关闭按钮 16×16px，默认透明度 0，hover 可见

## 8. 文件结构

```
src/components/home/
└── HomeTabBar.vue
```
