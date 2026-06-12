# Agent-LLM 解析 & 架构版本跟踪 — 开发计划文档

> 状态：方案设计完毕，待执行  
> 日期：2026-06-12

---

## 1. 背景与动机

当前 topocode 社区架构图（结构图）已完成基础建设：四模式下（内部依赖/调用、外部依赖/调用）的统一钻取状态机、力导向图/Dagre 图/表格/热力图联动、筛选面板、面包屑导航等。

下一阶段拓展两个方向：

| # | 功能 | 目标 |
|---|------|------|
| 1 | **模块语义理解** | 通过 Skills / Tools / LLM 解析，辅助理解模块功能与设计思想，生成 Mermaid / PlantUML 图，结果以 MD 文档形式供用户阅读 |
| 2 | **架构变更跟踪** | 通过 Skills / Tools / MCP 接口对接第三方 Agent（opencode、codex、cline 等），提供架构变更的图形化摘要分析 |

两项功能均通过 topocode 自身 Agent 化实现。

---

## 2. 基础设施现状评估

### 2.1 已有组件（可直接复用）

| 能力 | 成熟度 | 组件 |
|------|--------|------|
| **LLM 集成** | ✅ 完备 | 多 Provider、流式输出、Tool Calling、结构化输出、Prompt 模板 |
| **社区分析** | ✅ 完备 | Louvain 递归检测、L0-L5 层级、质量分、跨社区边 |
| **图生成** | ✅ 完备 | `DiagramOrchestrator` → Mermaid + PlantUML + 校验修复循环 |
| **图渲染** | ✅ 完备 | `plantuml_service.py` → SVG/PNG 渲染 |
| **文档存储** | ✅ 完备 | `report_subdocs` CRUD、`community_llm_results`、`saveOverallDoc` |
| **认知上下文** | ✅ 完备 | `AnalysisContext` 四层模型（项目→社区→文件→符号） |
| **变更追踪** | ✅ 完备 | `change_tracker/` 模块：Git Adapter + Diff Engine + 快照存储 + 影响分析 |
| **MCP 服务** | ✅ 完备 | 6 个工具 + 13 个复合技能 + 外部 Agent 指令 + ZMQ 转发 |
| **Web 浏览** | ✅ 完备 | `reports` 插件 → FastAPI HTTP 服务 + PlantUML 在线渲染 |
| **LLM 社区分析** | ✅ 完备 | 每社区 name/summary/mermaid/plantuml 持久化 |
| **CLI 入口** | ✅ 完备 | `main_cli.py` argparse 框架，已支持 8 个子命令 |

### 2.2 缺失能力

| 缺失 | 影响 |
|------|------|
| **Agent 运行时** | 无自主规划-执行循环，现有流程依赖用户手动触发 |
| **批量分析编排** | `skill_batch_analyze_communities` 技能存在但未从前端接入 |
| **代码变更自动响应** | 无文件监听，变更需显式调用 `checkFileChanges` |
| **增量分析** | 每次分析为全量重新扫描 |
| **可视化变更对比** | 无 Mermaid/PlantUML 图的 diff 展示 |
| **Agent 循环/规划器** | 无可自主迭代的 Agent loop |

---

## 3. 总体架构设计

### 3.1 新增核心模块：Agent 系统

```
backend-core/agent_workflow/  (新增)
  ├── runtime.py          — AgentRuntime: 规划→执行→观察 循环
  ├── memory.py           — AgentMemory: 上下文窗口管理
  ├── tools.py            — AgentTool 抽象 + 已有工具适配器
  ├── workflows/
  │   ├── arch_analyst.py — 架构分析 Agent: 批量 LLM 解读 → MD 文档 → 图
  │   └── arch_sentinel.py— 架构哨兵 Agent: 变更检测 → 差异分析 → 摘要
  └── __init__.py
```

### 3.2 整体架构图

```
                         ┌─────────────────────┐
                         │   AgentRuntime      │ (新增)
                         │  plan→exec→observe  │
                         └──────┬──────────────┘
                                │ 调用
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   DiagramOrchestrator   AnalysisContext    IncrementalAnalyzer
   (已有)                (已有)             (新增)
          │                     │                     │
          ▼                     ▼                     ▼
   community_llm_results  report_subdocs     change_tracker
   (已有)                 (已有)             (已有)
                                │
                                ▼
                        reports 插件 HTTP 服务
                        (已有, Web 浏览)
```

### 3.3 三模式集成全景

```
                  ┌──────────────────────────────┐
                  │       AgentRuntime            │
                  │  ArchAnalyst / ArchSentinel   │
                  └──────────┬───────────────────┘
                             │
         ┌───────────────────┼───────────────────┐
         ▼                   ▼                   ▼
    ┌─────────┐        ┌──────────┐        ┌──────────┐
    │   CLI   │        │   MCP    │        │   UI     │
    │ (新增)  │        │ (已有)   │        │ (已有)   │
    ├─────────┤        ├──────────┤        ├──────────┤
    │• analyze│        │• tools   │        │• 按钮    │
    │• diff   │        │• skills  │        │• 图表    │
    │• track  │        │• 外部Agent│       │• Web浏览 │
    │• export │        │  接入    │        │• MD预览  │
    │• CI/CD  │        │          │        │          │
    └─────────┘        └──────────┘        └──────────┘
         │                   │                   │
         └───────────────────┴───────────────────┘
                             │
                    ┌────────▼────────┐
                    │  SQLite DB +     │
                    │  community_llm   │
                    │  _results +      │
                    │  report_subdocs  │
                    └─────────────────┘
```

---

## 4. 功能一：模块语义理解（ArchAnalyst）

### 4.1 目标

批量 LLM 解析所有社区模块含义，生成结构化文档（Markdown + Mermaid/PlantUML 图），通过 Web 页面供用户浏览。

### 4.2 数据流

