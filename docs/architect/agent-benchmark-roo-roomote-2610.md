# Roo Code / Roomote 双项目对标分析 × Architect 能力定位

> 2026-10-06 · 外部对标分析（输入型文档）
> 上游消费方：[agent-capability-design-2609.md](agent-capability-design-2609.md)、[agent-arch-gap-adoption-2609.md](agent-arch-gap-adoption-2609.md)、[agent-harness-evaluation-2609.md](agent-harness-evaluation-2609.md)
> 分析对象：`/home/cuser/soft/Roo-Code-3.54.0`（Roo Code VS Code 扩展最终版）、`/home/cuser/soft/Roomote-1.16.0`（RooCodeInc 云端 agent 平台）
> 所有 `file:line` 锚点均基于上述两个源码树实测，可直接定位验证。

---

## 一、分析对象总览

### 1.1 关系澄清

两个项目同出 RooCodeInc，但是**两种产品形态**：

| | Roo Code 3.54.0 | Roomote 1.16.0 |
|---|---|---|
| 形态 | VS Code 扩展（IDE 内 agent） | 云端编码 agent 平台（Slack/Teams 发任务 → 沙箱 → PR） |
| 角色 | **Roo Code 系的终点**（`ClineProvider.ts:152` `latestAnnouncementId = "may-2026-final-roo-code-release"`，浏览器工具已移除） | **继任者**：团队重心转向云平台 |
| 架构核心 | 模式系统 + 审批循环 + shadow git 快照 | 多租户控制平面 + 沙箱供给 + 凭据防线 |

### 1.2 Roo Code 架构摘要（分层）

```
webview-ui/ (React+Vite, Context 状态)   packages/types (协议单一事实来源)
        ↕ postMessage: ~70 种 ExtensionMessage / ~130 种 WebviewMessage
src/core/webview/ClineProvider.ts (3149 行, Controller: 任务栈+状态推送+模式切换)
        ↕
src/core/task/Task.ts (4619 行, 核心 agent loop)
   ├── assistant-message/ (NativeToolCallParser 流式解析 + presentAssistantMessage 调度)
   ├── tools/ (26 个工具, BaseTool 模板方法)
   ├── auto-approval/ (审批四值决策 + 配额)
   ├── prompts/ (system prompt 10 章节组装)
   ├── context-management/ + condense/ (压缩/截断)
   └── checkpoints/ (编排) → services/checkpoints/ (shadow git)
src/api/ (27 个 provider, 统一 Anthropic 消息格式)
src/services/ (McpHub / tree-sitter / ripgrep / code-index / skills)
apps/cli (vscode-shim 复用扩展宿主跑终端 agent)
```

关键演进：**3.54.0 已完全迁移 native tool calling**，旧版"XML 标签嵌在文本流里解析工具"机制整体移除（`presentAssistantMessage.ts:301` 直接报错 "XML tool calls are no longer supported"）。

### 1.3 Roomote 架构摘要

```
用户(Slack/Web/Linear/GitHub) → api(Hono, :13001) → Postgres(Drizzle, ~130 表)
                                  │ enqueueTask() — prompt 预生成持久化 + 幂等三件套
                                  ▼
                     Redis queue:cloud-jobs:v2 (Lua 原子队列, scope=workspace)
                                  │ dequeueTaskRun() 轮询
                                  ▼
              controller → 铸 5h run token → spawn 沙箱(8 种 provider)
                                  │ docker exec -e AUTH_TOKEN（不进容器 env）
                                  ▼
   worker(run-task) → opencode serve → agent 循环 → roomote MCP 回 API
```

关键结论：**推理循环完全交给 OpenCode（`opencode serve` HTTP 形态），Roomote 只做控制平面**——prompt 组装、状态机、队列、MCP 网关、快照调度全部自研。BullMQ 仅做副业（定时/通知），任务主链路走自研 Redis 队列 + DB 兜底。

### 1.4 两项目核心对比

| 维度 | Roo Code | Roomote |
|---|---|---|
| Agent 引擎 | 自研 Task 循环（native tool calling） | OpenCode 内核 + 自研控制平面 |
| 任务状态 | 内存 + 本地 JSON 持久化 | Postgres 状态机 + Redis 队列 + DB 兜底 |
| 审批 | ask 循环 + auto-approval 四值决策 | 沙箱 permission 矩阵 + judge subagent |
| 快照 | shadow git（每任务 repo） | provider 快照/standby（快照即销毁） |
| 安全边界 | .rooignore / RooProtect / 工作区 | 零凭据沙箱 + 推理网关 + credential-egress |
| 上下文管理 | condense（LLM 摘要）+ 滑窗截断，非破坏性标签 | ROOMOTE_COMPACT_PROMPT 交接单 |

