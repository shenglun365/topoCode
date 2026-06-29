# Web UI 设计系统

## 1. 设计理念

### 1.1 核心原则

| 原则 | 说明 |
|------|------|
| **统一不统一** | viewer / chat / code 三个页面共用同一套视觉语言，看起来是同一个产品；但不强制每个页面使用相同的布局组件 |
| **层次分离** | `style.css` 定义「是什么产品」（品牌、色彩、字体、间距），各页面定义「页面做什么」（布局、功能组件） |
| **Viewer 极简、Chat 有度** | 文档和结构图页面保持现有极简工具风格不破坏；Chat 页面在共享视觉语言上增加 AI 科技感的适度修饰 |
| **CSS 变量驱动** | 所有品牌/主题/间距/圆角/阴影通过 CSS 自定义属性控制，不写死任何值 |

### 1.2 三个页面的定位

| 页面 | 角色 | 视觉风格定位 | AI 科技感 |
|------|------|-------------|-----------|
| `viewer.html` | 分析结果查看器（文档+结构图+热力图+文件列表） | 极简技术工具 | 仅 logo+配色暗示 |
| `chat.html` | AI 对话界面（多会话+SSE 流式+Agent） | 产品化对话 UI | 适度点缀（发光、芯片、badge） |
| `code.html` | 源码查看器 | 极简代码 | 不变 |

---

## 2. 文件结构

```
plugins/reports/static/
  ├── style.css           ← 共享设计系统（新增）
  ├── viewer.html         ← 引用 style.css，去掉重复变量/body（改造）
  ├── chat.html           ← 引用 style.css，+ chat 特有样式（新增）
  └── code.html           ← 引用 style.css 或至少共享变量（轻量改造）
```

### 依赖关系

```
style.css（基础层：变量 + reset + 通用组件 + 主题 + 品牌）
  ├── viewer.html（布局层：左右分栏 + 图 + 文档 + 面包屑等）
  ├── chat.html（布局层：侧栏 + 消息气泡 + 输入区，+AI 点缀）
  └── code.html（布局层：行号 + 高亮）
```

---

## 3. 共享设计系统（style.css）

### 3.1 CSS 变量

```css
:root {
  /* 品牌色 */
  --accent: #3b82f6;
  --accent-secondary: #8b5cf6;

  /* 背景 */
  --bg: #ffffff;
  --bg-secondary: #f8f9fa;
  --bg-tertiary: #f0f1f3;

  /* 文字 */
  --text: #333333;
  --text-secondary: #666666;
  --text-muted: #999999;

  /* 边框 */
  --border: #dddddd;
  --border-light: #eeeeee;

  /* 代码 */
  --bg-code: #f5f5f5;

  /* 几何 */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;

  /* 阴影 */
  --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.06);
  --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.10);
  --shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.14);

  /* AI 专属（仅 chat 使用） */
  --glow-ai: 0 0 12px rgba(59, 130, 246, 0.12);

  /* 字体 */
  --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, sans-serif;
  --font-mono: "Fira Code", "JetBrains Mono", "Cascadia Code", monospace;

  /* 字号 */
  --font-xs: 10px;
  --font-sm: 12px;
  --font-base: 14px;
  --font-lg: 16px;
  --font-xl: 20px;

  /* 间距 */
  --space-xs: 2px;
  --space-sm: 4px;
  --space-md: 8px;
  --space-lg: 12px;
  --space-xl: 16px;

  /* 头部 */
  --header-height: 40px;

  /* 过渡 */
  --transition-fast: 0.15s;
  --transition-normal: 0.2s;
}
```

### 3.2 暗色模式

```css
[data-theme="dark"],
@media (prefers-color-scheme: dark) {
  :root {
    --accent: #60a5fa;
    --accent-secondary: #a78bfa;

    --bg: #1a1a2e;
    --bg-secondary: #1e1e3a;
    --bg-tertiary: #252545;

    --text: #e0e0e0;
    --text-secondary: #b0b0b0;
    --text-muted: #777777;

    --border: #333333;
    --border-light: #2a2a2a;

    --bg-code: #16213e;

    --shadow-sm: 0 1px 2px rgba(0, 0, 0, 0.2);
    --shadow-md: 0 2px 8px rgba(0, 0, 0, 0.3);
    --shadow-lg: 0 4px 16px rgba(0, 0, 0, 0.4);

    --glow-ai: 0 0 12px rgba(96, 165, 250, 0.15);
  }
}
```

### 3.3 主题切换机制