```
用户触发 "分析全部社区"
  → AgentRuntime 规划：获取L0列表 → 分批 → 每批LLM分析 → 汇总
  → AgentMemory 装载 AnalysisContext 上下文
  → 对每社区：DiagramOrchestrator 生成 mermaid/plantuml → community_llm_results
  → 汇总：LLM 生成 overview.md（含内嵌图）
  → 持久化：saveOverallDoc(taskId, "整体架构分析", content)
  → 打开 reports 插件 Web 页面浏览
```

### 4.3 复用组件

- `AnalysisContext` → 构建 LLM 上下文
- `DiagramOrchestrator` → 生成 Mermaid + PlantUML
- `community_llm_results` → 持久化单社区结果
- `report.saveOverallDoc` → 持久化汇总文档
- `skill_batch_analyze_communities` → 批量调度框架
- `reports` 插件 → Web 服务呈现

### 4.4 新增工作

| 组件 | 说明 | 行数估算 |
|------|------|---------|
| `ArchAnalystWorkflow` | 规划-执行循环 | ~150 |
| Prompt 模板 `arch_overview` | 汇总文档生成 | ~40 |
| `/cmd` 指令解析 | AI 助手自然语言 → 结构化指令翻译 | ~60 |
| 右面板任务列表 | Agent 任务进度展示（步骤拆解 + 状态图标） | ~200 |

### 4.5 评估

| 维度 | 结论 |
|------|------|
| 必要性 | ⭐⭐⭐⭐⭐ — 48+ 社区逐个手动点击不现实 |
| 可行性 | ⭐⭐⭐⭐☆ — 95% 组件已有，缺编排层 |
| 工作量 | ~3 天 |

---

## 5. 功能二：架构变更跟踪（ArchSentinel）

### 5.1 目标

通过 MCP 协议对接第三方 AI Agent（opencode、codex、cline），在 Agent 完成编码任务后，自动对比架构变化，生成图形化变更摘要，帮助用户确认变更是否符合预期。

### 5.2 数据流

用户/Agent 主动触发 `ArchSentinel.start()` → 编码 → `ArchSentinel.stop()`，四路径统一：

```
GUI [开始追踪] ──┐
Agent skill  ────┤
CLI track start ─┼──→ AgentRuntime.start(ArchSentinel)
三方 MCP tool ───┘          │
                             │ 记录快照 vN → 用户编码
                             │
GUI [结束追踪] ──┐
Agent skill  ────┤
CLI track stop ──┼──→ AgentRuntime.stop(ArchSentinel)
三方 MCP tool ───┘          │
                             │ GitAdapter 获取变更文件
                             │ 增量分析变更文件 + 影响范围
                             │ Diff Engine 对比 v(N-1) vs vN
                             │ LLM 生成变更摘要
                             │ 持久化 .topocode/architecture/ (JSONL)
                             │ 更新 deltas.jsonl + communities.jsonl
                             ▼
                        变更摘要 + diff 数据 → 前端对比模式消费
```

### 5.3 复用组件

- `change_tracker/` — diff engine, snapshot store, git adapter, impact analyzer
- `AISessionTracker` — 会话开始/结束 + 质量检查
- `DiagramOrchestrator` — 变更前后的图生成
- `analysis.saveCommunityResult` — LLM 结果持久化
- MCP `topocode_session_summary` — 外部 Agent 入口

### 5.4 新增工作

| 组件 | 说明 | 行数估算 |
|------|------|---------|
| `ArchSentinelWorkflow` | 变更事件 → 增量分析 → LLM 摘要 → 文档 | ~200 |
| `IncrementalAnalyzer` | 仅扫描变更文件 + 影响范围 | ~250 |
| 可视化 Diff 图 | 前后图并排展示 + 变更标注 | ~120 |
| MCP 通知通道 | Agent 完成摘要 → 推送调用方 | ~60 |
| `deltas.jsonl` 写入 | 变更事件流追加 | ~40 |

### 5.5 评估

| 维度 | 结论 |
|------|------|
| 必要性 | ⭐⭐⭐⭐☆ — 重构频繁的项目价值极高 |
| 可行性 | ⭐⭐⭐☆☆ — 60% 组件已有，缺增量分析 + LLM 摘要 |
| 工作量 | ~5 天 |

---

## 6. CLI 模式扩展

### 6.1 现有 CLI 基础

`backend-core/main_cli.py` argparse 框架已支持：

```
topocode init/uninit/status      — 项目管理
topocode community/arch/diff     — 架构查询（只读 DB）
topocode serve                   — MCP Server
topocode install/uninstall       — Agent 安装器
topocode session                 — 占位
```

### 6.2 新增 CLI 命令

```
topocode arch
├── analyze [--communities] [--all] [--level L0]
│       LLM 批量分析社区
│       --output dir   输出 MD 文档
│       --model MODEL  指定 LLM 模型
│       --concurrency N 并行度 (默认 3)
│
├── overview [--output dir]
│       生成整体架构概览 MD
│
├── diagram <community-id> [--type mermaid|plantuml|both]
│       生成/修复单个社区的图
│
├── export [--format md|json|html] [--output dir]
│       导出完整架构文档
│
└── list [--level L0] [--json]
        列出社区结构

topocode diff
├── snapshots                    列出可用快照
├── compare <from> <to> [--output dir]
│       对比两个快照 → LLM 摘要
└── graph <from> <to> [--type mermaid|plantuml]
        生成架构变更可视化图

topocode track
├── start [--tag "v1.0"]         记录快照 (≡ ArchSentinel.start)
├── stop [--output dir]          对比 → LLM 摘要 → JSONL (≡ ArchSentinel.stop)
├── list [--limit 10]            历史追踪记录
└── status                       当前追踪状态
```

### 6.3 设计原则

| 原则 | 实现 |
|------|------|
| **共享 AgentRuntime** | CLI、MCP、UI 三条路径调用同一实例 |
| **人类可读 + 机器可读** | 默认 Markdown 输出，`--json` 输出结构化数据 |
| **CI 友好** | `--exit-code` 检测到架构问题返回非零 |
| **管道可组合** | 独立执行，支持 `&&` 串联 |