共同血统：双消息历史、提示词分层组装、非破坏性上下文操作、错误回喂 LLM 自我纠正。

---

## 二、Architect 能力定位（参照系）

Architect 现状：Vue3 前端 + Python 后端（`:3470`，architect.db）的架构工作台——需求管理、KB 知识库、会话、MCP、单测、mermaid 蓝图、命名规约提案卡、AGENTS.md 契约生成；v2 统一会话（`agent` 字段：`''`=architect 外循环，`cline/opencode/codex`=subagent）+ 工具回喂循环（`llm_round` 相位事件）。

参照系映射：

| 参照物 | 它是什么 | 对 architect 的启示 |
|---|---|---|
| Roo 的 **Architect 模式** | 读为主 + 只许编辑 `.md`（fileRegex 硬约束） | 架构师 agent 的核心是**分析产物**（蓝图/规约/契约文档），不是改代码 |
| Roo 的 **Orchestrator 模式** | 空 groups，只靠 `new_task` 委派 | 外循环不做重活，委派给 subagent（已有此模型） |
| Roomote 的 **Fast agent** | 无沙箱、进程内轻量 LLM 循环，处理"问答/聚合/委派决策" | architect 外循环 = Fast agent：对话、分析决策、发起委派 |
| Roomote 的 **沙箱 task** | 重执行（写码/跑测试/开 PR） | 委派给 cline/opencode/codex subagent 执行 |

**定位结论：architect 外循环 = Roomote Fast agent（轻外循环 + 委派）× Roo Architect 模式（只读分析 + 受限产出）× Roomote packaged skills（声明式分析技能库）。不重造 harness——这是 Roomote 最核心的教训："成熟 harness + 自研控制平面"。**

---

## 三、分类借鉴清单

### A. Harness / 循环层（architect 外循环自身）

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **流式解析/执行解耦四件套**：可变数组 + 游标 + 单飞锁 + ready 布尔 | Roo `presentAssistantMessage.ts:64-944` | `llm_round` 同步往返 → WS 流式 chunk 驱动，工具执行不阻塞下一 chunk 渲染 |
| **显式栈迭代替代递归** | Roo `Task.ts:2465-2472` | 外循环多轮分析/重试天然支持携带状态（retryAttempt 等） |
| **native tool calling + partial-json 增量解析** | Roo `NativeToolCallParser.ts:268` | 工具参数流式呈现（"正在读 XX 模块…"实时反馈） |
| **native 协议配对防御五层**（tool_use↔tool_result 一问一答） | Roo `Task.ts:2046-2131, 3350-3444` | 会话恢复时为孤儿 tool_use 补 "interrupted" 占位，防 API 400 |
| **compact prompt 交接单**（非摘要：必须重载清单 + 恢复后唯一动作） | Roomote `compact-prompt.ts:5-29` | 跨长会话/跨仓库分析的关键，KB 分析会话压缩直接抄 |
| **ToolRepetitionDetector + consecutiveMistakeCount** | Roo `ToolRepetitionDetector.ts:9`, `Task.ts:513` | 外循环防复读同一工具；失败计数 + 人类介入阈值 |

### B. 工具机制（对架构分析最有价值）

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **tree-sitter 结构大纲提取**（web-tree-sitter WASM，30+ 语言惰性加载） | Roo `services/tree-sitter/index.ts:97`, `languageParser.ts:78` | ★ 核心弹药：符号级大纲喂 graph-kernel/KB，比全文读便宜得多 |
| **工具三层防御**：请求前过滤 → 调用校验 → 提示词预告 | Roo `filter-tools-for-mode.ts:225` + `validateToolUse.ts:120` | 分析会话只给 read 组；产出类工具（写蓝图/规约）单独分组 |
| **文件正则约束**（`["edit", {fileRegex}]` 元组设计） | Roo `packages/types/src/mode.ts:37` | architect 的"写"仅限产物类型：`.md`/mermaid/契约 JSON |
| **`@mention` 上下文选择**（@file/@problems/@git-changes → 独立 content block） | Roo `core/mentions/index.ts:99` | 左栏对话引用代码位置的标准交互 |
| **FileContextTracker 新鲜度**（Roo 编辑集合抑制自触发） | Roo `context-tracking/FileContextTracker.ts:23` | KB 索引过期检测："文件已变更，分析结论可能过期" |
| **错误统一回喂 LLM**（FileRestrictionError 自带允许 pattern + 拿到的路径） | Roo `prompts/responses.ts:8-57`, `validateToolUse.ts:213` | 工具失败不是 UI 报错，而是模型自我纠正的机会 |

