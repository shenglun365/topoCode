# Agent 相关功能改版设计文档

> 版本: v5.2 | 日期: 2026-06-09 | 状态: 已完成 — 开发就绪
> 
> v5.2 更新: 分布式架构 — 云端内容管理/增强/订阅 + git 式节点模型
> v5.1 更新: 认知层级扩展为 7 层 + 自底向上三层追问 + 产品价值场景表
> v5.0 更新: 产品哲学重塑 — 以人为核心，提升认知层级而非信息量
> v4.3 更新: 新增架构学习/设计 Skills
> v4.1 更新: 明确 topocode 业务目标 — 架构驱动、质量优先，独立自足
> v4.0 更新: 精简对外 MCP Tools — 聚焦社区/架构/时序/质量层
> v3.0 更新: 内置 Agent 运行时 — topocode 自身具备 Agent 能力，不依赖第三方
> v2.0 更新: 全面 Agent 化架构 — LLM 解析基于统一上下文 + Skills 驱动

---

## 零、产品哲学 — 以人为核心

### 0.1 核心价值锚点

**topocode 存在的理由：提升人的认知层级，而非增加人的信息负担。**

### 0.1.1 认知层级：自上而下的七层追问

```
                人的认知层级（自上而下）

     目标级   ← 我要做什么？            topocode 帮人设定方向
     必要性级 ← 我为什么做？            topocode 帮人判断问题和优先级
     ──────────────────────────────────────────────
     决策级   ← 我该怎么做？            topocode 基于事实给出建议
     模式级   ← 这是什么模式？          topocode 识别架构模式
     社区级   ← 哪些东西是一体的？       topocode 揭示子系统边界
     ──────────────────────────────────────────────
     符号级   ← 这个函数叫啥？           codegraph / IDE 的领域
     文件级   ← 这个文件在哪？           IDE 基本能力
```

核心洞察：**多数工具停在符号/文件级（告诉你"有什么"），topocode 的价值在社区/模式/决策/必要/目标五级（帮你回答"为什么"和"怎么办"）。**

### 0.1.2 解释深度：自底向上的三层追问

认知层级解决"思考的维度"，还需要一个互补维度——**解释深度**，解决"理解的深度"。任何一层认知，都可以从三个深度追问：

| 追问层 | 含义 | 对 auth 社区的例子 |
|--------|------|-------------------|
| **1. 干了什么** (功能) | 这个模块/子系统实现了什么功能 | "auth 社区实现了用户认证和授权，包含 authenticate、authorize、jwtVerify 三个核心函数，是系统安全边界" |
| **2. 怎么干的** (逻辑) | 如何实现的：流程、协作、数据流 | "authenticate 解析 Bearer token → jwtVerify 验证签名 → 从 User 表加载角色 → authorize 检查权限。调用链跨 3 个文件，核心是 handler.ts 中的中间件模式" |
| **3. 为什么这么干** (因果) | 为什么这样实现：技术选型、外部约束、历史原因、权衡 | "选择 JWT 而非 session 是因为系统需要无状态水平扩展，但引入了 token 撤销难的问题。authenticate 跨了 jwt-community 和 api-community 两个社区，是因为安全中间件必须在请求入口拦截——这是框架层定义的硬约束，不是设计选择" |

**三层追问的核心价值**：第一层帮你"知道"，第二层帮你"理解"，第三层帮你"判断"——判断这个设计是精妙还是妥协，是主动选择还是被动继承。

### 0.1.3 二维模型

认知层级（自上而下）和解释深度（自底向上）构成完整的认知矩阵：

```
              目标级  ← 我要做什么？
              必要性级 ← 我为什么做？       每一层都追问:
              决策级  ← 我该怎么做？     ┌─────────────────┐
              模式级  ← 这是什么模式？   │ 干了什么 (功能)   │
              社区级  ← 哪些是一体的？   │ 怎么干的 (逻辑)   │
              符号级 / 文件级            │ 为什么这么干 (因果)│
                                        └─────────────────┘
              认知层级 (自上而下 → 抽象)  解释深度 (自底向上 → 因果)
```

**这意味着每个 tool 和 Skill 的输出不只是"展示数据"，而是"展示数据 + 解释逻辑 + 揭示因果"。**

**topocode 不做的事**：把 30,000 个符号列出来（信息轰炸）；告诉你 authenticate 在第 42 行（codegraph 已做到极致）。

**topocode 要做的事**：告诉你"auth 子系统的中心节点是 authenticate，理解它就理解了系统 60% 的请求处理链路。它是表示层和安全层的桥梁——边界由 JWT 验证这个安全约束定义。选择 JWT 是因为无状态扩展需求，但带来了 token 撤销难的问题——这个权衡值得关注。"

### 0.2 两个视角

**以人为核心（学习视角）**：帮助人从"在这个项目里看不懂"到"能抽象理解架构"，再到"能自主设计架构"。提升学习效率、学习体验、设计效率和设计体验。

**以事为核心（开发全流程视角）**：辅助人在设计、实现、迭代、重构各阶段做出高效高质量决策。感知变化、解读影响、给出建议——但决策权永远在人手里。

### 0.3 设计原则

| 原则 | 说明 |
|------|------|
| **输出抽象，而非枚举** | 每个 tool 回答的不是"有哪些"，而是"意味着什么" |
| **渐进披露** | 先给框架（3 层架构，12 个核心子系统），人需要时再展开具体模块 |
| **教人，而非替代人** | 解释"为什么形成这个社区"，让人建立架构直觉，而非生成一个无人理解的"正确答案" |
| **可知、可控** | 人对项目当前状况可知（community/arch_overview），对变更过程可控（diff/session/quality） |
| **本地部署、私域知识** | 每个人的 topocode 积累的是他关心的项目、他的分析历史——形成私域核心竞争力 |

### 0.4 与 codegraph 的关系

| | codegraph | topocode |
|---|---|---|
| **认知层级** | 符号级 / 文件级 | 社区级 / 模式级 / 决策级 / 必要性级 / 目标级 |
| **核心价值** | 信息效率 — 快速精准回答代码问题 | 认知升级 — 让人不再需要问那些问题 |
| **输出特征** | "authenticate 在 handler.ts:42，被 15 个函数调用" | "authenticate 是 auth 的中心节点，它的角色、为什么这样设计、有什么权衡" |
| **独立性** | — | topocode 完全自足，不假设 codegraph 存在 |

**topocode 不追求替代 codegraph，两者是不同认知层级的工具。**

### 0.5 产品价值：topocode 能帮使用者做什么

| 使用场景 | 用户面临的问题 | topocode 的帮助 | 触及的认知层 |
|---------|--------------|---------------|------------|
| **接手陌生项目** | 几百个文件，不知从哪看起 | `community` + `arch_overview` → 3 分钟建立"地图感"，知道有哪些子系统、谁依赖谁 | 社区级、模式级 |
| **准备重构** | 不知道改了核心模块会有什么连锁反应 | `quality_inspect` + `skill_recommend_refactor` → 识别风险点，给出具体解耦建议 | 决策级、必要性级 |
| **审查 AI 生成的代码** | AI 改了代码但不确定质量和影响 | `session_summary` + `diff` → 对 AI 的工作成果可知、可控，知道哪些模块需要重点检查 | 决策级 |
| **设计新模块** | 不确定新模块放在哪个子系统最合适 | `skill_validate_arch_impact` → 预测对现有架构的影响，推荐归属社区，评估风险 | 必要性级、决策级 |
| **长期维护后复盘** | 迭代了 100 个版本，项目有没有在腐化 | `topocode_community` 历史对比 + `skill_detect_arch_drift` → 架构趋势可视化，及早发现腐化信号 | 必要性级、目标级 |
| **向团队解释架构** | 需要让别人理解架构为什么是这样设计的 | `skill_explain_arch_pattern` + `topocode_architecture_overview` → 生成带因果解释的架构文档，不只展示结构，更解释缘由 | 模式级 |
| **对比技术方案** | 重构方案 A 和 B 哪个更好 | `skill_compare_arch` + `skill_recommend_refactor` → 基于社区检测数据对比两个方案的架构影响 | 目标级、必要性级 |
| **持续感知项目变化** | 每次发版后想知道架构是否朝好的方向演化 | `topocode_diff` + `skill_compare_arch` → 解读变化趋势，不只列差异 | 必要性级 |

---

## 一、背景与目标

### 业务目标

**topocode 的核心使命：提升人的架构认知水平，让人对软件现状和开发过程可知、可控。**

```
           架构分析 (基础能力)
                │
     ┌──────────┴──────────┐
     ▼                     ▼
 以人为核心               以事为核心
 (学习+设计效率)          (全流程决策辅助)
     │                     │
     ▼                     ▼
 提升认知层级            辅助高质量决策
 (抽象 > 枚举)           (感知 > 解读 > 建议)
```

### 核心定位

| 定位 | 说明 |
|------|------|
| **以人为核心** | 帮助人建立架构直觉、提升抽象思维，而非堆砌信息 |
| **可知** | 通过社区/架构视图，让人对项目整体结构一目了然 |
| **可控** | 通过 diff/quality/session 追踪，让人对变更影响心中有数 |
| **本地私域** | 围绕每个人的项目积累分析历史、架构理解，打造私域核心竞争力 |
| **独立自足** | 不假设任何外部工具存在，通过内置 Agent 完成全流程 |
| **不替代 codegraph** | codegraph 做符号/文件级，topocode 做社区/模式/决策级

### 现有问题

当前 topocode 已具备独立的代码架构分析能力（5 步 AST 管线 + Louvain 社区检测），并已实现基础 MCP Server，但存在以下问题：

1. **无 CLI 入口** — 仅 Electron 桌面应用，无法命令行使用
2. **工具设计偏 LSP 风格** — 依赖 file+line+char 定位，不符合 AI agent 通过结构名查询的模式
3. **对外工具定位模糊** — 14 个 tools 中有 8 个与 codegraph 重叠，没有聚焦独特价值
4. **无内置 Agent** — 无法自主驱动批量分析任务
5. **无法追踪 AI coding 会话** — 无法帮助用户了解 AI 做了什么、怎么做的、有什么潜在问题

### 改版目标

1. 建立 CLIMCP/Agent 三层体系，使 topocode 具备独立命令行 + AI 集成能力
2. 对外仅暴露 6 个架构层工具，每个工具输出架构洞察而非符号列表
3. 构建内置 Agent Runtime，自主驱动从分析到文档生成的完整流程
4. 将现有 LLM 模板全部 Skills 化，对内对外统一复用
5. 构建 AI Session 追踪系统，生成结构化变更摘要和质量报告

### 核心原则

- MCP Server 与 Web 预览服务**独立部署，不复用端口**
- 遵循 MCP 标准协议（JSON-RPC 2.0 over stdio）
- **不重复 codegraph** — codegraph 做符号/文件级，topocode 做社区/架构级
- **独立自足** — 不假设任何外部工具存在
- **架构驱动、质量优先** — 所有功能围绕架构理解和质量保障展开

---

## 二、codegraph-0.9.9 参考架构分析

### 2.1 CLI

基于 commander.js，延迟加载重型模块。关键命令：

| 命令 | 功能 |
|------|------|
| `init/uninit [path]` | 初始化/移除 `.codegraph/` |
| `index/sync [path]` | 全量索引 / 增量同步 |
| `status [path]` | 索引健康统计 (`--json`) |
| `query <search>` | FTS 符号搜索 |
| `files [path]` | 文件树 (tree/flat/grouped) |
| `serve` | 启动 MCP 服务 (`--mcp`) |
| `callers/callees/impact <symbol>` | 调用层级 / 影响分析 |
| `affected [files..]` | 变更关联测试文件 |

