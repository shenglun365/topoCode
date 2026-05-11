# ExtractDialog 组件设计

> 提取知识点对话框，将分析结果转化为知识文档

---

## 1. 组件职责

- 提供知识点提取表单
- 支持四维标签选择
- 预览生成的知识文档

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ 提取知识点                      [×]     │
├─────────────────────────────────────────┤
│ 标题: [____________________________]    │
│                                         │
│ 四维标签:                               │
│ 🔄 生命周期: [需求 ▼]                   │
│ 🛠 技术栈:   [Python ▼]                 │
│ 📐 抽象层级: [模块 ▼]                   │
│ 🎯 知识属性: [最佳实践 ▼]               │
│                                         │
│ 内容选择:                               │
│ ☑ 摘要  ☑ AST  ☑ 调用链                │
│ ☑ 依赖  ☑ 数据流  ☐ 日志               │
│                                         │
│ 备注: [____________________________]    │
│                                         │
│         [取消]      [确认提取]          │
└─────────────────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `visible` | `boolean` | `false` | 对话框可见性 |
| `task` | `AnalysisTask` | — | 源任务数据 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `close` | `void` | 关闭对话框 |
| `extract` | `{ data: ExtractData }` | 确认提取 |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `DialogWrapper` | 对话框容器 |
| `DimensionSelector` | 维度选择器 |
| `ContentCheckbox` | 内容复选框 |

## 5. 数据结构

```typescript
interface ExtractData {
  title: string;
  dimensions: {
    lifecycle: string;      // 开发生命周期
    techStack: string;      // 技术栈工具链
    abstraction: string;    // 抽象层级
    attribute: string;      // 知识属性用途
  };
  content: {
    summary: boolean;
    ast: boolean;
    callChain: boolean;
    dependency: boolean;
    dataFlow: boolean;
    logs: boolean;
  };
  notes: string;
  sourceTaskId: string;
}
```

## 6. 交互逻辑

- 打开对话框 → 填充任务默认信息
- 选择四维标签 → 下拉选择
- 选择内容项 → 复选框
- 点击确认 → 验证必填项 → emit extract 事件
- 点击取消 / ESC → 关闭对话框

## 7. 样式规范

- 对话框宽度：500px
- 圆角：8px
- 遮罩层：半透明黑色背景
- 按钮：主按钮右侧，次要按钮左侧

## 8. 文件结构

```
src/components/analysis/
├── ExtractDialog.vue
├── DimensionSelector.vue
└── ContentCheckbox.vue
```