### C. Skills 体系（Roomote 最大亮点，建议直接采用）

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **Packaged skills = SKILL.md 文件资产**（~30 个，运行时按需加载，非 prompt 前置） | Roomote `workflows/skills/standard/` | 现有服务拆成声明式技能：`analyze-module` / `extract-naming-conventions` / `generate-blueprint` / `draft-requirements` / `review-architecture` |
| **`<child_skill_registry>` 父子委派协议**（跨委派边界义务传递） | Roomote `implement-changes/SKILL.md:6-60` | "分析 → 出蓝图 → 生成脚手架"链条的技能编排 |
| **强制 N 选 1 路由**（`<initial_routing>`） | Roomote `standardTask.ts:487-502` | 外循环启动时强制选择分析路径，替代自由发挥 |
| **project > global、mode 专属 > 通用覆盖** | Roo `SkillsManager.ts:229-252` | 用户自定义分析技能覆盖内置技能 |
| **仓库本地技能发现** | Roomote `workspace/repo-local-skills.ts` | 被分析仓库自带 `.agents/skills/` 自动注册 |

### D. 提示词工程

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **三层职责分离**：身份（不变）/ 工作流信封（按任务类型）/ 环境指令（按部署） | Roomote §2.1；Roo `system.ts:41-110` | 产品身份层 + 分析工作流信封（按需求分析/蓝图/规约分型）+ 项目环境层 |
| **按消费者切换人格**（`reportConsumer: 'orchestrator'` 分叉） | Roomote `system-prompt.ts:48` | 同一 agent 服务"人（工作台对话）"和"上游（委派报告）" |
| **environment_details 请求级新鲜度**（每轮重算、不持久化、尾部独立块、保护缓存前缀） | Roo `getEnvironmentDetails.ts:23`, `Task.ts:2566-2598` | 每轮注入图谱状态/已分析模块/打开的资产 |
| **提示词快照测试** | Roo `prompts/__tests__/__snapshots__/system-prompt/*.snap` | ★ 低成本高收益，立即采纳 |
| **XML 信封 + `<request>` 转义防注入** | Roomote `standardTask.ts:578-614` | 用户需求文本包标签转义 |
| **规则文件优先级洋葱**（`rules-{mode}/` → 旧格式回退 → AGENTS.md 族） | Roo `custom-instructions.ts:382-507` | 已生成 AGENTS.md（contract-service）——补加载/合并链形成闭环 |

