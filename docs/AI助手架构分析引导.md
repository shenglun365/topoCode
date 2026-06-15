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
| **版本对比** | 工具栏 ⋮ 菜单 → 对比架构 | 手动选择版本 | 新增/删除/变更列表 |
| **架构追踪** | AI 面板 `/arch` 命令 | 手动输入 | 变更摘要 |
| **Agent 批量分析** | 右面板 Agent tab | 启动 agent 工作流 | 异步队列处理，进度推送 |

### 1.2 核心问题

1. **入口分散**：用户需要知道功能藏在哪里才能使用，每个功能有独立的操作路径
2. **缺乏引导**：无明确目的的用户打开页面后面对空白图，不知道从何开始
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

## 3. Agent 系统分层架构

### 3.1 总览

```

RouterHarness (Harness 层)
router.py:39
  dispatch(action, context)         → 路由到 Workflow 或 Skill
  dispatch_nl(nl, llm_fn)           → LLM 自然语言分类路由
  │
  │  注册：RouteEntry(workflow_class, tool_builder, sandbox_builder, context_transformer)
  │
  ▼
┌───────────────────────────────────────────────────┐
│ Skills 层 (技能编排)                                │
│ skill_executor.py + workflows/arch_analyst.py      │
│                                                    │
│  SkillDefinition                                   │
│    name: "skill_batch_analyze_communities"          │
│    steps: [SkillStepDef, ...]                       │
│    input_schema: {...}                              │
│                                                    │
│  每步 SkillStepDef:                                 │
│    name: 步骤名                                     │
│    tool: AgentTool 引用（不是 dispatcher handler）   │
│    post_process: 可选后处理                          │
│                                                    │
│  预置 Skills (4个):                                 │
│  ┌─────────────────────────────────────────────┐    │
│  │ skill_analyze_community          (D1)       │    │
│  │ skill_generate_diagram            (D2)      │    │
│  │ skill_generate_arch_overview     (D3)       │    │
│  │ skill_batch_analyze_communities   (D4)      │    │
│  └─────────────────────────────────────────────┘    │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────────────────┐
│ Tool 层 (原子能力)                                  │
│ tools.py + tool_factory.py                         │
│                                                    │
│  AgentTool 抽象基类:                                │
│    name / description / version / category         │
│    execute(**kwargs) → ToolResult                  │
│                                                    │
│  ToolRegistry (白名单):                             │
│    register(tool) / get(name) / to_schema_list()   │
│                                                    │
│  内置工具 (tool_factory.py):                        │
│  ┌─────────────────────────────────────────────┐    │
│  │ 分析: _AnalyzeCommunityTool (LLM)           │    │
│  │ 图:   _GenerateDiagramTool  (模板)          │    │
│  │ 总览: _GenerateOverviewTool (LLM)           │    │
│  │ 持久: _SaveResultsTool      (DB)            │    │
│  │ Sentinel: _SnapshotTool / _DiffTool /       │    │
│  │           _SummarizeTool / _SaveDeltaTool   │    │
│  └─────────────────────────────────────────────┘    │
└────────────────┬────────────────────────────────────┘
                 │
                 ▼
┌───────────────────────────────────────────────────┐
│ AgentRuntime (运行时层)                              │
│ runtime.py                                         │
│  run(workflow, tools, sandbox) → WorkflowResult    │
│                                                    │
│  核心循环:                                          │
│  1. workflow.plan(context) → list[SkillRef]        │
│  2. for each SkillRef:                             │
│       SkillExecutor.resolve(name) → SkillDefinition│
│       for each SkillStepDef:                       │
│         tool = tools.get(step.tool_name)           │
│         tool.execute(**step.args)                  │
│         sandbox 验证 + 重试 + 进度上报              │
│  3. workflow.finalize(results) → WorkflowResult    │
└────────────────┬────────────────────────────────────┘
                 │
     ┌───────────┼───────────┐
     ▼           ▼           ▼
┌─────────┐ ┌─────────┐ ┌────────────┐
│ Sandbox │ │ Memory  │ │ Workflow   │
│ 安全约束  │ │ 上下文   │ │ plan +     │
│ sandbox │ │ memory  │ │ finalize   │
│ .py     │ │ .py     │ │ base.py    │
│         │ │         │ │            │
│ Path    │ │ 跨步骤   │ │ ArchAnalyst│
│ Sandbox │ │ 传递     │ │ ArchSent. │
│ Content │ │         │ │            │
│ Guard   │ │         │ │            │
│ Rate    │ │         │ │            │
│ Limiter │ │         │ │            │
│ Budget  │ │         │ │            │
│ Tracker │ │         │ │            │
└─────────┘ └─────────┘ └────────────┘
```

### 3.2 Skills 层与标准 Agent 的区别

