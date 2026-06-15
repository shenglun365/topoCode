# AI 助手架构分析引导

## 1. 现状与问题

### 1.1 现有 AI 能力（已实现但入口分散）

当前系统已具备一套完整的 AI 驱动的架构分析能力，但分散在多个入口中，用户很难统一使用：

| 能力 | 入口 | 触发方式 | 输出 |
|------|------|---------|------|
| **项目概要总结** | ReportHome 卡片 | 点击"生成 AI 摘要"按钮 | 500 字以内的项目描述（README + 依赖分析） |
| **总体架构文档** | SubDocRegenDialog / ChatView 快捷操作 | 手动点击"生成架构文档" | Markdown 格式的完整架构文档（含层次、职责、模式、质量评估） |
| **社区命名与分析** | CommunityTagView + 批量分析按钮 | 选中社区 → 点击批量分析 | JSON：name + summary + mermaid + plantuml |
| **社区解释** | 图中右键 → 查看详情 | 右键菜单 | Markdown 社区详情（已存结果或重新生成） |
| **符号/边解释** | 代码浏览页面 | 右键/悬停 | 自然语言解释 |
| **版本对比** | 图顶栏 📊 按钮 | 手动选择版本 | 新增/删除/变更列表 |
| **架构追踪** | AI 面板 `/arch` 命令 | 手动输入 | 变更摘要 |
| **Agent 批量分析** | 右面板 Agent tab | 启动 agent 工作流 | 异步队列处理，进度推送 |

### 1.2 核心问题

1. **入口分散**：用户需要知道功能藏在哪里才能使用，每个功能有独立的操作路径
2. **缺乏引导**：无明确目的的用户打开页面后面对空白图和 15+ 按钮，不知道从何开始
3. **各能力之间无关联**：项目概要、架构文档、社区分析是独立触发的，无法在一个对话中串联
4. **图和控制面板分离**：AI 说话无法影响图展示，用户需要手动操作才能看到 AI 提到的内容

### 1.3 设计目标

- **统一入口**：AI 助手面板成为所有架构分析能力的统一入口，用户通过自然语言或点击引导即可使用任意能力
- **渐进引导**：无目的用户通过 🎓 引导入口获得从 0→1 的逐步学习路径
- **图-语联动**：AI 说话时图自动同步展示（高亮、下钻、过滤、切换）
- **能力融合**：将项目概要、架构文档、社区分析、版本对比等能力整合到对话流中，AI 根据上下文自动选择和调用

---

## 2. 方案总览

### 2.1 一句话概括

> 在结构图画布上提供一个 🎓 引导入口，点击后打开右侧 AI 助手面板。AI 可以调用所有现有架构分析能力（概要、文档、社区分析、解释、对比），通过对话引导用户逐步了解架构，同时用命令同步控制图展示。

### 2.2 用户使用场景

| 用户类型 | 场景 | 操作路径 |
|---------|------|---------|
| **无目的用户** | "这个项目是干什么的？架构怎么样？" | 点击 🎓 图标 → AI 自动引导 |
| **探索型用户** | "让我看看某某社区的细节" | 双击社区节点 → AI 自动解释 |
| **分析型用户** | "哪些社区质量差？和上次比有什么变化？" | 自由打字提问 → AI 调取数据 + 操作图 |
| **报告型用户** | "帮我生成一份架构文档" | 打字 "生成架构文档" → AI 生成 |
| **管理者** | "项目整体情况怎么样，画个总结报告" | 点击 "项目概要" 建议 → AI 生成摘要 |

---

## 3. 通信架构

### 3.1 整体架构