### 2.2 MCP Server 三模式

```
Direct mode (stdio)  →  单进程，适合类 Claude Code 桌面端
Proxy mode (default) →  thin stdio↔socket 代理，本地回答 initialize/tools/list
                        (~0ms，避免 daemon 冷启动)，tools/call 转发共享 daemon
Daemon mode (socket) →  后台守护进程，共享 CodeGraph + watcher + SQLite
                        客户端引用计数 + idle 超时 (300s) 自动退出
```

**关键设计点：**

- **Lazy project init**：直到 `tools/call` 才真正加载索引
- **Cross-project**：每个工具接受可选 `projectPath` 参数
- **Per-file staleness**：工具返回值头部检测待同步文件 → 横幅警告
- **Worktree mismatch**：检测 `.codegraph/` 属于不同 Git 工作区
- **Adaptive output budget**：按项目规模分层限制输出（max 24K chars）
- **Tiny-repo gating**：<500 文件仅暴露 3 个核心工具
- **Tool allowlist**：`CODEGRAPH_MCP_TOOLS` 环境变量过滤

### 2.3 8 个 MCP Tool

核心理念：**explore-first** — 一个 `codegraph_explore` 调用回答大部分问题。

| Tool | 职责 | 输入 |
|------|------|------|
| `codegraph_explore` | **PRIMARY** — 自然语言或符号名 → FTS+图遍历+源码，一次返回 | `query` |
| `codegraph_search` | 速查符号位置 (无源码) | `query`, `kind` |
| `codegraph_callers` | 谁调用了此符号 | `symbol` |
| `codegraph_callees` | 此符号调用了谁 | `symbol` |
| `codegraph_impact` | 变更影响半径 | `symbol`, `depth` |
| `codegraph_node` | **SECONDARY** — 单符号完整详情+所有重载 | `symbol`, `includeCode` |
| `codegraph_files` | 文件树+语言统计 | `path`, `pattern`, `format` |
| `codegraph_status` | 索引健康检查 | (无) |

**`codegraph_explore` 内部流程：**

1. FTS 搜索 + 图扩展
2. 胶水节点（同文件 callers/callees）
3. 命名种子注入 (query token → symbol definition)
4. Personalized PageRank 排序
5. 相关性门控 (剔除纯文本匹配)
6. 排序: 命名种子 → 图中心度 → term hits → 排斥测试/生成文件
7. Blast radius 摘要
8. 命名符号间最长调用链
9. 自适应体量 (多态叉文件仅签名单行；主干保留全文)
10. 动态分发边内联 (callback, event-emitter, React re-render 等)

### 2.4 SERVER_INSTRUCTIONS（替代 Skills）

codegraph **无显式 Skills 系统**，而是在 MCP `initialize` 响应中通过 `SERVER_INSTRUCTIONS` 注入代理行为指南：

- **Tool selection by intent** — 什么场景用什么工具
- **Common chains** — 重构规划 = search → callers → impact
- **Anti-patterns** — 不要用 grep 验证，不要 chain search+node，不要委托子 agent

这比 Skills 更高效：不占用额外 tool call round-trip，直接在 prompt 层面引导。

### 2.5 Agent 协作

8 个 Agent Target：claude, cursor, codex, opencode, hermes, gemini, antigravity, kiro

集成机制：**纯 MCP 协议**（JSON-RPC 2.0 over stdio）
- Agent 配置: `{"command": "codegraph", "args": ["serve", "--mcp"]}`
- Agent 作为父进程 spawn codegraph，通过 stdin/stdout 通信
- Installer 自动写入各 agent 的配置文件

---

## 三、topocode 现状与差距

### 3.1 现有能力

| 能力 | 状态 | 说明 |
|------|------|------|
| MCP Server | ✅ | 11 tools + 7 skills, JSON-RPC 2.0 over stdio |
| 分析管线 | ✅ | 5 步: AST → 解析 → 依赖 → 框架 → 社区 |
| 社区检测 | ✅ | Louvain 算法, 6 级层次, Hub/Orphan 过滤 |
| ZMQ RPC | ✅ | 89 方法, DEALER (5671) + PUB (5680) |
| 插件系统 | ✅ | 6 插件, 热加载 |
| LLM 集成 | ✅ | OpenAI / Ollama / LM Studio |
| Web 预览 | ✅ | Uvicorn HTTP (默认 3456) |

### 3.2 关键差距 vs codegraph

| 维度 | codegraph | topocode | 影响 |
|------|-----------|----------|------|
| **CLI** | ✅ commander.js | ❌ 无 | 无法命令行使用 |
| **explore-first 工具** | ✅ 一次调用回答 | ❌ 工具是 LSP 式 (file+line+char) | Agent 需多次 round-trip |
| **proxy/daemon 模式** | ✅ 三模式 | ❌ 仅直接模式 | 冷启动慢，无共享 |
| **cross-project** | ✅ 每工具 projectPath | ❌ 单项目 | 无法跨项目查询 |
| **staleness banner** | ✅ 待同步文件警告 | ❌ | Agent 可能用过期数据 |
| **SERVER_INSTRUCTIONS** | ✅ | ❌ | Agent 无工具选择指南 |
| **agent installer** | ✅ 8 个目标 | ❌ | 用户手动配置 |
| **AI session 追踪** | ❌ | ❌ | 无法追溯 AI 行为 |
| **output budget 控制** | ✅ 分层限制 | ❌ | 无 token 预算管理 |
| **tiny-repo gating** | ✅ | ❌ | 小项目工具过多 |

### 3.3 端口隔离决策

MCP Server **不与** Web 预览服务 (uvicorn, 默认 3456) 合并端口：

| 维度 | Web 预览服务 | MCP Server |
|------|-------------|------------|
| **协议** | HTTP/SSE | JSON-RPC 2.0 |
| **传输** | TCP port | stdio (子进程管道) |
| **受众** | 人类用户 Electron webview | AI Agent 子进程 |
| **生命周期** | 随应用启动/停止 | Agent 按需 spawn/kill |

MCP 标准集成即 `command: ["topocode", "serve"]` —— 零端口、零配置。如未来需支持 Web 端 MCP 客户端，通过独立 `--port` 参数启动 HTTP 桥接，而非合并到预览服务。

---

## 四、总体设计

### 4.1 核心哲学：架构驱动、质量优先、独立自足

topocode 不是单纯为第三方 Agent 提供 MCP 工具的被动服务。**topocode 自身是完整的 Agent 运行时**，以架构分析为内核，以提升代码质量为首要目标。

```
        架构分析 ──▶ 架构学习 ──▶ 架构设计
                        │
                        ▼
                 架构驱动开发
                       │
          ┌────────────┴────────────┐
          ▼                         ▼
    提升质量 (首要)           兼顾效率 (次要)
  质量检查/影响评估/         批量文档/智能问答/
  会话追溯/架构漂移          架构理解加速
```

```
                         ┌─── 用户交互 ───┐
                         │                │
                    CLI 命令          前端 Chat UI
                         │                │
                         ▼                ▼
               ┌──────────────────────────────────────────┐
               │         topocode Agent Runtime            │
              │                                          │
              │  ┌────────────┐  ┌────────────────────┐  │
              │  │ Agent Core │  │  Skill Executor    │  │
              │  │ (决策引擎)  │  │  (技能编排+执行)    │  │
              │  │ tools_call │  │  错误重试/进度上报   │  │
              │  └─────┬──────┘  └─────────┬──────────┘  │
              │        │                   │              │
              │        └─────────┬─────────┘              │
              │                  ▼                        │
              │  ┌────────────────────────────────────┐   │
               │  │         Skills Registry             │   │
               │  │  (内部 SDKMCP 双通道共享)         │   │
               │  │                                    │   │
               │  │  架构洞察(Tools) 文档生成  图生成   │   │
               │  │  community  arch_doc   mermaid_dep │   │
               │  │  comm_detail module_doc mermaid_call│  │
               │  │  arch_over.. source_doc plantuml   │   │
               │  │  diff       qa_answer  fix_diagram │   │
               │  │  session..  batch_run  render      │   │
               │  │  quality..                         │   │
               │  │  [ctx.符号/ctx.文件/ctx.准备 ..]    │   │
               │  │        内部 SDK 方法，非 MCP Tool   │   │
              │  └────────────────┬───────────────────┘   │
              │                   │                       │
              │  ┌────────────────▼───────────────────┐   │
              │  │      AnalysisContext               │   │
              │  │      统一上下文管理器                │   │
              │  └────────────────┬───────────────────┘   │
              └──────────────────┼───────────────────────┘
                                 │
                  ┌──────────────┼──────────────┐
                  ▼              ▼              ▼
            graph_node    graph_edge    community_hierarchy
                                 │
         ┌───────────────────────┴───────────────────────┐
         │                                               │
         ▼                                               ▼
  ┌─────────────┐                              ┌──────────────────┐
  │ MCP Server  │                              │  ZMQ API (前端)  │
  │ (对外暴露    │                              │  Electron UI     │
  │  同样Skills) │                              │  ChatView +      │
  │             │                              │  ReportViewer    │
  └──────┬──────┘                              └──────────────────┘
         │
   第三方 AI Agent
   (Claude/Codex/
    OpenCode/Cursor)
```

**核心区别：**

| 维度 | 内置 Agent 模式 | 外部 Agent (MCP) 模式 |
|------|----------------|----------------------|
| 谁做决策 | topocode 自己的 LLM backend | 外部 LLM (Claude/Codex/...) |
| 通信方式 | 进程内函数调用 | MCP (JSON-RPC 2.0 over stdio) |
| Skills 复用 | 直接调用 Skill Executor + 内部 SDK | 仅通过 MCP tools/list → tools/call |
| 上下文 | AnalysisContext 内存共享 | 随 MCP 请求序列化传递 |
| 批量任务 | 内置批处理+并发调度+进度上报 | Agent 逐次调用，自行编排 |
| 适用场景 | 独立运行分析任务，批量文档生成 | 用户在 IDE 中边写代码边查询 |

### 4.2 双通道架构：对内置 Agent 和对外部 Agent 统一 Skills

**同一個 Skills Registry 同时服务于两个通道：**

```
                    Skills Registry
                          │
          ┌───────────────┴───────────────┐
          │                               │
          ▼                               ▼
   ┌──────────────┐              ┌──────────────────┐
   │ 通道 A: 内置  │              │ 通道 B: 外部      │
   │ Agent Runtime │              │ MCP Server       │
   │               │              │                  │
   │ • 直接函数调用 │              │ • JSON-RPC 封装  │
   │ • 共享内存上下文│             │ • stdio/socket   │
   │ • 批量编排    │              │ • 上下文序列化    │
   │ • 进度推送    │              │ • 工具描述注入    │
   └──────┬────────┘              └────────┬─────────┘
          │                                │
          ▼                                ▼
    CLI / 前端 UI                   第三方 AI Agent
   (topocode analyze)              (Claude/Codex/...)
```

**设计原则：** Skill 定义一次，两个通道自动可用。内置 Agent 获得更优性能（无序列化、内存共享），外部 Agent 获得标准 MCP 兼容性。

### 4.3 现有模板 → Skills 的转换

