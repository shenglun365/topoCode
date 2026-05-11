# SettingsTabBar 组件设计

> 设置页顶部 Tab 导航 (6 项)

---

## 1. 组件职责

- 提供设置页 Tab 导航入口
- 高亮当前激活 Tab
- 响应点击切换设置子页面

## 2. Tab 列表

| Tab | id | 图标 | 说明 |
|-----|-----|------|------|
| AI 模型 | `ai` | 🤖 | LLM 模型配置、任务级绑定、用量限制、模型优先级 |
| Agent 管理 | `agents` | 🔧 | 外部 CLI Agent 配置与测试 |
| SKILL 管理 | `skills` | 🧩 | 设计契约校验拓展开关 |
| 通用设置 | `general` | ⚙️ | 主题、语言、HTTP 服务、字体 |
| 插件管理 | `plugins` | 🔌 | 语言解析器插件安装与管理 |
| 关于 | `about` | ℹ️ | 版本信息、检查更新、查看日志 |

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `activeTab` | `string` | `'ai'` | 当前激活的 Tab id |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `tab-change` | `{ tab: string }` | Tab 切换事件 |

## 4. 交互逻辑

- 点击 Tab → emit `tab-change` → 父组件切换右侧设置内容
- 激活态：底部 2px 高亮条 `var(--accent)`
- 悬停态：背景色 `var(--bg-hover)`

## 5. 样式规范

- 高度 36px
- 背景 `var(--bg-secondary)`
- Tab 项高度 36px，padding: 0 16px
- 激活态底部 2px solid `var(--accent)`

## 6. 文件结构

```
src/components/settings/
└── SettingsTabBar.vue
```
