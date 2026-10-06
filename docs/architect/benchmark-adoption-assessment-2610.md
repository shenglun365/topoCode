# 对标增强计划细化评估 —— 可行性与业务/架构一致性核验

> 2026-10-10 · 性质：评估报告（裁决输入型）
> 评估对象：[agent-benchmark-roo-roomote-2610.md](agent-benchmark-roo-roomote-2610.md)（A–H 借鉴清单 + P0/P1/P2 + D1–D8 差异化）· [unit-test-repositioning-2610.md](unit-test-repositioning-2610.md)（单测重定位）
> 对齐基准（现行规划五锚，按下述顺序取权威）：① [product-iteration-roadmap-2026-09.md](../product-iteration-roadmap-2026-09.md)（战略/北极星/Phase）② [architect-repositioning-20260926.md](../architect-repositioning-20260926.md)（主 agent 白名单/负面清单，治理单源）③ [data-sovereignty-20261004.md](data-sovereignty-20261004.md)（数据主权定稿，**最新架构事实**）④ [agent-capability-design-2609.md](agent-capability-design-2609.md) D8/D9（内核自研收敛 + MCP 独立轨道）⑤ [agent-arch-gap-adoption-2609.md](agent-arch-gap-adoption-2609.md) §二（明确不做清单/架构红线）
> 代码实证：`apps/architect/topoone_app_architect/agent/`（九层内核）、`agent/governance/{flow,flow_policy,gears}.py`、`agent/execution/{dispatch,context_pack}.py`、`agent/reflection/repair.py`、`sem/change_detector.py` 均已存在

---

## 一、总体结论（先读）

| 维度 | 结论 |
|---|---|
| **战略一致性** | ✅ 高。对标增强的主张（策略层 owner / 事实层感知 / 图感知上下文）与"工程闭环旗舰 + 黄金路径北极星"同向；执行层让渡与"人在环上、有效性=文件状态"基调完全兼容 |
| **架构一致性** | ✅ 中高，**2 处需修订、3 处需适配、1 处冲突**（详见 §三/§四）。最大修订项：benchmark B 节"tree-sitter 结构提取"与 1004 数据主权定稿冲突——architect 已裁决解析引擎走 KB `parseFileAst` 算力 + codegraph 双保险，**不搬解析器**，借鉴点应收窄为"大纲→上下文注入的消费模式" |
| **可行性** | ✅ 载体成熟度分层清晰：约 40% 条目载体已在（直接做）、40% 需适配落地、15% 需裁决、5% 建议砍（D5） |
| **规划融合** | 增强**不新开主线**：约 60% 条目可挂 roadmap 既有编号（P2-T4/T5/T6/T10、P3-T1/T4、L 组）或 v2-todo P1/P3，净新增约 15~25 人日 |
| **红线核验** | 4 条架构红线未被推翻（LLM 不入硬闸 / 单源真相 / prompt 瘦身 / 表面收敛准入）；1 条新增红线建议（judge 类 LLM 判定只出参考意见） |

## 二、对齐基准速查（五锚 → 增强计划的约束翻译）

| 锚 | 关键裁决 | 对增强计划的约束 |
|---|---|---|
| ① roadmap | 工程闭环旗舰；黄金路径完成率唯一验收尺度；用户排序 生态>个人>团队；Phase 1 地基→2 闭环→3 生态 | 新能力必须挂黄金路径（提案→设计→mandate→执行→验收）；学习类表面后置 |
| ② 0926 裁决 | 主 agent 只做五件事；负面清单：通用编码问答/直接写码/需求卡起草/单测判定/仓库直写 | 所有增强落在五件事内；"单测判定"禁 LLM 裁定（程序化门禁除外，单测文档 §0 已声明） |
| ③ 1004 数据主权 | architect 自管基线（`arch_graph_node/edge/ast_cache` + baseline 锚 + diff 层）；KB=纯算力；**不搬 parsers** | 解析类借鉴只取消费模式；图数据自管恰好是 D1 的地基（**利好**） |
| ④ capability-design | D8 不整体采用 cline SDK（sidecar 只是执行器）；D9 内核自研收敛 L0 策略/L1 补偿/L2 回合 | 外循环改造落在 L2 回合引擎演进，不引入外部 harness 做主循环 |
| ⑤ adoption 红线 | 状态迁移不可配置化；LLM 意图不入硬闸；tierSuggested 永不自动写；配置化只行为面不迁移面 | judge/timeout/自动补位类机制一律不得进入硬闸路径 |

## 三、A–H 借鉴清单逐项核验