| 维度 | 标准 Agent (OpenAI/LangChain) | Skills Agent (topocode) |
|------|------------------------------|------------------------|
| 规划方式 | LLM 实时决策每一步 | Workflow.plan() 输出预制 Skill 序列 |
| 工具粒度 | 原子 Tool | Skill（Tool 组合），内部含多个步骤 |
| LLM 调用 | 高频（每步决策都可能调） | 低频（仅 Skill 内部 Tool 执行用） |
| 可观测性 | 模型黑盒 | 步骤 + Skill 命名完全可见 |
| 复用性 | LLM 自组合 | SkillDefinition 定义一次，多处复用 |
| 适用场景 | 开放式探索 | 重复性高的确定流程（批量社区分析） |

### 3.3 Skills 定义清单

#### D1. `skill_analyze_community`

| 属性 | 说明 |
|------|------|
| 用途 | 分析单个社区（名称 + 功能摘要） |
| 步骤 | 1. `_AnalyzeCommunityTool.execute(community)` → LLM 生成 |
| LLM 调用 | 1 次 |
| 输入 | `task_id, comm_id, edge_type, community_data` |
| 输出 | `{communityId, name, summary}` |

#### D2. `skill_generate_diagram`

| 属性 | 说明 |
|------|------|
| 用途 | 模板化生成 Mermaid/PlantUML |
| 步骤 | 1. `_GenerateDiagramTool.execute(community, children, edges)` → 模板拼接 |
| LLM 调用 | 0 次（纯模板） |
| 输入 | `comm_id, type: "mermaid"|"plantuml"|"both"` |
| 输出 | `{mermaid, plantuml}` |

#### D3. `skill_generate_arch_overview`

| 属性 | 说明 |
|------|------|
| 用途 | 汇总所有社区结果，生成整体架构总览文档 |
| 步骤 | 1. `_GenerateOverviewTool.execute(all_results, project_summary)` → LLM 生成 |
| LLM 调用 | 1 次 |
| 输入 | `task_id, community_results[], project_name, project_summary` |
| 输出 | Markdown 架构总览文档 |

#### D4. `skill_batch_analyze_communities`

| 属性 | 说明 |
|------|------|
| 用途 | 批量 L0 社区分析 → 图 → 总览 |
| 步骤 | 1. 取 L0 社区列表 |
| | 2. for each (并发 N): `skill_analyze_community` + `skill_generate_diagram` |
| | 3. `skill_generate_arch_overview`(all_results) |
| | 4. `_SaveResultsTool.execute`(results) |
| LLM 调用 | N × analyze + 1 × overview = **N+1 次** |
| 输入 | `task_id, edge_type, max_concurrency=3` |
| 输出 | `{overview, diagrams[], results[]}` |

---

## 4. LLM 调用流程与成本清单

### 4.1 后端 Agent 分析流程（ArchAnalystWorkflow）

```
触发入口                                     LLM 调用?
──────────────────────────────────────────────────────
用户点击"批量分析" / AI 助手打字"分析所有社区"
  │
  ▼
1. task_manager.py → create_default_router()
   → RouterHarness.dispatch("analyze", task_id, ctx)
   → AgentQueue.enqueue()                          ❌ 无 LLM
  │
  ▼
2. AgentRuntime.run(ArchAnalystWorkflow, ctx)
   │
   ├─ 2a. workflow.plan(ctx) → list[SkillRef]
   │     = [skill_analyze_community(N次),
   │        skill_generate_diagram(N次),
   │        skill_generate_arch_overview,
   │        skill_save_results]                     ❌ 无 LLM
   │
   ├─ 2b. for each community (并发 N):
   │     │
   │     ├─ skill_analyze_community
   │     │   └─ _AnalyzeCommunityTool.execute()
   │     │       → LLMService.streaming_chat()
   │     │       → prompt: "agent_analyze_community"
   │     │       → 输出: name + summary (100-300字) ✅ LLM: 1次/社区
   │     │
   │     └─ skill_generate_diagram
   │         └─ _GenerateDiagramTool.execute()
   │             → _build_mermaid() + _build_plantuml()
   │             → 模板拼接，无 LLM                  ❌ 无 LLM
   │
   ├─ 2c. skill_generate_arch_overview
   │     └─ _GenerateOverviewTool.execute()
   │         → LLMService.streaming_chat()
   │         → prompt: "agent_generate_overview"
   │         → 输入: 全部社区分析结果 (0-10000字)
   │         → 输出: 800-1500字 Markdown 文档       ✅ LLM: 1次
   │
   └─ 2d. skill_save_results
       └─ _SaveResultsTool.execute()
           → DB 写入 community_llm_results           ❌ 无 LLM
  │
  ▼
3. AgentRuntime → workflow.finalize()
   → WorkflowResult → 通知前端                      ❌ 无 LLM
```

### 4.2 LLM 调用逐步详解

#### 步骤 2b-1: `_AnalyzeCommunityTool.execute()`