### 6.4 管道集成示例

```bash
# 保存当前架构快照
topocode track start --tag "pre-refactor"

# ... 进行重构 ...

# 结束追踪，生成变更摘要
topocode track stop --output reports/v13-review/

# 导出文档到项目 wiki
topocode arch export --format md --output docs/architecture/

# 对比发布前后的架构变化
topocode diff compare v12 v13 --output reports/v13-review/

# 批量生成所有社区图
topocode arch diagram --all --type mermaid --output diagrams/
```

---

## 7. 存储策略：SQLite 热 + Git JSONL 冷

### 7.1 设计原则

- **热数据** → SQLite：当前分析结果，实时查询
- **冷数据** → Git + JSONL：版本历史，人类可读，Git diff 友好

### 7.2 目录结构

```
<项目根目录>/
├── src/
├── .topocode/
│   ├── data/                   ← SQLite 热数据 (.gitignore)
│   │   ├── project.db
│   │   └── snapshots.db
│   └── architecture/           ← 新增：Git 跟踪的版本历史
│       ├── versions.jsonl      版本清单
│       ├── communities.jsonl   社区摘要快照
│       ├── deltas.jsonl        变更事件流
│       ├── v<N>/               每版本制品
│       │   ├── overview.md
│       │   ├── diagrams/
│       │   └── manifest.json
│       └── diffs/<from>-<to>/  版本间对比
│           ├── summary.md
│           ├── diff.mmd
│           └── delta.json
```

### 7.3 JSONL 数据结构

**`versions.jsonl`** — 版本清单（~200B/行）：

```jsonl
{"id":"v1","ts":"2026-06-12T10:00Z","trigger":"analysis","commit":"abc123","comm_count":48,"summary":"初始 L0 社区 48 个"}
{"id":"v2","ts":"2026-06-13T14:00Z","trigger":"change","commit":"def456","comm_count":50,"from":"v1","delta":"+2/-0"}
```

**`communities.jsonl`** — 社区摘要快照（~300B/行，按版本追加）：

```jsonl
{"v":"v1","cid":"comm-L0-INCL-0001","name":"Core Engine","nodes":120,"score":0.85,"summary":"核心调度引擎..."}
{"v":"v2","cid":"comm-L0-INCL-0001","name":"Core Engine","nodes":125,"score":0.87,"summary":"核心调度引擎..."}
```

**`deltas.jsonl`** — 变更事件流（~150B/行，仅记录变化）：

```jsonl
{"from":"v1","to":"v2","type":"community_grow","cid":"comm-L0-INCL-0001","nodes_delta":5,"risk":"low"}
{"from":"v1","to":"v2","type":"community_split","old":"comm-L0-INCL-0010","new":["comm-L1-010-0001","comm-L1-010-0002"],"risk":"medium"}
```

### 7.4 格式选型理由

| 维度 | SQLite 全量 | Git JSONL 冷存储 |
|------|-----------|-----------------|
| **存储增长** | O(N×M) 每版本全量冗余 | O(M+N) 基础 + 增量 |
| **历史查询** | SQL 查询 | `grep`/`jq` 按 version_id 过滤 |
| **Git diff** | ❌ 二进制 blob | ✅ 逐行文本 |
| **CI 集成** | 需 SQLite 客户端 | `cat *.jsonl | jq` |
| **备份/迁移** | 拷贝 .db | `git push` |
| **并发安全** | SQLite 单写锁 | 追加 JSONL + git commit |
| **人类可读** | 需 SQL 客户端 | 直接 `less` 查看 |

### 7.5 性能基准

500 个版本 × 500 个社区 = 250K 行 JSONL ≈ **75MB**。  
`grep '"v":"v499"' communities.jsonl` 在 SSD 上扫描 < **50ms**。  
无需额外索引。

### 7.6 存储职责划分

| 存储 | 内容 | 格式 | 管理者 |
|------|------|------|--------|
| SQLite | 当前分析数据（node/edge/doc/hierarchy） | 二进制 | topocode |
| SQLite | 最近 2 个快照（SnapshotStore） | 二进制 | topocode |
| Git | 版本清单 + 社区摘要 + 变更事件 | **JSONL** | git |
| Git | 每版本制品（overview.md + diagrams） | **静态文件** | git |
| Git | 版本间 diff（summary.md + diff.mmd/puml） | **静态文件** | git |

---

## 8. 实现优先级与路线图

### Phase 1：AgentRuntime 核心 + 云端 API 基础设施（~2.5 天）

```
backend-core/agent_workflow/
├── runtime.py         Agent 循环：plan → exec → observe → finalize
├── memory.py          上下文窗口管理
├── tools.py           工具抽象 + 适配器
├── sandbox.py         PathSandbox + ContentGuard + RateLimiter + BudgetTracker
├── cloud/
│   ├── client.py      云端通信协议（匿名化元数据提取 + HTTP 客户端）
│   ├── schema.py      匿名化数据结构定义
│   └── anonymize.py   社区元数据提取与脱敏
└── __init__.py
```

### Phase 2：ArchAnalyst 工作流（~2 天）

```
agent_workflow/workflows/arch_analyst.py   批量 LLM 分析社区
Prompt 模板 arch_overview                  汇总文档生成
```

### Phase 3：前端 UI 改造（~4 天）

```
AI 助手 /cmd 指令解析                         自然语言 → 结构化指令翻译
右面板任务列表重构                             废弃旧分析列表，Agent 任务展示
项目 Card 快照角标                            文件变更检测 + 角标 + 悬停详情
结构图对比模式                                面包屑 [📊] + 节点颜色 + 图例 + 钻取
Web 服务面板                                  启动/停止/端口显示 + 生命周期配置
前端 Store 新增                               任务状态 / 快照数据 / 对比 deltas 消费
```