> 判定图例：🟢 载体已在/直接做 · 🟡 需适配 · 🟠 需裁决 · 🔴 冲突修订

### A. Harness/循环层

| 条目 | 一致性 | 核验 |
|---|---|---|
| 流式四件套 | 🟢 | cv-268 已统一 `process_stream` 单源 + ExecutorProcessStrip（执行器过程感知通道）；增量=主 agent L2 回合（`agent/turns/chat.py`）补"游标+单飞锁+ready 位"三件（可变数组已有 SSE 形态） |
| 显式栈迭代 | 🟢 | 回合引擎已是循环形态，retry 携带状态与 v2-todo "prior_brief 接线"（已知小问题）合流 |
| native tool calling + partial-json | 🟡 | 主 agent 现为 `[TOOL_CALL]` 文本协议（cv-150 已防围栏误判）；迁移方向与 Roo 终局一致，但**时机绑 L 组**（结构化输出合法率 ≥99% 门禁先行），非近期 |
| 配对防御五层 | 🟡 | 执行器侧（cline/opencode）native 协议由 harness 自带；主 agent 侧会话恢复的孤儿 tool_call 补位值得抄（挂 P2-T8 sidecar 稳定性） |
| compact 交接单 | 🟢 | `adaptation.summarize_task` + overflowDigest（S3）已是载体；增量=摘要模板加"必须重载清单"段（纯 prompt 改动，过成对版本化纪律） |
| ToolRepetitionDetector | 🟢 | `reflection/repair.py` 修复循环已存在；增量=按签名去重计数（S1 repair_note 已做签名去重——**直接复用**） |

### B. 工具机制

| 条目 | 一致性 | 核验 |
|---|---|---|
| ~~tree-sitter 结构提取~~ | 🔴 **修订（含新事实）** | 双重冗余：① 与 1004 数据主权定稿冲突（不搬 parsers，走 KB `parseFileAst` 算力）；② **KB parsers 底座本就是 tree-sitter**（`language_loader.py` 独立语言包模式，已注册 19 个语言变体，主流语言全覆盖）——语言覆盖不是短板，缺的是"大纲→agent 上下文"的消费模式。收窄为：**符号大纲→上下文注入的消费模式**，数据源用自管 `arch_ast_cache`/`arch_graph_node`（已在），对标 Roo `parseSourceCodeDefinitionsForFile` 的"喂上下文"用法 |
| 三层防御 | 🟢 对应物更强 | architect 的对应物 = mandate allowedScope **符号级**约束（X/Y/Z 轴 + P2-T4 AST 锚点勾稽），比 Roo fileRegex 文件级更强；借鉴点收窄为"违规错误自带纠正信息"（FileRestrictionError 模式 → mandate 违规回执） |
| @mention | 🟢 | ReferenceParser.parse 已有（P1-T3 补测即可），增量小 |
| FileContextTracker | 🟢 | `sem/change_detector.py` 符号级三级识别 + baseline_diff 自管已是**超集**；增量=把结果喂给 D3 时效性标记（纯接线） |
| 错误回喂 | 🟢 | repair loop + dataset 已有闭环；与 Roo 模式同构 |

### C. Skills 体系

| 条目 | 一致性 | 核验 |
|---|---|---|
| packaged skills 化 | 🟢 轨道已在 | v2-todo P1"harness skills + 资产表"（`arch_assets` + `asset.upsert/list/delete` + 可执行 skills）就是同一主张；benchmark 增量=SKILL.md 的**强制路由/child registry 协议形态**（学协议，不学文件载体） |
| 载体形态 | 🟠 需裁决 | Roomote 用 SKILL.md 文件，v2-todo 用 arch_assets 表——二选一。建议：**表为真相源**（本地单机 + G 提升通道 P2-T6 依赖库），导出/导入用文件格式（对齐 D8 可分享性） |
| 仓库本地技能发现 | 🟡 | `.roo/` 式 repo-local 技能可挂 contract-service AGENTS.md 管道（方向一致，后置） |

### D. 提示词工程

| 条目 | 一致性 | 核验 |
|---|---|---|
| 三层分离 | 🟢 | system prompt 分型已落地（cv-267）；增量=把"身份/工作流信封/环境指令"显式化为目录结构（纯重构，过 prompt 瘦身纪律） |
| 按消费者切换人格 | 🟢 | sessionRole 对话回合制（cv-267：chat 角色 vs 任务角色）已是同构物 |
| environment_details | 🟡 | **须过 ctx_budget 统一装配预算**（S3 防守线③），且注入物从文件列表改为**图邻域摘要**（D1）；每轮重算+尾部追加保护缓存前缀的做法可抄 |
| 快照测试 | 🟢 | 成对版本化纪律（§6.5）的自然延伸，与 P1-T3/T4 测试安全网同族，**P0 不变** |
| `<request>` 转义 | 🟢 | 纯增量，零冲突 |
| 规则优先级洋葱 | 🟢 | AGENTS.md 双向闭环（contract-service）+ P2-T6 G 提升；一致 |

