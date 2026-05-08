# StatusBar 组件设计

> 状态栏：全局状态指示

---

## 1. 组件定位

UI Shell 底部固定状态栏，展示系统全局状态信息。

```
┌────────────────────────────────────────────────────────────┐
│ ● Python 后端  AST 就绪  main │ AI: Ollama  UTF-8  100%  │
└────────────────────────────────────────────────────────────┘
  24px high
```

---

## 2. 子组件结构

```
StatusBar
├── StatusSection (left)
│   ├── StatusItem ← Python 后端状态
│   ├── StatusItem ← AST 解析状态
│   └── StatusItem ← Git 分支
├── StatusSpacer
└── StatusSection (right)
    ├── StatusItem ← AI 模型
    ├── StatusItem ← 编码
    └── StatusItem ← 缩放
```

---

## 3. Props / Emits

### StatusBar

| Props | 类型 | 说明 |
|-------|------|------|
| `status` | `GlobalStatus` | 全局状态对象 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `click` | `{ item: string }` | 状态项点击 |

### StatusItem

| Props | 类型 | 说明 |
|-------|------|------|
| `label` | `string` | 显示文本 |
| `status` | `'ok' \| 'warn' \| 'error' \| 'none'` | 状态点颜色 |
| `icon` | `string` | 前置图标 |

---

## 4. 数据模型

```typescript
interface GlobalStatus {
  backend: { connected: boolean; label: string };
  ast: { ready: boolean; label: string };
  git: { branch: string };
  ai: { model: string };
  encoding: string;
  zoom: number;
}
```

---

## 5. 状态管理

```typescript
// stores/status.ts
interface StatusState {
  backend: 'connected' | 'disconnected' | 'error';
  astReady: boolean;
  gitBranch: string;
  aiModel: string;
  encoding: string;
  zoom: number;
}
```

---

## 6. 交互逻辑

- 状态项可点击，触发对应操作 (如点击 AI 模型 → 打开设置)
- 状态点颜色: green=正常, yellow=警告, red=错误, none=无状态
- 状态由各 Service 推送更新

---

## 7. 样式规范

| 元素 | 高度 | 背景 | 文字 |
|------|------|------|------|
| StatusBar | 24px | `var(--bg-secondary)` | `var(--text-muted)` |
| StatusItem | 24px | 透明 → hover `var(--bg-hover)` | 11px |
| 状态点 | 8px×8px | green/yellow/red | 圆角 |

---

## 8. 文件结构

```
src/components/shell/
├── StatusBar.vue         ← 根组件
├── StatusItem.vue        ← 状态项
└── index.ts
```