```
┌─────────────────────────────────────────────┐
│ CommunityGraphView                           │
│                                             │
│  ┌─────────────────────────┐    ┌───────┐   │
│  │  GraphCanvas             │    │ 🎓    │   │ ← 浮动入口
│  │  (Force/Table/Heatmap)   │    │       │   │
│  └─────────────────────────┘    └───────┘   │
│                                             │
│  provide:   GraphCommandBus (命令发送通道)    │
│  provide:   GraphState     (状态读取通道)    │
│  emit:      open-md        (打开 MD 详情)   │
└──────────────────┬──────────────────────────┘
                   │ provide/inject
                   ▼
┌─────────────────────────────────────────────┐
│ AIAssistantPanel (右面板 AI tab)              │
│                                             │
│  ┌─────────────────────────────────────┐    │
│  │  AI 消息流                           │    │
│  │                                     │    │
│  │  Assistant: 引导话术 + [CMD:] 标签    │    │
│  │  User:    自由提问或点击建议按钮       │    │
│  │                                     │    │
│  │  系统 prompt 中包含:                  │    │
│  │    · 总览：项目概要 + 架构文档内容     │    │
│  │    · 社区：数据 + 分析结果 + 图表      │    │
│  │    · 对比：版本差异 + 变更摘要         │    │
│  │    · 图状态：当前展示上下文            │    │
│  └─────────────────────────────────────┘    │
│                                             │
│  inject: GraphCommandBus (发送命令至图)      │
│  inject: GraphState     (读取图状态)         │
│  call:   社区所有现有 LLM 能力               │
└─────────────────────────────────────────────┘
```

### 3.2 GraphCommandBus（命令总线 → 图）

AIAssistantPanel 向 CommunityGraphView 发送命令的通道。

```typescript
type GraphCommand =
  // === 导航 ===
  | { type: 'highlight'; nodeIds: string[] }
  | { type: 'clearHighlight' }
  | { type: 'focus'; nodeId: string; animate?: boolean }
  | { type: 'drill'; communityId: string }
  | { type: 'rollUp' }

  // === 筛选 ===
  | { type: 'filterByQuality'; min?: number; max?: number }
  | { type: 'filterByCoreness'; min?: number }
  | { type: 'filterBySize'; min?: number; max?: number }
  | { type: 'hideNodes'; nodeIds: string[] }
  | { type: 'clearFilter' }

  // === 视图 ===
  | { type: 'setViewMode'; mode: 'force' | 'table' | 'heatmap' }
  | { type: 'setEdgeType'; edgeType: EdgeType }
  | { type: 'resetView' }

  // === 快照/对比 ===
  | { type: 'saveSnapshot' }
  | { type: 'compareVersions'; from: string; to: string }

  // === 分析 ===
  | { type: 'openCommunityDetail'; communityId: string }
```

### 3.3 GraphState（图状态 → AI）

CommunityGraphView 向 AIAssistantPanel 暴露当前图状态的通道。每次 AI 请求前自动注入。

```typescript
type GraphState = {
  // 当前视图参数
  edgeType: string
  viewMode: string
  drillLevel: string
  drillCommId: string | null
  selectedCommunityId: string | null

  // 图内容
  nodeCount: number
  visibleNodeIds: string[]

  // 统计数据
  stats: {
    totalL0: number
    avgQuality: number
    lowQualityCount: number   // qualityScore < 0.2
    highCorenessCount: number  // avgCoreness >= 3
    maxDepth: number
    topCommunities: Array<{
      id: string
      name: string
      nodeCount: number
      qualityScore?: number
      avgCoreness?: number
    }>
    lowQualityCommunities: Array<{
      id: string
      name: string
      qualityScore: number
    }>
  }
}
```

### 3.4 AI 回复中的命令嵌入

AI 在输出文本中嵌入 `[CMD: ...]` 标签，前端解析后执行：

```
"我们来看项目里最大的几个社区。
[CMD: highlight nodeIds="L0-utils,L0-service"]
[CMD: focus nodeId="L0-utils"]
L0-utils 有 45 个文件，是最核心的模块..."
```

**解析规则**：
- 正则：`/\[CMD:\s*(\w+)\s*(.*?)\]/g`
- 参数格式：`key="value"` 空格分隔
- 多个命令**串行执行**（等待前一个完成）
- 命令不影响文本显示

---

