# FileTree 组件设计

> 文件树，展示项目文件结构

---

## 1. 组件职责

- 展示项目文件目录结构
- 支持展开/折叠目录
- 支持文件选中高亮

## 2. 布局结构

```
┌─────────────────┐
│ src/          ▶ │ ← 目录 (可展开)
│ ├─ core/      ▶ │
│ ├─ auth.py   🐍 │ ← 文件 (带图标)
│ ├─ api.py    🐍 │
│ ├─ utils/    ▶ │
│ tests/        ▶ │
│ README.md     📄 │
└─────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `rootPath` | `string` | `''` | 项目根路径 |
| `selectedFile` | `string \| null` | `null` | 当前选中文件路径 |
| `expandedPaths` | `string[]` | `[]` | 已展开的目录路径 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `select` | `{ path: string }` | 选中文件 |
| `expand` | `{ path: string }` | 展开/折叠目录 |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `TreeNode` | 单个树节点 (目录/文件) |
| `FileIcon` | 文件图标 (根据扩展名) |

## 5. 数据结构

```typescript
interface FileNode {
  path: string;
  name: string;
  type: 'file' | 'directory';
  extension?: string;
  children?: FileNode[];
  expanded?: boolean;
}
```

## 6. 交互逻辑

- 点击目录 → 切换展开/折叠状态
- 点击文件 → emit select 事件，高亮选中
- 双击文件 → 打开文件编辑器 Tab

## 7. 样式规范

- 缩进：每级 16px
- 行高：24px
- 悬停背景：`var(--bg-hover)`
- 选中背景：`var(--bg-tertiary)`
- 箭头图标：展开 ▼，折叠 ▶

## 8. 文件结构

```
src/components/project/
├── FileTree.vue
├── TreeNode.vue
└── FileIcon.vue
```
