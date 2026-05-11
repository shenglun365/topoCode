# AgentManager 组件设计

> 外部 Agent 管理，配置 CLI Agent 工具

---

## 1. 组件职责

- 展示已配置的 Agent 列表
- 支持添加/编辑/删除 Agent
- 配置 Agent 执行参数

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ Agent 管理             [+ 添加 Agent]   │
├─────────────────────────────────────────┤
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ qwen-code                   [默认]  │ │
│ │ 路径: /usr/local/bin/qwen-code      │ │
│ │ 参数: --model qwen2.5-coder:7b      │ │
│ │ 状态: ● 可用                       │ │
│ │ [编辑] [测试]                      │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ cline                              │ │
│ │ 路径: /usr/local/bin/cline          │ │
│ │ 参数: --backend ollama              │ │
│ │ 状态: ● 可用                       │ │
│ │ [编辑] [测试]                      │ │
│ └─────────────────────────────────────┘ │
│                                         │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `agents` | `AgentConfig[]` | `[]` | Agent 配置列表 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `add` | `{ config: AgentConfig }` | 添加 Agent |
| `edit` | `{ id: string, config: AgentConfig }` | 编辑 Agent |
| `delete` | `{ id: string }` | 删除 Agent |
| `set-default` | `{ id: string }` | 设为默认 |
| `test` | `{ id: string }` | 测试 Agent |

### 数据结构

```typescript
interface AgentConfig {
  id: string;
  name: string;
  path: string;
  args: string[];
  isDefault: boolean;
  status: 'available' | 'not-found' | 'error';
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `AgentCard` | Agent 卡片 |
| `AgentForm` | Agent 配置表单 |
| `StatusDot` | 状态点 (复用) |

## 5. 交互逻辑

- 点击"添加 Agent" → 打开配置表单
- 点击"编辑" → 编辑 Agent 配置
- 点击"测试" → 测试 Agent 可执行性
- 点击"设为默认" → 设置默认 Agent
- 点击"删除" → 删除 Agent 配置

## 6. 样式规范

- 卡片圆角：8px
- 默认 Agent：金色边框
- 状态点：可用=绿色，未找到=灰色，错误=红色

## 7. 文件结构

```
src/components/settings/
├── AgentManager.vue
├── AgentCard.vue
└── AgentForm.vue
```
