# ProjectCard 组件设计

> 项目卡片，展示项目元数据和进度

---

## 1. 组件职责

- 展示项目基本信息 (名称/语言/文件数/进度)
- 响应点击选中项目
- 展示同步状态

## 2. 布局结构

```
┌─────────────────────────────┐
│ topoOne-ui            [Python]│
│ /home/user/projects/topoOne-ui│
│                              │
│ 128 files  ·  3 days ago     │
│ ████████████████████  100%   │
│ ● 已同步                     │
└─────────────────────────────┘
```

## 3. Props / Emits / Slots

### Props

| 属性 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `project` | `ProjectMeta` | — | 项目元数据 |

### Emits

| 事件 | 载荷 | 说明 |
|------|------|------|
| `select` | `{ projectId: string }` | 选中项目 |
| `sync` | `{ projectId: string }` | 同步项目 |

### Slots

| 名称 | 说明 |
|------|------|
| — | 无插槽 |

## 4. 子组件

| 组件 | 说明 |
|------|------|
| `ProgressBar` | 进度条 |
| `LanguageBadge` | 语言标签 |
| `StatusDot` | 状态点 |

## 5. 数据结构

```typescript
interface ProjectMeta {
  id: string;
  name: string;
  path: string;
  language: string;
  fileCount: number;
  lastModified: Date;
  syncStatus: 'synced' | 'changed' | 'error';
  analysisProgress: number;  // 0–100
}
```

## 6. 交互逻辑

- 点击卡片 → emit select 事件
- 悬停显示操作按钮 (同步/删除)
- 进度条颜色：100% 绿色，<100% 黄色，error 红色

## 7. 样式规范

- 卡片圆角：8px
- 悬停阴影：0 2px 8px rgba(0,0,0,0.15)
- 进度条高度：4px
- 语言标签：小型 badge，颜色根据语言变化

## 8. 文件结构

```
src/components/project/
├── ProjectCard.vue
├── ProgressBar.vue
├── LanguageBadge.vue
└── StatusDot.vue
```
