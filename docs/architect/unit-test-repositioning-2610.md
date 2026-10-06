# 单测能力重定位与感知补位机制设计

> 2026-10-10 · 定位设计 + 机制设计（输入型文档，供评审）
> 上游：[architect-repositioning-20260926.md](../architect-repositioning-20260926.md)（主 agent 定位裁决**治理单源**）· [runner-verify-gate-design.md](../runner-verify-gate-design.md)（验收门禁 V1~V5）· [product-iteration-roadmap-2026-09.md](../product-iteration-roadmap-2026-09.md)（旗舰闭环 + P2-T5）· [agent-benchmark-roo-roomote-2610.md](agent-benchmark-roo-roomote-2610.md)（对标分析）
> 消费方：UnitTestPage / unit-test-service 演进 · runner-verify-gate 实施 · contract-service AGENTS.md 规约扩展

---

## 0. 决策继承与兼容性声明（先读）

本文与 0926 定位裁决的关系（**不推翻、只细化**）：

| 0926 裁决原文 | 本文解释 | 兼容结论 |
|---|---|---|
| 白名单 #4「执行编排（计划分解→执行器路由→上下文包装配）」 | **测试策略规划是该职能的自然延伸**：分解时决定"测什么、验收标准是什么"，随上下文包（context_pack）注入执行器 | ✅ 归入既有职能 |
| 白名单 #5「资产比对验收（规约资产↔交付资产 diff）」 | 验收层 = 该条 + runner 程序化门禁（P2-T5 已立项），**判定走程序化验证，非 LLM 判定** | ✅ 归入既有职能 |
| 负面清单「单测判定（不做）」 | 指**主 agent 对话回路内不做 LLM 单测裁定**（不由模型说"测试写得对不对"）；程序化门禁（编译/运行/覆盖率阈值）与缺口清单（图驱动计算）均非 LLM 判定 | ✅ 边界重申，无冲突 |
| 负面清单「单测归执行器侧」 | 指**测试的编写与执行**（写用例、跑测试、修失败）归执行器；本文完全继承——执行层一律委派/自选，architect 不做 | ✅ 本文核心立场 |

## 1. 背景与问题

强 agent（Roo/Cline/Codex）与主流模型的单测闭环（读码→写用例→跑→修→绿）已 commodity 化。architect 的单测模块面临定位问题，三个候选方案的辨析结论：

| 选项 | 辨析 | 结论 |
|---|---|---|
| 针对性适配本地中小模型 | 单测生成恰是中小模型相对差距最大的场景（边界推理/mock 设计）；作为单测模块卖点是以短击长 | ❌ 不作为单测能力主张；转为部署形态问题（§6） |
| 自选环节按需构建 | 对**执行层**诚实且正确（commodity 不硬刚） | ⚠️ 只对执行层成立 |
| 其他思路 | **分层重定位**：执行层让出去，策略层与验收层收进来 | ✅ 本文主张 |

核心论证：architect 手里有三样 coding agent 没有的资产，恰好位于单测的**上游和下游**——graph-kernel（影响面/高风险节点）、requirement-service（需求↔验收标准模型）、KB+提案确认工作流（策略资产沉淀）。**测试的"编写与执行"在贬值，测试的"策略与验收"在增值。**

## 2. 定位：三层职责切分

```
architect（策略层 owner + 验收层门禁）
  测试策略规划（图驱动）→ 验收标准定义 → 委派/自选时经 context_pack/AGENTS.md 注入
     │ 委派（v2 agent 路由：cline/opencode/codex）      │ 结果回收为证据链
     ▼                                                ▼
执行层（commodity，委派或用户自选）
  写用例、跑测试、修失败 —— 用谁的模型/agent 都行
```

| 层 | owner | 能力项 | 竞品为何做不到 |
|---|---|---|---|
| 策略层 | architect | 图驱动高风险节点排序（扇入×核心域×覆盖交叉）；需求↔用例追溯矩阵；测试策略资产化（提案卡确认闭环，同命名规约模式） | coding agent 只有文件粒度，无图可达性与需求模型 |
| 执行层 | 执行器/用户 | 写用例、执行、修复循环 | —（commodity，不竞争） |
| 验收层 | architect+runner | 程序化验收门禁（runner-verify-gate V1~V5）；缺口检测与补位（§4/§5） | 验收定义权在架构侧，agent 自述不算数 |

