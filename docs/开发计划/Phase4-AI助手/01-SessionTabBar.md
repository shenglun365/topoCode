# SessionTabBar 组件设计

> Session Tab 栏，管理多对话会话

---

## 1. 组件职责

- 展示所有 Session Tab
- 支持新建/关闭/切换 Session
- 展示 Session 状态

## 2. 布局结构

```
┌──────────────────────────────────────────────────────┐
│ [● 当前项目] [● 通用对话] [● 历史会话] [+] [搜索]    │
└──────────────────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sessions` | `Session[]` | `[]` | Session 列表 |
| `activeSession` | `string` | `''` | 当前激活 Session ID |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `create` | `void` | 新建 Session |
| `switch` | `{ sessionId: string }` | 切换 Session |
| `close` | `{ sessionId: string }` | 关闭 Session |
| `rename` | `{ sessionId: string, name: string }` | 重命名 Session |

### 数据结构

```typescript
interface Session {
  id: string;
  name: string;
  type: 'project' | 'general' | 'history';
  messages: ChatMessage[];
  createdAt: Date;
  updatedAt: Date;
  status: 'active' | 'idle' | 'error';
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `TabItem` | 单个 Tab |
| `TabActions` | Tab 操作按钮 |
| `TabSearch` | Session 搜索 |

## 5. 交互逻辑

- 点击 Tab → 切换 Session
- 点击"+" → 新建 Session
- 点击"×" → 关闭 Session
- 右键 Tab → 重命名/关闭其他
- 拖拽 Tab → 调整顺序

## 6. 样式规范

- Tab 高度：32px
- 激活 Tab：底部边框高亮
- 关闭按钮：悬停显示
- 新 Session 默认名称："新对话"

## 7. 文件结构

```
src/components/coder/
├── SessionTabBar.vue
├── TabItem.vue
├── TabActions.vue
└── TabSearch.vue
```