### E. 人机协作 / 审批（与提案卡交互高度相关）

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **审批四值决策** approve/deny/ask/**timeout**（timeout 自动采纳建议答案） | Roo `auto-approval/index.ts:47-90` | 命名规约提案卡：agent 提案 → 用户确认（现模型）+ 低风险提案 timeout 自动通过 |
| **ask 阻塞轮询 + 排队消息消费** | Roo `Task.ts:1384-1422` | 分析会话中用户补充信息排队，不丢消息 |
| **followup_question + 建议答案** | Roo `ask_followup_question` | 需求澄清环节结构化提问 |
| **用户手动编辑检测反馈给 LLM** | Roo `DiffViewProvider.saveChanges` | 用户改了 agent 生成的蓝图/规约 → diff 反馈给模型学习偏好 |

### F. 多 agent 编排（已有 subagent 路由，补齐协议）

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **委派即隔离**（new_task 与其他工具同现时截断 + is_error 注入） | Roo `Task.ts:3411-3437` | 委派 cline/opencode/codex 的原子性 |
| **actor-scoped turns**（换人后旧消息不在新凭据下执行） | Roomote `run-task.ts:1284-1439` | 多人工作台会话安全 |
| **委派报告契约**（六段式 `<reporting_context>` + 非空结题校验） | Roomote `standardTask.ts:382-400` | subagent 回报 architect 的结构化结果（要分析结论，不要流水账） |
| **judge/advisor subagent 模式** | Roomote `opencode-prompt-subagents.ts:51-105` | 架构评审 judge（蓝图 vs 代码实际结构一致性）；卡壳时 advisor |
| **幂等三件套**（launchIdempotencyKey + advisory lock + 唯一索引） | Roomote `task-run-queue.ts:1597-1609` | 委派任务不重复发起 |

### G. 状态 / 协议 / 工程化

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **协议双端共享**（packages/types 定义全部消息类型） | Roo `vscode-extension-host.ts:23-629` | Vue ↔ Python WS 协议单一 schema 源（zod/pydantic 双生成） |
| **序列号防竞态**（seq 单调递增 + 前端丢弃旧快照） | Roo `ExtensionStateContext.tsx:136-175` | WS 重连/多标签页下流式消息不回退 |
| **双历史 + 非破坏性标签**（condenseParent/truncationParent，rewind 可复活） | Roo `context-management/index.ts:65-115`, `condense/index.ts:451-477` | 长分析会话压缩 + 用户回退正交可逆 |
| **Zod schema 三职合一**（校验/类型/JSON Schema 导出） | Roo `packages/types/src/mode.ts` | 技能/提案/契约文件的 schema 即文档 |
| **YAML 输入防御性解析**（零宽字符清洗、回退 JSON） | Roo `CustomModesManager.ts:115-142` | 用户手写配置的现实主义处理 |
| **模型角色声明**（coding/explore/judge 分模型 + fallback 链） | Roomote `types/model-provider-config.ts TASK_MODEL_ROLE_DESCRIPTORS` | 分析用便宜模型、评审用强模型 |

### H. MCP（已有 McpPage，值得补三点）

| 借鉴点 | 来源锚点 | 落点 |
|---|---|---|
| **project > global 配置覆盖** | Roo `McpHub.ts:453-471` | MCP 配置层级 |
| **alwaysAllow/disabledTools 按工具粒度**（支持 `*` 通配） | Roo `McpHub.ts:1024` | 分析类 MCP 工具免审批 |
| **工具名 sanitized + 模糊反解**（`mcp--server--tool` 64 字符上限） | Roo `utils/mcp-name.ts:127,149` | 工具名兼容性与历史回显 |

---

## 四、优先级路线图建议

- **P0（立即，低成本）**：提示词快照测试、三层 prompt 分离、`<request>` 转义、审批四值决策（增强提案卡）、Zod schema、序列号防竞态
- **P1（核心竞争力）**：tree-sitter 结构大纲提取（喂 graph-kernel）、packaged skills 化现有服务、compact 交接单、native tool calling 流式四件套、AGENTS.md 规则链闭环
- **P2（规模化）**：judge subagent、actor-scoped turns、委派报告契约、模型角色路由、MCP 配置覆盖体系

---

## 五、Architect 的独立特性与差异化竞争优势

### 5.1 竞品坐标系

```
              写代码优化（autonomy ↑）
                      │
      Roo/Cline/Cursor │ Devin/Roomote
      （IDE 编码 agent） │（云端自治 agent）
                      │
  ─────────────────────┼─────────────────────
     理解已有系统 ←    │    → 设计未来系统
                      │
      Swimm/Backstage │ Architect（TopoCode）
      （静态文档工具）  │（人机协同知识型 agent）
                      │
              理解/知识优化（curation ↑）
```

四类竞品的空档：**IDE agent 优化"写得快"，云 agent 优化"无人值守"，文档工具静态且人工，架构建模工具（C4/Structurizr）纯手工绘图**。没有人做"从代码中**归纳**知识、经人确认**固化**、再反哺生成与执行"的闭环。Architect 的机会正在于此。

### 5.2 现有独立特性盘点（已具备差异化基因的能力）

| # | 特性 | 现状证据 | 为什么有差异化 |
|---|---|---|---|
| 1 | **知识资产沉淀 + 提案确认工作流** | naming-service 提案卡（agent 归纳 → pending → 界面确认 → active）；kb-assets/semantic-asset-service | 对标"知识的 PR review"。Roo/Roomote 的对话产物即焚，Architect 的分析结论是**带确认链的持久资产**——数据壁垒 + 工作流切换成本 |
| 2 | **命名规约归纳 + 带证据违约检查** | naming-service（规约归纳提议、`规约违约检查(agent 通道): active 规约 × 变更符号 → 带证据违约清单`） | "从代码学规约"而非"人写规约"。Roo 的 `.roo/rules` 靠人写；Architect 反向归纳，且违约有证据链 |
| 3 | **AGENTS.md 双向闭环** | contract-service（agentsMd 生成 + 条目 injected） | 既能生成 AGENTS.md 给下游 coding agent 消费，又能从代码/会话归纳条目——Roo 只读不写 |
| 4 | **需求 → 蓝图 → 脚手架 → 单测工作流闭环** | requirement-service / req-draft-service → overview-service（蓝图）→ scaffold-service → unit-test-service | 四段全链路；竞品各占一段（Jira 管需求、Cursor 写码），无人串成架构主线。单测段的定位细化见 [unit-test-repositioning-2610.md](unit-test-repositioning-2610.md)（策略层 owner + 感知补位机制） |
| 5 | **多 harness 中立编排** | v2 统一会话 `agent` 字段（`''`=外循环；cline/opencode/codex=subagent） | 与 Roomote "harness 可替换"同构，但面向**分析域**而非编码域。下游 harness 换代不伤上层知识资产 |
| 6 | **graph-kernel 图内核** | packages/graph-kernel | ★ Roo/Roomote 都没有图结构。竞品 agent 用 grep/AST 碎片化理解；图内核是一等公民 |
| 7 | **Mermaid 蓝图人机共编** | diagram 组件、guide-service（"由 agent 依据需求草拟，用户逐层细化确认"） | C4 工具是纯手工，agent 蓝图工具是纯自动；"草拟-细化-确认"的共编模式是第三条路 |

### 5.3 值得深挖的差异化方向（按独特性排序）

**D1. Graph-grounded agent context（图感知上下文）——最深的护城河**

现状：所有 coding agent 的代码理解 = grep + read_file + AST 单文件大纲（Roo `parseSourceCodeDefinitionsForFile`）。
深挖：用 graph-kernel 把"图查询"变成 agent 的一等工具——`call_graph(callers/callees)`、`module_deps`、`impact_radius(symbol)`、`arch_layers`。
- 外循环每轮注入的不是文件列表，而是**当前分析焦点在图上的邻域**（Roo environment_details 的图版）
- tree-sitter 大纲（P1 已列）作为图的增量构建器：`符号大纲 → 图增量合并 → KB 引用图`
- 这是 Roo/Roomote/Cline 生态**无法低成本复制**的能力（它们没有图内核，补建需要重构上下文管线）

**D2. 架构漂移检测（blueprint ↔ code 一致性 judge）**

移植 Roomote judge 模式（`opencode-prompt-subagents.ts:51-83`：proof diff 快照比对"未披露的源码漂移"）：
- 蓝图（overview-service 产出）与代码实际结构定期比对，产出"漂移清单"（新模块未上图、图上模块已删除、依赖方向违反蓝图）
- judge subagent 用便宜模型跑增量比对，强模型只裁决疑点（模型角色路由，G 节）
- 杀手级用例：架构评审会前自动出漂移报告。竞品无此能力——它们根本没有持久蓝图可比对

**D3. 知识资产的时效性管理（KB 与源码变更联动）**

移植 FileContextTracker（Roo `context-tracking/FileContextTracker.ts:23`）+ Roomote 快照卫生思想：
- KB 条目/规约/蓝图记录"基于哪个 commit 分析"
- 仓库变更 → 受影响条目标记 `stale`（图可达性计算影响面：改了 X，哪些 KB 条目引用了 X 的符号）
- 与 D1 天然协同：图增量更新时同步打标

**D4. 规约执行闭环（规约 → 注入 → 生成 → 回归检查）**

命名规约现在是"检查清单"；闭环化：
1. 归纳（已有）→ 2. 生成 AGENTS.md 注入 subagent（contract-service 已有管道）→ 3. scaffold/委派生成代码自动合规 → 4. 违约检查回归（已有）→ 5. 违约证据反哺规约修订（新）
- 形成自我改进回路，是"学习型 agent"叙事的实证支点

**D5. 架构学习路径生成（onboarding 场景）**

产品名定位是"源码架构分析与学习工具"，但"学习"尚未产品化：
- 图上做路径规划（入口 → 核心域 → 边界），生成带叙事的学习路线 + 每站验证问题（followup_question 模式，E 节）
- 新人 day-1 到 day-5 路线；每次代码变更追加"增量学习卡"
- 竞品：Swimm 类工具靠人工写教程；agent 驱动的个性化学习路径是空档

**D6. 增量分析（repo watch → 图增量 → KB 增量修订）**

Roomote 的增量同步思想（`pullRequestSyncStates` 游标，`db/schema.ts:2801`）移植到分析域：分析不是一次性快照而是持续过程，成本从 O(全仓) 降到 O(变更集)。

**D7. 分析成本归因**

Roomote `llmUsageEvents`（按 workflow phase 归因，`workflow-phase.ts:7-52`）移植：每次分析/每张蓝图/每条规约的 token 成本可归因，支撑企业版定价与"分析预算"功能。

**D8. 分析技能的可分享性（技能市场潜力）**

Packaged skills（C 节）采纳后，SKILL.md 天然是可分享资产：`extract-naming-conventions`、`review-architecture` 可以在组织内/社区流通——构建生态位的低成本入口。

### 5.4 竞争壁垒小结

| 壁垒类型 | 支撑 |
|---|---|
| **数据壁垒** | KB/规约/蓝图是用户组织私有知识资产，随使用加深而增值，迁移成本高 |
| **工作流壁垒** | 提案确认工作流把 agent 输出纳入组织治理，竞品"纯对话"无法替代 |
| **技术壁垒** | graph-kernel + 图感知上下文需要上下文管线整体重构，先发者优势明显 |
| **生态壁垒** | AGENTS.md 双向闭环 + 多 harness 中立，使 architect 成为"架构层协议节点"——下游 harness 可换，架构知识资产留在本位 |

---

## 六、行动建议汇总

1. **立即**（本周可做）：提示词快照测试、`<request>` 转义、审批四值决策落地到提案卡、Zod schema 化技能/提案
2. **P1 主线**：tree-sitter 大纲 → graph-kernel 增量合并（D1 地基）；packaged skills 化五个现有服务；compact 交接单
3. **差异化主攻**：D1 图感知上下文 + D2 漂移检测 + D3 知识时效性，三者共享图内核地基，建议作为 v3 能力主线立项
4. **叙事锚点**：对外统一口径——"coding agent 帮你写代码，Architect 帮你**看懂并守住**你的架构"

---

## 附：关键文件速查（两个参照项目）

| 主题 | 锚点 |
|---|---|
| Roo 主循环 | `src/core/task/Task.ts:2427(initiateTaskLoop), 2461(栈循环), 3876(attemptApiRequest)` |
| 流式解析 | `src/core/assistant-message/NativeToolCallParser.ts:268, presentAssistantMessage.ts:64` |
| 审批 | `src/core/auto-approval/index.ts:47, commands.ts:256, AutoApprovalHandler.ts:13` |
| 上下文 | `src/core/context-management/index.ts:243, condense/index.ts:254, message-manager/index.ts:48` |
| 模式系统 | `packages/types/src/mode.ts:96,168; src/shared/modes.ts:51,111; src/core/tools/validateToolUse.ts:120` |
| 提示词 | `src/core/prompts/system.ts:41; sections/custom-instructions.ts:382; sections/index.ts:1-10` |
| API 层 | `src/api/index.ts:91,111; providers/base-openai-compatible-provider.ts:26; transform/stream.ts:1` |
| MCP | `src/services/mcp/McpHub.ts:150,453,1024; src/utils/mcp-name.ts:127` |
| checkpoint | `src/services/checkpoints/ShadowCheckpointService.ts:79,129; src/core/checkpoints/index.ts:27` |
| Roomote 入队 | `packages/cloud-agents/src/server/task-run-queue.ts:183,1363` |
| Roomote 工作流 | `packages/cloud-agents/src/server/workflows/standardTask.ts:49,487,578` |
| Roomote skills | `packages/cloud-agents/src/server/workflows/skills/standard/implement-changes/SKILL.md` |
| Roomote subagent | `packages/cloud-agents/src/opencode-prompt-subagents.ts:4,51,85` |
| Roomote compact | `packages/cloud-agents/src/compact-prompt.ts:5` |
| Roomote 凭据 | `apps/api/src/handlers/credential-egress/CONTRACT.md; apps/worker/src/lib/github-token.ts:156` |
| Roomote 沙箱接口 | `packages/compute-providers/src/types.ts:198` |