### E. 审批

| 条目 | 一致性 | 核验 |
|---|---|---|
| 四值决策 | 🟡 | choices 问询卡（cv-282：fingerprint 单源 + 原位更新）+ 任务卡一次确认已覆盖 approve/deny/ask；**timeout 自动采纳**与"人在环上"基调有张力 → 见 §四裁决项 2 |
| 队列消息消费 | 🟢 | task_input 转达 + steer 排队（cv-273）已在 |
| followup 建议 | 🟢 | present-options 候选菜单（#5 批丙）已在 |

### F. 多 agent 编排

| 条目 | 一致性 | 核验 |
|---|---|---|
| 委派即隔离 | 🟡 | dispatch 前置门禁（脏区检测 cv-269/282）已在；"new_task 同轮截断"增量可挂 dispatch.py |
| 结题报告契约 | 🟢 | K2 里程碑结构化回执（harness-eval 已采纳）+ execution_report 沉淀单元（0926 P3 ✅）；单测文档 §3.1 的测试段=其字段扩展 |
| judge/advisor | 🟠 **边界收紧** | advisor≈reflection 层已有；**judge 用 LLM 做验收判定违反"LLM 不入硬闸"红线**（adoption §二）与 verify-gate 验证制 → 降级为"L3 参考意见"（plan-C-UI 双通道先例），**永不做门禁** |
| actor-scoped turns | 🟡 | 多人场景 roadmap 已后置（团队用户排序第 3）；单机形态下降为"会话操作者一致性校验"（小） |
| 幂等三件套 | 🟢 等价物在 | SQLite 单机无 advisory lock 需求；任务卡 fingerprint 单源（cv-282）即等价物 |

### G. 工程化

| 条目 | 一致性 | 核验 |
|---|---|---|
| 协议双端共享 | 🟢 | CONV-04 API 契约门禁已在；增量=TS/Py schema 双生成（P3-T1 工具面做厚时顺带） |
| 序列号防竞态 | 🟡 | ArchWs 事件流需核验 seq；SSE msgCount 已有粗粒度（v2-todo 已知小问题），补单调 seq 属小改 |
| 双历史+非破坏标签 | 🟢 理念已在 | architect 单流落库 + specVersions append 旧行永不改（cv-279）已是同构物；**不必照搬 Roo 双历史**（其为 IDE rewind 场景设计） |

### H. MCP

| 条目 | 一致性 | 核验 |
|---|---|---|
| 配置覆盖/粒度审批/命名规整 | 🟢 | 与 P3-T1（工具面做厚）+ arch_mcp_calls 审计同向；`report_test_asset` 上报工具（单测文档 §3.2）挂此轨 |

### 单测重定位方案

| 核验点 | 结论 |
|---|---|
| 与 0926 裁决 | ✅ 文档 §0 已逐条声明（策略层归白名单 #4、验收=程序化门禁非 LLM 判定） |
| 与 P2-T5 verify gate | ✅ 互补：策略层供弹（高风险清单/契约注入）、门禁兜底（L3 拦截）；`.topo/tests.yaml` 清单可挂 K2 回执字段而非独立文件（**简化建议**） |
| 与 P2-T7 表面收敛 | ✅ UnitTestPage 是既有表面升级且挂黄金路径末端，合规；**新增"测试策略工作台"不新开页面**，原位升级 |
| 追溯矩阵载体 | ✅ requirement-service + `acceptance.linkedTests` 预留（plan-C-M0 冻结稿）+ arch_acceptance_facts |
| 中小模型 | ✅ 与 L 组四级梯度完全对齐（S 档=微调小模型；哑铃型曲线 roadmap §6.3 原文在案） |

## 四、冲突与需裁决清单（4 项，建议登记 tech-debt-ledger 待决策单）

