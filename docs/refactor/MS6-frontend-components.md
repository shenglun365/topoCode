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
| **W0 安全网** ✅ | 六目标件 vitest 挂载冒烟+交互守卫（Vue 原生 createApp 挂载，零新依赖；两域 vitest 补 vue 插件口径已统一） | architect 64/64 + workbench 19/19 + 双域 typecheck 干净 | 1.5d |
| **W1 AssetManagementWorkspace**（3,296） | 按 tab/区域拆子组件 + composables（数据加载/选择态/批量操作） | W0 测试全绿+新增覆盖；`vue-tsc` 零新错 | 1.5d |
| **W2 SemanticGraphView**（2,649） | 拆三层：SVG 渲染 / 交互（zoom-pan/视口判定 nodeVisibleInViewport）/ 数据变换 | 同上 | 1.5d |
| **W3 AnalysisChat**（2,383） | 拆消息渲染/输入区/会话态 composables | 同上 | 1d |
| **W4 ReportHome + ProjectCard**（1,443+1,441） | 各拆子组件+composables | 同上 | 1.5d |
| **W5 community-store 抽 useComponentAnalysis**（1,252） | 组件分析逻辑抽 composable，store 瘦身为状态容器 | 同上 | 1d |
| **W6 收尾** | types 死类型清理 + **DiagramViewer 裁决已定案（2026-09-25 方案A：留 web-core；RebuildDialog=私有子件标注已落）**+ 文档回写 | 全套件+milestones 更新 | 1d |

**合计 ~9 人日**（与原估算一致）。tag 计划：开工前 `git tag pre-MS6`。

## 4. 风险与缓解
| 风险 | 缓解 |
|---|---|
| 大组件隐式依赖（provide/inject、事件总线、store 直引） | W0 先做依赖盘点（grep inject/emit/$bus）入档再动刀 |
| 拆出后 props 钻透过深 | 允许 composables 内直引 store（项目既有模式），不强推纯 props |
| 用户在途工作冲突 | 每批开工前核 git status；涉 chat/ 目录先协调 |
| vitest 对大组件挂载超时 | shallowMount+关键子组件 stub |

## 5. 与其他里程碑的接口
- W6 DiagramViewer 裁决**已定案（方案A 留 web-core）**——MS7-W3 无迁移联动；重评触发条件（第 3 消费应用/需求分叉）已写入组件头注
- 不依赖 MS5-V3B / MS7，可**立即开工**


---

## 6. W0 执行记录（2026-09-25）

### 6.1 依赖盘点（动刀前入档）
| 目标 | props/emits | 外部依赖面 | inject/provide |
|---|---|---|---|
| AssetManagementWorkspace | 无 props / 无 emits | api-client + semantic-asset/git/kb-assets/requirement 四服务；useRouter（import 了但**未实际使用**——W1 顺带清除） | 无 |
| SemanticGraphView | tab/diffFiles/compareData/fileIndex... / emit close | settings-store + semantic-asset-service；自含 GraphTabDef/GraphFileEntry 导出 | 无 |
| AnalysisChat | turns/busy/busyLabel... / emit send、set-analysis-mode... | api-client；contract/naming/kb-analysis 均 type-only | 无 |
| ReportHome | taskId/tabId / emit open-md、open-presummary | project/analysis/report/community 四 store + ipc + display-dispatcher | 无 |
| ProjectCard | project / emit select | project store + ipc | 无 |
| community-store | ——（store） | ipc/llmClient/control-dispatcher/sound + analysis/project store；模块级 ref：pipelineSummary/agentCompletedSignal | 无 |

**盘点结论**：六件均无 inject/provide 纠缠，拆分只需处理 props/emits/store 三类边界——比预估干净。

### 6.2 安全网落地
- 新增 6 文件 / 20 例：architect 3 文件 10 例（AMW 挂载+页头+重复挂载；SGV 空索引+**FILE_BUDGET 规模闸门守卫**+命名空间渲染；AC 空挂载+busyLabel 覆盖/**默认回落**（真实 i18n key `requirement.chat.thinking`）+turns 渲染）
- workbench 3 文件 10 例（RH 挂载+重复挂载+空态；PC 名称渲染+**点击 emit select**（h() + onSelect 捕获）+pinned 样式位；CS **15 键运行时形状守卫**+模块信号量+动作面>10+getSelections 默认值）
- 挂载方式：Vue 原生 `createApp`（@vue/test-utils 因 registry 无授权不可装——零新依赖方案）；emit 捕获用 `h()` 透传 `onXxx`
- 桩策略：服务面 Proxy 全桩 + RICH 默认形状（items/total/counts/status...）；jsdom 缺 API 补桩（ResizeObserver/scrollTo）
- 门禁：architect **64/64**、workbench **19/19**、双域 `vue-tsc --noEmit` 干净