## 3. 感知机制：architect 如何知道外部 agent 干了什么

### 3.0 三层认知模型（核心设计原则）

architect 永远不需要"看见 agent 循环内部"，只需要三层：

```
事实层（Facts）   ← 从仓库/报告观测的客观证据（不依赖 agent 汇报）——权威
主张层（Claims）  ← agent 结题时的结构化自述（可撒谎/可遗漏）——只是线索
验证层（Verify）  ← 用事实核验主张（judge / 门禁）——差异即事件
```

参照：Roomote 服务端从 tool transcript 解析 PR 并回查 GitHub API（`extract-pull-requests.ts:90-115`），缓存为 `pullRequestFacts` + 增量游标 `pullRequestSyncStates`——测试文件/运行结果/覆盖率同为仓库客观存在，同构可解。

### 3.1 路径 A：强感知（architect 发起的委派）——契约回传

1. **结题报告契约**：委派载荷（context_pack）要求结构化报告含测试段：新增测试文件清单、运行结果、覆盖率、未覆盖部分及理由；非空校验（空报告=委派失败，参照 Roomote advisor 退出契约）
2. **测试清单规约**：contract-service 生成的 AGENTS.md 增加一条——新增/修改测试必须登记 `.topo/tests.yaml` 清单（轻量 manifest：agent 可写、architect 可校验；schema 见 §7 开放问题）
3. **测试满意度机制**：参照 Roomote chat-reply-satisfaction（状态文件 + stop hook 强制 closeout，最多 3 次提醒）：委派任务在"测试证据已登记"前不置 done——把闭环变成协议义务而非自觉

### 3.2 路径 B：弱感知（用户/外部 agent 自主工作）——增量事实同步

| 观测点 | 机制 | 参照锚点 |
|---|---|---|
| 测试资产出现/变更 | 增量同步扫描测试文件模式（`*.test.ts`/`test_*.py`/`*_test.go`/`*.spec.ts`…），识别归属 diff | Roomote `pullRequestSyncStates` 游标（`db/schema.ts:2801`） |
| 运行结果/覆盖率 | 解析标准报告：JUnit XML / vitest-jest JSON / lcov-cobertura（CI 产物或本地运行） | 事实层缓存 = `pullRequestFacts`（`db/schema.ts:2687`） |
| agent 主动上报 | architect MCP（McpPage 已有）暴露 `report_test_asset` / `report_test_run` 工具，外部 agent 自愿上报 | Roomote `report_to_parent_session` MCP 工具 |
| 时效性标记 | 符号变更 → 图可达性算受影响测试 → 标 stale | Roo `FileContextTracker.ts:23`（自触发抑制）+ benchmark D3 |

**设计约束：主张层只当线索，事实层才是权威**——agent 报 3 个测试、事实层只见到 2 个文件落盘，差异本身是待核验事件。

## 4. 缺口检测：四类"未闭环"的显式建模

| 缺口类型 | 检测方式 | 严重度加权 |
|---|---|---|
| 覆盖缺口 | 覆盖率映射到图：核心符号（高扇入/核心域）无测试可达 | 图权重，非行覆盖率 |
| 追溯缺口 | 验收标准↔用例矩阵中无证据的验收项 | 需求优先级 |
| 质量缺口 | 程序化检测：无断言测试、纯快照测试、flaky（重跑方差） | runner-verify-gate 已设计（flaky 判定见其 §错误分类） |
| 漂移缺口 | 代码变了测试没变（stale）；结题报告声称有测试但事实层没有 | 变更影响面 |

触发时机（保证"及时"）：
- **事件驱动**：仓库增量同步完成 → 图增量重算 → 缺口清单更新；委派结题 → 门禁评估
- **周期兜底**：定时扫描兜住事件丢失（参照 Roomote sleep-check 观察者模式，`apps/bullmq/src/scheduled-jobs/sleep-check.ts:316`）

## 5. 补位分级 L0~L3

缺口清单进入策略工作台后，四值决策风格分级（复用提案卡心智）：