## 4. AI 助手的能力体系

### 4.1 六大能力模块

AI 助手内置以下六大能力模块，同一份系统 prompt 中全部可用，AI 根据用户意图自动选择：

#### 模块 A：项目概要总结

| 属性 | 说明 |
|------|------|
| 触发方式 | 用户提问 "这个项目是干什么的？" 或 🎓 引导第一步 |
| 数据源 | `ipc.report.getProjectSummary()` → 读取 `projects.summary` |
| 生成方式 | 调用 `report-store.generateProjectSummary(projectId)` → LLM 从 README + 依赖分析生成 |
| 已有接口 | `core_service.py:2548` `report.generateProjectSummary` |
| 前端消费 | `ReportHome.vue` `projectSummaryText`，展示在摘要卡片和弹窗 |
| 整合方式 | AI 读取 `projectSummaryText` 后用自己的话介绍，不直接展示原始文本 |

#### 模块 B：总体架构文档

| 属性 | 说明 |
|------|------|
| 触发方式 | "生成架构文档"、"帮我写一份架构报告" 或 🎓 引导后期 |
| 数据源 | 社区层级的完整数据 + 跨社区边 + 质量分数 + LLM 生成 |
| 生成方式 | `report-store.regenerateOverallDoc()` → 使用 `templateId: 'regenerate_overall_doc'`，结构化模式 |
| 已有接口 | `prompt_templates.json` 中 `report_overall_architecture` / `regenerate_overall_doc` |
| 已有 UI | `SubDocRegenDialog.vue` → 弹出 `SubDocViewer.vue` 展示 Markdown |
| 整合方式 | AI 对话中直接调用 `regenerateOverallDoc()`，结果通过 `open-md` 事件打开详情 tab |

#### 模块 C：社区详解

| 属性 | 说明 |
|------|------|
| 触发方式 | "解释一下 L0-utils"、"这个社区是干什么的" 或双击节点 |
| 数据源 | `community-store` 中的社区数据 + `llmClient.explainCommunity()` |
| 生成方式 | `community-store.runTask()` → `templateId: 'community_analyze'`，结构化输出 `{name, summary, mermaid, plantuml}` |
| 已有接口 | `llmClient.explainCommunity(communityId)` / `community-store.runTask()` |
| 已有 UI | 右键菜单 → `open-md` 事件 → `SubDocViewer.vue` |
| 整合方式 | AI 选择社区后调用 `runTask()` 获取结果，同时用 `[CMD: focus]` 定位到图 |

#### 模块 D：符号/边/代码解释

| 属性 | 说明 |
|------|------|
| 触发方式 | "这个调用是做什么的"（从代码视图中） |
| 接口 | `llmClient.explainSymbol()` / `explainEdge()` / `summarizeCode()` |
| 模板 | `source_explain` / `edge_explain` / `src_to_pseudocode` |
| 整合方式 | AI 对话中可直接调用 `explainSymbol()` 获取解释，无需切换页面 |

#### 模块 E：版本对比与架构追踪

| 属性 | 说明 |
|------|------|
| 触发方式 | "和上次比有什么变化？"、"有哪些新增的社区" 或 🎓 引导 |
| 数据源 | 社区快照时间线 + `community-store` 对比数据 |
| 已有接口 | `compareVersions` / `ArchSentinelWorkflow` / `/diff` 命令 |
| 已有 UI | 📊 对比按钮 + 版本选择 + 图着色（新增绿/删除红/变更橙/不变灰） |
| 整合方式 | AI 调用 `[CMD: compareVersions]` 触发对比，然后读取结果并解读 |

#### 模块 F：Agent 批量分析

| 属性 | 说明 |
|------|------|
| 触发方式 | "分析所有社区"、"批量生成社区文档" |
| 接口 | `community-store.triggerArchAnalysis()` → 后端 `ArchAnalystWorkflow` |
| 进度 | AgentTaskList 面板展示任务进度 |
| 整合方式 | AI 告知用户启动 Agent 任务，引导用户到 Agent tab 查看进度 |