```javascript
// localStorage key = 'theme'
// 值: 'light' | 'dark' | 'system'
// 页面加载时立即读取并设置 <html data-theme="...">
// system 模式监听 prefers-color-scheme change

function getTheme() {
  const saved = localStorage.getItem('theme') || 'system';
  if (saved !== 'system') return saved;
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function setTheme(mode) {
  localStorage.setItem('theme', mode);
  document.documentElement.dataset.theme = getTheme();
}
```

- 切换选项：`light` ↔ `dark`（按钮单击轮换），`system`（长按/设置菜单可选）
- 所有页面共享同一个 `localStorage` key，切换后同源页面即时生效

### 3.4 自定义主题（可扩展）

用户可在 `~/.topocode/theme.json` 中覆盖变量：

```json
{
  "light": { "--accent": "#6366f1", "--bg": "#fafafa" },
  "dark":  { "--accent": "#818cf8", "--bg": "#0f0f1a" }
}
```

加载流程：页面初始化 → 读取 theme.json（如果存在）→ 合并到 CSS 变量 → 渲染。

---

## 4. I18N

### 4.1 机制

轻量无依赖，全局函数 + localStorage 持久化：

```javascript
const i18n = {
  locale: localStorage.getItem('locale') || (navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US'),
  strings: {
    'zh-CN': { /* ... */ },
    'en-US': { /* ... */ },
  },
  t(key, ...args) {
    let s = this.strings[this.locale][key] || key;
    args.forEach((a, i) => s = s.replace(`{${i}}`, a));
    return s;
  }
};
```

### 4.2 字符串表范围

**共享通用**（~15 键）：

```
返回首页    ← Back
加载中…    Loading…
错误        Error
重试        Retry
取消        Cancel
确定        OK
搜索…       Search…
```

**chat 特有**（~30 键，在 chat.html 内定义）：

```
新建会话    New Session
发送        Send
输入消息…   Type a message…
模型选择    Model Selection
引用        Reference
正在查询…   Querying…
会话已归档  Session archived
```

**viewer 特有**（替换现有 `_(key)` 模式，~10 键）

### 4.3 语言选择器

- 位置：header 右侧，主题切换按钮旁
- 形态：语言缩写按钮 `中` / `EN`
- 点击切换，reload 并持久化到 `localStorage`
- 默认规则：browser 语言 `zh` → `zh-CN`，否则 `en-US`

---

## 5. 品牌识别

### 5.1 Logo

```html
<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" stroke-width="2.5"
     stroke-linecap="round" stroke-linejoin="round">
  <circle cx="12" cy="5" r="2.5"/>
  <circle cx="5" cy="19" r="2.5"/>
  <circle cx="19" cy="19" r="2.5"/>
  <line x1="11" y1="7" x2="6" y2="17"/>
  <line x1="13" y1="7" x2="18" y2="17"/>
  <line x1="7" y1="19" x2="17" y2="19"/>
</svg>
```

- 三个节点 + 三条边，抽象表示代码结构图中的节点/边
- 颜色使用 `--accent`，跟随主题自动变化

### 5.2 Wordmark

- "TopoCode" 文字，紧跟 logo 右侧
- `font-weight: 600; font-size: 14px; color: var(--text)`
- 在 chat 页面可以加后缀：「TopoCode AI」

### 5.3 顶部渐变线

header 上边缘 2px 高渐变色线，替代纯色 `border-top`：

```css
.header {
  border-top: none;
  background-image: linear-gradient(to right, var(--accent), var(--accent-secondary));
  background-size: 100% 2px;
  background-repeat: no-repeat;
  background-position: top;
}
```

### 5.4 Viewer 品牌改动范围（最小侵入）

| 位置 | 现有状态 | 改动后 |
|------|----------|--------|
| header 左端 | 无 logo | 加 logo + "TopoCode" |
| header 顶部 | 纯色 `border-bottom: 1px solid var(--border)` | 顶部加 2px 渐变线 |
| header 右端 | 仅「返回首页」链接 | 增加 ☀/🌙 + 语言切换按钮 |
| 页面主体 | 不变 | **不做任何改变** |

三个改动均不侵入文档、图、热力图等核心功能区域。

---

## 6. AI 科技感（chat 专有）

### 6.1 AI 消息气泡微发光

仅 `.message.ai` 有，用户消息没有，刻意区分人机感：

```css
.message.ai {
  box-shadow: var(--glow-ai);
}
```

### 6.2 AI 打字指示器

LLM 生成过程中的三个脉冲点动画：

