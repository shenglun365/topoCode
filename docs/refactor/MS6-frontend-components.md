# MS6 前端巨型组件拆分（B5）细化设计

> 状态：**待评审**（评审通过后按批执行，每批全绿合入）
> 核证日期：2026-09-25（工作区 clean，基线 dev-1 @ 07ba81c）

## 1. 核证快照（实测）

### architect（vitest 基建 ✓）
| 组件 | 行数 | 路径 | 备注 |
|---|---|---|---|
| AssetManagementWorkspace | **3,296** | src/pages/ | 最大巨石 |
| SemanticGraphView | **2,649** | src/components/assets/ | 手绘 SVG（无图库依赖，zoom-pan/viewBox 自实现） |
| AnalysisChat | **2,383** | src/components/requirements/ | |
| ConversationDock | 951 | src/components/chat/ | 用户在途件已合入（e06d1bd），**软上限内不入本批** |

### workbench（vitest 基建 ✓）
| 目标 | 行数 | 路径 |
|---|---|---|
| ReportHome | **1,443** | src/components/report/ |
| ProjectCard | **1,441** | src/components/project/ |
| community-store | **1,252** | src/stores/ → 抽 useComponentAnalysis（现不存在） |

### 移交项
- **DiagramRebuildDialog + DiagramViewer 共改裁决**（MS2 移交）：web-core 现存 446+ 行 DiagramViewer，消费方 5 处（architect FlowDiagram / chat ChatSession+ChatMessage / docs DocViewer / workbench AIAssistantPanel+ChatView）
- **architect types/index.ts 死类型清理**：Blueprint/KbQuery* 等（MS2 在途保护 deferred）

## 2. 目标 / 非目标
- **目标**：六目标件降至 <800 行/件；每件拆出"子组件 + composables + 类型"三层；行为零变（纯结构重构）
- **非目标**：不改 UI/交互/API 契约；不动 ConversationDock（951 行软上限内）；不做性能优化（除顺带）

## 3. 批次划分（安全网先行，同 MS1 模式）

| 批 | 内容 | 判据（全绿门禁） | 预估 |
|---|---|---|---|
| **W0 安全网** | 六目标件各加 vitest 挂载冒烟+关键交互测试（props/事件/渲染守卫）；type-check+lint+test 基线 | `npm run test` architect+workbench 全绿；新增≥3 例/件 | 1.5d |
| **W1 AssetManagementWorkspace**（3,296） | 按 tab/区域拆子组件 + composables（数据加载/选择态/批量操作） | W0 测试全绿+新增覆盖；`vue-tsc` 零新错 | 1.5d |
| **W2 SemanticGraphView**（2,649） | 拆三层：SVG 渲染 / 交互（zoom-pan/视口判定 nodeVisibleInViewport）/ 数据变换 | 同上 | 1.5d |
| **W3 AnalysisChat**（2,383） | 拆消息渲染/输入区/会话态 composables | 同上 | 1d |
| **W4 ReportHome + ProjectCard**（1,443+1,441） | 各拆子组件+composables | 同上 | 1.5d |
| **W5 community-store 抽 useComponentAnalysis**（1,252） | 组件分析逻辑抽 composable，store 瘦身为状态容器 | 同上 | 1d |
| **W6 收尾** | types 死类型清理 + DiagramRebuildDialog/DiagramViewer 裁决（三选一：留 web-core / 随 MS7 chat 迁移下沉 / 各域复制）+ 文档回写 | 全套件+milestones 更新 | 1d |

**合计 ~9 人日**（与原估算一致）。tag 计划：开工前 `git tag pre-MS6`。

## 4. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 大组件隐式依赖（provide/inject、事件总线、store 直引） | W0 先做依赖盘点（grep inject/emit/$bus）入档再动刀 |
| 拆出后 props 钻透过深 | 允许 composables 内直引 store（项目既有模式），不强推纯 props |
| 用户在途工作冲突 | 每批开工前核 git status；涉 chat/ 目录先协调 |
| vitest 对大组件挂载超时 | shallowMount+关键子组件 stub |

## 5. 与其他里程碑的接口
- W6 的 DiagramViewer 裁决**输入 MS7-W3**（chat 上提时 ChatSession 依赖它——若选"下沉"，随 MS7 迁）
- 不依赖 MS5-V3B / MS7，可**立即开工**