### Phase 4：CLI 扩展（~1.5 天）

```
backend-core/main_cli.py                   新增 arch/diff/track 命令
--output dir 文件写入                       新增 MD 文件写入逻辑
--json 结构化输出                           已有 json.dumps 模式
```

### Phase 5：ArchSentinel 工作流 + 存储层（~4 天）

```
agent_workflow/workflows/arch_sentinel.py  用户/Agent 触发 start → 编码 → stop
backend-core/incremental_analyzer.py       仅扫描变更文件 + 影响范围
.topocode/architecture/ 初始化              创建目录结构
JSONL 追加写入工具                          versions / communities / deltas
```

---

## 9. 前端接入计划

### 9.1 操作入口：AI 助手对话栏 `/cmd`

```
用户在 AI 助手栏输入自然语言或 /cmd 指令
  → AI 翻译为结构化指令 → 展示确认卡片 → 用户确认
  → AgentRuntime 启动
  → 右面板任务列表显示进度
```

无需新增按钮——复用现有 AI 助手对话栏，新增 `/arch` 指令解析能力。

### 9.2 右面板任务列表

现有"分析任务列表"废弃重构为 Agent 指令任务列表：
- 每项显示：状态图标 + 摘要 + 进度条 + 步骤拆解 + 取消/重试
- 支持多任务排队（一个执行中，其余 queued）
- 完成后可 [打开 Web 浏览] 跳转详细报告

### 9.3 项目 Card 快照提醒

- 手动触发扫描（可单项目/批量）
- Card 角标显示待处理文件变更数量
- 悬停/点击展开详情：变更文件数、社区变化预判、[保存快照]/[忽略]

### 9.4 结构图对比模式

- 面包屑区新增 [📊] 对比按钮
- 默认：当前数据 vs 最近快照，可切换版本
- 节点颜色：🟢新增 🔴删除 🟠变更 ⚪无变化
- 完整支持 L0→L1→L2 钻取
- 对比数据来源：`deltas.jsonl` → store → 前端 computed 计算差异状态

### 9.5 `/cmd` 指令与 MCP/CLI 的统一

```
同一 AgentRuntime 实例：
  /arch analyze --all --level L0  →  CLI: topocode arch analyze --all
  /arch track start               →  CLI: topocode track start
  /arch diff                      →  CLI: topocode diff compare
  MCP skill 调用                  →  同一 AgentWorkflow
```

---

## 10. MCP / Skills / CLI 职责对应

```
MCP tool:  topocode_diff              → CLI: topocode diff compare
MCP tool:  topocode_session_summary   → CLI: topocode track stop
MCP skill: skill_analyze_community    → CLI: topocode arch analyze
MCP skill: skill_batch_analyze        → CLI: topocode arch analyze --all
```

同一个 `AgentWorkflow` 类同时服务 CLI 命令和 MCP skill 调用，零代码分叉。

---

## 11. 附录：当前评审已修复问题

本次计划开始前已完成全栈评审修复 13 项（见文档当时记录），关键修复包括：

- 后端：`commit()` 补充、`file_count` 修正、`levels` 返回值、`resolve_key`、异常捕获窄化、复合索引同步
- 前端：层级解析、死分支、筛选面板、分页重置、监听器泄漏、拖拽越界、状态保留、O(n²)→O(1) 查找优化

---

## 12. 战略定位与知识护城河

### 12.1 定位：架构认知中间件

```
主流 AI Coding 工具（Copilot/Cursor/Claude Code）
         │
         │ 负责 "怎么写"
         ▼
    ┌─────────┐
    │ 代码仓库 │
    └─────────┘
         │
         │ Topocode 负责 "结构长什么样"
         │ "为什么这样长" "变了多少"
         ▼
┌─────────────────────────────────┐
│          Topocode               │
│  社区检测 + LLM 解读 + 版本追踪  │
│  本地私有知识 + 云端专业知识     │
└─────────────────────────────────┘
```

Topocode 不是写代码的工具，而是**让所有 AI Coding 工具在写代码之前先理解架构的中间件**。

| Topocode 角色 | 对接对象 |
|--------------|---------|
| **上游** | Copilot/Cursor — 编码完成后，告知架构变化了什么 |
| **侧翼** | Claude Code/Codex — Agent 通过 MCP 获取架构上下文 |
| **互补** | Git — 代码版本管理归 Git，架构知识版本管理归 Topocode |
| **受益者** | 开源项目 — `.topocode/architecture/` 随项目发布，新人快速上手 |

### 12.2 功能无护城河

Topocode 作为**开源本地部署工具**，算法（Louvain 社区检测、D3 力导向渲染）和功能（社区图、热力图、钻取）在 AI Coding 时代极易被复制：

> 任何功能 ≈ 2 周内可被主流工具复现。

代码和算法层面**不构成护城河**。

### 12.3 知识即护城河

真正的壁垒是**持续积累的架构知识**：

| 类型 | 说明 | 不可替代性 |
|------|------|-----------|
| **本地私有知识** | `.topocode/architecture/` 版本化的 JSONL 历史——项目专属、Git 管理、随项目生长越来越有价值 | ⭐⭐⭐⭐⭐ |
| **云端专业知识** | topocode-cloud 知识库——行业架构模式、反模式规则、跨项目基准数据、微调 LLM | ⭐⭐⭐⭐ |
| **架构专用 AI** | 微调模型（命名/摘要/评估专项）、变更风险评估、跨项目模式识别 | ⭐⭐⭐ |

### 12.4 云端知识库三层架构