### 4.2 能力调用方式

AI 通过以下三种方式调用能力：

```
1. 读取已有数据（不产生 LLM 调用）
   → 直接读取 graphState / communityStore / projectSummaryText
   → 示例："这个项目有 23 个 L0 社区..."

2. 调用前端现有 LLM 接口（复用已有 prompt 模板）
   → 通过 JavaScript Function Calling 或预设动作
   → 示例："让我帮你生成一份架构文档" → 调用 regenerateOverallDoc()

3. 通过 AI 对话生成（利用 AI 自身能力）
   → 通过消息上下文传递数据，AI 直接回复
   → 示例："这个社区质量低的原因是..."
```

---

## 5. 交互设计

### 5.1 完整用户路径

#### 场景 A：🎓 引导模式（无目的用户）

```
页面加载 → 看到结构图和 🎓 图标
  ↓ 点击 🎓
右面板展开 + AI 加载引导 prompt
  ↓
AI: "我来带你了解这个项目的架构。
     这个项目包含 {N} 个 L0 社区，覆盖 {M}% 的源文件。
     [CMD: highlight nodeIds="top3"]
     最大的社区是 {name}（{count} 个节点），我们先来看它。"
  ↓
AI: "双击它可以查看内部子社区结构。
     除了结构图，我还可以帮你：
     · 📄 生成架构文档
     · 📊 对比历史版本
     · 🔍 深入了解某个社区
     你想从哪个开始？"
  ↓
→ 用户双击社区 → AI 收到状态变化 → 继续引导子社区
→ 或用户打字 "生成架构文档" → AI 调用 regenerateOverallDoc()
→ 或用户打字 "对比上次版本" → AI 调用 compareVersions()
```

#### 场景 B：普通对话模式（有目的用户）

```
用户直接在 AI 面板打字："解释一下 L0-service 这个社区"
  ↓
AI: "好的，让我查一下 L0-service 的详细信息。
     [CMD: focus nodeId="L0-service"]
     [CMD: highlight nodeIds="L0-service"]
     L0-service 是一个服务层社区..."
  ↓
AI: "需要我深入分析它的子社区，还是看看它依赖了哪些外部包？"
```

#### 场景 C：双击社区触发解释

```
图中双击 L0-utils 节点
  ↓
触发 drill（下钻到子社区） + 同时向 AI 发消息
  ↓
AI: "你已经进入了 L0-utils 的子社区视图。
     它包含 {N} 个子社区:
     · L1-utils-core — 核心工具（质量: 0.85）
     · L1-utils-io    — IO 模块（质量: 0.12 ⚠️）
     ...
     [CMD: focus nodeId="L1-utils-core"]
     需要我详细分析哪个子社区？"
```

### 5.2 引导对话流设计

#### Tour 1：架构全景探索（默认）

```
Step 1: 总览介绍
  → 读取 graphState.stats
  → "这个项目有 {totalL0} 个 L0 社区，最深 {maxDepth} 层级，覆盖了大部分源文件。
     其中 {highCorenessCount} 个是核心组件，{lowQualityCount} 个质量偏低。"
  → [CMD: highlight nodeIds="top3"]

Step 2: 最大社区
  → 取 stats.topCommunities[0]
  → "最大的社区是 {name}（{nodeCount} 节点），我们来看看它的内部结构。"
  → [CMD: focus nodeId="top1"]
  → "双击可以下钻到它的子社区。"

Step 3: 质量诊断
  → 取 stats.lowQualityCommunities
  → "我注意到有 {lowQualityCount} 个社区质量分偏低。"
  → [CMD: filterByQuality max="0.2"]
  → "红色边框的就是这些低质量社区。质量分基于模块度，越低表示内部耦合越弱。"

Step 4: 核心组件
  → "另一方面，有 {highCorenessCount} 个核心组件（k-core ≥ 3）。
     这些组件被大量其他代码依赖，是架构的重中之重。"
  → [CMD: filterByCoreness min="3"]
  → "橙色节点就是核心组件。"

Step 5: 外部依赖
  → "我们来看看这个项目依赖了哪些外部包。"
  → [CMD: setEdgeType edgeType="EXTERNAL_INCLUDE"]
  → "切换到外部依赖视图。"

Step 6: 深入选择
  → "以上是项目的架构概览。接下来你想：
     · 📄 生成完整的架构文档
     · 📊 对比历史版本
     · 🔍 深入了解某个具体的社区
     · 💡 自由提问"
```

