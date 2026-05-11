# DocEditor 组件设计

> 文档编辑器，支持编辑/浏览双模式

---

## 1. 组件职责

- 提供 Markdown 编辑功能
- 支持实时预览
- 支持代码块语法高亮

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ [编辑] [浏览] [预览]        [保存] [×]  │
├─────────────────────────────────────────┤
│                                         │
│  ┌──────────────┐  ┌──────────────┐    │
│  │ # 标题       │  │  ┌──────────┐│    │
│  │             │  │  │ ## 标题   ││    │
│  │ 正文内容     │  │  │          ││    │
│  │             │  │  │ 正文渲染  ││    │
│  │ ```python    │  │  │          ││    │
│  │ def foo():   │  │  │ ```py    ││    │
│  │   pass       │  │  │ def foo: ││    │
│  │ ```          │  │  │ ```      ││    │
│  │             │  │  │          ││    │
│  └──────────────┘  └──────────────┘    │
│   ← 编辑区         ← 预览区            │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `doc` | `KnowledgeDoc` | - | 文档数据 |
| `mode` | `'edit' \| 'view' \| 'preview'` | `'edit'` | 编辑模式 |
| `readonly` | `boolean` | `false` | 只读模式 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `mode-change` | `{ mode: string }` | 模式切换 |
| `save` | `{ docId: string, content: string }` | 保存文档 |
| `close` | `void` | 关闭编辑器 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `EditorToolbar` | 工具栏 |
| `EditorArea` | 编辑区 (Monaco Editor) |
| `PreviewArea` | 预览区 (Markdown 渲染) |
| `CodeBlock` | 代码块 (语法高亮) |

## 5. 交互逻辑

- 模式切换：编辑/浏览/预览
- 编辑模式：Monaco Editor 编辑 Markdown
- 预览模式：实时渲染 Markdown
- 保存：Ctrl+S 或点击保存按钮
- 代码块：支持语法高亮和复制

## 6. 样式规范

- 编辑器：Monaco Editor 主题与 Catppuccin 匹配
- 预览区：Markdown 渲染样式
- 代码块：等宽字体，语法高亮

## 7. 文件结构

```
src/components/knowledge/
├── DocEditor.vue
├── EditorToolbar.vue
├── EditorArea.vue
├── PreviewArea.vue
└── CodeBlock.vue
```