```
┌─────────────────────────────────────────────────┐
│              topocode-cloud                     │
│                                                 │
│  Layer 3: 行业架构知识库                         │
│  ┌─────────────────────────────────────────┐    │
│  │ • 架构模式库 (Pipeline/Plugin/EventBus)  │    │
│  │ • 反模式检测规则                          │    │
│  │ • 参考架构（按语言/框架/规模索引）         │    │
│  │ • 行业基准数据（匿名化聚合）               │    │
│  │ • 演变规律库（社区增长/分裂的典型模式）     │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  Layer 2: 架构专用 AI                           │
│  ┌─────────────────────────────────────────┐    │
│  │ • 微调 LLM（架构命名/摘要/评估专项）       │    │
│  │ • 架构变更风险评估模型                     │    │
│  │ • 跨项目模式识别                          │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  Layer 1: 基础服务                              │
│  ┌─────────────────────────────────────────┐    │
│  │ • API / MCP / Hermes 协议                │    │
│  │ • 知识消费计量                             │    │
│  │ • 用户/团队/组织多租户                     │    │
│  └─────────────────────────────────────────┘    │
│                                                 │
│  ← 匿名化元数据上传 / 专业分析结果下载 →         │
│                                                 │
├─────────────────────────────────────────────────┤
│              topocode 本地                       │
│                                                 │
│  .topocode/architecture/  ← 始终私有、Git 管理  │
│  社区检测 + 图生成 + 变更追踪 + 本地 LLM 解读   │
│                                                 │
└─────────────────────────────────────────────────┘
```

### 12.5 数据隐私模型

```
用户本地                           topocode-cloud
─────────                         ──────────────
完整代码图        ──不上传──→      
文件路径          ──不上传──→      
社区名称          ──不上传──→      
                                  
社区数量 (48)     ──上传────→     匿名化聚合
节点数分布        ──上传────→     行业基准计算
质量分分布        ──上传────→     模式匹配
边类型比例        ──上传────→     微调 LLM 推理
社区层级深度      ──上传────→     "含 Pipeline 模式"
                                  
                  ←──返回────     专业分析结果
                  ←──返回────     行业对标数据
                  ←──返回────     优化建议
```

### 12.6 产品壁垒演进路径

| 阶段 | 时间 | 里程碑 | 内容 |
|------|------|--------|------|
| **Phase 1** | 当前 | 开源工具 | 社区检测 + 图视图 + 本地 LLM 解读 + JSONL 存储 — 功能完备 |
| **Phase 2** | 3-6 月 | 基础云服务 | 匿名化元数据上传、模式匹配、行业基准对比、Pro 订阅 |
| **Phase 3** | 6-12 月 | 知识平台 | 微调 LLM 上线、匿名数据反哺知识库、Team 版、知识市场 |
| **Phase 4** | 12+ 月 | 行业标准 | Hermes 成为 Agent 间架构知识交换协议、行业级基准数据库 |

### 12.7 开发计划调整

**Phase 1 追加**：云端 API 基础设施

| 新增组件 | 说明 | 行数估算 |
|---------|------|---------|
| `cloud/client.py` | 云端通信协议（匿名化元数据提取 + HTTP 客户端） | ~150 |
| `cloud/schema.py` | 匿名化数据结构定义 | ~60 |
| `cloud/anonymize.py` | 社区元数据提取与脱敏 | ~80 |
| UI 设置页面 | 云端连接配置 + 数据共享开关 | ~100 |

此调整为后续 Phase 2-4 的知识库迭代预留标准接口，不影响 Phase 1 的本地功能独立运行。

---

## 13. Agent 功能边界与合规框架

### 13.1 服务边界定义

| 维度 | 允许（IN SCOPE） | 禁止（OUT OF SCOPE） |
|------|-----------------|---------------------|
| **操作对象** | 社区结构、图、LLM 解读结果、`.topocode/architecture/` 下的 JSONL/MD | 任何项目源代码文件 |
| **文件系统** | `.topocode/` 子目录读写、项目根目录只读（分析引擎需要） | `.topocode/` 以外任何目录的写操作 |
| **网络出站** | LLM API 调用（用户配置的 provider）、topocode-cloud API（需用户开启） | 任何其他 URL、任意 HTTP 请求 |
| **网络入站** | MCP stdio 协议、HTTP API（本地） | 不绑定公网端口 |
| **执行能力** | 预定义工具集（社区检测、图生成、文档写入、JSONL 追加） | 任意 shell 命令、code eval |
| **LLM 输出** | 仅作为文档内容/分析结果存储 | 不直接作为代码执行、不作为系统命令 |

### 13.2 Agent 能力清单（白名单）

Agent 允许调用的工具（代码层面白名单，不可动态扩展）：

```
 分析类:
  ├── detect_communities(taskId, edgeType)    → 已有
  ├── get_cross_edges(taskId, edgeType, lv)    → 已有
  └── get_community_detail(commId)             → 已有

 生成类:
  ├── generate_diagram(commId, type)           → 已有(DiagramOrchestrator)
  ├── generate_overview(taskId)                → 已有(LLM + AnalysisContext)
  └── generate_change_summary(fromV, toV)      → 新增

 持久化类:
  ├── save_community_result(commId, result)    → 已有
  ├── save_overall_doc(taskId, title, content)  → 已有
  ├── append_version_jsonl(entry)              → 新增
  └── append_delta_jsonl(entry)                → 新增

 通信类:
  ├── mcp_response(tool, result)               → 已有
  └── cloud_upload_anonymized(stats)           → 新增
```

### 13.3 禁止清单（硬约束）

Agent 硬约束（代码层面强制，非约定）：

| 禁止项 | 说明 |
|--------|------|
| `write_file()` | 不写项目源文件 |
| `read_file()` | 不读 `.topocode/` 外的文件（分析引擎除外） |
| `exec_shell()` | 不执行 shell 命令 |
| `http_get(任意URL)` | 不行任意网络请求 |
| `eval_text_as_code()` | 不执行 LLM 输出 |
| `git_commit()` | 不操作项目 git 仓库 |
| `access_other_project()` | 不跨项目访问 |
| `delete_any_data()` | 不删除任何数据 |
| `modify_config()` | 不修改系统配置 |

### 13.4 合规框架

#### 数据隐私