#### Tour 2：质量深度诊断

```
Step 1: 定位问题
  → "发现 {lowQualityCount} 个低质量社区。"
  → [CMD: filterByQuality max="0.2"]

Step 2: 逐个分析
  → 用 explainCommunity() 获取最差社区的分析
  → "最差的是 {name}（{score}），原因是..."

Step 3: 生成改进建议
  → "需要我对这些低质量社区生成详细的改进建议吗？"
  → 用户确认 → 调用 regenerateCommunityDoc() 生成文档
```

#### Tour 3：版本对比（有时间线数据时）

```
Step 1: 检测可用快照
  → 读取 timeline 数据
  → "当前有 {N} 个历史版本可用，需要对比吗？"

Step 2: 执行对比
  → [CMD: compareVersions from="prev" to="curr"]

Step 3: 解读变化
  → "对比上次分析，有以下变化：
     · 新增 N 个社区（绿色）
     · 移除 M 个社区（红色）
     · K 个社区有变化（橙色）"
  → [CMD: highlight nodeIds="added"]
```

### 5.3 引导模式 vs 普通对话

| 维度 | 🎓 引导模式 | 普通 AI 对话 |
|------|-----------|-------------|
| 触发方式 | 点击 🎓 图标 | 用户主动打开 AI tab |
| 系统 prompt | 含引导指令 + 六大能力描述 + 图状态注入 | 标准 AI 助手 prompt |
| 初始行为 | 主动分析数据，按 Tour 1 逐步引导 | 等待用户提问 |
| 命令权限 | 可执行所有 GraphCommand | 仅用户要求时执行 |
| 图状态注入 | 每次请求自动注入 | 仅用户提及图时注入 |
| 用户打断 | 引导中随时打字提问，AI 回答后继续 | 正常 |
| 何时退出 | 用户关闭右面板 / 清空对话 / 手动说"结束引导" | 无引导概念 |

### 5.4 🎓 入口图标

```
┌────────────────────────────────────────────┐
│  Top Bar  (breadcrumb + search + toolbar)   │
├────────────────────────────────────────────┤
│                                            │
│            Graph Canvas                     │
│                                            │
│                                  ┌──────┐  │
│                                  │  🎓  │  │ ← 右下角浮动
│                                  └──────┘  │
├────────────────────────────────────────────┤
│  Force Bar / Legend                        │
└────────────────────────────────────────────┘
```

- 仅力导向图 / dagre 模式可见
- table / heatmap 模式隐藏
- 全屏模式下隐藏（全屏已有退出按钮，不增加入口）
- 点击后：
  1. 如果右面板折叠 → 自动展开 + 切到 AI tab
  2. 如果右面板已展开 → 直接注入引导 prompt
  3. AI 开始 Tour 1

---

## 6. 前端数据流

### 6.1 数据流动图

```
community-store.ts
  ├── tasks[taskId].communities[]          ← 社区列表
  ├── tasks[taskId].crossCommunityEdges[]  ← 跨社区边
  ├── tasks[taskId].externalStats          ← 外部依赖统计
  └── tasks[taskId].uniqueFileCounts       ← 覆盖文件统计

report-store.ts
  ├── getProjectSummary()                 ← 项目概要
  ├── regenerateOverallDoc()               ← 生成架构文档
  └── regenerateCommunityDoc()             ← 社区文档

llmClient.ts
  ├── chat()  /  explainCommunity()       ← 通用对话 / 社区解释
  ├── explainSymbol() / explainEdge()      ← 符号/边解释
  └── summarizeCommunityName()             ← 社区命名

ai-session-store.ts (或 panelStore)
  └── activeTaskId / activeTaskName        ← AI 当前绑定哪个 task

                                    ↓
                            ┌───────────────┐
                            │ AI assistant  │
                            │  system prompt │
                            └───────┬───────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
            GraphCommandBus    GraphState     LLM 接口调用
            (发命令到图)       (读图状态)     (生成内容)
```