| 属性 | 说明 |
|------|------|
| 文件 | `agent_workflow/workflows/arch_analyst.py:32` |
| Prompt 模板 | `agent_analyze_community`（或硬编码 fallback） |
| 输入上下文 | 社区节点列表 + 边数据（max 6000 字） |
| temperature | 0.3 |
| max_tokens | 800 |
| 输出 | `{communityId, name, summary}` |
| Token 估算 | 输入 ~1500 / 输出 ~200 / 每次 ~1700 |
| **调用次数** | **N 次**（N = L0 社区数，通常 10-50） |
| **并发** | `max_concurrency=3`（`RateLimiter` 控制） |

#### 步骤 2c: `_GenerateOverviewTool.execute()`

| 属性 | 说明 |
|------|------|
| 文件 | `agent_workflow/workflows/arch_analyst.py:94` |
| Prompt 模板 | `agent_generate_overview`（或硬编码 fallback） |
| 输入上下文 | N 个社区的分析结果拼接（max 10000 字） + 项目概要 |
| temperature | 0.3 |
| max_tokens | 2000 |
| 输出 | 800-1500 字 Markdown 架构总览文档 |
| Token 估算 | 输入 ~3000 + N×200 / 输出 ~500 / 每次 ~3500+N×200 |
| **调用次数** | **1 次** |

### 4.3 Token 总成本估算

以 N=30 个 L0 社区为例：

| 步骤 | LLM 调用次数 | 输入 Token | 输出 Token | 总计 |
|------|-------------|-----------|-----------|------|
| analyze_community × N | 30 | 1500×30=45,000 | 200×30=6,000 | 51,000 |
| generate_overview | 1 | 9,000 | 500 | 9,500 |
| **合计** | **31 次** | **54,000** | **6,500** | **~60,000 tokens** |

> 以 deepseek-chat 计费模型折算：60K tokens ≈ ¥0.06（约 6 分钱）

### 4.4 前端 AI 对话的 LLM 调用

用户在 AI 面板打字时，调用的是 `llmClient.chat()` → `LLMService.streaming_chat()`，**这是独立的另一条 LLM 路径**，与后端 Agent 无关：

```
AIAssistantPanel
  │
  ├─ 用户打字 → llmClient.chat(messages)
  │   → LLMService.streaming_chat(session_id, model_id, messages)
  │   → LLM 回复 + 嵌入 [CMD:] 标签
  │   → 前端解析 CMD → GraphCommandBus.execute()
  │
  └─ 用户点击 Suggestion Chip
      → 同上
```

| 场景 | LLM 调用 | 输入 | 输出 |
|------|---------|------|------|
| 🎓 引导模式 | 每次用户回复 1 次 | graphState + 社区数据 + 对话历史 | 引导话术 + [CMD:] |
| 普通提问 | 每次用户问题 1 次 | graphState(可选) + 对话历史 | 回答 + [CMD:](可选) |
| 生成架构文档 | 前端调用 `regenerateOverallDoc()` → 独立 LLM | 结构化 prompt | Markdown 文档 |

### 4.5 双 LLM 路径关系

```
前端 LLM 路径                         后端 Agent LLM 路径
(llmClient.chat)                     (AgentTool.execute via llm_adapter)
                                     A
│                                     │
│  AI 面板对话                          Agent 批量分析
│  prompt: 系统指令+图状态+历史          prompt: agent_analyze_community
│  输出: 自然语言+[CMD:]                输出: 结构化 name+summary
│                                     │
│  ● 交互式、流式                         ● 批量式、结构化
│  ● 用户可见                             ● 用户不可见
│  ● 每次一问                             ● N+1 次/批
│  ● Token 小 (~500)                     ● Token 大 (~2000/次)
```

---

## 5. 通信架构

### 5.1 整体架构

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

### 5.2 全链路数据流（从用户输入到图变化）

### 5.3 GraphCommandBus（命令总线 → 图）

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

  // === Agent 任务调度（AI → 后端 Agent） ===
  | { type: 'dispatchAgent'; action: string; params: Record<string, any> }
```

`dispatchAgent` 命令由 AI 确认后发出，前端的 AIAssistantPanel 收到后调用 `RouterHarness.dispatch(action, taskId, params)`，与 `[CMD:]` 图命令不同——**`[CMD:]` 是同步图操作，`dispatchAgent` 是异步后端任务**。

### 5.4 GraphState（图状态 → AI）

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

### 5.5 AI 回复中的命令嵌入

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

### 5.6 意图识别 → 确认 → 执行流程

当用户请求涉及后端 Agent 任务时（分析、生成、对比、诊断），AI 走**三步确认模式**，不能直接执行：

```
用户输入: "分析所有社区的结构"

第一步：意图识别
  AI 从对话中判断:
    - 动作类型: analyze / diff / track_start / track_stop
    - 参数: level, edge_type, tag 等
    - 是否涉及后端 Agent 调用
  生成 /cmd 指令: /arch analyze --all --level L0

第二步：确认请求
  AI 输出确认卡片，包含:
    - 即将执行的命令原文
    - 预估资源消耗（社区数、时间、Token）
    - [确认执行] [修改参数] [取消] 三个操作
  → 此阶段不触发后端调用