```css
.typing-indicator span {
  width: 6px; height: 6px;
  border-radius: 50%;
  background: var(--accent);
  opacity: 0.4;
  animation: typingPulse 1.2s ease-in-out infinite;
}
@keyframes typingPulse {
  0%, 100% { opacity: 0.4; transform: scale(1); }
  50% { opacity: 1; transform: scale(1.3); }
}
```

### 6.3 引用上下文芯片

```
┌─ [doc] 社区文档: CoreModule ─ [✕] ─┐
│  该社区负责核心模块的依赖管理...       │
└──────────────────────────────────────┘
```

- 左侧 3px 竖条：doc=蓝(`--accent`)，graph=紫(`--accent-secondary`)
- 圆角容器，浅灰色背景，右上角关闭按钮

### 6.4 模型 badge

```
[DeepSeek V4 Pro] [API]
```

- `[本地]` → `background: rgba(59,130,246,0.1); color: var(--accent)`
- `[API]` → `background: rgba(139,92,246,0.1); color: var(--accent-secondary)`

### 6.5 Tool 调用中间状态

```
┌─ 📊 正在查询社区数据… ──────────┐
│  工具: topocode_community        │
│  参数: edgeType=INCLUDE, level=0 │
└──────────────────────────────────┘
```

- 已有 spinner 动画复用
- 执行完成后自动替换为结果摘要或消失

### 6.6 几何点状背景（chat 专属）

```css
.chat-messages {
  background-image: radial-gradient(circle, var(--border-light) 1px, transparent 1px);
  background-size: 20px 20px;
}
```

---

## 7. 页面布局统一约定

### 7.1 Header

```
┌─ 2px 渐变线（accent → accent-secondary）─────────────────────────┐
│ [logo] TopoCode  [页面标题]              [☀/🌙] [中/EN] [返回]    │
│────────────────────────────────────────────────────────────────────│
```

- `height: 40px`
- 左侧：logo + wordmark + 页面标题
- 右侧：主题切换 + 语言切换 + 其他链接
- header 底部 `1px solid var(--border)` 分割线

### 7.2 通用组件

| 组件 | 定义位置 | 使用页面 |
|------|----------|----------|
| `.btn` | style.css | viewer, chat |
| `.btn.active` | style.css | viewer, chat |
| `.link` | style.css | viewer, chat, code |
| `.badge` | style.css | chat |
| `.loading` | style.css | viewer, chat, code |
| `.error-msg` | style.css | viewer, chat, code |
| `.tabs` / `.tab-item` | style.css | viewer |
| `.ellipsis` | style.css | viewer, chat |
| `.text-muted` | style.css | viewer, chat, code |
| `.mono` | style.css | viewer, chat, code |
| `.fade-in` | style.css | viewer, chat |

---

## 8. I18N 字符串完整表

### 8.1 共享表（style.css 附带 JS）

```javascript
const _sharedStrings = {
  'zh-CN': {
    'back': '← 返回首页',       'loading': '加载中…',
    'error': '错误',             'retry': '重试',
    'cancel': '取消',            'ok': '确定',
    'save': '保存',              'delete': '删除',
    'search': '搜索…',          'close': '关闭',
    'light_mode': '浅色模式',    'dark_mode': '深色模式',
  },
  'en-US': {
    'back': '← Back',           'loading': 'Loading…',
    'error': 'Error',            'retry': 'Retry',
    'cancel': 'Cancel',          'ok': 'OK',
    'save': 'Save',              'delete': 'Delete',
    'search': 'Search…',        'close': 'Close',
    'light_mode': 'Light Mode',  'dark_mode': 'Dark Mode',
  }
};
```

### 8.2 chat 特有表（chat.html 内）

```javascript
const _chatStrings = {
  'zh-CN': {
    'page_title': 'TopoCode AI',
    'new_session': '新建会话',       'send': '发送',
    'input_placeholder': '输入消息…', 'model_select': '模型选择',
    'model_local': '本地',           'model_api': 'API',
    'reference_doc': '引用文档',     'reference_graph': '引用图',
    'tool_running': '正在查询数据…', 'session_archived': '已归档',
    'session_delete_confirm': '确定删除该会话？',
    'session_empty': '暂无会话',     'no_messages': '开始一个新的对话',
    'thinking': '思考中…',          'error_network': '网络错误',
    'error_model': '模型无效',       'stop_generating': '停止生成',
  },
  'en-US': {
    'page_title': 'TopoCode AI',
    'new_session': 'New Session',   'send': 'Send',
    'input_placeholder': 'Type a message…',
    'model_select': 'Model Selection',
    'model_local': 'Local',         'model_api': 'API',
    'reference_doc': 'Doc Reference', 'reference_graph': 'Graph Reference',
    'tool_running': 'Querying data…', 'session_archived': 'Archived',
    'session_delete_confirm': 'Delete this session?',
    'session_empty': 'No sessions yet', 'no_messages': 'Start a new conversation',
    'thinking': 'Thinking…',       'error_network': 'Network Error',
    'error_model': 'Invalid Model', 'stop_generating': 'Stop',
  }
};
```

