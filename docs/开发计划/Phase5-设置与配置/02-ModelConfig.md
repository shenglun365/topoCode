# ModelConfig 组件设计

> 模型配置管理，管理 LLM 模型和路由

---

## 1. 组件职责

- 展示已配置的模型列表
- 支持添加/编辑/删除模型
- 配置模型路由规则

## 2. 布局结构

模型配置页面包含以下区块：

```
┌──────────────────────────────────────────────┐
│ 当前使用: Ollama / qwen2.5-coder:7b   ● 在线  │
├──────────────────────────────────────────────┤
│ 已保存的配置                    [+ 添加配置]  │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │ 🦙 Ollama - qwen2.5-coder:7b    [默认]   │ │
│ │ http://localhost:11434                    │ │
│ │ 本地 · Temperature: 0.7 · Max: 4096      │ │
│ │ [测试连接] [编辑]              [删除]     │ │
│ └──────────────────────────────────────────┘ │
│ ┌──────────────────────────────────────────┐ │
│ │ 🤖 OpenAI - gpt-4o                       │ │
│ │ https://api.openai.com                   │ │
│ │ 云端 · Temperature: 0.5 · Max: 8192      │ │
│ │ [测试连接] [设为默认] [编辑]    [删除]    │ │
│ └──────────────────────────────────────────┘ │
│ ...                                          │
├──────────────────────────────────────────────┤
│ 任务级模型绑定                                │
│                                              │
│ ┌─────────────┬─────────────────────────┐   │
│ │ 语法结构分析 │ Ollama / qwen2.5 ▼     │   │
│ │ 代码功能分析 │ OpenAI / gpt-4o ▼      │   │
│ │ AI 问答     │ Ollama / qwen2.5 ▼     │   │
│ └─────────────┴─────────────────────────┘   │
├──────────────────────────────────────────────┤
│ 用量限制                                      │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │ OpenAI / gpt-4o  已用 12,450 / 50,000   │ │
│ │ ████████░░░░░░░░░░░░░░░░░░ 25%          │ │
│ │ 月度限额: [50000] tokens/月    [保存]    │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 模型优先级 (拖拽排序)                          │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │ ⠿ 1. Ollama / qwen2.5-coder:7b  本地    │ │
│ │ ⠿ 2. OpenAI / gpt-4o           云端    │ │
│ │ ⠿ 3. LM-Studio / llama3-8b     本地    │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 隐私设置                                      │
│ 仅使用本地模型: [✓] (源码不上传外部)          │
│ 匿名使用数据:  [ ]                           │
└──────────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `models` | `ModelConfig[]` | `[]` | 模型配置列表 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `add` | `{ config: ModelConfig }` | 添加模型 |
| `edit` | `{ id: string, config: ModelConfig }` | 编辑模型 |
| `delete` | `{ id: string }` | 删除模型 |
| `set-default` | `{ id: string }` | 设为默认 |
| `test` | `{ id: string }` | 测试连接 |

### 数据结构

```typescript
interface ModelConfig {
  id: string;
  name: string;
  type: 'ollama' | 'openai' | 'custom';
  model: string;
  endpoint: string;
  apiKey?: string;
  isDefault: boolean;
  status: 'online' | 'offline' | 'error';
  temperature?: number;
  maxTokens?: number;
}

// 任务级模型绑定
interface TaskModelBinding {
  taskType: 'syntax' | 'function' | 'qa';     // 语法结构分析 / 代码功能分析 / AI问答
  modelId: string;
}

// 用量限制
interface ModelUsageLimit {
  modelId: string;
  monthlyLimit: number;          // 月度限额 (tokens)
  currentUsage: number;          // 当前已用 (tokens)
  alertThreshold: number;        // 告警百分比 (默认 80)
}

// 模型优先级
interface ModelPriority {
  modelId: string;
  order: number;                 // 调用顺序 (1=最高优先级)
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `ModelCard` | 模型卡片 |
| `ModelForm` | 模型配置表单 |
| `StatusDot` | 状态点 (复用) |

## 5. 交互逻辑

- 点击"添加模型" → 打开配置表单
- 点击"编辑" → 编辑模型配置
- 点击"测试" → 测试模型连接
- 点击"设为默认" → 设置默认模型
- 点击"删除" → 删除模型配置

## 6. 样式规范

- 卡片圆角：8px
- 默认模型：金色边框
- 状态点：在线=绿色，离线=灰色，错误=红色

## 7. 文件结构

```
src/components/settings/
├── ModelConfig.vue
├── ModelCard.vue
└── ModelForm.vue
```