| 原则 | 实现 |
|------|------|
| **默认本地** | 首次运行时云端功能默认关闭，需用户主动开启 |
| **代码不出境** | 源文件路径、符号名、社区名永驻本地，仅统计数字上传 |
| **匿名化不可逆** | `cloud/anonymize.py` 保证：计数 → 上传，名称 → 本地 |
| **可验证** | 匿名化逻辑开源，用户可审计上传数据 |

#### 安全防护

| 防护层 | 实现 |
|--------|------|
| **工具白名单** | `AgentRuntime.__init__(tools: list[AgentTool])` — 只允许传入的工具集 |
| **文件沙箱** | `PathValidator`（已有）确保所有路径在 `project_root` 下，且写操作仅在 `.topocode/` |
| **LLM 输出隔离** | 所有 LLM 输出走 `content_sanitizer`：不包含可执行指令、不包含文件路径引用 |
| **预案回滚** | Agent 执行失败时：不修改数据、不回滚已完成步骤、不静默吞错 |
| **速率限制** | LLM 调用：并发 ≤ 3、间隔 ≥ 200ms；云端 API：频率 ≤ 1 req/s |

#### 许可合规

| 场景 | 策略 |
|------|------|
| Topocode 自身 | 开源（AGPLv3 或 MIT），用户自由部署修改 |
| 生成的 MD 文档/图 | 继承项目自身许可，topocode 不主张权利 |
| 云端知识库 | 独立服务条款，匿名化聚合数据归 topocode-cloud，用户原始数据永远归用户 |
| LLM Provider | 用户自配 API key，topocode 不代理中转 LLM 流量 |

#### 运维合规

| 约束 | 实现 |
|------|------|
| **Token 预算** | `--max-tokens 50000` / 每次 Agent 运行上限，达到即停 |
| **超时** | `--timeout 300` / 单次 Agent 运行最长 5 分钟 |
| **并发控制** | 同时仅一个 Agent 实例运行（SQLite 单写锁天然保证） |
| **可观测** | 所有 Agent step → `console.log` + `progress` event + 可选 `--verbose` |
| **可中断** | Ctrl+C → 保存已完成步骤的结果，不丢失数据 |

### 13.5 Agent 架构中的合规锚点

```
AgentRuntime
    │
    ├── ToolRegistry (白名单)
    │   └── 仅允许注册的 AgentTool 子类
    │
    ├── PathSandbox
    │   ├── 读: PathValidator(project_root).validate(path)
    │   └── 写: path must startswith ".topocode/"
    │
    ├── ContentGuard
    │   └── 所有 LLM 输出过 sanitize(): 剔除代码块、shell 命令、URL
    │
    ├── RateLimiter
    │   ├── LLM: 3 concurrent / 200ms interval
    │   └── Cloud: 1 req/s
    │
    └── BudgetTracker
        ├── token_used < max_tokens → 继续
        └── elapsed < timeout → 继续
```

### 13.6 与外部 Agent 的交互边界

```
外部 AI Coding Agent (opencode/codex/cline)
         │
         │ MCP request: topocode_community_detail
         ▼
    ┌─────────────┐
    │  MCP Server │  ← Topocode 响应端
    └─────┬───────┘
          │ 返回：社区名 + 摘要 + 图 + 子社区列表
          │
          │ MCP request: topocode_session_summary
          ▼
    ┌──────────────┐
    │ ArchSentinel │  ← Topocode Agent（产生变更摘要）
    └──────┬───────┘
           │ 返回：变更摘要 + diff 图 + 风险评估
           │
           ▼
    外部 Agent 读取摘要 → 告知用户 "改动了 Core Engine 层，风险低"
```

**关键边界**：Topocode Agent 只做**分析→输出**，不做**规划→修改**。外部 Agent 才是做决策的主体。

### 13.7 一句话边界原则

> Topocode Agent **观察项目、解读结构、记录变化**。永远不写源码、不执行命令、不代做决策。它是架构的"观察者"和"记录者"，不是编码的"参与者"。

---

## 14. 文档完整性检查 & 开发就绪声明

### 14.1 文档章节索引

| # | 章节 | 状态 |
|---|------|------|
| 1 | 背景与动机 | ✅ |
| 2 | 基础设施现状评估 | ✅ |
| 3 | 总体架构设计（AgentRuntime + 三模式集成） | ✅ |
| 4 | 功能一：模块语义理解（ArchAnalyst） | ✅ |
| 5 | 功能二：架构变更跟踪（ArchSentinel） | ✅ |
| 6 | CLI 模式扩展 | ✅ |
| 7 | 存储策略：SQLite 热 + Git JSONL 冷 | ✅ |
| 8 | 实现优先级与路线图 | ✅ |
| 9 | 前端接入计划 | ✅ |
| 10 | MCP / Skills / CLI 职责对应 | ✅ |
| 11 | 附录：评审已修复问题 | ✅ |
| 12 | 战略定位与知识护城河 | ✅ |
| 13 | Agent 功能边界与合规框架 | ✅ |
| 14 | 完整性检查 & 开发就绪声明 | ✅ |
| 15 | UI/UE 流程设计 | ✅ |
| 16 | 最终确认记录 | ✅ |

### 14.2 实施路线图（汇总）

| Phase | 内容 | 依赖 | 预估 |
|-------|------|------|------|
| **P1** | AgentRuntime 核心 + 云端 API 基础设施 | 无 | ~2.5 天 |
| **P2** | ArchAnalyst 工作流（批量 LLM 解读） | P1 | ~2 天 |
| **P3** | 前端 UI 改造（/cmd + 任务列表 + Card 角标 + 对比模式 + Web 面板）| P1 | ~4 天 |
| **P4** | CLI 扩展（arch/diff/track 命令）| P1 + P2 | ~1.5 天 |
| **P5** | ArchSentinel + 存储层（start/stop + 增量分析 + JSONL）| P1 + P2 | ~4 天 |

**总计：~14 天**

