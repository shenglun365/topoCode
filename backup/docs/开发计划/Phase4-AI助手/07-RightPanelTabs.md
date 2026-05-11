# RightPanelTabs 组件设计

> 右面板 4 Tab，展示 AI 助手的上下文信息

---

## 1. 组件职责

- 提供 4 个 Tab 切换 (代码解析/知识库/Spec/任务配置)
- 动态渲染对应 Tab 内容

## 2. 布局结构

```
┌─────────────────────────────────────────┐
│ [代码解析] [知识库] [Spec] [任务配置]   │
├─────────────────────────────────────────┤
│                                         │
│  [Tab 内容区]                           │
│                                         │
│  代码解析: 文件树/函数列表               │
│  知识库: 相关知识卡片                    │
│  Spec: 设计文档列表                      │
│  任务配置: 任务参数表单                  │
│                                         │
└─────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `activeTab` | `string` | `'code'` | 当前激活 Tab |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `tab-change` | `{ tab: string }` | Tab 切换 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `TabBar` | Tab 切换栏 |
| `CodeParseTab` | 代码解析 Tab |
| `KnowledgeTab` | 知识库 Tab |
| `SpecTab` | Spec Tab |
| `TaskConfigTab` | 任务配置 Tab |

## 5. 交互逻辑

- 点击 Tab → 切换内容
- Tab 内容根据选中项动态更新
- 任务配置 Tab 提供表单输入

## 6. 样式规范

- Tab 栏：底部边框高亮
- Tab 内容：滚动容器

## 7. 文件结构

```
src/components/coder/
├── RightPanelTabs.vue
├── TabBar.vue
├── CodeParseTab.vue
├── KnowledgeTab.vue
├── SpecTab.vue
└── TaskConfigTab.vue
```
