# TaskReport 组件设计

> 任务报告，展示分析结果的详细报告

---

## 1. 组件职责

- 展示任务执行的完整报告
- 支持多种分析视图 (AST/调用链/依赖/数据流)
- 提供导出和提取知识点入口

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ 全量报告          [完成] [导出] [提取]   │
├─────────────────────────────────────────┤
│ 摘要                                    │
│ 项目: topoOne-ui  语言: Python          │
│ 范围: src/**  耗时: 2.3s                │
├─────────────────────────────────────────┤
│ [AST] [调用链] [依赖] [数据流] [日志]   │ ← Tab 切换
├─────────────────────────────────────────┤
│                                         │
│  [分析视图内容]                          │
│                                         │
│  AST 树 / 调用链图 / 依赖图 / 数据流图   │
│                                         │
└─────────────────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `task` | `AnalysisTask` | — | 任务数据 |
| `report` | `TaskReportData` | — | 报告数据 |
| `activeTab` | `string` | `'ast'` | 当前激活 Tab |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `tab-change` | `{ tab: string }` | Tab 切换 |
| `export` | `{ taskId: string }` | 导出报告 |
| `extract` | `{ taskId: string }` | 提取知识点 |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `ReportHeader` | 报告标题栏 |
| `ReportTabs` | Tab 切换栏 |
| `ASTViewer` | AST 树查看器 |
| `CallChainViewer` | 调用链查看器 |
| `DependencyViewer` | 依赖图查看器 |
| `DataFlowViewer` | 数据流查看器 |
| `LogViewer` | 日志查看器 |

## 5. 数据结构

```typescript
interface TaskReportData {
  task: AnalysisTask;
  ast?: ASTNode;
  callChain?: CallChainNode[];
  dependencies?: DependencyGraph;
  dataFlow?: DataFlowGraph;
  logs: string[];
}

interface ASTNode {
  type: string;
  name: string;
  children: ASTNode[];
}

interface CallChainNode {
  id: string;
  name: string;
  target: string;
  callers: string[];
  callees: string[];
}
```

## 6. 交互逻辑

- Tab 切换 → 显示对应分析视图
- AST 树：点击节点展开/折叠
- 调用链/依赖/数据流：SVG 图形，可拖拽节点
- 点击"提取知识点" → 打开 ExtractDialog

## 7. 样式规范

- Tab 栏：底部边框高亮
- AST 树：缩进显示，节点可点击
- 图形视图：SVG 画布，节点圆形/方形，箭头连接

## 8. 文件结构

```
src/components/analysis/
├── TaskReport.vue
├── ReportHeader.vue
├── ReportTabs.vue
├── ASTViewer.vue
├── CallChainViewer.vue
├── DependencyViewer.vue
├── DataFlowViewer.vue
└── LogViewer.vue
```