> 注：P3（UI）与 P2（ArchAnalyst）可并行执行，P4（CLI）依赖 P2 完成后端工作流，P5 可与 P3/P4 并行。实际并行后总工期约 **8-10 天**。

### 14.3 关键设计决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| Agent 运行时位置 | `backend-core/agent_workflow/` 新模块 | 独立于 MCP Server，可被 CLI/UI/MCP 三者复用 |
| 存储策略 | SQLite（热） + Git JSONL（冷） | 人类可读、CI 友好、Git diff 可用、无存储上限 |
| 输出格式 | 同一 `AgentWorkflow` 服务 CLI/MCP/UI 三条路径 | 零代码分叉 |
| 云端集成时机 | Phase 1 预留接口，Phase 2 实现 | 先闭环本地场景，再扩展云能力 |
| Agent 能力边界 | 预定义白名单 + 硬约束（代码级禁止） | 安全可控，不可越权 |

### 14.4 新增文件清单

```
backend-core/
├── agent_workflow/
│   ├── __init__.py
│   ├── runtime.py            AgentRuntime — plan→exec→observe 循环
│   ├── memory.py             AgentMemory — 上下文窗口管理
│   ├── tools.py              AgentTool 抽象 + 白名单注册
│   ├── sandbox.py            PathSandbox + ContentGuard + RateLimiter
│   ├── workflows/
│   │   ├── __init__.py
│   │   ├── arch_analyst.py   架构分析 Agent
│   │   └── arch_sentinel.py  架构哨兵 Agent
│   └── cloud/
│       ├── __init__.py
│       ├── client.py         云端通信协议
│       ├── schema.py         匿名化数据结构
│       └── anonymize.py      元数据脱敏

现有文件修改:
  backend-core/main_cli.py                       新增 arch/diff/track/session 命令
  src/components/report/CommunityArchitecturePanel.vue  新增按钮 + 面板
  src/stores/community-store.ts                   新增 startArchAnalysis/getArchChangeReports
  src/types/ipc.ts                                新增分析相关 IPC 类型
  electron/preload.ts                             新增 IPC 桥接方法
```

---

## 15. UI/UE 流程设计

### 15.1 用户旅程全景

```
用户打开项目
    │
    ├── 已有分析数据？
    │   ├── YES → 进入主界面（当前架构视图）
    │   └── NO  → [运行分析] 按钮 → 等待解析完成 → 进入社区视图
    │
    ├── 场景A: 想理解架构
    │   └── AI 助手输入 "帮我分析下全部社区" → 翻译为 /cmd → 确认 → Agent 执行
    │       → 右面板任务列表显示进度 → 完成 → 面板内结果概要 + Web 页面浏览详情
    │
    ├── 场景B: 即将重构
    │   └── 项目 Card 提示文件变更 → [保存快照] → 重构编码
    │       → 再次保存快照 → 结构图 [📊 对比] → 查看变更
    │
    ├── 场景C: 新人接手项目
    │   └── 打开已有 `.topocode/architecture/` → 阅读历史文档 + 社区图
    │       → 了解项目分层 + 模块职责 + 架构演变的来龙去脉
    │
    └── 场景D: AI coding agent 接入
        └── Agent 通过 MCP tool/skill 自动调用 topocode
           → 编码前获取架构上下文 → 编码后触发变更摘要
```

### 15.2 `/cmd` 指令系统

#### 指令格式（可扩展）

```
/arch analyze [--communities] [--all] [--level L0]
      批量 LLM 分析社区，生成 name/summary/mermaid/plantuml

/arch overview
      生成整体架构概览 MD

/arch diagram <community-id> [--type mermaid|plantuml|both]
      生成/修复单个社区图

/arch export [--format md|json|html] [--output dir]
      导出完整架构文档

/arch track start [--tag "描述"]
      开始架构追踪（记录快照）

/arch track stop
      结束追踪，生成变更摘要

/arch track list [--limit 10]
      查看历史追踪记录

/arch diff [v-from] [v-to]
      对比两个版本的架构变化（默认: 当前 vs 最近快照）

/arch settings
      配置 LLM 模型、Token 上限、Web 服务端口、云端开关
```

#### 交互流程

```
用户在 AI 助手栏输入 "帮我分析下全部社区"
    │
    ▼
AI 助手 → LLM 翻译为结构化指令
    │
    ▼
┌──────────────────────────────┐
│  🔧 即将执行:                 │
│  /arch analyze --all --level L0│
│                              │
│  预计: 48 个社区, ~3 分钟     │
│  Token 预算: 50000           │
│  LLM 模型: deepseek-chat     │
│                              │
│  [确认执行]  [修改参数]  [取消]│
└──────────────────────────────┘
    │ 点击 [确认执行]
    ▼
  右面板任务列表新增任务 → AgentRuntime 启动
```

**设计原则**：
- 用户可手动输入 `/` 前缀指令，也可自然语言描述 → AI 解析
- AI 翻译的指令**必须用户确认**后方执行（防误操作）
- 确认卡片内可调整参数（`--level L1`, `--model xxx` 等）
- 指令体系保持拓展性：未来增加 `/arch deploy`, `/arch benchmark` 等

### 15.3 右面板任务列表

现有"分析任务列表"废弃，重构为 Agent 指令任务列表。

```
┌──────────────────────────────────────┐
│  Agent 任务 (2)                       │
│                                      │
│  ┌──────────────────────────────────┐│
│  │ 🔄 LLM 分析 L0 社区              ││
│  │ ██████████░░░░░░░░ 12/48  25%   ││
│  │                                  ││
│  │ ✅ 已完成: Core Engine           ││
│  │ ✅ 已完成: Data Layer            ││
│  │ ⏳ 进行中: Network Handler       ││
│  │ ⬜ 等待中: 45 个社区              ││
│  │                                  ││
│  │ [取消] [后台]                    ││
│  └──────────────────────────────────┘│
│                                      │
│  ┌──────────────────────────────────┐│
│  │ ✅ 导出架构文档 (HTML)           ││
│  │ 已完成: 2026-06-12 14:35         ││
│  │ [打开] [重试]    [✕]            ││
│  └──────────────────────────────────┘│
└──────────────────────────────────────┘
```