### 8.3 viewer 特有翻译

```javascript
const _viewerStrings = {
  'zh-CN': { 'toc_title': '子组件目录', 'no_doc': '未解析' },
  'en-US': { 'toc_title': 'Sub-Components', 'no_doc': 'unresolved' }
};
```

---

## 9. 实施路线

| 步骤 | 内容 | 工时 | 前置 |
|------|------|------|------|
| 1 | `style.css` 编写全部变量 + reset + 暗色 + 品牌元素 + 通用组件 | 0.5d | 无 |
| 2 | `viewer.html` 去掉重复变量/body，引用 style.css，加 logo + 主题切换 + i18n | 0.5d | 1 |
| 3 | `code.html` 轻量迁移到共享变量 | 0.2d | 1 |
| 4 | i18n 函数 + 字符串表 + 语言选择器（style.css 附加 JS） | 0.3d | 1 |
| 5 | 主题切换按钮 + localStorage 同步 | 0.3d | 1 |
| 6 | `chat.html` 在此基础上构建（算入 P2.4） | (2d) | 1-5 |
| **合计** | WEB UI 设计系统基础建设 | **1.5d** | |

---

## 10. Viewer 改造对照表

### 10.1 删除部分

从 `viewer.html` `<style>` 中删除变量块、暗色模式、`* { margin/padding/box-sizing }`、`body` 基线规则。

### 10.2 改为引用

```html
<link rel="stylesheet" href="/static/style.css">
```

### 10.3 Header 改动

```html
<div class="header">
  <span class="logo-bar">
    <svg class="logo" ...>...</svg>
    <span class="wordmark">TopoCode</span>
  </span>
  <span class="title" id="docTitle">TopoCode Documents</span>
  <span class="header-right">
    <button id="themeToggle" class="btn-icon" title="切换主题">☀</button>
    <button id="localeToggle" class="btn-icon" title="切换语言">中</button>
    <button id="toggleLeft" class="toggle-btn" title="切换文档栏">📄</button>
    <button id="toggleRight" class="toggle-btn" title="切换结构图栏">🔗</button>
    <a href="/" id="backLink">← 返回首页</a>
  </span>
</div>
```

### 10.4 新增 JS

```javascript
const savedTheme = localStorage.getItem('theme') || 'system';
document.getElementById('themeToggle').textContent = savedTheme === 'dark' ? '🌙' : '☀';
const savedLocale = localStorage.getItem('locale') || (navigator.language.startsWith('zh') ? 'zh-CN' : 'en-US');
document.getElementById('localeToggle').textContent = savedLocale === 'zh-CN' ? '中' : 'EN';
```

### 10.5 viewer 完全不变的区域

文档内容渲染、左右分栏+拖拽、Cytoscape 图、热力图、文件列表、浮动面板、面包屑、图工具栏、筛选面板、上下文菜单、右面板标签页、粒度切换、图叠加层、全部 JS 交互逻辑。

---

## 11. 设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 共享样式方式 | 一个 `style.css` 文件，不拆多文件 | 避免加载过多文件；大小预估 <5KB |
| i18n 实现 | 全局 JS 对象，不引入库 | 无依赖，字符串量小，不需要 ICU 格式 |
| 主题存储 | `localStorage` + `<html data-theme>` | 简单可靠，所有页面共享 |
| 自定义主题 | 可选 `~/.topocode/theme.json`，非必须 | 电力用户需求，不增加基础复杂度 |
| Logo SVG | inline SVG，不依赖外部资源 | 自包含，跟随主题色，无额外请求 |
| 气泡风格 | 单色气泡，通过 `--glow-ai` 区分 AI/用户 | 保持简洁，不与主流聊天 UI 过度竞争 |

---

> **文档状态**: 设计完成
> **关联文档**: `docs/web端AI对话agent能力拓展.md`, `docs/项目结构分析-导出导入设计.md`
> **关联文件**: `plugins/reports/static/style.css`, `plugins/reports/static/viewer.html`, `plugins/reports/static/chat.html`, `plugins/reports/static/code.html`
