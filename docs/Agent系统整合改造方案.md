# Agent 系统整合改造方案

> 基于 `Agent相关能力代码位置总览.md`（当前准确）、`agent相关功能改版文档.md` v5.2（哲学参考）、`AGENT-LLM解析-架构版本跟踪-开发计划文档.md`（缺失列表）、`AI助手架构分析引导.md`（统一入口设计）四份文档汇总分析
> 生成日期: 2026-06-15

---

## 一、概述

当前 AI 能力分布存在三个核心问题：

1. **入口分散**：AIAssistantPanel（对话）、AgentTaskList（批量分析）、ChatView（聊天）、右键菜单（符号解释）、按钮（社区分析）各自独立，用户无法统一使用
2. **能力孤岛**：后端 Agent 工作流（ArchAnalystWorkflow / ArchSentinelWorkflow）与前端对话 AI 互不感知，无法联动
3. **工具完整但无循环**：RouterHarness、SkillExecutor、三层工具系统均已实现，但缺少自主规划-执行-反思的运行时循环，Agent 仍停留在"触发-返回"模式

本方案以 **AI Assistant 对话面板为统一入口，后端 Agent 工作流为能力提供方**，形成"前端 AI 对话 → GraphCommandBus 图联动 → 后端 Agent 批量分析"的双层架构。

---

## 二、现有能力清单与代码映射

### 2.1 后端 Agent 工作流（已实现，可用）

| 模块 | 文件 | 能力 | 状态 |
|------|------|------|------|
| RouterHarness | `backend-core/agent_workflow/router.py:39` | 路由用户请求到 Workflow+Tool 组合 | ✅ 可运行 |
| ArchAnalystWorkflow | `backend-core/agent_workflow/workflows/arch_analyst.py` | 社区分析 + 图表生成 + 概览生成 + DB 持久化 | ✅ 可运行 |
| ArchSentinelWorkflow | `backend-core/agent_workflow/workflows/arch_sentinel.py` | 版本差异 → Diff 计算 → 变更摘要生成 | ✅ 可运行 |
| Agent Runtime | `backend-core/agent_workflow/runtime.py` | Workflow 执行上下文管理 | ✅ 可运行 |
| Security Sandbox | `backend-core/agent_workflow/sandbox.py` | 工具调用沙箱 | ✅ 可运行 |
| Tool Layer | `backend-core/agent_workflow/tools.py` | 15 个 Core Tools | ✅ 可运行 |
| JSONL Store | `backend-core/agent_workflow/jsonl_store.py` | Agent 执行日志存储 | ✅ 可运行 |

### 2.2 MCP / Skill 层（已实现，可用）

| 模块 | 文件 | 能力 | 状态 |
|------|------|------|------|
| SkillExecutor | `backend-core/mcp_server/skill_executor.py:39` | 13 个内置 Skill 执行 | ✅ 可运行 |
| register_core_skills | `backend-core/mcp_server/skills.py` | 注册所有内置 Skill | ✅ 可运行 |
| MCP Server Bridge | `backend-core/mcp_server/` | stdio transport + JSON-RPC 协议 | ✅ 可运行 |
| skill_batch_analyze_communities | `skill_executor.py` | 批量社区分析（前端未接入） | ⚠️ 无前端入口 |

### 2.3 前端 AI 组件（已实现，但分散）

| 组件 | 文件 | 能力 | 问题 |
|------|------|------|------|
| AIAssistantPanel | `src/components/ai/AIAssistantPanel.vue` | LLM 对话 + `/arch` 命令触发 Agent | 无图联动 |
| AgentTaskList | `src/components/ai/AgentTaskList.vue` | Agent 任务查看/管理 | 与 AI 对话独立 |
| ChatView | `src/components/report/ChatView.vue` | 快捷操作按钮 + AI 对话 | 与 AIAssistantPanel 功能重叠 |
| RightPanel | `src/components/panel/RightPanel.vue` | 右侧面板容器 | registry 未启用 |

### 2.4 图渲染层（用来显示的组件）

| 组件 | 文件 | 能力 |
|------|------|------|
| CommunityGraphView | `src/components/report/CommunityGraphView.vue` | Graph 视图容器 + 钻取 + 工具栏 |
| GraphCanvas | `src/components/report/GraphCanvas.vue` | 画布，渲染器切换 |
| D3ForceRenderer | `src/components/report/renderers/D3ForceRenderer.ts` | 力导向布局 |
| DagreRenderer | `src/components/report/renderers/DagreRenderer.ts` | 层次化布局 |
| CommunityTagView | `src/components/report/CommunityTagView.vue` | Tag 视图 |
| CommunityArchitecturePanel | `src/components/report/CommunityArchitecturePanel.vue` | 编排 tag/graph 双模式 |