| # | 事项 | 冲突对象 | 建议裁决 |
|---|---|---|---|
| 1 | **skills 载体形态**：SKILL.md 文件 vs arch_assets 表 | v2-todo P1（表）↔ benchmark C 节（文件） | 表为真相源、文件为交换格式（同时满足 G 提升与 D8 可分享） |
| 2 | **timeout 自动采纳审批**：低风险提案超时自动通过 | "人在环上"基调（harness-eval 1.1 锚点 2） | 默认关闭；仅命名规约类提案可开，且首启需用户显式 opt-in |
| 3 | **judge LLM 判定边界**：架构漂移裁决用 LLM | "LLM 不入硬闸"红线 + verify-gate 验证制 | judge 只出 L3 参考意见（双通道呈现），门禁一律程序化 |
| 4 | **D5 学习路径生成**：新增学习类表面 | roadmap §1.1 主线 A 降为地基"不加新表面" | 砍掉或后置 Phase 3+；学习叙事由 P3-T5 渐进披露间接承载 |

## 五、优先级重排：增强条目 → 既有轨道归位表

> 原则：**不新开主线**；benchmark P0/P1/P2 重映射到 roadmap Phase + v2-todo，只有无家可归者才新开编号。

| benchmark 条目 | 归位 | 增量估时 | 备注 |
|---|---|---|---|
| P0 快照测试/`<request>` 转义/schema 化 | P1-T3/T4 测试安全网同族（Phase 1 尾） | 1~2d | 零冲突 |
| P0 四值决策（无 timeout）+ 序列号 | 既有 choices/ArchWs 小改 | 1d | timeout 见裁决 2 |
| P1 图邻域上下文（原 tree-sitter 行**修订后**） | **P2-T4 mandate 质量加固**（第一个消费场景：锚定勾稽的上下文供给） | 3~4d | D1 主线的第一步行 |
| P1 packaged skills 化 | **v2-todo P1**（arch_assets + skills） | 复用已排 | 增量=路由协议设计（裁决 1） |
| P1 compact 交接单模板增强 | S3 overflowDigest 模板扩展 | 0.5d | 纯 prompt |
| P1 AGENTS.md 规则链闭环 | contract-service + K2 回执 | 2d | |
| P1 单测策略层（追踪矩阵/缺口清单） | **P2-T5 V 组**扩展字段 + UnitTestPage 原位升级 | 3~5d | 挂验收环节 |
| P2 委派报告契约测试段 | K2 结构化回执 schema 扩展 | 1d | |
| P2 模型角色路由 | **L 组 L6**（llm service 模型路由）复用 | 复用已排 | 增量=角色维度 |
| P2 MCP 配置体系 | P3-T1 | 复用已排 | |
| D8 技能可分享 | **P3-T4 资源中心**同轨 | 复用已排 | Phase 3 |
| D5 学习路径 | 无归位（裁决 4：砍/后置） | — | |
| **净新增合计** | | **~12~16 人日**（其余复用已排轨道） | |

对照 roadmap 总量 96~124 人日：增强带来的净增约 10%~13%，且全部落在既有 Phase 结构内——**排期可行性成立**。

## 六、风险登记（评估新增）

| 风险 | 缓解 |
|---|---|
| native tool calling 迁移与 L 组耦合脱节（模板改了微调模型没回归） | 成对版本化纪律强制（roadmap §6.5 已有）；迁移排 L4 门禁之后 |
| skills 双载体并行（表+文件各写一套） | 裁决 1 落地前，benchmark C 节只学协议不落实现 |
| 表面反弹（策略工作台膨胀成新巨石） | 遵守 P2-T7 准入 + UnitTestPage 原位升级（不新页面）；行数棘轮门禁照走 |
| 事实层同步（弱感知）与分析管线抢算力 | 挂 baseline_refresh 编排（1004 已有一键作业），增量扫描复用 change_detector |

## 七、结论

1. **战略层：通过。** 对标增强与"工程闭环旗舰"叙事互为加强——benchmark 的差异化主张（图感知/事实层/策略层）正是黄金路径各环节的弹药供给，不是旁支。
2. **架构层：通过（附修订）。** 数据主权定稿是最新事实，benchmark 的 B 节 tree-sitter 行与 D5 需按 §三/§四 修订（本评估已同步修订 benchmark 原文两处）；其余条目在五锚内均有合法落点。
3. **可行性：成立。** 载体实证充分（九层内核/dispatch/context_pack/change_detector/repair 全在），净新增约 12~16 人日，60% 条目挂既有轨道。
4. **后续动作**：① 4 项裁决按 tech-debt-ledger 单源流程登记；② benchmark P1 首步行定为 P2-T4 的图邻域上下文供给（D1 与 mandate 加固的交点，一子两吃）；③ 单测策略层进入 P2-T5 V 组设计评审议程。