第三步：用户决策
  用户点击 [确认执行] 或打字"确认"
    → AI 调用 RouterHarness.dispatch() / triggerArchAnalysis()
    → 走 Skills/Tools 层执行任务
  用户点击 [修改参数]
    → AI 与用户交互调整参数后重新确认
  用户点击 [取消]
    → AI 回到普通对话模式
```

**系统 prompt 约定**：

```
当用户请求需要执行后端 Agent 任务时，你的流程是：
1. 识别意图 → 生成对应的 /arch <action> 指令
2. 展示确认信息（包含指令原文、预估消耗）
3. 等待用户确认后才执行
4. 用户拒绝则放弃执行，回到对话

可能触发的指令：
- /arch analyze [--all] [--level L0|L1|...] [--edge-type INCLUDE|CALL]
- /arch overview
- /arch diagram <community-id>
- /arch diff [v-from] [v-to]
- /arch track start [--tag <desc>]
- /arch track stop
```

**确认卡片前端实现**（AIAssistantPanel）：

```
AI 回复内容...  ← 正常 Markdown 渲染

--- 分隔线 ---
┌────────────────────────────────────────────┐
│  🔧 即将执行架构分析                        │
│  /arch analyze --all --level L0            │
│                                           │
│  📊 23 个社区 | ⏱ ~2 分钟 | 💰 ~¥0.06    │
│                                           │
│  [✓ 确认执行]  [✎ 修改参数]  [✕ 取消]     │
└────────────────────────────────────────────┘
```

确认卡片由前端解析 AI 回复中的特定标签（如 `[CONFIRM: cmd="/arch analyze --all" communities=23]`）渲染，不在 AI 回复中手写表格。

---

## 6. AI 助手的能力体系

### 6.1 六大能力模块

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
| 已有 UI | 对比模式（工具栏 ⋮ → 选择版本） + 图着色（新增绿/删除红/变更橙/不变灰） |
| 整合方式 | AI 调用 `[CMD: compareVersions]` 触发对比，然后读取结果并解读 |

#### 模块 F：Agent 批量分析

| 属性 | 说明 |
|------|------|
| 触发方式 | 用户说"分析所有社区" → AI 意图识别 → 用户确认 → 执行 `/cmd` |
| 接口 | `RouterHarness.dispatch("analyze", ...)` → 后端 `ArchAnalystWorkflow` |
| 进度 | 通过 GraphCommandBus 推送进度事件，或由 AI 轮询状态 |
| 整合方式 | AI 识别用户意图 → 生成 `/arch analyze` 指令 → 展示确认卡片 → 用户同意后执行 |

### 6.2 能力调用方式

AI 通过以下四种方式调用能力：

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

4. 通过 Skills/Tools 执行后端 Agent 任务（意图识别 → 确认 → 执行）
   → AI 识别用户意图 → 生成 `/cmd` 指令 → 展示确认信息 → 用户同意后 dispatch
   → 示例：用户说"分析所有社区" → AI 识别 → "即将 /arch analyze --all，确认？" → 用户确认 → 执行
```

---

## 7. 交互设计

### 7.1 完整用户路径

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
→ 或用户打字 "分析所有社区" → AI 识别意图 → 生成 `/arch analyze --all`
  ┌─────────────────────────────────────┐
  │  即将执行: /arch analyze --all      │
  │  预计分析 23 个 L0 社区             │
  │  LLM 调用约 24 次，预估 2 分钟      │
  │  [确认执行] [修改参数] [取消]        │
  └─────────────────────────────────────┘
  → 用户确认 → RouterHarness.dispatch("analyze", ...) → AgentRuntime 执行
→ 或用户打字 "对比上次版本" → 同上的确认流程

🎓 引导模式下，AI 也可以**主动建议**执行 Agent 任务：
```
AI: "...以上是项目概览。我建议进行一次完整的社区分析，
    可以深入了解每个模块的职责。需要执行吗？
    [CONFIRM: cmd="/arch analyze --all" communities=23]"
```
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

#### 场景 D：意图识别触发 Agent 任务（核心模式）

当用户提出涉及"分析/生成/对比/诊断"等操作意图时，AI 走"**识别 → 确认 → 执行**"三步流程：