### 2.5 现有 AI 能力入口清单

| 入口 | 触发方式 | 对应能力 | 用户路径 |
|------|---------|---------|---------|
| AI Assistant Tab | 点击右侧 AI 标签 | 对话 + `/arch` Agent | 主动打开 |
| Agent Task Tab | 点击 Agent 任务标签 | 批量分析任务管理 | 主动打开 |
| 🎓 入口 | 结构图顶部 | （新设计，未实现） | 被动引导 |
| ChatView 按钮 | ReportHome 下方 | 快捷分析 | 主动点击 |
| 右键菜单 → 解释 | 右键节点 | 符号/边解释 | 主动触发 |
| 社区分析按钮 | 社区卡片 | 社区详细分析 | 主动点击 |
| 版本对比按钮 | 工具栏 | 版本差异分析 | 主动点击 |

---

## 三、能力矩阵分析

### 3.1 已实现可复用

| 能力 | 提供方 | 复用方式 |
|------|--------|---------|
| 路由调度 | RouterHarness.dispatch() | 直接调用 |
| 社区分析 | ArchAnalystWorkflow | 通过 AI 对话触发 |
| 版本对比 | ArchSentinelWorkflow | 通过 AI 对话触发 |
| Skill 执行 | SkillExecutor | 通过 AI 对话触发 |
| Core Tools（15 个） | tools.py | AI 调用 |
| 安全沙箱 | sandbox.py | 自动生效 |
| 节点解释 | explainCommunity + LLM | 现有 RPC |
| 语义搜索 | /arch 命令 | 通过 AI 对话触发 |

### 3.2 已设计未实现

| 能力 | 设计位置 | 优先级 |
|------|---------|--------|
| GraphCommandBus（13 命令） | `AI助手架构分析引导.md` | P0 |
| GraphState 状态通道 | `AI助手架构分析引导.md` | P0 |
| `[CMD:]` 标签解析 | `AI助手架构分析引导.md` | P0 |
| 🎓 引导入口 | `AI助手架构分析引导.md` | P0 |
| 三段式引导对话流 | `AI助手架构分析引导.md` | P1 |
| Suggestion Chips | `AI助手架构分析引导.md` | P1 |
| 双击社区联动 | `AI助手架构分析引导.md` | P1 |
| AI 说话+图同步 | `AI助手架构分析引导.md` | P0 |

### 3.3 真实缺失（来自开发计划文档）

| 能力 | 原文档 | 优先级 | 说明 |
|------|--------|--------|------|
| Agent 运行时循环 | `AGENT-LLM解析-架构版本跟踪-开发计划文档.md` | P1 | 自主规划→执行→反思，非阻塞 |
| Agent 批量分析前端入口 | 同上 | P1 | AI 对话触发 vs 独立 Tab |
| 增量分析 | 同上 | P2 | 基于 change_tracker Git diff |
| 可视化变更对比 | 同上 | P2 | Mermaid 图 diff |
| Agent 编排跨工作流 | 同上 | P2 | 多 Workflow 串联 |

### 3.4 过期设计（不实现）

| 设计 | 来源 | 原因 |
|------|------|------|
| 认知七层级 | `agent相关功能改版文档.md` v5.2 | 纯产品哲学，无工程落地路径 |
| 三层追问设计 | 同上 | 未验证，过度设计 |
| Skills 架构重写 | 同上 | 当前 SkillExecutor 可工作 |
| MCP 路由重设计 | 同上 | 当前 MCP Server 可工作 |
| 分布式云端架构 | 同上 | 远期，非当前阶段 |
| Git 式节点模型 | 同上 | 远期，非当前阶段 |

---

## 四、目标架构

```
┌─────────────────────────────────────────────────────────┐
│                    用户交互层（前端）                      │
│                                                         │
│  ┌────────────────┐   ┌──────────────────────────────┐  │
│  │ AIAssistantPanel │   │     CommunityGraphView       │  │
│  │  (统一对话入口)   │   │  ┌────────────────────────┐ │  │
│  │                  │   │  │  🎓 入口 (引导)         │ │  │
│  │  ┌────────────┐ │   │  │  GraphCanvas            │ │  │
│  │  │ [CMD:] 解析 │ │   │  └────────────────────────┘ │  │
│  │  │ 引导对话流  │ │   └──────────┬───────────────────┘  │
│  │  │ Suggestion  │ │              │                      │
│  │  └────────────┘ │     provide/inject                  │
│  └────────┬─────────┘              │                      │
│           │                        │                      │
│  ┌────────▼────────────────────────▼──────────────────┐  │
│  │           GraphCommandBus + GraphState              │  │
│  │   (provide/inject, CommunityGraphView 提供)         │  │
│  │   highlight / focus / drill / rollUp / filterBy..  │  │
│  │   setViewMode / setEdgeType / compareVersions       │  │
│  └────────────────────────┬───────────────────────────┘  │
│                           │                              │
└───────────────────────────┼──────────────────────────────┘
                            │ IPC
┌───────────────────────────▼──────────────────────────────┐
│                    后端能力层                              │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │           RouterHarness.dispatch()                │    │
│  │  ┌────────────┐  ┌────────────┐  ┌───────────┐  │    │
│  │  │ ArchAnalyst │  │ArchSentinel│  │ SkillExec │  │    │
│  │  │  Workflow   │  │  Workflow  │  │           │  │    │
│  │  └────────────┘  └────────────┘  └───────────┘  │    │
│  └──────────────────────────────────────────────────┘    │
│                                                          │
│  ┌──────────────────────────────────────────────────┐    │
│  │           change_tracker (Git 变更检测)           │    │
│  │           → 增量 Agent 分析事件源                 │    │
│  └──────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### 数据流

```
用户输入对话
  │
  ▼
