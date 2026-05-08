# AboutPage 组件设计

> 版本信息、检查更新、查看日志

---

## 1. 组件职责

- 显示应用版本和构建信息
- 提供检查更新入口
- 提供查看日志入口
- 展示技术栈和依赖信息

## 2. 数据结构

```typescript
interface AppInfo {
  version: string;          // 版本号 (如 "1.0.0")
  buildNumber: string;      // 构建号 (如 "20260429")
  electronVersion: string;  // Electron 版本
  nodeVersion: string;      // Node.js 版本
  pythonVersion: string;    // Python 版本
  updateStatus: 'checking' | 'up-to-date' | 'available' | 'error';
  latestVersion?: string;   // 最新版本号
}
```

## 3. Props / Emits

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `appInfo` | `AppInfo` | — | 应用信息 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `check-update` | `void` | 触发检查更新 |
| `view-logs` | `void` | 打开日志文件 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `AppInfoCard` | 版本和技术栈信息卡片 |
| `UpdateButton` | 检查更新按钮 (含状态反馈) |

## 5. 技术栈展示

```
Electron 33.0 · Vue 3.5 · Python 3.12
D3.js 7.9 · Mermaid 11.0 · Tree-sitter
```

## 6. 更新状态映射

| updateStatus | 显示 | 按钮文本 |
|-------------|------|----------|
| `up-to-date` | "已是最新版本" | 检查更新 |
| `checking` | "正在检查..." | (禁用) |
| `available` | "新版本 v{x} 可用" | 下载更新 |
| `error` | "检查更新失败" | 重试 |

## 7. 样式规范

- 居中布局，max-width 600px
- 版本号 16px 粗体
- 技术栈信息 12px，颜色 `var(--text-muted)`
- 按钮组间距 8px

## 8. 文件结构

```
src/components/settings/
├── AboutPage.vue
└── AppInfoCard.vue
```