```
用户打字: "帮我分析所有社区的结构"
  │
  ▼
1. AI 意图识别
   ├─ 识别动作为: "analyze"
   ├─ 提取参数: "all communities", "L0"
   └─ 映射为指令: /arch analyze --all --level L0
  │
  ▼
2. 展示确认信息
   ┌────────────────────────────────────────────┐
   │ 🔧 即将执行:                                │
   │ /arch analyze --all --level L0             │
   │                                            │
   │ 预计: 23 个社区, ~2 分钟                    │
   │ Token: ~45,000                             │
   │                                            │
   │ [确认执行] [修改参数 --level L1] [取消]      │
   └────────────────────────────────────────────┘
  │
  ▼ (用户点击 [确认执行])
  │
3. 执行
   → AI 调用 `RouterHarness.dispatch("analyze", ...)`
   → 或前端调用 `community-store.triggerArchAnalysis()`
   → 走 Skills/Tools 层的定序流程
  │
  ▼
4. 结果呈现
   → AI 读取分析结果 → 嵌入 [CMD:] 标签联动图
   → "分析完成！项目共 23 个 L0 社区，其中 15 个 INCLUDE 社区、8 个 CALL 社区。
      质量分布: 最优 {name}(0.92), 最差 {name}(0.15 ⚠️)
      [CMD: filterByQuality max="0.2"]
      红色边框的就是低质量社区，建议重点关注。"
```

#### 场景 E：用户主动修改参数确认

```
用户打字: "对比一下最近的版本"
  │
  ▼
AI: "/arch diff v12 v13 即将执行，需要确认吗？"
  │
  ▼
用户: "不，对比 v10 和 v13"
  │
  ▼
AI: "好的，改为 /arch diff v10 v13
     ┌──────────────────────────┐
     │ 确认执行 /arch diff v10 v13? │
     │ [确认] [取消]              │
     └──────────────────────────┘"
```

### 7.2 引导对话流设计

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

### 7.3 引导模式 vs 普通对话

| 维度 | 🎓 引导模式 | 普通 AI 对话 |
|------|-----------|-------------|
| 触发方式 | 点击 🎓 图标 | 用户主动打开 AI tab |
| 系统 prompt | 含引导指令 + 六大能力描述 + 图状态注入 | 标准 AI 助手 prompt |
| 初始行为 | 主动分析数据，按 Tour 1 逐步引导 | 等待用户提问 |
| 命令权限 | 可执行所有 GraphCommand | 仅用户要求时执行 |
| 图状态注入 | 每次请求自动注入 | 仅用户提及图时注入 |
| 用户打断 | 引导中随时打字提问，AI 回答后继续 | 正常 |
| 何时退出 | 用户关闭右面板 / 清空对话 / 手动说"结束引导" | 无引导概念 |

### 7.4 🎓 入口图标

- 位于结构图画布右下角浮动，仅力导向图 / dagre 模式可见
- table / heatmap 模式隐藏
- 全屏模式下由全屏 bar 控制，不额外显示浮动入口
- 点击后：右面板自动打开 + 切到 AI tab，注入引导 prompt，AI 开始 Tour 1

---

## 8. 前端数据流

### 8.1 数据流动图

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

### 8.2 AI 系统 prompt 结构

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

### 8.3 建议动作（Suggestion Chips）

AI 回复末尾附带建议动作芯片，用户点击即可触发：

```
AI: "以上是 L0 层的概览，接下来你想了解什么？"

[Suggestion Chips]
[子社区结构] [外部依赖] [质量分析] [生成文档]
```

建议由 AI 生成（在回复文本中用 `[SUGGEST: label="子社区结构" command="drill" args="..."]` 标签输出），或者由前端根据当前上下文自动生成默认建议。

---

## 9. 整合现有功能清单

### 9.1 无需新改动的现有功能

以下功能已有完整实现，AI 助手通过对话/命令接入，不需要为 AI 功能修改原有逻辑：

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

### 9.2 需要新增/改动的功能

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
| CONFIRM 标签解析 | `AIAssistantPanel.vue` | 解析 `[CONFIRM:]` → 渲染确认卡片 |
| dispatchAgent 执行 | `AIAssistantPanel.vue` | 确认后调用 `triggerArchAnalysis()` |
| suggestion chips | `AIAssistantPanel.vue` | 解析 `[SUGGEST:]` 标签展示建议按钮 |
| 自动触发社区解释 | `CommunityGraphView.vue` | 双击节点时同步向 AI 发送上下文 |

### 9.3 不需要为 AI 功能改动的文件

- `CytoscapeGraph.vue` — 所有命令通过 CommunityGraphView 的现有方法转发
- `community-store.ts` — 只消费，不修改
- `report-store.ts` — 只消费，不修改
- `llmClient.ts` — 只消费，不修改
- `GraphToolbar.vue` / `GraphBreadcrumb.vue` / `NodeFilterPanel.vue` — 面板/工具栏已优化完毕，AI 集成时不额外改动

---

## 10. 实现计划（按架构依赖分优先度）

### 10.1 架构依赖图

> 组件层级关系：`AppShell → [MainContent → CGV] + [RightPanel → AIAssistantPanel]`
> CGV 和 AIAssistantPanel **不在同一个 Vue 子树**，无法使用 provide/inject。
> **采用 Pinia store 模式**实现跨子树通信（与现有代码库中 store 使用方式一致）。