```
L0 建议   缺口 → pending 提案卡（"核心模块 X 无测试，建议补充"）→ 用户确认    [默认]
L1 委派   确认后精确委派："这 3 个符号需要测试" + 调用方契约（图邻域）+ KB 测试风格样本
L2 快速   architect 内部 generateTests 草稿路径（B1 已有）直接补小缺口
L3 拦截   验收门禁不达标 → 任务不置 done（runner-verify-gate 承载）——闭环定义权兜底
```

自动补位策略用户可配（参照 Roo auto-approval 分级：只读放行/写入审批），默认 L0，信任建立后升 L1。

## 6. 本地中小模型：部署形态问题，不是单测能力问题

不在单测模块上主张中小模型适配；若企业离线/私有化是产品级诉求，正确路径（与 roadmap 哑铃型模型成本洞察一致——大模型在头尾、小模型在腰）：

1. **上下文工程换模型能力**（benchmark D1 的应用）：把 10w token 仓库理解压成 2k token 图邻域（被测函数调用方契约 + KB 测试风格样本 + mock 边界）——中小模型写出合格单测，强模型写得更好，**一鱼两吃**
2. **结构化管线**：schema 约束输出 + 校验失败回喂（Roo 错误回喂模式）+ 分步生成（策略=小模型 → 骨架=中模型 → 断言细节=强模型/委派）
3. **验收不靠模型靠门禁**：程序化验收（覆盖率阈值/运行通过/lint）本就是机械活，runner-verify-gate 天然适配私有化形态

## 7. 落地形态

1. **UnitTestPage 升级**："测试管理页" → "测试策略工作台"：上半屏策略资产（图驱动高风险清单 + 覆盖缺口，提案卡确认）；下半屏执行会话（保留现有 WS 执行，默认委派 subagent / 用户自带 agent）
2. **保留降级** `generateTests` 草稿路径为快速路径（L2），主推策略委派
3. **追溯矩阵**为第一切入能力：requirement-service 已有需求模型，纯数据映射 + UI，不含模型竞争
4. **执行层委派**复用 v2 agent 路由 + context_pack（不新建委派通道）

### 开放问题（评审时定）

- `.topo/tests.yaml` schema：最小字段集（path / target_symbols / registered_at / run_last）与 `.git/info/exclude` 投影（cv-272 规约文档投影模式可复用）
- 覆盖率报告的采集端：绑 runner 门禁（执行时顺带产出）还是独立扫描（需要跑测试，成本高）——倾向前者，弱感知场景降级为"测试文件存在性"级事实
- 追溯矩阵的数据模型：挂 `arch_acceptance_facts` 还是新表（database-design.md §arch_unit_tests 侧）

## 8. 价值总结

1. **零侵入**：对强 agent 零改造（不接协议也可靠事实层感知）；接 MCP/清单规约则感知更细——渐进增强
2. **自洽**：感知输出（缺口清单）= 策略层输入；补位动作 = 策略层执行委派——单测模块由此真正闭环，且不越 0926 裁决雷池一步
3. **复用度高**：全部机制有已验证参照实现（Roomote facts/judge/满意度、Roo 审批分级/FileContextTracker），且对应项均已在路线图（P2-T5、G3/G6）

---

## 附：参照锚点（源码实测，详见 benchmark 文档）

| 机制 | 锚点 |
|---|---|
| PR 事实解析（主张→事实核验） | Roomote `packages/sdk/src/server/lib/task-runs/extract-pull-requests.ts:90` |
| 事实缓存 + 增量游标 | Roomote `packages/db/src/schema.ts:2687(pullRequestFacts), 2801(pullRequestSyncStates)` |
| 结题报告契约 | Roomote `workflows/standardTask.ts:382-400` |
| 满意度/强制 closeout | Roomote slack-stop-hook + chat-reply-satisfaction（最多 3 次提醒） |
| 定时兜底扫描 | Roomote `apps/bullmq/src/scheduled-jobs/sleep-check.ts:316` |
| 审批分级 | Roo `src/core/auto-approval/index.ts:47`（approve/deny/ask/timeout 四值） |
| 文件新鲜度自触发抑制 | Roo `src/core/context-tracking/FileContextTracker.ts:23,270` |
| 错误回喂 | Roo `src/core/prompts/responses.ts:8-57` |