### 6.2 AI 系统 prompt 结构

每次 AI 请求前构建的 messages 数组：

```
messages = [
  // 1. 系统指令（固定）
  { role: 'system', content: SYSTEM_PROMPT },

  // 2. 图状态（随当前图变化）
  { role: 'system', content: `当前图状态:\n${JSON.stringify(graphState)}` },

  // 3. 社区数据（已加载的当前 level 数据，可选）
  { role: 'system', content: `当前社区列表:\n${JSON.stringify(visibleCommunities)}` },

  // 4. 项目概要（可选）
  { role: 'system', content: `项目概要:\n${projectSummaryText}` },

  // 5. 历史对话
  ...previousMessages,
]
```

### 6.3 建议动作（Suggestion Chips）

AI 回复末尾附带建议动作芯片，用户点击即可触发：

```
AI: "以上是 L0 层的概览，接下来你想了解什么？"

[Suggestion Chips]
[子社区结构] [外部依赖] [质量分析] [生成文档]
```

建议由 AI 生成（在回复文本中用 `[SUGGEST: label="子社区结构" command="drill" args="..."]` 标签输出），或者由前端根据当前上下文自动生成默认建议。

---

## 7. 整合现有功能清单

### 7.1 无需改动的现有功能

以下功能已有完整实现，AI 助手通过对话/命令接入，不修改原有逻辑：

| 功能 | 文件 | 接入方式 |
|------|------|---------|
| 社区数据读取 | `community-store.ts` | AI 直接读取 store |
| 跨社区边加载 | `community-store.loadCrossCommunityEdges()` | AI 命令触发 |
| 社区节点列表 | `community-store.loadCommunityNodeLists()` | AI 命令触发 |
| 社区命名/分析 | `community-store.runTask()` / `llmClient.explainCommunity()` | AI 调接口 |
| 批量分析 | `community-store.triggerArchAnalysis()` → Agent 工作流 | AI 引导用户 |
| 社区详情打开 | `open-md` 事件 → SubDocViewer | AI 命令触发 |
| 图渲染 | `CytoscapeGraph.vue` | 通过 props 驱动，不直接改 |
| 筛选面板 | `NodeFilterPanel.vue` | 通过 hiddenIds 驱动 |
| 对比模式 | `CommunityGraphView.vue` compareActive | 命令触发 |
| 全屏 | `useGraphFullscreen` | 命令触发（可选） |

### 7.2 需要新增/改动的功能

| 功能 | 涉及文件 | 改动说明 |
|------|---------|---------|
| GraphCommandBus | 新增 `src/composables/useGraphCommandBus.ts` | provide/inject 命令总线 |
| GraphCommand 类型 | 新增 `src/types/graph-commands.ts` | 命令联合类型 + GraphState 接口 |
| GraphCommand 解析 | 新增 `parseCommandTag()` | AI 回复中的 `[CMD:]` 标签解析 |
| 🎓 入口按钮 | `CommunityGraphView.vue` | 右下角浮动图标 |
| 命令执行 | `CommunityGraphView.vue` `executeCommand()` | 路由到已有方法 |
| 引导 prompt | `AIAssistantPanel.vue` | 引导模式的系统 prompt |
| 图状态注入 | `AIAssistantPanel.vue` | 每次请求前注入 graphState JSON |
| CMD 标签解析 | `AIAssistantPanel.vue` | 流式完成后解析并执行命令 |
| suggestion chips | `AIAssistantPanel.vue` | 解析 `[SUGGEST:]` 标签展示建议按钮 |
| 自动触发社区解释 | `CommunityGraphView.vue` | 双击节点时同步向 AI 发送上下文 |