```
P0   graph-commands.ts (类型 + 解析器)          【新建】
       │
       ▼
P1   useGraphCommandBus (Pinia store / 共享 composable)  【新建】
     · enqueue(cmd) — 串行队列
     · graphState   — 响应式图状态
       │
       ├──────────────────────────────────────────┐
       ▼                                           ▼
     CommunityGraphView                          AIAssistantPanel  【改现有】
     · 写入 graphState          ────────▷        · 读取 graphState
     · executeCommand()                          · 流式后解析 [CMD:] → enqueue
     · 调用 store.enqueue()                      · 注入 graphState 到 system prompt
       │                                           │
       ▼                                           ▼
P2   ┌─────────────────┐                ┌─────────────────────┐
     │ executeCmd 路由   │                │ AI 面板核心增强       │
     │ highlight        │                │ · 引导模式 prompt    │
     │ focus / drill    │                │ · 普通模式           │
     │ filterBy*        │                │ · [CMD:] 解析执行    │
     │ setViewMode      │                └──────────┬──────────┘
     │ resetView        │                           │
     │ hideNodes        │                ┌──────────┴──────────┐
     │ compare          │                ▼                      ▼
     └─────────────────┘          P3   引导交互增强        P4  联动入口
                                  · [SUGGEST:] chips    · 🎓 浮动按钮
                                  · [CONFIRM:] 卡片     · 双击→AI 通知
                                  · agent 调度          · agent 调度确认
```

### 10.2 P0：类型与协议定义（无前置依赖）【全部新建】

| # | 内容 | 文件 | 来源 | 行数 |
|---|------|------|------|------|
| P0.1 | `GraphCommand` 联合类型（Section 5.3） | `src/types/graph-commands.ts` | 新建 | 40 |
| P0.2 | `GraphState` 接口（Section 5.4） | `src/types/graph-commands.ts` | 新建 | 30 |
| P0.3 | `parseCommandTag()` 解析函数 + 白名单校验 | `src/types/graph-commands.ts` | 新建 | 30 |
| | **P0 合计** | | | **~100** |

**验收标准**：
- `parseCommandTag('[CMD: highlight nodeIds="L0-1,L0-2"]')` → `{ type: 'highlight', nodeIds: ['L0-1', 'L0-2'] }`
- 未知命令 → 静默返回 `null`
- TypeScript 类型编译通过

### 10.3 P1：命令执行通道 + 图端执行（依赖 P0）

| # | 内容 | 文件 | 来源 | 行数 |
|---|------|------|------|------|
| P1.1 | `useGraphCommandBus`（Pinia store 或共享 composable，含串行队列 + graphState） | `src/stores/graph-command-store.ts` 或 `src/composables/useGraphCommandBus.ts` | 新建 | 80 |
| P1.2 | CGV 接入 store：`watch` 图状态变化 → 写入 `graphState` | `CommunityGraphView.vue` | 改现有 | 25 |
| P1.3 | CGV `executeCommand()` → 路由到已有方法（见映射表） | `CommunityGraphView.vue` | 改现有 | 50 |
| P1.4 | CGV 监听 store 队列 → 自动执行命令（或 CGV 只写入 graphState，AIAssistantPanel 调用 enqueue） | `CommunityGraphView.vue` | 改现有 | 30 |
| | **P1 合计** | | | **~185** |

**`executeCommand()` 命令 → 现有方法映射表**：

| 命令 | 现有目标方法 / 路径 |
|------|-------------------|
| `highlight` | `setHighlightedNodeIds(nodeIds)` |
| `clearHighlight` | `setHighlightedNodeIds(new Set())` |
| `focus` | `cytoRef.zoomTo(nodeId, animate)` |
| `drill` | `drillDown(communityId)` |
| `rollUp` | `handleRollUp()` |
| `filterByQuality` | `hiddenNodeIds` — 隐藏不匹配节点 |
| `filterByCoreness` | `hiddenNodeIds` — 隐藏不匹配节点 |
| `filterBySize` | `hiddenNodeIds` — 隐藏不匹配节点 |
| `hideNodes` | `hiddenNodeIds` — 加入隐藏集合 |
| `clearFilter` | `hiddenNodeIds = new Set()` |
| `setViewMode` | `internalViewMode / externalViewMode = mode` |
| `setEdgeType` | `selectedEdgeType = edgeType` |
| `resetView` | `handleResetView()` |
| `compareVersions` | `toggleCompare()` + `compareSelected()` |
| `openCommunityDetail` | `open-md` emit |
| `dispatchAgent` | `communityStore.triggerArchAnalysis(taskId, projectId)` 或 `RouterHarness.dispatch()` |

**验收标准**：
- `useGraphCommandBus` 串行队列：前一个命令 resolve 后下一个才执行
- `graphState` 与当前视图同步（viewMode / drillLevel / selectedCommunityId / visibleNodeIds / stats）

### 10.4 P2：AI 面板增强 — 图—AI 双向通信（依赖 P1）

> `AIAssistantPanel.vue` 已存在（461 行），具备：流式对话、消息列表、</>/cmd> 指令检测与确认卡片。
> P2 是对现有文件的**功能增强**，非新建组件。

