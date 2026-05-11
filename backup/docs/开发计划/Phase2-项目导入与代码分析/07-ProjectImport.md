# ProjectImport 组件设计

> 项目导入：项目卡片列表 + 拖拽导入 + 项目视图

---

## 1. 组件定位

模块一入口，管理项目导入和浏览。

```
┌─────────────────────────────────────────┐
│ TopoOne                                 │
│ 源码架构分析与可视化教学工具              │
├─────────────────────────────────────────┤
│ 最近项目                                 │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ │
│ │topoOne-ui│ │backend-api│ │data-pipe │ │
│ │Python    │ │Go        │ │Rust      │ │
│ │128 files │ │256 files │ │64 files  │ │
│ │████████  │ │████░░░░  │ │████████  │ │
│ └──────────┘ └──────────┘ └──────────┘ │
├─────────────────────────────────────────┤
│  拖拽项目文件夹到此处 或 [选择文件夹]     │
│  支持: Python / Go / JavaScript / Java  │
└─────────────────────────────────────────┘
```

---

## 2. 子组件结构

```
ProjectImport
├── DefaultView                 ← 默认视图 (无项目选中)
│   ├── PageHeader              ← 标题 + 副标题
│   ├── ProjectCardGrid         ← 最近项目卡片
│   │   └── ProjectCard × N
│   ├── ImportZone              ← 拖拽导入区
│   └── QuickStart              ← 快速入门引导
└── ProjectView                 ← 项目视图 (选中项目后)
    ├── ProjectTitleBar         ← 项目名称 + 状态 + 设置
    ├── ViewModeToggle          ← 文件树 / 任务列表 切换
    ├── FileTreeView            ← 文件树 (条件渲染)
    └── TaskListView            ← 项目内任务 (条件渲染)
```

---

## 3. Props / Emits / Slots

### ProjectImport

| Props | 类型 | 默认值 | 说明 |
|-------|------|--------|------|
| `projects` | `ProjectMeta[]` | `[]` | 项目列表 |
| `selectedProject` | `string \| null` | `null` | 当前选中项目 ID |
| `viewMode` | `'files' \| 'tasks'` | `'files'` | 项目内视图模式 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `select` | `{ projectId: string }` | 选中项目 |
| `deselect` | - | 取消选中 (返回默认视图) |
| `import` | `{ path: string }` | 导入项目 |
| `switch-view` | `{ mode: 'files' \| 'tasks' }` | 切换视图模式 |

### ProjectCard

| Props | 类型 | 说明 |
|-------|------|------|
| `project` | `ProjectMeta` | 项目元数据 |

| Emits | 载荷 | 说明 |
|-------|------|------|
| `select` | `{ projectId: string }` | 点击卡片 |

### ImportZone

| Emits | 载荷 | 说明 |
|-------|------|------|
| `drop` | `{ path: string }` | 拖拽文件 |
| `browse` | — | 点击选择按钮 |

### Slots

| 名称 | 说明 |
|------|------|
| `default` | 默认视图内容 (ProjectCardGrid + ImportZone) |
| `project-view` | 项目视图内容 (FileTree/TaskList + TaskReport) |

---

## 4. 数据模型

```typescript
interface ProjectMeta {
  id: string;
  name: string;
  path: string;
  language: string;
  fileCount: number;
  lastModified: Date;
  syncStatus: 'synced' | 'changed' | 'error';
  analysisProgress: number;  // 0-100
}
```

---

## 5. 状态管理

```typescript
// stores/project.ts
interface ProjectState {
  projects: ProjectMeta[];
  selectedProjectId: string | null;
  viewMode: 'files' | 'tasks';
}

defineActions({
  async importProject(path: string) { /* ... */ },
  selectProject(id: string) { this.selectedProjectId = id; },
  deselectProject() { this.selectedProjectId = null; },
});
```

---

## 6. 交互逻辑

### 6.1 项目导入

- 拖拽文件夹到 ImportZone → 获取路径 → emit `import`
- 点击"选择文件夹" → Electron `dialog.showOpenDialog({ properties: ['openDirectory'] })` → emit `import`
- 导入后调用 `ProjectService.importProject(path)` → 更新项目列表

### 6.2 项目选中

- 点击 ProjectCard → emit `select` → 切换到 ProjectView
- ProjectView 显示项目文件树/任务列表
- 点击"返回" → emit `deselect` → 回到 DefaultView

### 6.3 视图模式切换

- ViewModeToggle: 文件树 / 任务列表
- 左面板同步切换 (文件树 → LeftPanel 显示文件树; 任务 → 显示任务列表)

---

## 7. 样式规范

| 元素 | 尺寸 | 说明 |
|------|------|------|
| ProjectCard | 自适应网格 | 圆角卡片，hover 阴影 |
| ImportZone | 全宽，最小 120px 高 | 虚线边框，hover 高亮 |
| 进度条 | 卡片底部 | green=100%, yellow=<100%, red=error |

---

## 8. 文件结构

```
src/components/pages/home/
├── ProjectImport.vue         ← 根组件
├── DefaultView.vue           ← 默认视图
├── ProjectView.vue           ← 项目视图
├── ProjectCard.vue           ← 项目卡片
├── ProjectCardGrid.vue       ← 卡片网格
├── ImportZone.vue            ← 拖拽导入区
├── QuickStart.vue            ← 快速入门
├── ProjectTitleBar.vue       ← 项目标题栏
└── index.ts
```