### 7.3 不改动的文件（重申）

- `CytoscapeGraph.vue` — 所有命令通过 CommunityGraphView 的现有方法转发
- `RightPanel.vue` / `panelStore` — 用现有 toggleRight / setRightTab
- `community-store.ts` — 只消费，不修改
- `report-store.ts` — 只消费，不修改（保持 generateOverviewDoc 等独立可用）
- `llmClient.ts` — 只消费，不修改
- `NodeFilterPanel.vue` / `GraphToolbar.vue` / `GraphBreadcrumb.vue` — 不动

---

## 8. 实现计划

### 8.1 实现步骤

| 步骤 | 内容 | 文件 | 预估行数 |
|------|------|------|---------|
| 1 | GraphCommand + GraphState 类型定义 | `src/types/graph-commands.ts` | 50 |
| 2 | GraphCommandBus provide/inject composable | `src/composables/useGraphCommandBus.ts` | 70 |
| 3 | `[CMD:]` 标签解析函数 | `src/types/graph-commands.ts` 或独立 util | 30 |
| 4 | CommunityGraphView 🎓 按钮 + provide command bus | `CommunityGraphView.vue` | 40 |
| 5 | CommunityGraphView executeCommand() 实现 | `CommunityGraphView.vue` | 50 |
| 6 | CommunityGraphView graphState 响应式映射 | `CommunityGraphView.vue` | 30 |
| 7 | AIAssistantPanel inject commandBus + graphState | `AIAssistantPanel.vue` | 30 |
| 8 | AIAssistantPanel 引导模式 prompt | `AIAssistantPanel.vue` | 40 |
| 9 | AIAssistantPanel `[CMD:]` 解析与执行 | `AIAssistantPanel.vue` | 30 |
| 10 | AIAssistantPanel `[SUGGEST:]` 解析与按钮 | `AIAssistantPanel.vue` | 30 |
| 11 | 双击节点自动通知 AI | `CommunityGraphView.vue` | 15 |
| 12 | 引导模式 vs 普通模式切换 | `AIAssistantPanel.vue` | 15 |
| | **总计** | | **~430** |

### 8.2 依赖关系

```
Step 1 (类型) → Step 2 (composable) → Step 3 (解析器)
                                        ↓
Step 4 + Step 5 + Step 6 (CommunityGraphView)  ← 可并行
Step 7 + Step 8 + Step 9 + Step 10 + Step 12 (AIAssistantPanel)  ← 可并行
```

### 8.3 测试验证点

| 验证点 | 方法 |
|--------|------|
| `[CMD:]` 标签解析正确 | 单元测试 parseCommandTag() |
| 命令顺序执行 | 模拟 highlight → focus → drill 串行执行 |
| 图状态同步 | graphState 变化后 debounce 注入 AI context |
| 引导模式入口 | 点击 🎓 后右面板打开 + AI 引导 prompt |
| 普通对话 vs 引导 | 直接开 AI tab 无引导 prompt |
| 双击联动 | 双击节点后 AI 收到上下文消息 |

---

## 9. 风险与注意事项

| 风险 | 说明 | 缓解方案 |
|------|------|---------|
| 命令执行时机 | `[CMD:]` 在流式输出中尚未完成 | 流式**完成后**统一解析执行，不在 chunk 中边收边执行 |
| 状态同步延迟 | 命令执行后图状态变化 → AI 下一次请求才有新状态 | AI 响应前先等待命令执行完毕，再读取最新 graphState 注入 |
| AI 幻觉命令 | 生成不存在的命令类型或参数 | `parseCommandTag` 做白名单校验，未知命令静默忽略 |
| 多命令竞态 | `[CMD: drill X]` 后 `[CMD: focus Y]` → Y 在钻取后的新图中可能不存在 | 串行执行，每个命令完成后等待 nextTick 再执行下一个 |
| 用户操作冲突 | 用户拖拽节点的同时 AI 发 highlight/focus 命令 | 引导模式下用户仍可自由拖拽，AI 命令不影响用户操作 |
| 引导 vs 手动切换 | 用户打开引导后切换到其他 tab 再回来 | 引导上下文保持，连续对话 |
| LLM token 消耗 | 图状态 JSON + 社区数据列表可能很长 | 按需注入（仅注入当前视图相关的数据），不注入全量 community-store |

