# PluginManager 组件设计

> 语言解析器插件安装与管理

---

## 1. 组件职责

- 展示已安装的语言 AST 解析器插件列表
- 支持启用/禁用/安装/卸载操作
- 显示插件版本、加载状态

## 2. 数据结构

```typescript
interface ParserPlugin {
  id: string;             // 插件标识
  name: string;           // 显示名称
  icon: string;           // 图标 emoji
  version: string;        // 版本号
  engine: string;         // 解析引擎 (默认 Tree-sitter)
  status: 'loaded' | 'loading' | 'not-installed' | 'error';
  progress?: number;      // 加载进度 0-100
  enabled: boolean;       // 启用/禁用
}
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `plugins` | `ParserPlugin[]` | `[]` | 插件列表 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `install` | `{ id: string }` | 安装插件 |
| `uninstall` | `{ id: string }` | 卸载插件 |
| `toggle` | `{ id: string, enabled: boolean }` | 启用/禁用 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `PluginCard` | 单个插件卡片 (名称/版本/状态/开关) |
| `StatusDot` | 复用：状态指示点 |

## 5. 示例插件清单

| 插件 | 图标 | 版本 | 默认状态 |
|------|------|------|----------|
| Python AST 解析器 | 🐍 | v2.1.0 | 已加载 |
| JavaScript AST 解析器 | 📜 | v1.8.0 | 已加载 |
| Java AST 解析器 | ☕ | v1.5.0 | 未安装 |
| Go AST 解析器 | 🐹 | v1.2.0 | 加载中 |

## 6. 交互逻辑

- 已加载插件 → 显示绿色"已加载"标签 + 启用开关
- 加载中插件 → 显示进度条
- 未安装插件 → 显示"安装"按钮
- 错误状态 → 显示红色标签 + 重试按钮

## 7. 样式规范

- 每个 PluginCard: padding 12px, border-bottom 分隔
- 图标 20px，名称 12px 粗体
- 操作按钮右对齐

## 8. 文件结构

```
src/components/settings/
├── PluginManager.vue
└── PluginCard.vue
```