**任务状态定义**：

| 图标 | 状态 | 说明 |
|------|------|------|
| ⬜ | `queued` | 排队中 |
| 🔄 | `running` | 执行中 |
| ✅ | `completed` | 成功 |
| ⚠️ | `partial` | 部分成功（某些社区跳过） |
| ❌ | `failed` | 失败 |
| ◼ | `cancelled` | 用户取消 |

**交互行为**：
- Agent 执行中可切换视图 Tab，任务不中断
- 完成后可点击 [打开 Web 浏览] 跳转详细报告
- 失败/部分成功的任务可 [重试]（跳过已完成的社区）

### 15.4 项目 Card 快照提醒

#### 触发方式

用户手动触发（可单项目扫描，可批量扫描多个项目）。

#### 提醒形式

```
┌────────────────────────────────┐
│ llama.cpp              ⚡2    │  ← ⚡角标: 2 个待处理的提醒
│ 最后分析: 6月12日              │
│ 上次快照: v12 (3天前)          │
└────────────────────────────────┘
    │ 鼠标悬停 (tooltip)
    ▼
┌──────────────────────────────┐
│ 检测到 15 个文件变化           │
│ 新增: 3 社区候选               │
│ 变更: Core Engine (120→138)   │
│ 最近快照: v12 (6月9日)         │
│ [保存快照 v13]  [查看详情]     │
│ [忽略]                        │
└──────────────────────────────┘
```

- Card 空间有限，仅显示 ⚡角标符号
- 鼠标悬停或点击展开详细信息（tooltip / popover）
- [保存快照] → 触发 `AgentRuntime.start(ArchSentinel, --tag v13)` → 记录快照 → 生成 JSONL
- 再次保存 → `AgentRuntime.stop(ArchSentinel)` → diff v12-v13 → 持久化

### 15.5 结构图对比模式

#### 触发

面包屑区域新增 [📊] 对比按钮。

#### 默认行为

点击即进入对比模式：**当前数据 vs 最近一次快照**（如 v12）。
可随时切换对比的版本节点（下拉选择 v1, v2, ... v12）。

#### 对比模式下的行为

- **完整支持钻取**：L0 → L1 → L2 任意层级
- **钻取后的节点持续显示颜色差异**（子社区的变更状态继承父社区对比结果）
- **图例常驻**：图角落显示

```
🟢 新增节点         🔴 删除节点
🟠 变更节点         ⚪ 无变化
```

其中"变更"指：节点在两个版本间存在但属性不同（node_count 变化、file_count 变化、quality_score 变化、或者 LLM 摘要不同）。

#### 非图视图的对比

| 视图 | 对比表现 |
|------|---------|
| 力导向图 / Dagre | 节点颜色 + 图例 |
| 表格 | 行底色：🟢新增 / 🔴删除 / 🟠变更 |
| 热力图 | 单元格边框颜色表示变化方向 |

#### 面包屑导航调整

```
对比模式开启后，面包屑格式：

[📊 退出对比] [当前: v13] vs [v12] [选择对比版本▾] [L0 社区] [L0-INCL-0042 >]
```

点击 [📊 退出对比] 回到普通视图。

### 15.6 Web 服务生命周期

- **默认保活**：`reports` 插件 HTTP 服务保持运行（开销极低）
- **配置项**：设置中可选 "自动启动" 或 "手动启动"
- **手动控制**：面板内提供 [启动 Web] / [停止 Web] 按钮，显示当前端口号
- **端口冲突**：自动递增（8730 → 8731 → ...）

### 15.7 分析结果展示细节

#### 进度阶段

分析任务在右面板任务列表显示实时进度 + 步骤拆解：

```
任务: LLM 分析 L0 社区 (48)
├── ✅ 规划完成: 48 社区, 3 批次
├── 🔄 批次 1/3: 分析社区 1-16
│   ├── ✅ Core Engine
│   ├── ⏳ Data Layer
│   └── ⬜ 14 个待执行
├── ⬜ 批次 2/3: 分析社区 17-32
└── ⬜ 批次 3/3: 分析社区 33-48
```

#### 完成状态

```
✅ 分析完成 — 48/48 社区
📊 生成 48 Mermaid + 48 PlantUML
📝 生成 1 个架构总览文档
⏱ 耗时: 2分34秒, Token: 37,200

[打开 Web 浏览] [重试失败的] [关闭]
```

点击 [打开 Web 浏览] → 浏览器打开 → 项目概览页（总览 + 社区列表 + 图集 + 搜索）。

---

## 16. 最终确认记录

| # | 问题 | 最终决策 |
|---|------|---------|
| A1 | `/cmd` 格式 | `/arch <action> [options]` 体系，可扩展 |
| A2 | 自然语言 → `/cmd` | AI 自动翻译，用户确认后执行 |
| B3 | 任务列表 | 废弃现有分析任务列表，重构为 Agent 任务列表 |
| C4 | 快照触发 | 用户手动触发，支持单项目/批量扫描 |
| C5 | Card 提醒 | 角标 + 悬停/点击展开详情 |
| D6 | 对比触发 | 面包屑 [📊]，默认当前 vs 最近快照，可切换版本 |
| D7 | 对比+钻取 | 完整支持，子节点继承父节点颜色差异 |
| D8 | 图例 | 🟢新增 🔴删除 🟠变更 ⚪无变化（源码变更状态） |
| 新增 | 分析进度面板 | 右面板任务列表，Agent 步骤拆解 |
| 新增 | Web 服务 | 默认保活，可配置手动/自动，按钮控制 |
| 新增 | 追踪操作 | 非持续后台追踪，用户主动 start → 编码 → stop, 各路径统一触发 |