AIAssistantPanel
  ├─ 普通模式 → LLM 回复（含 [CMD:] 标签）
  │              ├─ 解析标签 → GraphCommandBus.execute()
  │              │               └─ CommunityGraphView 更新图
  │              └─ 渲染回复 + Suggestion Chips
  │
  ├─ 🎓 引导模式 → 注入引导 System Prompt
  │                └─ 分步交互（Tour 1/2/3）
  │
  └─ /arch 命令 → RouterHarness.dispatch()
                   └─ Agent Workflow → 结果回写 → 图联动
```

---

## 五、改造路线图

### Phase 1: AI ↔ 图通信（P0，当前范围）

**目标**：AIAssistantPanel 说话时结构图同步响应

| # | 任务 | 涉及文件 | 工作量 |
|---|------|---------|--------|
| 1.1 | GraphCommandBus + GraphState 类型定义 | `src/types/command-bus.ts` | 小 |
| 1.2 | CommunityGraphView provide GraphCommandBus + GraphState | `CommunityGraphView.vue` | 中 |
| 1.3 | CommunityGraphView 实现 executeCommand() | `CommunityGraphView.vue` | 中 |
| 1.4 | AIAssistantPanel inject GraphCommandBus | `AIAssistantPanel.vue` | 小 |
| 1.5 | 实现 `[CMD:]` 标签解析器 | `AIAssistantPanel.vue` | 小 |
| 1.6 | 实现白名单校验 + 串行执行 | `AIAssistantPanel.vue` | 小 |
| 1.7 | 先实现 3 条核心命令：highlight / focus / drill | `CommunityGraphView.vue` | 中 |
| 1.8 | 🎓 入口按钮（force/dagre 模式下显示） | `CommunityGraphView.vue` | 小 |
| 1.9 | 🎓 点击 → 展开 AI 面板 + 注入引导 prompt | `CommunityGraphView.vue` + `AIAssistantPanel.vue` | 小 |
| 1.10 | 引导模式 vs 普通模式的 system prompt 切换 | `AIAssistantPanel.vue` | 小 |

**验证标准**：
- AI 回复中包含 `[CMD: highlight key="main.Service"]` → 图中对应节点高亮
- AI 回复中包含 `[CMD: focus key="community.3"]` → 图钻取到社区 3
- 🎓 入口在 force/dagre 模式显示，点击展开 AI 面板并进入引导模式
- 引导对话走完 Tour 1（全景探索 6 步）

### Phase 2: 引导对话 + Suggestion Chips（P1）

**目标**：完整的引导学习体验

| # | 任务 | 涉及文件 | 工作量 |
|---|------|---------|--------|
| 2.1 | 实现 `[SUGGEST:]` 标签 → 渲染可点击建议按钮 | `AIAssistantPanel.vue` | 小 |
| 2.2 | 实现 Tour 1 全景探索（6 步对话流） | 引导数据定义 | 中 |
| 2.3 | 实现 Tour 2 质量诊断（3 步） | 同上 | 中 |
| 2.4 | 实现 Tour 3 版本对比（3 步） | 同上 | 中 |
| 2.5 | 双击社区 → drill + 同步向 AI 发送上下文 | `CommunityGraphView.vue` | 小 |
| 2.6 | 实现setViewMode / setEdgeType / rollUp 命令 | `CommunityGraphView.vue` | 中 |
| 2.7 | 实现 filterByQuality / filterByCoreness / filterBySize / hideNodes / clearFilter 命令 | `CommunityGraphView.vue` | 中 |
| 2.8 | 实现 compareVersions / openCommunityDetail 命令 | `CommunityGraphView.vue` + 后端 | 中 |

**验证标准**：
- 引导模式下，用户可完成 3 个 Tour 的全部步骤
- Suggestion Chips 出现在 AI 回复末尾，点击触发对应操作
- 双击社区钻取的同时，AI 面板显示该社区的上下文信息

### Phase 3: Agent 统一入口 + 增量分析（P1-P2）

**目标**：AI 对话可触发后端 Agent 工作流

| # | 任务 | 涉及文件 | 工作量 |
|---|------|---------|--------|
| 3.1 | AIAssistantPanel 调用 RouterHarness.dispatch() | `AIAssistantPanel.vue` + 后端 | 中 |
| 3.2 | 对话中触发 ArchAnalystWorkflow（社区分析） | 后端适配 | 中 |
| 3.3 | 对话中触发 ArchSentinelWorkflow（版本对比） | 后端适配 | 中 |
| 3.4 | Agent 结果回写 → 图联动 | GraphCommandBus | 中 |
| 3.5 | Agent Task List 与 AI 对话结果互通 | `AgentTaskList.vue` | 中 |
| 3.6 | 评估 ChatView 与 AIAssistantPanel 合并 | `ChatView.vue` | 小 |
| 3.7 | 评估 AgentTaskList 与 AIAssistantPanel 合并 | `AgentTaskList.vue` | 小 |
| 3.8 | 增量分析：change_tracker Git diff → 触发增量 Agent 分析 | `change_tracker/` + Agent | 大 |
| 3.9 | Agent 运行时循环（自主规划→执行→反思） | `runtime.py` | 大 |

**验证标准**：
- AI 对话中输入"分析当前项目的架构" → 触发 ArchAnalystWorkflow → 结果以图表形式展示
- AI 对话中输入"对比上次版本" → 触发 ArchSentinelWorkflow → 差异展示
- Agent 任务结果可从 AgentTaskList 查看，也可在 AI 对话中回溯
- 代码变更后自动触发增量 Agent 分析（可选，P2）

### Phase 4: 差异化高级能力（P2，远期）

| # | 任务 | 说明 |
|---|------|------|
| 4.1 | 可视化变更对比（Mermaid 图 diff） | 架构版本间差异的可视化展示 |
| 4.2 | Agent 编排跨工作流 | 多个 Workflow 串联执行 |
| 4.3 | 全量 Agent 能力通过 AI 对话暴露 | 消除所有独立入口 |

---

## 六、实施建议

### 优先级原则
- **P0（必须）**：AI 说话+图同步，这是核心交互创新，也是用户感知最强的能力
- **P1（重要）**：引导对话 + Suggestion Chips + Agent 入口统一，提升用户体验
- **P2（增强）**：增量分析 + 运行时循环 + 可视化对比，差异化竞争力

### 风险
1. `[CMD:]` 标签解析在流式输出中可能断裂 → 方案：流式完成后统一解析
2. 图渲染性能受频繁命令影响 → 方案：命令队列 + debounce
3. 后端 Agent 工作流执行时间长（分钟级）→ 方案：非阻塞触发 + 进度通知
4. ChatView 和 AgentTaskList 的合并可能影响现有用户习惯 → 方案：渐进式合并，先互通再统一

### 依赖关系
- Phase 1 独立，无外部依赖，可立即开始
- Phase 2 依赖 Phase 1 的 GraphCommandBus
- Phase 3 依赖 Phase 1 的 AI 面板改造，后端的 RouterHarness 已就绪
- Phase 4 依赖 Phase 3 的 Agent 结果回写管道

---

## 七、附录：文档溯源表

| 文档 | 状态 | 对本方案的价值 | 是否需更新 |
|------|------|---------------|-----------|
| `Agent相关能力代码位置总览.md` | ✅ 准确 | 代码位置映射 | ❌ 无需更新 |
| `agent相关功能改版文档.md` v5.2 | ⚠️ 过期 | 哲学参考，不实现 | ⚠️ 可归档 |
| `AGENT-LLM解析-架构版本跟踪-开发计划文档.md` | ⚠️ 待执行 | 缺失列表参考 | ❌ 无需更新（由本方案替代） |
| `AI助手架构分析引导.md` | ✅ 当前 | Phase 1-2 详细设计 | ✅ 按本方案持续更新 |
| `架构可视化功能改版.md` | ✅ 完成 | Graph 组件参考 | ❌ 无需更新 |
| `数据库与LLM管线清理评估.md` | ✅ 完成 | 背景参考 | ❌ 无需更新 |
| `语法分析结构分析改造计划.md` | 📝 进行中 | 独立轨道，无冲突 | ❌ 单独跟踪 |
| `architecture-assessment.md` | ✅ 完成 | 架构评估背景 | ❌ 无需更新 |
| `待办事项06-14.md` | 📝 进行中 | 部分项与本方案重叠 | ✅ 完成后更新 |
