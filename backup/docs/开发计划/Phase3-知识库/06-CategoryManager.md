# CategoryManager 组件设计

> 知识库四维分类管理 Tab，展示和管理四个维度的标签体系

---

## 1. 组件职责

- 按四维分类体系展示所有标签
- 支持每个维度的标签增删改
- 支持 LLM 辅助推荐标签
- 作为知识库页面"分类管理"Tab 的内容

## 2. 数据结构

```typescript
interface Dimension {
  id: string;               // 维度标识
  name: string;             // 维度名称
  icon: string;             // 维度图标
  color: 'blue' | 'green' | 'yellow' | 'red';
  tags: CategoryTag[];      // 该维度下的标签
}

interface CategoryTag {
  id: string;
  label: string;            // 标签文本
  count?: number;           // 关联知识点数量
  color?: string;           // 自定义颜色
}
```

## 3. 四维配置

| 维度 | id | 图标 | 颜色 | 默认标签 |
|------|-----|------|------|----------|
| 开发生命周期 | `lifecycle` | 🔄 | blue | 需求、设计、编码、测试、部署、运维、重构 |
| 技术栈工具链 | `techStack` | 🛠️ | green | Python、Go、JavaScript、数据库、Docker、CI-CD |
| 抽象层级 | `abstraction` | 📐 | yellow | 架构、模块、类、函数、配置、数据 |
| 知识属性用途 | `attribute` | 🎯 | red | 最佳实践、设计模式、常见陷阱、规范、分析结果、教学素材 |

## 4. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `dimensions` | `Dimension[]` | 四维默认值 | 四维标签体系 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `add-tag` | `{ dimensionId: string, label: string }` | 添加标签 |
| `edit-tag` | `{ dimensionId: string, tagId: string, label: string }` | 编辑标签 |
| `delete-tag` | `{ dimensionId: string, tagId: string }` | 删除标签 |
| `ai-recommend` | `{ dimensionId: string }` | 触发 LLM 推荐标签 |

## 5. 子组件

| 组件 | 说明 |
|------|------|
| `DimensionCard` | 单个维度的卡片 (名称/标签列表/操作) |
| `TagChip` | 单个标签芯片 (文本 + 角标计数) |
| `TagForm` | 标签编辑表单 |

## 6. 交互逻辑

- 每个维度独立卡片展示
- 标签以 flex-wrap 形式排列
- 点击标签可快速跳转到知识库筛选
- "LLM 辅助推荐"按钮触发 AI 分析当前知识库数据，推荐合适的标签
- 编辑/删除标签操作需确认（警告：会影响关联的知识点）

## 7. 样式规范

- DimensionCard: padding 14px, margin-bottom 12px
- 维度标题 13px 粗体
- 标签芯片: padding 4px 10px, border-radius 12px, 10px 字体
- 标签数量角标: 右上角 8px 微标

## 8. 文件结构

```
src/components/knowledge/
└── CategoryManager.vue
```
