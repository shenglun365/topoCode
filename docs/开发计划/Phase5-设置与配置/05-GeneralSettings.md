# GeneralSettings 组件设计

> 通用设置，管理主题/语言/字体/自动保存/HTTP 服务

---

## 1. 组件职责

- 提供通用设置项
- 支持主题/语言/字体/自动保存配置
- 配置本地 HTTP 服务（知识库文档 URI 访问）

## 2. 布局结构

```
┌──────────────────────────────────────────────┐
│ 通用设置                                      │
├──────────────────────────────────────────────┤
│                                              │
│ 外观                                         │
│ 主题: [☀️ 亮色] [🌙 暗色] [💻 系统]          │
│ 语言: [简体中文 ▼]                            │
│ 代码字体大小: [━━━━━●━━━] 13px               │
│ 自动保存间隔: [60 秒 ▼]                       │
│                                              │
├──────────────────────────────────────────────┤
│ 本地 HTTP 服务                                │
│                                              │
│ ┌──────────────────────────────────────────┐ │
│ │ 知识库文档本地访问: [✓]                   │ │
│ │ 端口: [8080]    地址: http://localhost:8080│ │
│ │ [🔗 测试连接] [🌐 浏览器打开]             │ │
│ │                                          │ │
│ │ 可用 URI 路径:                            │ │
│ │ /kb/docs/<文档ID>        — 浏览模式打开    │ │
│ │ /kb/docs/<文档ID>/edit   — 编辑模式打开    │ │
│ └──────────────────────────────────────────┘ │
│                                              │
└──────────────────────────────────────────────┘
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `settings` | `GeneralSettings` | - | 设置数据 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `update` | `{ settings: GeneralSettings }` | 更新设置 |

### 数据结构

```typescript
interface GeneralSettings {
  theme: 'dark' | 'light' | 'system';
  language: 'zh' | 'en';
  fontSize: number;              // 代码字体大小 10-20
  autoSaveInterval: number;      // 自动保存间隔 (秒), 0=关闭
  httpServer: {
    enabled: boolean;            // 是否启用 HTTP 服务
    port: number;                // 端口号 (默认 8080)
  };
}
```

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `SettingSection` | 设置分组 |
| `SettingItem` | 设置项 |
| `SelectBox` | 下拉选择 |
| `ToggleSwitch` | 开关 |
| `InputField` | 输入框 |
| `SliderControl` | 滑块控件 |

## 5. 交互逻辑

- 修改设置 → 自动保存到 electron-store
- 主题切换 → 实时更新 CSS 变量
- 语言切换 → 提示重启
- HTTP 端口修改 → 验证端口可用性 → 重启 HTTP 服务
- "测试连接" → 发送 GET 请求到 `http://localhost:{port}/kb/docs/`
- "浏览器打开" → Electron shell.openExternal

## 6. 样式规范

- 设置分组：标题 + 分隔线
- 设置项：标签 + 控件，padding 8px 0
- 按钮：次要操作样式

## 7. 文件结构

```
src/components/settings/
├── GeneralSettings.vue
├── SettingSection.vue
├── SettingItem.vue
├── SelectBox.vue
├── ToggleSwitch.vue
├── SliderControl.vue
└── InputField.vue
```