| # | 内容 | 文件 | 来源 | 行数 |
|---|------|------|------|------|
| P2.1 | 接入 `useGraphCommandBus` store，获取 `graphState` + 调用 `enqueue()` | `AIAssistantPanel.vue` | 改现有 | 15 |
| P2.2 | 每次 AI 请求前将 `graphState` JSON 注入 system prompt 消息 | `AIAssistantPanel.vue` | 改现有 | 25 |
| P2.3 | 流式响应完成后解析 `[CMD:]` 标签 → 调用 `store.enqueue()` | `AIAssistantPanel.vue` | 改现有 | 35 |
| P2.4 | 引导模式 prompt（含六大能力描述 + Tour1 流程指令） | `AIAssistantPanel.vue` | 改现有 | 50 |
| P2.5 | 引导模式 vs 普通模式切换（mode ref：'guide'/'normal'，默认 normal） | `AIAssistantPanel.vue` | 改现有 | 15 |
| | **P2 合计** | | | **~140** |

**验收标准**：
- 普通模式下等待用户输入，不主动发消息
- 引导模式下自动发送 Tour 1 的第一步 → 等待用户响应
- AI 回复中的 `[CMD: highlight ...]` 被解析且图同步变化

### 10.5 P3：引导交互增强（依赖 P2）

> 现有 `/cmd` 确认卡片已存在基础 UI（`showCmdConfirm` + 确认/取消按钮）。
> P3 扩展为：支持 `[CONFIRM:]` 解析 + 成本预估，新增 `[SUGGEST:]` 芯片。

| # | 内容 | 文件 | 来源 | 行数 |
|---|------|------|------|------|
| P3.1 | `[SUGGEST:]` 标签解析 → Suggestion Chips 渲染 | `AIAssistantPanel.vue` | 改现有 | 30 |
| P3.2 | `[CONFIRM:]` 标签解析 → 统一确认卡片（含成本预估 + 复用现有 `/cmd` 卡片 UI） | `AIAssistantPanel.vue` | 改现有 | 50 |
| P3.3 | 确认后调用 `dispatchAgent` → `communityStore.triggerArchAnalysis()` | `AIAssistantPanel.vue` | 改现有 | 20 |
| | **P3 合计** | | | **~100** |

**验收标准**：
- `[SUGGEST: label="生成文档" command="genDoc"]` → 渲染为可点击芯片，点击等同用户打字
- `[CONFIRM: cmd="/arch analyze --all" communities=23]` → 渲染确认卡片，确认后执行 agent

### 10.6 P4：联动与入口（依赖 P2）

| # | 内容 | 文件 | 来源 | 行数 |
|---|------|------|------|------|
| P4.1 | 🎓 浮动入口按钮（canvas 右下角，力导/dagre 模式可见） | `CommunityGraphView.vue` 或 `GraphCanvas.vue` | 改现有 | 30 |
| P4.2 | 双击社区节点 → 向 store 推送 `{ event: 'drill', communityId }`，AI 面板读取并自动解释 | `CommunityGraphView.vue` + `AIAssistantPanel.vue` | 改现有 | 25 |
| | **P4 合计** | | | **~55** |

**验收标准**：
- 点击 🎓 → 右面板展开 + AI tab + 注入引导 prompt
- 双击节点 → AI 收到 `{ event: 'drill', communityId, context }` 并自动解释

### 10.7 总量估算

| 层级 | 新建行数 | 改现有行数 | 合计 | 核心产出 |
|------|---------|-----------|------|---------|
| P0 | ~100 | 0 | ~100 | 类型安全的命令协议 + 解析器 |
| P1 | ~80 | ~105 | ~185 | store 式命令通道 + CGV 命令路由 + 图状态推送 |
| P2 | 0 | ~140 | ~140 | AI 面板增强：命令联动 + 引导模式 |
| P3 | 0 | ~100 | ~100 | 确认卡片 + 建议芯片 + agent 调度 |
| P4 | 0 | ~55 | ~55 | 🎓 入口 + 双击联动 |
| **总计** | **~180** | **~400** | **~580** | |

### 10.8 测试验证点

| 验证点 | 层级 | 方法 |
|--------|------|------|
| `[CMD:]` 标签解析正确 | P0 | 单元测试 `parseCommandTag()` |
| 命令串行执行 | P1 | 模拟 highlight → focus → drill 串行 |
| 图状态同步 | P1 | graphState 变化后注入 AI context |
| AI 命令联动图 | P2 | 打字"高亮最大的社区" → AI 回复含 `[CMD: highlight]` → 图同步变化 |
| 引导模式入口 | P2 | 普通开 AI tab → 无引导 prompt |
| 引导流程 | P2 | 🎓 触发 → AI 主动发送 Tour 1 第一步 |
| 确认卡片 | P3 | AI 识别到 analyze → 渲染确认卡片 |
| Suggestion Chips | P3 | AI 回复含芯片 → 可点击触发 |
| 🎓 入口 | P4 | 力导向图右下角可见，table/heatmap 隐藏 |
| 双击联动 | P4 | 双击节点 → AI 解释该社区 |