---

## 10. 附录：现有 AI 接口文档

### 10.1 Prompt 模板清单（`prompt_templates.json`）

| 模板 ID | 用途 | 模式 | 前端调用处 |
|---------|------|------|-----------|
| `community_name` | 社区命名 | structured | `llmClient.summarizeCommunityName()` |
| `community_analyze` | 社区详细分析 | structured | `community-store.runTask()` |
| `report_overall_architecture` | 生成架构文档 | structured | `report-store.regenerateOverallDoc()` |
| `regenerate_community_doc` | 重新生成社区文档 | structured | `report-store.regenerateCommunityDoc()` |
| `regenerate_overall_doc` | 重新生成整体架构文档 | structured | `report-store.regenerateOverallDoc()` |
| `diagram_regenerate_mermaid` | 生成 Mermaid | structured | `report-store.regenerateCommunityDiagram()` |
| `diagram_regenerate_plantuml` | 生成 PlantUML | structured | `report-store.regenerateCommunityDiagram()` |
| `edge_explain` | 解释调用/依赖边 | chat | `llmClient.explainEdge()` |
| `source_explain` | 解释源码符号 | chat | `llmClient.explainSymbol()` |
| `src_to_pseudocode` | 源码转伪代码 | chat | `llmClient.summarizeCode()` |
| `agent_explain_community` | Agent 解释社区 | chat | `llmClient.explainCommunity()` |
| `agent_generate_overview` | Agent 生成概要 | structured | backend ArchAnalystWorkflow |
| `agent_analyze_community` | Agent 分析社区 | structured | backend ArchAnalystWorkflow |
| `agent_summarize_changes` | Agent 总结变更 | structured | backend ArchSentinelWorkflow |

### 10.2 后端 Agent 工作流

| 工作流 | 文件 | 职责 |
|--------|------|------|
| `ArchAnalystWorkflow` | `agent_workflow/workflows/arch_analyst.py` | 社区分析 + 图表生成 + 概览生成 + 持久化 |
| `ArchSentinelWorkflow` | `agent_workflow/workflows/arch_sentinel.py` | 版本对比 → Diff → 变更摘要 |

### 10.3 前端核心 LLM 函数

```typescript
// src/services/llmClient.ts
chat(options: ChatOptions): Promise<string>        // 通用对话（流式 + 结构化）
explainCommunity(communityId: string): Promise<ExplainCommunityResult>
explainSymbol(symbolId: string, fileId: string, ...): Promise<string>
explainEdge(edgeSource: string, edgeTarget: string): Promise<string>
summarizeCode(code: string, language: string): Promise<string>
summarizeCommunityName(community: CommunityItem): Promise<{name, category, summary}>

// src/stores/community-store.ts
analyzeSelected(taskId, modelId, batchSize): Promise<void>   // 批量分析
triggerArchAnalysis(taskId, projectId): Promise<void>         // Agent 工作流

// src/stores/report-store.ts
regenerateOverallDoc(taskId, projectId, prompt?): Promise<void>
regenerateCommunityDoc(taskId, communityId, projectId, prompt?): Promise<void>
getProjectSummary(projectId): Promise<{summary: string; generated_at: string}>
generateProjectSummary(projectId): Promise<{summary: string}>
saveProjectSummary(projectId, summary): Promise<void>

// 图命令协议（新增）
// AI 回复中嵌入 [CMD: type key="val" key="val"] → parseCommandTag() 解析 → executeCommand() 执行
```
