# ChatFlow 组件设计

> 对话消息流，展示用户和 AI 的对话历史

---

## 1. 组件职责

- 展示对话消息列表
- 支持消息滚动加载
- 提供消息输入框

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│                                         │
│  ┌───────────────────────────────────┐  │
│  │ [用户消息]                         │  │
│  │                                   │  │
│  │ [AI 回复]                          │  │
│  │  - 文本回复                        │  │
│  │  - 上下文卡片 (inline)             │  │
│  │  - Spec 卡片 (inline)              │  │
│  │  - 任务状态卡片 (inline)           │  │
│  │                                   │  │
│  └───────────────────────────────────┘  │
│                                         │
├─────────────────────────────────────────┤
│ [💬 普通问答 │ 🏗️ 设计任务]  模式切换   │
├─────────────────────────────────────────┤
│ [输入消息...]              [📎] [发送]  │
│ 模型: Ollama / qwen2.5-coder:7b   [⚙️] │
└─────────────────────────────────────────┘
```

## 2a. 模式切换

输入区上方提供模式切换按钮：

| 模式 | 图标 | 说明 |
|------|------|------|
| 普通问答 | 💬 | 自由对话，AI 基于上下文回答代码相关问题 |
| 设计任务 | 🏗️ | 结构化设计模式，AI 生成 Spec 设计文档 + 调度 Agent 执行 |

模式切换影响：
- **普通问答**: 后端构建 Prompt 时偏重解释、分析、建议
- **设计任务**: 后端构建 Prompt 时偏重生成设计文档、函数签名、约束校验

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `messages` | `ChatMessage[]` | `[]` | 消息列表 |
| `sessionId` | `string` | `''` | Session ID |
| `loading` | `boolean` | `false` | 是否正在加载 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `send` | `{ content: string }` | 发送消息 |
| `stop` | `void` | 停止生成 |
| `scroll` | `{ position: number }` | 滚动位置 |

### 数据结构

```typescript
interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  type: 'text' | 'context' | 'spec' | 'task' | 'error';
  timestamp: Date;
  metadata?: Record<string, any>;
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `MessageList` | 消息列表容器 |
| `ChatMessage` | 单个消息 |
| `MessageInput` | 消息输入框 |
| `LoadingIndicator` | 加载指示器 |

## 5. 交互逻辑

- 输入消息 → 点击发送或按 Enter → emit send 事件
- AI 回复流式显示
- 滚动到顶部 → 自动加载更多历史消息
- 点击"停止" → 停止 AI 生成

## 6. 样式规范

- 用户消息：右侧，蓝色背景
- AI 消息：左侧，灰色背景
- 消息气泡：圆角 8px
- 输入框：底部固定，多行文本

## 7. 文件结构

```
src/components/coder/
├── ChatFlow.vue
├── MessageList.vue
├── ChatMessage.vue
├── MessageInput.vue
└── LoadingIndicator.vue
```
