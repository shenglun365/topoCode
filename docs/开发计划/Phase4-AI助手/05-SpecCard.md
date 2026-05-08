# SpecCard 组件设计

> Spec 摘要卡片，展示 AI 生成的设计文档摘要

---

## 1. 组件职责

- 展示 Spec 文档摘要
- 提供查看/编辑入口
- 展示文档状态

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ 📋 用户认证模块设计文档      [草稿]      │
│                                         │
│ 基于用户需求生成的模块设计文档...        │
│                                         │
│ 包含: 架构设计 / 接口定义 / 数据模型    │
│                                         │
│ [查看] [编辑]                           │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `spec` | `SpecDoc` | - | Spec 文档数据 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `view` | `{ specId: string }` | 查看 Spec |
| `edit` | `{ specId: string }` | 编辑 Spec |

### 数据结构

```typescript
interface SpecDoc {
  id: string;
  title: string;
  status: 'draft' | 'reviewed' | 'approved';
  summary: string;
  sections: string[];
  createdAt: Date;
  updatedAt: Date;
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `SpecHeader` | Spec 标题栏 |
| `SpecSummary` | Spec 摘要 |
| `SpecSections` | Spec 章节列表 |
| `SpecActions` | 操作按钮 |

## 5. 交互逻辑

- 点击"查看" → 打开 Spec 查看器
- 点击"编辑" → 打开 Spec 编辑器
- 状态标签：草稿=灰色，已审核=黄色，已批准=绿色

## 6. 样式规范

- 卡片圆角：8px
- 状态标签：小型 badge
- 边框：左侧 3px 高亮条

## 7. 文件结构

```
src/components/coder/
├── SpecCard.vue
├── SpecHeader.vue
├── SpecSummary.vue
├── SpecSections.vue
└── SpecActions.vue
```