当前 `prompt_templates.json` 中 20+ 模板全部转换为 Skills，详见 [七.1](#71-现有模板--skills-转换)。

**核心变化**：
- 每个模板变为原子 Skill，Agent 自主组合而非按固定 Pipeline 执行
- 文本、命名、图生成分离为独立 Skills，便于专注优化和复用
- 复合模板（如 `community_analyze`）变为 `skill_analyze_community`，内部组合子 Skills

**转换后批量分析示例：**

```
skill_batch_analyze_communities(task_id):
  1. topocode_community(level=0) → [comm_1, ..., comm_N]
  2. for each comm (并发): skill_analyze_community(comm_id)
  3. skill_generate_arch_overview(all_results)
  4. skill_generate_mermaid_dep_graph + call_graph (并行)
  5. → 返回完整文档包
```

### 4.4 Agent 模式 vs Pipeline 模式

两种模式均基于同一 Skill Registry：

| 维度 | Agent 模式 (内置 Agent 默认) | Pipeline 模式 |
|------|----------------------------|---------------|
| **触发** | `topocode analyze --agent` 或前端 Chat | `topocode analyze --pipeline` |
| **决策者** | topocode 内置 Agent (LLM tools_calling) | 固定执行顺序 |
| **Skills** | Agent 自主选择+组合 | 按预定义链顺序调用 |
| **批量处理** | Agent 自主分片+并发 | 串行固定顺序 |
| **错误处理** | Agent 感知并重试/跳过 | 固定重试逻辑 |
| **上下文** | AnalysisContext 跨 Skill 共享 | 不共享 |
| **交互性** | 用户可中途追问/修正 | 无交互，一次性产出 |
| **适用场景** | 交互式探索、Q&A、迭代完善、批量分析 | 离线生成、CI/CD、确定性输出 |

### 4.5 设计决策

| 决策 | 理由 |
|------|------|
| **以人为核心，提升认知层级** | 每个 tool 输出的是认知洞察（模式/角色/边界），不是数据列表 |
| **输出抽象，渐进披露** | 先给框架（3 层架构），人需要时再展开；避免信息轰炸 |
| **教人，而非替代人** | 解释"为什么"，让人建立架构直觉；决策权永远在人手里 |
| **独立自足，不假设外部工具** | topocode 自身完成全流程，不依赖 codegraph 或任何其他工具 |
| **不追求替代 codegraph** | 两者不同认知层级，topocode 不重复符号/文件级查询 |
| **双通道统一 Skills** | 同一套 Skills 既服务内置 Agent 也服务外部 MCP Agent |
| **对外仅 6 个 MCP Tools** | 每个 tool 帮人建立一种架构认知，而非堆砌功能 |
| **现有模板全部 Skills 化** | 原子化 → Agent 自主组合；消除 pipeline 硬编码 |
| MCP 保留 stdio 为主 | 对外部 agent 保持标准兼容 |
| Pipeline 模式保留作为离线选项 | 无 LLM 环境或需要确定性输出时使用 |

---

## 五、CLI 设计

### 5.1 入口

```bash
topocode <command> [options]
```

使用 Python `argparse` 实现，CLI 入口文件 `backend-core/main_cli.py`。

### 5.2 命令一览

#### 项目初始化

```bash
topocode init [path]               # 创建 .topocode/ + 运行首次分析
topocode uninit [path]             # 清除分析数据
topocode status [path] [--json]    # 分析统计 (节点数/边数/社区数/文件数)
```

#### 架构查询 (对应对外 MCP Tools)

```bash
topocode community [type] [--level N] [--json] # 社区层次结构 (INCLUDE/CALL)
topocode arch [--focus TYPE] [--json]          # 架构总览 (overview/dep/call/structure)
topocode diff [from] [to] [--scope TYPE]       # 版本间架构差异
topocode quality [--focus TYPE] [--comm ID]    # 架构质量检查
```

> 注意：符号/文件级的查询（定义查找、调用者、文件浏览等）不属于 topocode 的职责范围。如需这些能力，使用 codegraph 或 IDE 内置 LSP。

#### Agent 集成

```bash
topocode serve [--mcp] [--proxy] [--port PORT]   # 启动 MCP Server
topocode install [agent...] [--global]             # 安装到 agent 配置
topocode uninstall [agent...]                      # 移除
topocode detect                                    # 检测已安装的 agents
```

#### AI Session 追踪

```bash
topocode session start [--tag TAG]   # 开始追踪 (记录快照)
topocode session stop                # 结束追踪 + 生成摘要
topocode session summary [id]        # 查看会话摘要
topocode session list                # 列出历史会话
topocode session diff [id]           # 符号级变更差异
topocode session quality [id]        # 质量检查报告
```

### 5.3 全局选项

```
--project-root PATH    项目根目录 (默认当前目录)
--json                 输出 JSON 格式
--log-level LEVEL      日志级别 (DEBUG/INFO/WARN/ERROR)
```

---

## 六、对外 MCP Tools（帮人建立架构认知）

### 6.1 设计原则：提升认知层级

codegraph 回答"点"和"线"（符号在哪、谁调用谁），topocode 回答"面"和"体"（哪些是一体的、整体怎么组织的）。每个 tool 的目标不是返回数据，而是帮助人建立一种架构认知。

```
认知层级          topocode 的贡献
───────────────────────────────────
决策级  ← 我该怎么做？          diff/session_summary 解读变化含义
模式级  ← 这是什么模式？        arch_overview 识别分层/微服务/管道
社区级  ← 哪些东西是一体的？    community/community_detail 揭示模块边界
───────────────────────────────────  ← topocode 的价值区间
符号级  ← 这个函数叫啥？        (codegraph 的领域)
文件级  ← 这个文件在哪？        (IDE 基本能力)
```

### 6.2 工具清单（仅 6 个）

| # | Tool | 帮人建立什么认知 | 不是做什么 |
|---|------|----------------|-----------|
| 1 | `topocode_community` | 系统由哪些子系统组成，它们怎么分层 | 不是列文件列表 |
| 2 | `topocode_community_detail` | 一个子系统内部怎么组织的，谁在中心 | 不是列函数签名 |
| 3 | `topocode_architecture_overview` | 整体架构模式是什么，关键依赖链 | 不是输出所有边 |
| 4 | `topocode_diff` | 这次变更对架构意味着什么 | 不是 git diff |
| 5 | `topocode_session_summary` | AI 改了哪些模块，有什么风险 | 不是 commit log |
| 6 | `topocode_quality_inspect` | 哪里有架构风险，优先级是什么 | 不是 lint 报告 |

### 6.3 工具定义

每个 tool 的输出遵循"干了什么 → 怎么干的 → 为什么这么干"三层结构。

```python
# ── 1. 建立"子系统"认知 ──

TOPocode_COMMUNITY = ToolDefinition(
    name="topocode_community",
    description=(
        "识别项目由哪些子系统构成（干了什么），标注每层的角色——"
        "中心节点/桥接节点/边缘节点（怎么干的），"
        "解释社区边界为何形成——依赖密度、框架约定还是历史遗留（为什么这么干）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "edge_type": {
                "type": "string",
                "enum": ["INCLUDE", "CALL"],
                "description": "INCLUDE=依赖关系视角, CALL=调用关系视角",
            },
            "level": {"type": "number", "default": 0},
        },
        "required": ["edge_type"],
    },
)

# ── 2. 建立"内部组织"认知 ──

TOPocode_COMMUNITY_DETAIL = ToolDefinition(
    name="topocode_community_detail",
    description=(
        "深入理解一个子系统（干了什么）：它的核心是什么（Hub 节点），"
        "内部符号如何协作（怎么干的），"
        "它的边界为何这样切分——是被框架约束还是被领域逻辑驱动（为什么这么干）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "comm_id": {"type": "string"},
            "include_hierarchy": {"type": "boolean", "default": True},
        },
        "required": ["comm_id"],
    },
)

# ── 3. 建立"整体模式"认知 ──

TOPocode_ARCHITECTURE_OVERVIEW = ToolDefinition(
    name="topocode_architecture_overview",
    description=(
        "识别项目整体架构模式——分层/微服务/管道/事件驱动（干了什么），"
        "分析关键依赖链和子系统角色分布（怎么干的），"
        "解释这个模式的形成原因——技术选型、团队结构、还是业务需求驱动（为什么这么干）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "enum": ["overview", "dependencies", "call_flow", "structure"],
                "default": "overview",
            },
        },
    },
)

# ── 4. 建立"变化含义"认知 ──

TOPocode_DIFF = ToolDefinition(
    name="topocode_diff",
    description=(
        "发现两个版本间架构的差异（干了什么），"
        "分析差异分布在哪些社区、哪些依赖边增减（怎么干的），"
        "解读变化趋势：架构是更清晰了还是更耦合了？这个变化是故意的还是无意的（为什么这么干）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "from_commit": {"type": "string"},
            "to_commit": {"type": "string"},
            "scope": {"type": "string", "enum": ["files", "communities", "full"], "default": "full"},
        },
    },
)

# ── 5. 建立"AI 影响"认知 ──

TOPocode_SESSION_SUMMARY = ToolDefinition(
    name="topocode_session_summary",
    description=(
        "列出 AI coding agent 的变更（干了什么），"
        "分析变更在架构层面的分布和影响（怎么干的），"
        "评估是否存在架构风险、是否引入了反模式（为什么这么干——以及是否需要关注）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string"},
        },
    },
)

# ── 6. 建立"风险"认知 ──

TOPocode_QUALITY_INSPECT = ToolDefinition(
    name="topocode_quality_inspect",
    description=(
        "识别架构风险点——循环依赖、Hub 过载、架构漂移（干了什么），"
        "分析每个风险的形成机制和影响范围（怎么干的），"
        "解释为什么这是问题——会带来什么后果，以及解决方向建议（为什么这么干——以及怎么办）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "focus": {"type": "string", "enum": ["cyclic_deps", "hub_overload", "arch_drift", "test_gaps", "all"], "default": "all"},
        },
    },
)
```

### 6.4 与 codegraph 共存时避免混淆

topocode 是独立、自足的工具，不依赖也不设计为与 codegraph 协同。但如果用户同时部署了两者（例如 `codegraph serve` 和 `topocode serve` 都在运行），Agent 可能同时看到两套工具。以下指引帮助 Agent 区分职责，避免用错：

> **topocode 只回答"面/体/时/质"的问题，其余不是它的职责。**

| 用户意图 | 应当用 | 不应当用 |
|---------|--------|---------|
| "这个项目怎么组织的？" | `topocode_community` | — |
| "auth 子系统的内部结构？" | `topocode_community_detail` | — |
| "代码质量怎么样？" | `topocode_quality_inspect` | — |
| "刚才的改动影响了哪些模块？" | `topocode_diff` | — |
| "AI 改了什么东西？" | `topocode_session_summary` | — |
| "authenticate 函数的定义在哪？" | **不是 topocode 的职责** | — |
| "谁调用了 authenticate？" | **不是 topocode 的职责** | — |
| "这个文件里有哪些符号？" | **不是 topocode 的职责** | — |

当 Agent 环境中同时存在 codegraph 和 topocode 时，简单规则：
- **查函数/类/文件/调用链 → 用 codegraph**（如果有的话）
- **查子系统/架构/质量/时序 → 用 topocode**
- **只有 topocode 时 → topocode 自身完全够用**（内置 Agent 可通过 Skills 完成从分析到文档的全流程）

### 6.5 Tiny-repo Gating

项目总文件数 < 500 时，仅暴露核心 3 个工具：
`topocode_community`, `topocode_community_detail`, `topocode_architecture_overview`

### 6.6 废弃旧工具

以下当前 MCP tools 将废弃（codegraph 已覆盖或 LSP 式接口不适合 Agent）：

| 废弃 | 原因 |
|------|------|
| `get_definition` | LSP 式 (file+line+char)，不适合 Agent |
| `get_references` | → `codegraph_callers` / `codegraph_callees` |
| `get_symbol_info` | → `codegraph_node` |
| `get_call_hierarchy` | → `codegraph_callers` / `codegraph_callees` |
| `get_file_symbols` | → `codegraph_files` |
| `get_dependencies` | → `topocode_community` (架构级依赖，更优) |
| `search_symbol` | → `codegraph_search` |
| `get_changes` | → `topocode_diff` (架构级差异，更优) |
| `get_version_history` | → 内部使用，不暴露为 MCP tool |
| `evaluate_change` | → `topocode_quality_inspect` (结构化质量检查) |
| `track_symbol_history` | → 内部使用，不暴露为 MCP tool |

保留过渡期 `backward_compat: true` 模式，旧工具名调用时返回 deprecation notice + 新工具名建议。

---

## 七、Skills 设计 (内置 Agent 驱动)

核心思路：**现有 prompt 模板全部原子化为 Skills，内置 Agent 自主组合。外部 Agent 通过 MCP 也可调用。**

Skills 分为五类：对外架构洞察 Tools（6 个）、内部文档生成 Skills、内部图生成 Skills、批量编排 Skills、会话追踪 Skills。各子章节如下：

### 7.1 现有模板 → Skills 转换

当前 `prompt_templates.json` 中 20+ 模板，每个对应一个固定意图。转换为独立 Skills 后，Agent 可自由组合：

| 现有模板 | 转为 Skill | 模式 | 说明 |
|---------|-----------|------|------|
| `community_analyze` | `skill_analyze_community` | tools_calling | 单社区完整分析（名/摘要/图）→ 内部组合子 Skills |
| `community_name` | `skill_name_community` | structured | 社区命名（原子化，可独立调用） |
| `community_architecture` | `skill_arch_community` | chat | 社区架构描述 |
| `community_business` | `skill_business_community` | chat | 业务场景分析 |
| `community_pseudocode` | `skill_pseudocode_community` | chat | 伪码生成 |
| `file_summarize` | `skill_summarize_file` | structured | 文件级摘要 |
| `source_explain` | `skill_explain_source` | chat | 源码级解释 |
| `report_overall_architecture` | `skill_generate_arch_overview` | tools_calling | 项目架构总览 → 内部组合多个子 Skills |
| `report_project_summary` | `skill_project_summary` | chat | 项目概览 |
| `report_arch_decomposition` | `skill_decompose_arch` | chat | 架构分层 |
| `report_core_modules` | `skill_describe_modules` | chat | 核心模块说明 |
| `report_dependency_analysis` | `skill_analyze_dependencies` | chat | 依赖分析 |
| `report_final_assembly` | → 并入 `skill_generate_arch_overview` | — | Agent 自主决定是否需要分步 |
| `diagram_regenerate_mermaid` | `skill_fix_mermaid` | structured | Mermaid 修正 |
| `diagram_regenerate_plantuml` | `skill_fix_plantuml` | structured | PlantUML 修正 |
| `arch_analysis` | `skill_arch_qa` | tools_calling | 架构自由问答 |

### 7.2 Skills 全景

```
                     topocode Skills Registry
                              │
       ┌──────────────────────┼──────────────────────┐
       │                      │                      │
  ┌────▼────┐          ┌──────▼──────┐        ┌──────▼──────┐
  │架构洞察  │          │  文档生成    │        │  图生成      │
  │(6 Tools)│          │  (Skills)   │        │  (Skills)   │
  └─────────┘          └─────────────┘        └─────────────┘
       │                      │                      │
  community              skill_analyze_       skill_mermaid_
  community_detail       community            dep_graph
  arch_overview          skill_arch_          skill_mermaid_
  diff                   community            call_graph
  session_summary        skill_name_          skill_plantuml_
  quality_inspect        community            component
                         skill_summarize_     skill_fix_
                         file                 mermaid
                         skill_explain_       skill_fix_
                         source               plantuml
                         skill_generate_      skill_render_
                         arch_overview        diagram
                         skill_project_
                         summary
                          skill_arch_qa

       ┌──────────────────────┐       ┌──────────────────────┐
       │  架构学习/设计 (Skills)│       │    批量编排 (Skills)   │
       └──────────────────────┘       └──────────────────────┘
              │                              │
       skill_explain_              skill_batch_
       arch_pattern                analyze_communities
       skill_compare_              skill_batch_
       arch                        generate_docs
       skill_recommend_
       refactor
       skill_validate_
       arch_impact
       skill_detect_
       arch_drift

              │
       ┌──────┴──────┐
       │会话追踪      │
       │(Skills)     │
       └─────────────┘
              │
       skill_track_
       ai_session
       skill_audit_
       changes
```

### 7.3 对外架构洞察 Tools（帮人建立架构认知）

| Tool | 帮人建立什么认知 |
|------|----------------|
| `topocode_community` | 系统由哪些子系统构成，它们怎么分层 |
| `topocode_community_detail` | 一个子系统内部怎么组织的，谁在中心 |
| `topocode_architecture_overview` | 整体架构模式是什么 |
| `topocode_diff` | 这次变更对架构意味着什么 |
| `topocode_session_summary` | AI 改了哪些模块，有什么风险 |
| `topocode_quality_inspect` | 哪里有架构风险，优先级是什么 |

### 7.4 内外部接口边界

| 接口 | 可见范围 | 包含 |
|------|---------|------|
| **对外 MCP Tools** (6 个) | 外部 Agent + 内置 Agent | `topocode_community`, `community_detail`, `arch_overview`, `diff`, `session_summary`, `quality_inspect` |
| **内部 Skills** (~17 个) | 仅内置 Agent | `skill_analyze_community`, `skill_generate_arch_overview`, `skill_generate_*_diagram`, `skill_fix_*`, `skill_batch_*`, 等 |
| **内部 SDK 方法** | 仅内置 Agent | `ctx.check_ready()`, `ctx.get_project_layer()`, `ctx.get_community_layer()`, `ctx.get_symbol_layer()`, `ctx.get_file_layer()` |

**设计意图**：外部 Agent 通过 6 个 coarse-grained Tools 获取架构洞察。内置 Agent 通过内部 Skills + 内部 SDK 完成细粒度的分析、文档生成和批量编排。Skills 本身不暴露为 MCP tools — 外部 Agent 如需生成文档，组合调用 6 个公开 Tools 自行实现。

### 7.5 内部 Agent SDK 方法

内置 Agent Runtime 可直接调用以下 SDK 方法（不在 MCP 中暴露）：

```python
class AnalysisContext:
    def check_ready(task_id) -> bool:          # 确认分析数据就绪
    def get_project_layer() -> ContextLayer:    # 项目级概览
    def get_community_layer(id) -> ContextLayer:# 社区层：节点/边/子社区
    def get_file_layer(path) -> ContextLayer:   # 文件层：符号列表
    def get_symbol_layer(name) -> ContextLayer: # 符号层：签名+调用链
    def get_downward_path(path) -> list[Layer]: # 自顶向下路径
    def get_upward_path(symbol) -> list[Layer]: # 自底向上路径
    def format_for_llm(layers, direction) -> str:# 格式化为 LLM context
```

### 7.6 文档生成 Skills

```python
# ── 架构总览 ──

Skill("skill_generate_arch_overview",
    description="生成项目架构总览文档: 整体结构、L0 社区、关键依赖",
    input_schema={
        "scope": {"type": "string", "default": "project"},
        "detail_level": {"type": "string", "enum": ["brief", "standard", "deep"]},
        "include_diagrams": {"type": "boolean", "default": True},
    },
    # Agent 内部流程:
    # 1. topocode_community("INCLUDE", L0) → 依赖社区
    # 2. topocode_community("CALL", L0) → 调用社区
    # 3. 对各 L0 社区生成摘要
    # 4. 组装 Markdown 文档
    # 5. 若 include_diagrams → 调用 skill_generate_dep_diagram + skill_generate_call_diagram
)

# ── 模块文档 ──

Skill("skill_generate_module_doc",
    description="生成单个社区/模块的详细文档",
    input_schema={
        "comm_id": {"type": "string", "required": True},
        "focus": {"type": "string", "enum": ["architecture", "api", "data_flow", "all"]},
        "direction": {"type": "string", "enum": ["top-down", "bottom-up"]},
    },
    # Agent 内部流程:
    # 1. topocode_community_detail(comm_id) → 社区结构
    # 2. ctx.get_community_layer(comm_id)  → 关键符号列表 (内部 SDK)
    # 3. 按 direction 组织摘要:
    #    top-down: 功能特性 → 子模块 → 关键接口
    #    bottom-up: 核心函数逻辑 → 模块协作 → 架构模式
    # 4. 可选 skill_generate_dep_diagram / skill_generate_call_diagram
)

# ── 源码文档 ──

Skill("skill_generate_source_doc",
    description="生成源码级说明: 单文件或单符号的详细分析",
    input_schema={
        "target": {"type": "string", "required": True},  # 文件路径或符号名
        "type": {"type": "string", "enum": ["file", "symbol"]},
        "include_call_chain": {"type": "boolean", "default": True},
    },
)

# ── 问答 ──

Skill("skill_answer_question",
    description="基于完整知识图谱回答用户问题",
    input_schema={
        "question": {"type": "string", "required": True},
    },
    # Agent 自主决定使用哪些工具来回答问题
    # 无固定步骤 — 纯 Agent 驱动
)
```

### 7.7 图生成 Skills

图生成与文本分析**完全分离**为独立 Skills：

```python
Skill("skill_generate_mermaid_dep_graph",
    description="基于文本摘要生成 Mermaid 依赖图(graph LR)",
    input_schema={
        "summary": {"type": "string", "required": True},  # 文本摘要作输入
        "scope": {"type": "string"},                       # 社区/文件范围
        "style": {"type": "string", "enum": ["default", "dark", "minimal"]},
    },
    # 单独 session: 聚焦关系可视化，不受文本生成干扰
)

Skill("skill_generate_mermaid_call_graph",
    description="基于文本摘要生成 Mermaid 调用图(graph TD)",
    input_schema={
        "summary": {"type": "string", "required": True},
        "max_depth": {"type": "number", "default": 3},
    },
)

Skill("skill_generate_plantuml_component",
    description="基于文本摘要生成 PlantUML 组件图",
    input_schema={
        "summary": {"type": "string", "required": True},
    },
)

Skill("skill_fix_diagram",
    description="验证并修正图代码: 语法检查 → 自动修正 → 再验证",
    input_schema={
        "code": {"type": "string", "required": True},
        "type": {"type": "string", "enum": ["mermaid", "plantuml"]},
        "text_summary": {"type": "string"},  # 用原始摘要验证完整性
    },
)

Skill("skill_render_diagram",
    description="渲染图代码为 SVG (PlantUML 服务端渲染, Mermaid 客户端渲染)",
    input_schema={
        "code": {"type": "string", "required": True},
        "type": {"type": "string", "enum": ["mermaid", "plantuml"]},
    },
)
```

### 7.8 会话追踪 Skills

```python
Skill("skill_track_ai_session",
    description="完整 AI 会话追踪: 开始 → 监控 → 分析变更 → 生成摘要",
    input_schema={
        "tag": {"type": "string", "default": ""},
        "project_id": {"type": "string", "required": True},
    },
)

Skill("skill_audit_changes",
    description="审计 AI 代码变更: 检查缺失测试/反模式/硬编码密钥/架构漂移",
    input_schema={
        "session_id": {"type": "string", "required": True},
    },
)
```

### 7.9 架构学习/设计 Skills (P0 优先级)

从"告诉你架构是什么"升级到"帮你理解为什么、怎么做"。这些 Skills 是 topocode 差异化价值的核心延伸。

```python
# ── P0-1: 架构模式解释 ──

Skill("skill_explain_arch_pattern",
    description=(
        "解释社区检测结果背后的成因：为什么这些文件/符号形成一个社区？"
        "社区的边界是由什么决定的（依赖密度/调用频率/框架约定）？"
        "该社区在整体架构中的角色和模式（分层/微服务/管道/事件驱动）。"
    ),
    input_schema={
        "comm_id": {"type": "string", "required": True},
        "question": {"type": "string", "description": "具体想了解什么 (默认: 全面解释)"},
    },
    # Agent 内部流程:
    # 1. ctx.get_community_layer(comm_id) → 社区内外部结构
    # 2. topocode_architecture_overview(focus="structure") → 整体架构上下文
    # 3. 分析: 内聚度、耦合度、边界特征、模式匹配
    # 4. 生成自然语言解释 + 模式图示
)

# ── P0-2: 架构对比 ──

Skill("skill_compare_arch",
    description=(
        "对比两个版本的架构差异，分析演化趋势。不仅列出变化，更解读："
        "架构是变得更模块化还是更耦合？哪些社区在膨胀/萎缩？"
        "Hub 节点在迁移还是固化？依赖方向是否符合预期？"
    ),
    input_schema={
        "from_commit": {"type": "string", "required": True},
        "to_commit": {"type": "string", "description": "目标版本 (默认: 当前)"},
    },
    # Agent 内部流程:
    # 1. topocode_diff(from, to, scope="full") → 架构级差异
    # 2. 对比: 社区数变化 / Hub 迁移 / 依赖边长消 / 模块化度
    # 3. 趋势解读: 向好的方向还是坏的方向演化？
    # 4. 生成对比报告 + 趋势分析
)

# ── P0-3: 重构建议 ──

Skill("skill_recommend_refactor",
    description=(
        "基于架构分析结果，给出具体的重构建议。"
        "针对 Hub 过载、循环依赖、社区边界不合理、过度耦合等问题，"
        "分析根因并建议解耦方案 —— 提取接口/引入中间层/拆分模块/重新分组。"
    ),
    input_schema={
        "community_id": {"type": "string", "description": "关注特定社区 (默认: 全项目分析)"},
        "max_suggestions": {"type": "number", "default": 5},
    },
    # Agent 内部流程:
    # 1. topocode_quality_inspect(focus="all") → 质量问题清单
    # 2. ctx.get_community_layer(each_problematic) → 深入分析
    # 3. 模式匹配: Hub 过载 → 职责拆分? 循环依赖 → 依赖倒置?
    # 4. 生成具体建议: 移到哪个文件/社区, 引入什么抽象
)

# ── P1-4: 架构影响预测 ──

Skill("skill_validate_arch_impact",
    description=(
        "预测新增/修改模块对架构的影响。回答：放在哪个社区合适？"
        "会不会引入循环依赖？对现有社区边界的冲击？"
        "是否有架构漂移风险？"
    ),
    input_schema={
        "target_file": {"type": "string", "required": True, "description": "新增或修改的文件路径"},
        "change_description": {"type": "string", "description": "变更内容描述"},
    },
    # Agent 内部流程:
    # 1. ctx.get_file_layer(target_file) → 当前状态
    # 2. topocode_community → 找到最合适的归属社区
    # 3. 模拟: 新增文件会产生哪些依赖边？是否形成循环？
    # 4. 输出: 建议社区归属 + 影响评估 + 风险提示
)

# ── P1-5: 架构漂移检测 ──

Skill("skill_detect_arch_drift",
    description=(
        "检测项目架构是否偏离了历史模式或预期结构。"
        "分析最近 N 次提交的趋势：社区在膨胀还是分裂？"
        "新代码是否打破了原有的分层约定？依赖方向是否反转？"
    ),
    input_schema={
        "recent_commits": {"type": "number", "default": 10, "description": "分析最近 N 次提交"},
        "baseline_commit": {"type": "string", "description": "基准版本 (默认: 首次分析快照)"},
    },
    # Agent 内部流程:
    # 1. topocode_diff(baseline, current, scope="full") → 总体漂移量
    # 2. 逐次提交分析趋势线 (社区数、Hub 迁移、依赖密度)
    # 3. 检测: 是否偏离分层/模块化/微服务等预期模式
    # 4. 生成漂移报告 + 趋势图
)
```

### 7.10 Agent 自主组合示例

Agent 收到用户请求后的典型决策链：

```
用户: "分析整个项目并生成完整架构文档"

Agent 决策:
  1. ctx.check_ready(task_id)                     → 确认分析数据就绪 (内部 SDK)
  2. ctx.get_project_layer()                      → 项目结构概览 (内部 SDK)
  3. topocode_community("INCLUDE", level=0)       → 获取 L0 依赖社区
  4. topocode_community("CALL", level=0)          → 获取 L0 调用社区
  5. skill_generate_arch_overview(
       scope="project", detail="standard",
       include_diagrams=True
     )
     ├─ 内部: ctx 读取各社区符号表 → 组装架构文档 →
     │  生成依赖图 → 生成调用图 → 返回完整文档
     └─ 返回: { markdown, mermaid_dep, mermaid_call }

用户: "auth 模块的认证流程怎么实现的？画个图"

Agent 决策:
  1. ctx.get_community_layer("auth-community")   → 获取社区内符号列表 (内部 SDK)
  2. ctx.get_symbol_layer("authenticate")        → 获取符号详情+调用链 (内部 SDK)
  3. skill_generate_module_doc(
       comm_id="auth", focus="data_flow",
       direction="bottom-up"
     )
     → 从核心函数逻辑 → 模块协作 → 架构总结
  4. skill_generate_mermaid_call_graph(
       summary=上步输出的摘要
     )
  5. skill_fix_diagram(
       code=生成的 mermaid, type="mermaid",
       text_summary=文本摘要
     )
  7. 返回: { 流程说明, mermaid图 }

用户: "刚才的依赖图少了 rate-limiter 模块"

Agent 决策:
  1. topocode_community_detail("rate-limiter")   → 获取遗漏模块信息
  2. skill_generate_mermaid_dep_graph(
       summary=上次文本摘要 + rate-limiter 信息
     )
  3. skill_fix_diagram(...)                     → 修正
  4. 返回: 更新后的图
```

### 7.11 SERVER_INSTRUCTIONS — 对外部 Agent 版（MCP `initialize` 响应）

> **使用场景**: 当外部 Agent（Claude/Codex/OpenCode 等）通过 MCP 协议连接 topocode 时，此指令在 `initialize` 响应中注入，帮助 Agent 正确选择 topocode 的工具。

```python
SERVER_INSTRUCTIONS = """
# topocode — 架构认知工具

topocode 是独立的架构认知工具。它的目标不是输出数据，而是帮助人建立架构理解。
每个 tool 的设计遵循"渐进披露"原则：先给框架，人需要时再展开细节。

## 建立架构认知的路径

1. **先看整体** → `topocode_community` + `topocode_architecture_overview`
   了解系统由哪些子系统构成，整体是什么模式。这一步帮人建立"地图感"。

2. **深入关注点** → `topocode_community_detail`
   对感兴趣的子系统深入了解：它的核心是什么，怎么组织的。

3. **追踪变化** → `topocode_diff` / `topocode_session_summary`
   理解变更对架构意味着什么，不只是变了什么文件。

4. **评估风险** → `topocode_quality_inspect`
   知道应该先关注什么问题。

## 什么时候不应当用 topocode

以下问题的答案在符号级/文件级，不在 topocode 的认知层级：

- 查找单个函数的定义位置
- 查找谁调用了某个函数
- 浏览目录结构
- 按名称搜索符号

## 输出风格

- 先给结论（"这个系统是 3 层架构，auth 是中心子系统"）
- 再给依据（"因为 12 个社区形成了清晰的层次，auth 的度=15 是最高"）
- 最后给路径（"想深入了解 auth → topocode_community_detail"）

- 不要输出原始数据列表，输出已经提炼过的认知洞察
- 如果环境中也有 symbol 级工具（如 codegraph），让它们做它们擅长的事
"""
```

### 7.12 图生成质量保证链

```
                文本摘要
                   │
     ┌─────────────┼─────────────┐
     ▼             ▼             ▼
  Mermaid      PlantUML      (其他格式)
  生成器        生成器
     │             │
     ▼             ▼
  skill_fix_diagram (验证 + 自动修正, 最多 2 轮)
     │             │
     ├── 语法检查 ──┤
     ├── 完整性检查─┤  (摘要中的模块都在图中?)
     ├── 一致性检查─┤  (Mermaid 和 PlantUML 内容一致?)
     └── 样式优化 ──┘  (布局、配色)
           │
           ▼
  skill_render_diagram → SVG
           │
           ▼
       最终产出
```

### 7.13 批量任务编排 (内置 Agent 的核心能力)

内置 Agent 区别于外部 Agent 的关键能力：**自主驱动批量分析任务**。

```python
Skill("skill_batch_analyze_communities",
    description=(
        "批量分析所有 L0 社区: 并发分析 → 统一命名 → "
        "组装总览文档 → 生成依赖图/调用图。内置并发控制 + 进度上报 + 错误重试。"
    ),
    input_schema={
        "task_id": {"type": "string", "required": True},
        "edge_types": {"type": "array", "default": ["INCLUDE", "CALL"]},
        "max_concurrency": {"type": "number", "default": 3},
    },
)
```

**内置 Agent 的批量执行流程：**

```
用户: topocode analyze --agent --task-id xxx
         │
         ▼
  Agent Runtime 收到批量分析任务
         │
          ├─► Step 1: ctx.check_ready(task_id) → 确认分析数据就绪 (内部 SDK)
         │
         ├─► Step 2: skill_batch_analyze_communities(task_id)
         │       │
         │       ├─ 内部并发调度 (max_concurrency=3):
         │       │   comm_1 ── skill_analyze_community ──► ✅
         │       │   comm_2 ── skill_analyze_community ──► ✅
         │       │   comm_3 ── skill_analyze_community ──► ❌ → 重试 → ✅
         │       │   comm_4 ── skill_analyze_community ──► ⏳
         │       │
         │       ├─ 进度推送 (ZMQ PUB):
         │       │   {event:"batch.progress", current:5, total:42}
         │       │
         │       └─► 返回: {results:[...], errors:[...], duration:"32s"}
         │
         ├─► Step 3: skill_generate_arch_overview(all_results)
         │
         ├─► Step 4: 并行 skill_generate_mermaid_dep_graph + call_graph
         │
         └─► Step 5: 持久化 + 返回
                  {event:"batch.complete", communities:42, duration:"45s"}
```

**内置 Agent vs 外部 Agent 对比：**

| 能力 | 内置 Agent | 外部 Agent (MCP) |
|------|-----------|-----------------|
| 批量并发 | ✅ 内置调度器, max_concurrency | Agent 自行控制 |
| 进度上报 | ✅ ZMQ PUB → 前端实时进度 | ❌ 无内置 |
| 错误恢复 | ✅ 内置重试+跳过策略 | Agent 自行处理 |
| 上下文共享 | ✅ 内存零拷贝 | JSON 序列化传输 |
| 结果持久化 | ✅ 直接写 SQLite | 通过 MCP tool 间接写 |
| Skills 调用 | 进程内函数 (零延迟) | JSON-RPC round trip |

### 7.14 SERVER_INSTRUCTIONS — 内置 Agent 版（进程内 System Prompt）

> **使用场景**: 当 topocode 内置 Agent Runtime 启动时，此指令作为 system prompt 注入。内置 Agent 可直接访问 AnalysisContext 和所有内部 SDK 方法，能力集比外部 Agent 更丰富。

```python
SERVER_INSTRUCTIONS = """
# topocode 内置 Agent — 以人为本的架构认知引擎

你的目标不是输出更多数据，而是帮助人建立架构认知、做出更好决策。

## 核心原则

1. **输出抽象，而非枚举**
   ❌ "auth 社区有 12 个节点、45 条边"
   ✅ "auth 是业务层的中心子系统。它的核心是 authenticate（Hub 节点，度=15）。
       它连接了表示层（接收请求）和安全层（JWT 验证），是系统的安全边界。"

2. **渐进披露**
   先给框架（3 层架构），人追问时再展开。不要一次性倾倒所有信息。

3. **教人，而非替代人**
   解释"为什么 auth 和 middleware 属于不同社区"（边界是由关注点分离定义的），
   让人建立架构直觉。决策权永远在人手里。

## 批量任务指南

| 用户意图 | 使用 Skill | 注意 |
|---------|-----------|------|
| "分析整个项目" | `skill_batch_analyze_communities` | 完成后主动告诉人：系统的关键发现是什么，不是列举 42 个社区 |
| "生成架构文档" | `skill_batch_generate_docs` | 文档要有"地图感"——人看完应该知道从哪里开始深入 |
| "只看总览" | `skill_batch_generate_docs(scope="overview_only")` | 总览的目的是帮人选方向，不是展示完整信息 |
| "这个模块怎么设计的" | `skill_explain_arch_pattern` | 重点是"为什么这样设计"，不是"有什么文件" |
| "上次改动有什么影响" | `topocode_diff` + `skill_compare_arch` | 解读变化趋势，不只列变更清单 |

## 原则

- 先告诉人最重要的洞察是什么，再提供支持细节
- 批量任务用批处理 Skill，不要逐个社区手动调用
- 图单独生成——文本完成后，图用独立 session
- 失败自动重试，不需用户干预
"""
```

---

## 八、MCP Server 架构升级

### 8.1 三模式架构

```
┌─────────┐     ┌──────────────┐     ┌─────────────────┐
│  Direct │     │    Proxy     │     │     Daemon      │
│ (stdio) │     │(stdio→socket)│     │   (socket)      │
├─────────┤     ├──────────────┤     ├─────────────────┤
│ 单进程   │     │ 轻量代理      │     │ 共享守护进程      │
│ 直接处理  │     │ 本地回答:     │     │ 多客户端共享:     │
│ 所有请求  │     │  initialize  │     │  CodeGraph      │
│         │     │  tools/list  │     │  + Watcher      │
│         │     │ 转发:        │     │  + SQLite       │
│         │     │  tools/call  │     │ refcount 管理    │
│         │     │             │     │ idle 超时 300s   │
└─────────┘     └──────┬───────┘     └────────┬────────┘
                       │                      │
                       └────── Unix Socket ───┘
```

**模式选择：**

| 场景 | 模式 |
|------|------|
| 用户 `topocode serve` 在终端运行 | Direct |
| AI agent 作为子进程 spawn（默认） | Proxy → Daemon |
| 需要 HTTP 桥接的 Web 客户端 | Daemon + HTTP bridge |
| `topocode serve --port 9876` | Daemon + HTTP API |

### 8.2 Proxy 模式流程

```
Agent  spawns: topocode serve
    │
    ▼
Proxy (stdio 端) 启动:
    1. 检查是否已有 daemon 在运行 (Unix socket /tmp/topocode-{uid}.sock)
    2. 无 → spawn daemon，等待 socket ready
    3. 有 → 连接 daemon
    │
    ├─ Agent → initialize   → Proxy 本地回答 (含 SERVER_INSTRUCTIONS)
    ├─ Agent → tools/list   → Proxy 本地回答 (静态 tool 列表)
    ├─ Agent → tools/call   → Proxy 转发到 daemon → 结果返回 agent
    └─ Agent → ping         → Proxy 本地回答
```

### 8.3 Daemon 生命周期

```python
class MCPDaemon:
    """
    共享 MCP 守护进程
    
    - 绑定 Unix socket (或 TCP port)
    - 维护 client refcount
    - idle 超时 (默认 300s) 自动退出
    - 共享 AnalysisStore + FileWatcher
    """
    
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.refcount = 0          # 活跃客户端数
        self.idle_timeout = 300    # idle 超时 (秒)
        self.store = None          # 共享 AnalysisStore
        self.watcher = None        # 共享 FileWatcher
    
    async def handle_client(self, reader, writer):
        self.refcount += 1
        try:
            await self._serve_jsonrpc(reader, writer)
        finally:
            self.refcount -= 1
    
    async def _idle_check(self):
        """idle 超时检查 — 无客户端时自动退出"""
        while True:
            await asyncio.sleep(30)
            if self.refcount == 0:
                logger.info("Daemon idle, shutting down...")
                break
```

### 8.4 Staleness Banner

```python
def check_staleness(mentioned_files: list[str], store: AnalysisStore) -> list[str]:
    """检测返回值中引用的文件是否滞后于磁盘"""
    stale = []
    for fp in mentioned_files:
        db_mtime = store.get_file_indexed_at(fp)
        disk_mtime = os.path.getmtime(os.path.join(project_root, fp))
        if disk_mtime > db_mtime + 1:  # 1s 容差
            stale.append(fp)
    return stale

def attach_staleness_banner(text: str, stale_files: list[str]) -> str:
    if not stale_files:
        return text
    return (
        f"⚠️ 以下文件在索引同步后已编辑: {', '.join(stale_files)}\n"
        f"请使用 Read 工具获取这些文件的最新内容。\n\n"
        + text
    )
```

### 8.5 Cross-project 支持

所有工具添加可选 `projectPath` 参数 → ToolHandler 维护 `Map<projectPath, AnalysisStore>` 缓存：

```python
class ToolHandler:
    def __init__(self):
        self._stores: dict[str, AnalysisStore] = {}  # projectPath → store
    
    def _get_store(self, project_path: str | None) -> AnalysisStore:
        if not project_path:
            return self._default_store
        if project_path not in self._stores:
            self._stores[project_path] = AnalysisStore(project_path)
        return self._stores[project_path]
```

---

## 九、Agent Installer

### 9.1 架构

```
plugins/installer/
├── plugin.json
├── plugin_entry.py           # register_methods + CLI 命令
├── installer.py              # Installer 核心逻辑
└── targets/
    ├── __init__.py           # TARGETS registry
    ├── base.py               # AgentTarget 抽象基类
    ├── claude.py             # Claude (claude.ai / Claude Code)
    ├── opencode.py           # OpenCode
    ├── codex.py              # OpenAI Codex
    ├── cursor.py             # Cursor
    ├── copilot.py            # GitHub Copilot
    ├── gemini.py             # Gemini CLI
    └── windsurf.py           # Windsurf
```

### 9.2 AgentTarget 接口

```python
class AgentTarget(ABC):
    """单个 AI coding agent 的安装目标"""
    
    id: str              # "claude", "opencode", "codex", ...
    name: str            # 显示名 "Claude Code"
    
    @abstractmethod
    def detect(self) -> bool:
        """检测 agent 是否已安装"""
        ...
    
    @abstractmethod
    def install(self, project_root: str, global_: bool = False) -> str:
        """
        写入 MCP 配置到 agent 配置文件
        返回写入的配置文件路径
        """
        ...
    
    @abstractmethod
    def uninstall(self, project_root: str, global_: bool = False) -> str:
        """移除 MCP 配置"""
        ...
    
    def describe_paths(self) -> list[str]:
        """返回可能的配置文件路径列表"""
        ...
```

### 9.3 安装内容示例

**Claude** (`~/.claude/claude_desktop_config.json` 或 `.mcp.json`)：

```json
{
  "mcpServers": {
    "topocode": {
      "command": "topocode",
      "args": ["serve"],
      "env": {}
    }
  }
}
```

**OpenCode** (`opencode.json`)：

```json
{
  "mcp": {
    "topocode": {
      "type": "local",
      "command": ["topocode", "serve"]
    }
  }
}
```

**Cursor** (`.cursor/mcp.json`)：

```json
{
  "mcpServers": {
    "topocode": {
      "command": "topocode",
      "args": ["serve"]
    }
  }
}
```

### 9.4 CLI 命令

```bash
topocode detect                     # 列出已检测到的 agents
topocode install claude opencode    # 安装到指定 agents
topocode install --all              # 安装到所有检测到的 agents
topocode install --global claude    # 全局安装 (非项目级)
topocode uninstall claude           # 移除
```

---

## 十、AI Session 追踪

### 10.1 核心概念

```
AI Session 生命周期:

  start()          monitor()           stop()
     │                │                   │
     ▼                ▼                   ▼
 [快照] ──────▶ [监 控] ──────▶ [分析变更] ──────▶ [生成摘要]
 记录文件状态      轮询变更事件      diff 文件/符号/社区    Markdown 文档
  (mtime+hash)    (FileWatcher)    (symbol-level diff)   (结构化输出)
```

### 10.2 SessionTracker

```python
class AISessionTracker:
    """
    追踪 AI coding agent 在项目中的活动。
    
    使用场景:
      - 用户启动 AI coding 会话前执行 `topocode session start`
      - AI 完成工作后执行 `topocode session stop`
      - 查看摘要: `topocode session summary`
    """
    
    def __init__(self, project_root: str, store: AnalysisStore):
        self.project_root = project_root
        self.store = store
        self._active_session: str | None = None
        self._snapshot: dict[str, FileSnapshot] | None = None
    
    def start(self, tag: str = "") -> str:
        """
        开始追踪
        
        1. 生成 session_id
        2. 记录当前文件快照: {file_path: {mtime, sha256, symbol_count}}
        3. 关联当前分析任务 task_id
        4. 写入 ai_sessions 表
        """
        ...
    
    def stop(self) -> dict:
        """
        停止追踪, 分析变更, 生成摘要
        
        1. 扫描文件系统, 对比快照 → 变更列表
        2. 分析符号级变更 (新增/修改/删除)
        3. 分析社区变化 (新增/消失/规模变化)
        4. 运行质量检查
        5. 生成 Markdown 摘要
        6. 写入 ai_session_changes + ai_session_issues 表
        """
        ...
    
    def generate_summary(self, session_id: str) -> str:
        """生成 Markdown 摘要文档"""
        ...
    
    def quality_check(self, session_id: str) -> list[Issue]:
        """检查 AI 变更质量"""
        ...
```

### 10.3 摘要文档模板

```markdown
# AI Session Summary: {tag}

**会话 ID**: {session_id}
**时间**: {started_at} → {ended_at} | **耗时**: {duration}
**分析任务**: {task_id}

---

## 做了什么 (What Changed)

| 变更类型 | 数量 |
|---------|------|
| 新增文件 | {files_added} |
| 修改文件 | {files_modified} |
| 删除文件 | {files_deleted} |
| 新增符号 | {symbols_added} |
| 修改符号 | {symbols_modified} |
| 删除符号 | {symbols_deleted} |

### 关键文件

| 文件 | 变更 | 影响符号 |
|------|------|---------|
| `src/api/handler.ts` | 修改 | `authenticate`, `authorize` |
| `src/types/models.ts` | 新增 | `User`, `Session` |
| `src/middleware/auth.ts` | 新增 | `jwtVerify` |

---

## 怎么做的 (How)

### 新增调用关系

```
authenticate ←── handleLogin
authenticate ←── handleRefresh
User        ←── 8 references (src/api/, src/types/, src/components/)
```

### 新增依赖

```
src/api/ ──imports──▶ src/middleware/  (新依赖边)
```

### 社区变化

| 社区 | 变化 | 规模 |
|------|------|------|
| `comm-xxx-auth` | **NEW** | 12 节点 |
| `comm-xxx-api` | 扩大 | 5→23 节点 |

---

## 可能的问题 (Issues)

| 严重度 | 文件:行 | 问题 |
|--------|--------|------|
| **HIGH** | `src/api/handler.ts:42` | `authenticate` 无测试覆盖 |
| **HIGH** | `src/middleware/auth.ts:15` | 密钥硬编码: `"secret123"` |
| MEDIUM | `src/types/models.ts:8` | `Session.expiresAt` 未使用 |
| LOW | `src/middleware/` | 无类型检查覆盖 |
| INFO | — | 新模块 `auth` 缺少 README |

---

## 架构影响

### 社区变化详情

- **新增社区**: `auth-module` (12 节点, INCLUDE 边)
  - 核心符号: `authenticate`, `jwtVerify`, `User`
- **社区扩大**: `api-community` 5→23 节点 (因 auth 聚合)
  - 中心节点: `handleLogin` (度=15)
- 无社区消失

### 风险提示

- `authenticate` 为中心节点 (调用度=15)，后续修改影响范围大
- `User` 类型被 8 个文件引用，接口变更需同步
- 建议补充单元测试覆盖 `authenticate` 和 `authorize`
- 建议将 `jwtVerify` 中硬编码密钥改为环境变量

---

*由 topocode AI Session Tracker 自动生成*
```

### 10.4 数据模型

```sql
-- AI 会话表
CREATE TABLE ai_sessions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT,
    tag TEXT DEFAULT '',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    status TEXT DEFAULT 'active',  -- active, completed, failed
    file_snapshot TEXT,            -- JSON: {path: {mtime, sha256, symbol_count}}
    summary_markdown TEXT,         -- 摘要文档
    quality_score REAL,
    metadata TEXT,                 -- JSON
    created_at TEXT DEFAULT (datetime('now'))
);

-- 会话变更明细
CREATE TABLE ai_session_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    change_type TEXT NOT NULL,     -- added, modified, deleted
    symbol_name TEXT,
    symbol_kind TEXT,
    old_signature TEXT,
    new_signature TEXT,
    old_content TEXT,
    new_content TEXT,
    FOREIGN KEY (session_id) REFERENCES ai_sessions(id)
);

-- 会话质量问题
CREATE TABLE ai_session_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    file_path TEXT,
    line_number INTEGER,
    issue_type TEXT NOT NULL,      -- missing_test, hardcoded_secret, unused_code, anti_pattern, breaking_change, ...
    severity TEXT NOT NULL,        -- HIGH, MEDIUM, LOW, INFO
    title TEXT NOT NULL,
    description TEXT,
    suggestion TEXT,
    FOREIGN KEY (session_id) REFERENCES ai_sessions(id)
);

-- 索引
CREATE INDEX idx_ai_sessions_project ON ai_sessions(project_id, started_at DESC);
CREATE INDEX idx_ai_session_changes_session ON ai_session_changes(session_id);
CREATE INDEX idx_ai_session_issues_session ON ai_session_issues(session_id, severity);
```

### 10.5 质量检查规则

```python
QUALITY_CHECKS = {
    "missing_test": {
        "description": "新增/修改的函数缺少对应测试文件",
        "severity": "HIGH",
        "check": lambda change, project: not has_corresponding_test(change.file_path, project),
    },
    "hardcoded_secret": {
        "description": "代码中发现硬编码的密钥/密码/Token",
        "severity": "HIGH",
        "check": lambda change: re.search(r'(secret|password|token|api_key)\s*[:=]\s*["\']', change.content),
    },
    "unused_import": {
        "description": "新增的 import 未被使用",
        "severity": "LOW",
        "check": lambda change: is_unused_import(change),
    },
    "missing_type_annotation": {
        "description": "新增函数缺少类型标注",
        "severity": "MEDIUM",
        "check": lambda change: change.kind == "function" and not change.has_type_annotations,
    },
    "too_many_params": {
        "description": "函数参数过多 (>5)",
        "severity": "LOW",
        "check": lambda change: change.kind == "function" and change.param_count > 5,
    },
}
```

---

## 十一、项目结构

```
topoOne-ui/
├── topocode                       # CLI 入口 (symlink → backend-core/main_cli.py)
├── backend-core/
│   ├── main.py                    # Electron 后端 (保持不变)
│   ├── main_cli.py                # CLI 入口 (新增)
│   ├── analyst_runner.py          # 分析管线 (已改版)
│   ├── analysis_context.py        # 统一上下文管理器 (新增)
│   ├── bidirectional_analyzer.py  # 双向分析 (新增)
│   ├── diagram_orchestrator.py    # 图生成编排器 (新增)
│   ├── instruction_manager.py     # 用户自定义指令 (新增)
│   ├── ai_session_tracker.py      # AI Session 追踪 (新增)
│   ├── mcp_server/
│   │   ├── __main__.py            # 入口
│   │   ├── server.py              # MCPServer + 三模式启动 (升级)
│   │   ├── proxy.py               # stdio↔socket 代理 (新增)
│   │   ├── daemon.py              # 共享守护进程 (新增)
│   │   ├── tools.py               # 工具定义 (升级: topocode_ 前缀)
│   │   ├── skills.py              # Skills 定义 (升级: Agent 驱动)
│   │   ├── skill_executor.py      # Skill 执行器
│   │   ├── dispatcher.py          # 工具分发 (升级)
│   │   ├── server_instructions.py # SERVER_INSTRUCTIONS (新增)
│   │   ├── path_validator.py      # 路径安全
│   │   └── result_compressor.py   # 结果压缩 + output budget
│   └── store/
│       ├── schema.py              # DDL (新增 ai_sessions 等表)
│       ├── connection.py          # SQLiteContext (RLock)
│       └── analysis_store.py      # CRUD (新增 AI 会话方法)
├── plugins/
│   ├── parsers/                   # 18 语言解析器
│   ├── community/                 # 社区分析
│   ├── reports/                   # Web 预览 (简化为纯渲染)
│   └── installer/                 # Agent Installer (新增)
│       ├── plugin.json
│       ├── plugin_entry.py
│       └── targets/
│           ├── base.py
│           ├── claude.py
│           ├── opencode.py
│           ├── codex.py
│           └── cursor.py
├── src/                           # 前端 (大幅简化)
│   ├── components/
│   │   ├── ChatView.vue           # 统一 AI 对话 (替代 ReportAIPanel + Pipeline)
│   │   └── ReportViewer.vue       # 文档/图渲染预览
│   ├── stores/
│   │   ├── chat-store.ts          # 会话管理 (简化)
│   │   └── report-store.ts        # 文档持久化 (简化)
│   └── types/
│       └── ipc.ts                 # IPC 类型 (更新)
└── docs/
    └── agent相关功能改版文档.md    # 本文档
```

**前端简化对比：**

| 文件 | 之前 | 之后 | 说明 |
|------|------|------|------|
| `ReportGenerationPipeline.vue` | 700行 | **删除** | Pipeline 编排 → Agent 自主决策 |
| `CommunityAnalysisPipeline.vue` | 589行 | **删除** | 批量分析 → Agent Skill 处理 |
| `ReportAIPanel.vue` | 630行 | → 合并入 `ChatView.vue` | 统一对话界面 |
| `community-store.ts` | 415行 | → ~80行 | 仅保留数据查询 |
| `report-store.ts` | 298行 | → ~100行 | 仅保留持久化 |
| `pipeline-store.ts` | 217行 | **删除** | 无需要管理的 pipeline 状态 |
| `ChatView.vue` | — | ~300行 | **新增** 统一对话 |
| `ReportViewer.vue` | — | ~200行 | **新增** 文档/图渲染 |
| **合计** | **~2850行** | **~680行** | **降低 76%** |

---

## 十二、实施路线

### 依赖关系

```
Phase 1 (统一上下文)
    │
    ├──▶ Phase 2 (双向分析)
    │
    ├──▶ Phase 3 (独立图生成)
    │         │
    │         └──▶ Phase 4 (图 Skills)
    │
    ├──▶ Phase 5 (用户自定义指令)
    │
    └──▶ Phase 6 (Agent 化 Skills + 前端简化)
              │
              ├──▶ Phase 7 (Agent Installer)
              │
              └──▶ Phase 8 (架构学习/设计 Skills)
```

### 阶段详情

| 阶段 | 内容 | 新增文件 | 修改文件 | 预估 |
|------|------|---------|---------|------|
| **P1** 统一上下文管理 | `AnalysisContext` 类、层次化缓存、LLM 格式化 | `analysis_context.py` | `llm_service.py`, `prompt_manager.py` | 1天 |
| **P2** 双向分析 | Top-down/Bottom-up 分析器、4 个新模板 | `bidirectional_analyzer.py` | `prompt_templates.json` | 1天 |
| **P3** 独立图生成 | `DiagramOrchestrator`、4 个图模板、验证+修正链 | `diagram_orchestrator.py` | `prompt_templates.json`, `community-store.ts` | 1.5天 |
| **P4** 图生成 Skills | MCP Skills: fix/render/enhance_diagram | — | `mcp_server/skills.py`, `tools.py` | 0.5天 |
| **P5** 用户自定义指令 | `InstructionManager`、`agent_configs` 扩展、前端设置页 | `instruction_manager.py` | `llm_service.py`, `schema.py`, `settings` 前端 | 1天 |
| **P6** Agent 化 Skills | 文档生成 Skills + SERVER_INSTRUCTIONS 升级 + 前端简化为统一 ChatView | — | `skills.py`, `server_instructions.py`, `src/` 大幅删减 | 2天 |
| **P7** Agent Installer | 8 个 Agent Target 插件 | `plugins/installer/*` | — | 1天 |
| **P8** 架构学习/设计 Skills | 5 个架构学习 Skill: explain/compare/recommend/validate/detect | — | `mcp_server/skills.py`, `tools.py` | 1.5天 |

**P8 优先级明细：**

| 子阶段 | Skill | 优先级 | 预估 |
|--------|-------|--------|------|
| P8.1 | `skill_explain_arch_pattern` | **P0** | 0.3天 |
| P8.2 | `skill_compare_arch` | **P0** | 0.3天 |
| P8.3 | `skill_recommend_refactor` | **P0** | 0.3天 |
| P8.4 | `skill_validate_arch_impact` | **P1** | 0.3天 |
| P8.5 | `skill_detect_arch_drift` | **P1** | 0.3天 |

### 并行化策略

```
P1 (1d) ──┬── P2 (1d)    ──┐
          ├── P3 (1.5d)  ──┤
          ├── P5 (1d)    ──┤── 可并行
          └── P6 (2d)    ──┘
                │
                ├── P4 (0.5d, 依赖 P3)
                ├── P7 (1d, 独立)
                └── P8 (1.5d, 依赖 P1 + P6)
                     │
                     └── P8.1→P8.3 优先, P8.4→P8.5 次之
```

P1 完成后 P2/P3/P5/P6 可并行开发。P8 依赖 P1（上下文）和 P6（Skills 化）。P7 完全独立。

总计串行路径：P1 + P3 + P4 = **约 3 天**
总计全部阶段（含并行）：**约 7.5 天**（1 人全栈）

---

## 十三、附录

### A. MCP 协议交互示例

```
→ {"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}
← {"jsonrpc":"2.0","id":1,"result":{
     "protocolVersion":"2024-11-05",
     "capabilities":{"tools":{}},
     "serverInfo":{"name":"topocode","version":"0.1.0"},
     "instructions":"# topocode — 代码架构知识图谱\n..."
   }}

→ {"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}
← {"jsonrpc":"2.0","id":2,"result":{"tools":[...]}}

→ {"jsonrpc":"2.0","id":3,"method":"tools/call","params":{
     "name":"topocode_explore",
     "arguments":{"query":"AuthService loginUser"}
   }}
← {"jsonrpc":"2.0","id":3,"result":{
     "content":[{"type":"text","text":"..."}]
   }}
```

### B. 与 codegraph 共存于同一项目

topocode 是独立工具，不依赖也不设计为与 codegraph 协同。但如果用户同时部署了两者：

- codegraph: `.codegraph/` 索引目录，`codegraph serve` MCP 服务
- topocode: `.topocode/` 配置目录，`topocode serve` MCP 服务

两者使用不同目录、不同工具前缀，不会相互干扰。两者也不在同一认知层级：codegraph 回答符号/文件级问题，topocode 回答社区/模式/决策级问题。topocode 自身完全自足，不假设 codegraph 一定存在。

### C. 向后兼容

- 旧工具名 (`get_definition` 等) 保留至 v1.0，调用时返回 deprecation warning
- 旧 `graph_community` 表不变，`ai_sessions` 为新表无冲突
- 现有 `plugin.json` 格式不变，installer 为新增插件

### D. LLM 解析流程调优对照

本文档第十、十一章涵盖的 LLM 解析流程重构与本文的核心 Agent 化架构是一体的：

| 调优项 | 对应章节 | 核心变化 |
|--------|---------|---------|
| 统一上下文管理 | 四、总体设计 + P1 | 7 处分散的 context 组装 → `AnalysisContext` 单一入口 |
| 双向分析 (top-down/bottom-up) | 七、Skills + P2 | 固定模板 pipeline → Agent 驱动的 `skill_generate_*_doc` |
| 图生成独立会话 | 七、Skills + P3 | 混合一次调用 → 文本/图分离为独立 Skill 会话 |
| 图生成质量链 | 七.8 + P4 | 无质检 → fix → validate → render 三阶链 |
| 用户自定义指令 | P5 | 无 → `InstructionManager` 注入 system prompt |

所有这些优化的目标一致：将 LLM 生成能力从硬编码的模板管道，转变为 Agent 可自主组合的 MCP Skills。

---

## 十四、分布式架构与云端服务

### 14.1 核心类比：topocode 是架构领域的 git

```
git 模型:
  本地:  git clone → 本地仓库 → commit/branch/diff/log
  远程:  GitHub/GitLab → push/pull/fork/PR

topocode 模型:
  本地:  topocode init → 本地知识库 → analyze/diff/quality/session
  云端:  topocode Cloud → 架构注册/基准对比/模式匹配/演化参照
```

**核心原则**：
- 本地完全自足，离线 100% 可用（与 git 一样）
- 云端是增强层，提供参照系和知识共享（与 GitHub 一样）
- 不上传源码，只上传聚合指标（社区数/度分布/模式标签）

### 14.2 整体架构

```
                    topocode 分布式架构

      ┌───────────────────┐    ┌───────────────────┐
      │    本地 topocode   │    │   本地 topocode    │
      │    (开发者 A)      │    │    (开发者 B)      │
      │                   │    │                   │
      │  • 项目分析        │    │  • 项目分析        │
      │  • 私域知识        │    │  • 私域知识        │
      │  • Agent Runtime   │    │  • Agent Runtime   │
      │  • 6 本地 Tools    │    │  • 6 本地 Tools    │
      │  • 4 云端 Tools    │    │  • 4 云端 Tools    │
      └────────┬──────────┘    └────────┬──────────┘
               │                        │
               │  MCP over TLS           │  MCP over TLS
               │                        │
               ▼                        ▼
      ┌────────────────────────────────────────────────┐
      │              topocode Cloud                    │
      │                                                │
      │  ┌──────────────┐  ┌──────────┐  ┌──────────┐ │
      │  │   内容管理     │  │  内容增强  │  │ 内容订阅  │ │
      │  │              │  │          │  │          │ │
      │  │ • 架构注册库  │  │ • 基准对比 │  │ • API Key │ │
      │  │ • 模式目录   │  │ • 相似搜索 │  │ • 分级访问 │ │
      │  │ • 演化路径库  │  │ • 模式匹配 │  │ • 用量控制 │ │
      │  │ • 指标基准库  │  │ • 演化参照 │  │ • 隐私控制 │ │
      │  └──────────────┘  └──────────┘  └──────────┘ │
      │                                                │
      │  ┌──────────────────────────────────────────┐  │
      │  │          OSS 分析流水线                    │  │
      │  │  • 定期拉取高价值 OSS 仓库 → 全量分析      │  │
      │  │  • commit 跟踪 → 架构演化记录              │  │
      │  │  • 跨项目模式提取 → 模式目录更新            │  │
      │  └──────────────────────────────────────────┘  │
      └────────────────────────────────────────────────┘
```

### 14.3 云端三层服务

#### 层一：内容管理

**架构注册库** — 类似 npm registry，注册的是架构知识：

```json
{
  "project": "django-rest-framework",
  "analyzed_at": "2026-06-09",
  "commit": "abc123",
  "language": "python",
  "framework": "django",

  "communities_L0": { "count": 8, "patterns": ["layered", "plugin-based"] },
  "communities_by_edge": { "INCLUDE": [...], "CALL": [...] },

  "metrics": {
    "hub_degree_median": 6,
    "hub_degree_p95": 14,
    "community_size_median": 12,
    "coupling_density": 0.3,
    "modularity_score": 0.72
  },

  "evolution_since_v1": {
    "community_count_trend": "stable",
    "hub_migration": ["auth_center → distributed"],
    "arch_drift_score": 0.15
  }
}
```

**模式目录** — 跨项目提取的架构模式：

```json
{
  "pattern": "middleware-authentication-hub",
  "description": "安全中间件作为认证中心节点，连接表示层和业务层",
  "found_in": ["django-rest-framework", "express-api", "spring-security"],
  "typical_metrics": { "hub_degree": "8-14", "community_size": "8-20" },
  "common_evolution": "随着项目增长，认证中心倾向于从单一 Hub 分裂为多个子角色",
  "anti_pattern_when": "hub_degree > 20, 或跨了 >3 个社区边界"
}
```

**演化路径库** — 跟踪同一项目多版本的架构变化：

```
spring-framework 演化路径:
  v3.0 (2010): monolithic-layered (4 communities, modularity=0.45)
  v4.0 (2014): modular-layered  (6 communities, modularity=0.61) ← 引入 DI 容器
  v5.0 (2018): reactive-split   (9 communities, modularity=0.73) ← WebFlux 引入
  v6.0 (2024): service-oriented (12 communities, modularity=0.78)

→ 提取知识: Spring 每 4 年一次重大架构重构，每次社区数增加约 50%，模块化度稳步提升
```

**指标基准库** — 按语言/框架分组的统计基准：

```json
{
  "python+django": {
    "community_count_L0": { "p25": 4, "p50": 7, "p75": 12 },
    "hub_degree": { "p50": 6, "p95": 14 },
    "modularity_score": { "p50": 0.65, "p25": 0.52 },
    "orphan_rate": { "p50": 0.15, "warning_threshold": 0.30 }
  }
}
```

#### 层二：内容增强（云端 MCP Tools）

本地 topocode 通过这 4 个工具查询云端：

```python
# ── 1. 相似项目搜索 ──

TOPocode_CLOUD_SEARCH = ToolDefinition(
    name="topocode_cloud_search",
    description=(
        "在云端架构注册库中搜索与当前项目相似的开源项目。"
        "按语言、框架、社区规模匹配。返回相似项目的架构特征和关键指标。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "language": {"type": "string"},
            "framework": {"type": "string"},
            "community_count_range": {"type": "string", "description": "例如 '5-15'"},
        },
        "required": ["language"],
    },
)

# ── 2. 基准对比 ──

TOPocode_CLOUD_BENCHMARK = ToolDefinition(
    name="topocode_cloud_benchmark",
    description=(
        "将当前项目的架构指标与同类项目对比，给出偏差分析。"
        "不是打分，是告诉你'你的指标在同类型项目中处于什么位置'。"
        "例如：你的 auth 社区 degree=15，同类项目 median=8——处于异常区间。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "required": True},
            "compare_against": {"type": "string", "description": "基准项目集 (默认: 同语言+同框架)"},
        },
        "required": ["project_id"],
    },
)

# ── 3. 模式匹配 ──

TOPocode_CLOUD_PATTERN_MATCH = ToolDefinition(
    name="topocode_cloud_pattern_match",
    description=(
        "识别当前项目的架构模式，并查找与它属于同一模式的其他项目。"
        "输出：该模式的定义、常见优势、常见陷阱、其他项目的演化路径。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string", "required": True},
        },
        "required": ["project_id"],
    },
)

# ── 4. 演化参照 ──

TOPocode_CLOUD_EVOLUTION_REF = ToolDefinition(
    name="topocode_cloud_evolution_ref",
    description=(
        "查找同类项目在架构演化中出现过的类似变化，"
        "提供'其他人遇到同样问题是怎么解决的'的参照。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "change_description": {"type": "string", "description": "当前面临的架构变更描述"},
            "language": {"type": "string"},
        },
        "required": ["change_description"],
    },
)
```

#### 层三：内容订阅（鉴权）

```
服务分层:

免费层 (默认)
  ├─ topocode_cloud_search          # 基础搜索
  ├─ topocode_cloud_benchmark       # 基础对比 (3 个项目)
  └─ topocode_cloud_pattern_match   # 模式匹配

高级层
  ├─ 无限基准对比
  ├─ topocode_cloud_evolution_ref   # 演化参照
  ├─ 自定义项目集合对比
  └─ 定期推送关注项目的架构变化
```

**鉴权配置：**

```json
// ~/.topocode/cloud.json
{
  "api_key": "tc_sk_xxx",
  "endpoint": "https://cloud.topocode.dev",
  "privacy": {
    "upload_metrics": true,
    "upload_patterns": false,
    "allow_benchmark_contrib": false
  }
}
```

### 14.4 与本地能力的协作

| 本地已有能力 | 云端增强后 | 认知层级提升 |
|------------|-----------|------------|
| `topocode_community` 告诉你有哪些子系统 | `cloud_benchmark` 告诉你"同类项目通常有多少子系统" | 社区级 → 必要性级 |
| `topocode_quality_inspect` 告诉你哪里有风险 | `cloud_pattern_match` 告诉你"这个风险在业界产生过什么后果" | 决策级 → 目标级 |
| `skill_recommend_refactor` 给出基于自身项目的建议 | `cloud_evolution_ref` 告诉你"其他项目面对同样问题时的解决方案和效果" | 决策级 → 目标级 |
| `skill_compare_arch` 对比同一项目的历史版本 | `cloud_search` + `cloud_benchmark` 对比你的项目与业界同类项目 | 必要性级 → 目标级 |

### 14.5 实施节奏

| 阶段 | 内容 | 依赖 | 预估 |
|------|------|------|------|
| **P9.1** 种子知识库 | 预分析 20 个高价值 OSS 项目，提取架构快照+演化路径，建立模式目录 v1 | 本地分析管线已完成 | 2 天 |
| **P9.2** 云端 MCP Tools | 4 个 cloud_* Tools 接入 MCP Server，本地可查询云端 | P9.1 | 1 天 |
| **P9.3** 鉴权与分级 | API Key 认证、用量控制、隐私开关 | P9.2 | 1 天 |
| **P9.4** 自动化流水线 | OSS 项目定期分析、commit 跟踪、模式库自动更新 | P9.1 + 基础设施 | 2 天 |

P9 总计约 6 天，为 P1-P8 完成后的中远期规划。
