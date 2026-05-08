# KnowledgeCard 组件设计

> 知识文档卡片，展示文档摘要和操作入口

---

## 1. 组件职责

- 展示知识文档基本信息
- 展示四维标签
- 提供操作入口 (收藏/置顶/更多)

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ 📄 JWT认证规范              [已审核]    │
│                                         │
│ JWT Token 的生成、验证、刷新流程规范...  │
│                                         │
│ 🔄设计 🛠Python 📐模块 🎯最佳实践       │
│                                         │
│ 3 days ago              [★] [📌] [···] │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `doc` | `KnowledgeDoc` | - | 文档数据 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `open` | `{ docId: string }` | 打开文档 |
| `toggle-fav` | `{ docId: string }` | 切换收藏 |
| `toggle-pin` | `{ docId: string }` | 切换置顶 |
| `more` | `{ docId: string }` | 更多操作 |

### 数据结构

```typescript
interface KnowledgeDoc {
  id: string;
  title: string;
  type: 'project' | 'document';
  status: 'draft' | 'pending' | 'reviewed';
  description: string;
  dimensions: {
    lifecycle: string;
    techStack: string;
    abstraction: string;
    attribute: string;
  };
  favorite: boolean;
  pinned: boolean;
  createdAt: Date;
  updatedAt: Date;
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `DocHeader` | 文档标题栏 |
| `DocDescription` | 文档描述 |
| `DocTags` | 四维标签 |
| `DocActions` | 操作按钮 |

## 5. 交互逻辑

- 点击卡片主体 → 打开文档编辑器
- 点击星标 → 切换收藏状态
- 点击图钉 → 切换置顶状态
- 点击"更多" → 弹出操作菜单 (编辑/删除/分享)

## 6. 样式规范

- 卡片圆角：8px
- 悬停阴影
- 状态标签：草稿=灰色，待审核=黄色，已审核=绿色
- 四维标签：颜色根据维度区分

## 7. 文件结构

```
src/components/knowledge/
├── KnowledgeCard.vue
├── DocHeader.vue
├── DocDescription.vue
├── DocTags.vue
└── DocActions.vue
```