### 10.9 架构审查：冲突、遗漏与补丁问题

#### 冲突 1：provide/inject 不可行 ← 关键

**发现**：CGV 和 AIAssistantPanel 不在同一 Vue 子树中。

```
AppShell
  ├── MainContent → ... → CommunityGraphView
  └── RightPanel → AIAssistantPanel
```

Vue 3 provide/inject 仅支持父→子方向，CGV 无法 provide 到 AIAssistantPanel。

**解决方案**：使用 Pinia store（`useGraphCommandStore`）替代。与现有代码库 store 模式一致，CGV 和 AIAssistantPanel 分别导入同一 store 实例通信。

**影响**：P1.1（`useGraphCommandBus` → Pinia store，已体现在更新后的计划表中）

#### 冲突 2：两套聊天系统并存

**发现**：`AIAssistantPanel.vue`（461 行，已存在）和 `ChatView.vue`（≈200 行）功能重叠。

| 功能 | AIAssistantPanel | ChatView |
|------|:---:|:---:|
| 流式对话 | ✅ | ✅ |
| /cmd 指令 | ✅ | ❌ |
| 快捷操作 | ❌ | ✅ (查看架构总览/质量检查/生成文档) |
| session 绑定 | ✅ | ❌ |
| Markdown 渲染 | ❌ | ✅ |

**建议**：P4 后迁移 ChatView 快捷操作到 AIAssistantPanel。此改造**不在 P0-P4 范围内，单独计划。**

#### 冲突 3：`[CONFIRM:]` vs `/cmd` 双重确认逻辑

**发现**：现有 `/cmd` 确认和计划中的 `[CONFIRM:]` 确认高度相似但触发不同。`/cmd` 在 `.handleSend()` 中检测，`[CONFIRM:]` 在流式响应完成后解析。

**解决**：P3.2 统一为一个确认组件，`showCmdConfirm` 扩展支持两类触发源，返回统一的 `{ text, action, args, cost }`。

#### 遗漏 1：命令执行后的错误反馈

**问题**：AI 发 `[CMD: drill nodeId="nonexistent"]` → 找不到社区 → 无人通知 AI。

**解决**：`executeCommand()` 返回 `{ success, error? }`，AIAssistantPanel 在下一次请求中注入执行结果。

#### 遗漏 2：引导模式下用户中途退出恢复

**问题**：引导 Tour 进行中，用户关闭右面板或切换 tab，恢复后引导状态丢失。

**解决**：引导模式使用独立消息队列（不混入普通对话流），关闭面板不丢失。

#### 遗漏 3：筛选命令阈值与 NodeFilterPanel 对齐

**问题**：`[CMD: filterByQuality min=0.5]` 支持任意阈值，但 NFP 使用固定阈值（high≥0.5, low≤0.2）。

**解决**：`executeCommand` 先就最近固定阈值。AI system prompt 中明确告知可用阈值。

#### 遗漏 4：graphState 注入的数据量控制

**问题**：topCommunities + lowQualityCommunities 列表可能挤占 token 预算。

**解决**：topCommunities 限 5 个，lowQuality 限 10 个。注入前检查 JSON 长度，超过 2000 字符剪裁。

#### 架构补丁 1：ChatView 快捷操作迁移（后续）

ChatView 的快捷操作在 P4 后迁移至 AIAssistantPanel 引导模式。非 P0-P4 硬依赖。

#### 架构补丁 2：graphState 与 communityStore 数据去重

`graphState` 是 `communityStore` 的精简视图，只包含 AI prompt 所需最少信息。AI 需要详细数据时通过 `explainCommunity()` 单独获取。

#### 审查结论

| 类别 | 数量 | 处置 |
|------|------|------|
| 关键冲突 | 1 (provide/inject) | 已修复：改为 Pinia store |
| 设计冲突 | 2 (两套聊天/双确认) | 统一方案明确，实施时处理 |
| 功能遗漏 | 4 | 已补充缓解方案 |
| 架构补丁 | 2 | 列入后续计划 |

**整体评估**：无阻塞性冲突。核心调整已体现于更新后的 §10.1-§10.6 计划表。

---

## 11. 风险与注意事项

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

## 12. 附录：现有 AI 接口文档

### 12.1 Prompt 模板清单（`prompt_templates.json`）

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

### 12.2 后端 Agent 工作流

| 工作流 | 文件 | 职责 |
|--------|------|------|
| `ArchAnalystWorkflow` | `agent_workflow/workflows/arch_analyst.py` | 社区分析 + 图表生成 + 概览生成 + 持久化 |
| `ArchSentinelWorkflow` | `agent_workflow/workflows/arch_sentinel.py` | 版本对比 → Diff → 变更摘要 |

### 12.3 前端核心 LLM 函数

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
