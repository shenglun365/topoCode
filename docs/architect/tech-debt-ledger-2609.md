# 技术挂账台账(tech-debt ledger) — topoOne architect

> 单源备忘录: 所有「已登记、未偿还」项集中在此。每项含来源/现状/触发条件/验收口径。
> 规则: 偿还一项勾一项; 新挂账必须附理由与归属轨道(禁止无主挂账)。
> 更新: 2026-09-22(架构采纳轨道待决策清单入账; 两份已消费计划文档残余转移+清理)。
> 更新: 2026-10-10(对标增强轨道待决策清单入账, 来源 benchmark-adoption-assessment-2610.md §四)。
> 更新: 2026-10-10(全库死代码清理收口入账: 见 §「死代码清理 2026-10-10」)。

## D4 · 行数棘轮抬升的偿还(未做, 绑定重构轨道)

**现状**: chat.py 620 / dispatch.py 780 / req_agent.py 1311(豁免持续上调, 有理由登记, 零偿还)。

| 轨道 | 内容 | 触发条件 | 验收 |
|---|---|---|---|
| ChatTurn 接缝重构 | turns/context.py 六块接线全量 Provider 化(ToolSurfaceProvider 模式, 补偿管线装配点归位) | 消费清单(R1)再扩 ≥2 项, 或 context.py 再增接线块 | context.py 回到 <150 行纯装配; Provider 登记即消费门禁 |
| DispatchTurn 拆分 | execution/dispatch.py(590→780)按 propose/confirm/input/stop/ignore 域拆分 | 再增 ≥1 个任务生命周期动作 | 拆后单文件 ≤500, 豁免撤销 |
| req_agent 拆分 | req_agent.py(1311)按 工具面/提示面/通道 域拆分(工具面已迁 impl/) | 文档/协议改动被迫频繁动它 | capability 文档单源彻底脱离该文件 |

> **⚠️ 触发线信号(2026-09-22)**: ChatTurn 轨道——context.py 177→360(反思闭环注入面
> 加入, 采纳文档 S1/S3)。「再增接线块」条款接近触发; context.py 下次功能性改动时
> 应同步启动 Provider 化重构, 而非继续原地增长。

## D5 · 澄清策略库可配置化(✅ 已偿还 2026-09-22, 随 GU-4)

**偿还记录**: 策略库迁 `flow_policy.goal.strategies` 单源(缺省条目在
`governance/goal_defaults.py`, 配置经 CollabConfigStore 深合并);
`clarify.py` 只留引擎(load/match/gap/directive); 写侧校验冻结要素词表。
改一条澄清问题 = PUT /flow-policy 零发版。触发条件消亡。

## 架构采纳轨道·待决策清单(2026-09-22)

> 决策理由与形态约束的单源在 `agent-arch-gap-adoption-2609.md`; 本表只登记「待拍板」项。
> P0(S0-S3)与 P1(#3/#5)已落地; 以下为遗留决策面。

### A · 数据驱动开关(先观察后拍板)

| ID | 任务 | 决策点 | 建议时机/阈值 |
|---|---|---|---|
| A1 | 翻开 GU-L2 分类(`goal.escalation.llmFallback`, 现缺省关) | intent_misroute/intent_llm 样本量与误路由模式是否支撑启用 | 样本 ≥20 且周增稳定 → 单会话灰度验证 → 翻缺省 |
| A2 | 吞错计数扩面 | 是否扩展至其余静默 `except: pass` 路径(现仅点名 8 处) | 计数器稳定运行一个周期(≈2 周)后复核 |
| A3 | 溢出摘要未命中回合延迟 | 装配段同步轻调用延迟是否可接受, 或改异步预计算/后台预热 | 观察 overflow_digest 延迟遥测后定 |
| A4 | GU 指引遵从率(真实流量观察, 2026-09-22 批丙登记; 批丁已配套 `prompt_sections` 分层字数遥测——层重×失遵可直接归因) | clarify-first/present-options 指令注入后模型是否按姿态执行——实证 cv-222/223: 模型仍直接取证落卡(产物正确、路线修正, 但「先问」未发生); `goal_profile.action` 遥测恒开可测遵从比 | 样本攒足后遵从率低且伤体验 → 评估指引文案强化 / L2 翻开联动; 与 A1 同数据面 |

### B · 缓议项重开(不做清单挂了重开条件)

| ID | 任务 | 重开条件/现状 |
|---|---|---|
| B1 | #6 评估域扩展(P2) | #2 数据口已就绪——决策是否立项及归属域 |
| B2 | dossier 进主对话链(#4 重半) | 溢出摘要通道稳定后评估(须先解 ctx_budget 冲突) |
| B3 | 挡位刻度表(gears `_TIERS`)进配置 | 须先设计挡位配置的等价测试方案再裁决 |
| B4 | mining 接入 `aggregate_failures` 消费端 | 只读 API 已就绪(#3 数据地基), 何时排入 mining 批次 |
| B5 | 项目级 flow policy 覆盖 | 项目级 config 基座立项(schema 已预留 merge 点, roles 三级覆盖同款) |
| B6 | 知识图谱层 / A2A 自动移交 | 仅产品方向变更时重开(当前明确不做, 人在环路) |

### C · UI 补全(REST 已就绪)

| ID | 任务 | 决策点 |
|---|---|---|
| C1 | /flow-policy 管理页 | 配置页立项排期(触发: 策略编辑频次成为真实诉求) |
| C2 | tier-suggestions 展示位 | 放模型管理页或独立面板; 采纳按钮接既有 `PUT /llm/model-profiles/{id}`(manual 档) |

### E · 小项收尾

| ID | 任务 | 说明 |
|---|---|---|
| E1 | 评审 §4.4 称谓口径落实 | 裁决「采纳随文档」，统一称谓的措辞修正未逐处执行（纯文档活） |
| E2 | P0/P1 运行数据复盘 | repair_note 命中率 / digest 缓存命中率 / swallow 分布 → 反哺 A1-A3 决策 |

### F · 对话选择层(cv-217 排查产出, 2026-09-22)

> 排查与设计稿: `goal-understanding-2609.md`(单源)。三道门锁死目标理解:
> 人格门(双教学冲突)/模式门(auto+无需求=澄清死路)/入口门(策略库知识成死代码)。
> **GU-1/2/3 已落地(2026-09-22 批甲)**: GoalProfile 产出器+决策表引擎(policy.goal)+
> 人格统一(posture 静态块, 路由段退役)——详见设计稿 §五。

| ID | 任务 | 状态/决策点 |
|---|---|---|
| F1 | 人格统一(能力文档×路由段合并) | ✅ 已落地(GU-3: posture 静态块+路由段退役) |
| F2 | 关键词闭集→性质判据(判据三问) | ✅ 已落地(随 F1 posture 块) |
| F3 | 澄清前置(auto 死路解锁) | ✅ 已落地(GU-4 批乙: 引擎收敛缺口面, 立卡前归 GU; D5 策略库配置化同批偿还) |
| F4 | GU 归一设计定稿 | ✅ 已定稿并全量落地(GU-1~5, 见设计稿 §四/§五) |

## 对标增强轨道·待决策清单(2026-10-10 → 同日裁决完毕)

> 决策理由与核验的单源在 `benchmark-adoption-assessment-2610.md`(五锚一致性核验)。
> **用户裁决(2026-10-10): D-1~D-9 全部落定**; 实施计划按 `adoption-batch1-plan-2610.md`
> (裁决落定版)执行。整体目标口径: 提升需求分析/架构分析/架构设计能力, 学外部优点
> 不照搬机制, 保持灵活(规范性支持但不严格限制每一步), CI/CD 采取跨系统服务整合。

| ID | 任务 | 裁决(2026-10-10) | 备注 |
|---|---|---|---|
| G1(D-1) | skills 载体形态 | ✅ **表为真相源**(arch_assets) | 当前不考虑外部生态兼容, yaml 导入导出降为远期 |
| G2(D-4) | timeout 自动采纳审批 | ✅ **不做审批流程, 预留控制能力** | 模式=执行前规划+执行后审核; 通用 `approval` 扩展位缺省 none, 未来挂人工/主控 agent 审批; "人在环上"细化诠释见 0926 文档附录 |
| G3(D-5) | judge LLM 判定边界 | ✅ **人工终审 + 系统多角度辅助展示** | 流程图/结构图/代码/影响评估/LLM 语义分析; LLM 永不做门禁; D2 形态=comp-graph 扩展(多视图证据面板) |
| G4(D-7) | D5 学习路径 | ✅ **暂缓** | 排序键(图中心度)作为 W5 实施细节落地; 完整功能 Phase 3 复审 |
| —(D-2) | AGENTS.md 权威关系 | ✅ **方案 A**: 生成基线段(定界符)+`.topo/rules/` 追加+手改问询 | W4 按此执行 |
| —(D-3) | 追溯矩阵数据模型 | ✅ **延后** | 避免过度严谨限制自由; linkedTests 预留位不动 |
| —(D-6) | native tool calling 时机 | ✅ **暂缓** | 先依托大中模型跑通完整流程; **L 组优先级整体下调** |
| —(D-8) | 覆盖率采集端 | ✅ **暂缓至 CI/CD 整合** | 跨系统服务整合定位, 届时数据来自外部系统 |
| —(D-9) | W6 首批技能 | ✅ **随实施定**: extract.requirement / analyze.suggest / test.strategy(W5 后) | 非独立决策面 |

## 已消费计划文档·残余转移(2026-09-22)

以下两项计划文档已全量消费(自述「全部环节落地完毕」/决策矩阵 as-built),
残余未决项转移至本台账后文档删除(git 保留全文):

| 来源 | 残余项 | 归属轨道 |
|---|---|---|
| orchestration-plan §7 | 探针套件扩充/评分权重校准(待实战数据) | 编排增量 |
| orchestration-plan §7 | 并行下发调度 | 编排增量 |
| orchestration-plan §7 | PR 语义推广到跨会话(现链式基点仅同会话) | 编排增量 |
| batch5 §0-#4 | K4 @引用不读内容: 检索返回裁剪(预览+定位符)+系统段显式纪律 | KB 检索体验 |
| batch5 §0-#5 | M4 小模型协议健壮性: 受限生成为终局(B4 文档单源化前置) | M4 轨道 |
| batch5 §0-#9 | A2 taskPlan CAS 暂缓 + writeScopes 告警尾量 | task_graph |

## 文档清理记录(2026-09-22)

| 文档 | 处置 | 理由 |
|---|---|---|
| orchestration-plan.md | **删除** | 环节十一~十五 + PR 语义全部落地(文档自述), 残余已上表转移; git 保留全文 |
| agent-harness-batch5-decisions.md | **删除** | 决策矩阵 6/9 已落地 as-built, 其余转移; 上游 harness-evaluation-2609 保留为外部参照 |
| agent-session-flow.md | 保留+增补 | 全景图仍有导航价值; 相位机 ①.5 入图, 按其维护约定补同步 |

## 其它已登记未偿还项

| 项 | 来源 | 现状 | 触发/验收 |
|---|---|---|---|
| 需求忽略前端按钮 | cv-186 遗留 | REST `/requirements/{id}/ignore` 就绪; 需求卡为流内 markdown 无独立组件承载, 暂无 UI | 需求台账面板立项时补按钮列 |
| task-21 存量 pending_confirm 迁移 | cv-186 遗留 | 按「存量原状」裁决保留确认按钮流程 | 用户主动要求迁移时写一次性脚本 |
| task.propose tasks 列表折叠 | cv-188 遗留 | 可读参数错误已能让模型一轮自纠; 多卡连发折叠未做 | 审计表再现高频 `tasks` 误传时加 |
| KB 关联口径放宽评估 | cv-187 注意点 | 判定单源 = kb_degraded(无项目或无 baselineId); 「仅看 kbProjectId 关联」未采纳 | 出现「已关联未建基线却需 kb 检索」的真实用例时评估(影响全插件 KB API 口径) |
| 提示级/执行级执法边界收窄 | 审计 B1 | 澄清指令仍是提示级(挡位引擎 §14.7 声明); KB 面与落卡收尾已执法级 | 澄清误触发率可测后, 评估 propose 前置确定性门 |

## 死代码清理 2026-10-10(已执行, 遗留入账)

> 5 批 commit(aa8b1496/77fcde94/bc65bb57/ffdc351e/246ffec7), 净删 ≈ −4,476 行。
> 已还: 前端死码 7 文件+21 死类型 / 失效脚本 6 / git 产物 untrack 31 / 断链 import ×3 /
> unowned_job+frameworks 接线修复 / test:py 接入三套孤儿测试。

| 项 | 现状 | 触发/验收 |
|---|---|---|
| EventKind `turn_done` 漂移 | `test_event_kind_constants_consistent` 红(EventKind 常量与 _KINDS 不一致; 系 execution 域在途改动引入, 清理时经 stash 复核非清理所致) | turn_done 事件落地者补 _KINDS + runner-events 基线后转绿 |
| tagent 双轨对拍漂移 ×3 | `test_start_pipeline_ab_analysis`/`_ab_all_skipped`(weighted_done 口径 legacy=60/tagent=180)、`test_tagent_host::test_list_batch_files`(L0 社区调用 0≠2)已标 xfail(strict=False) | 管线 owner 裁决双轨口径后摘 xfail |
| arch_routes `/tags` 端点疑似孤儿 | 前端 tag-store 已删(docstring 自述「承载前端 tag-store 持久化」)——端点与内置分类法是否仍被 KB 链路消费未核证, 故未删 | KB 面板接入 tags API 时核证; 无消费者则随下次 MS 删除 |
| ESLint 存量 9736 | 较清理前 9741 净减; MS1 豁免备案口径不变 | MS6/MS7 顺带偿还 |

## 已偿还(索引)

- ~~D1 文案单源偏离~~ → providers/builtin 收编(card_closing/clarify_* 取文函数)
- ~~D2 mcp.call 字面量散落~~ → KB_FACE_TOOLS 单源
- ~~D3 synthetic 标记游离~~ → collab/cards.MSG_FLAG_SYNTHETIC 登记
- ~~D5 澄清策略库配置化~~ → flow_policy.goal.strategies 单源(2026-09-22, 随 GU-4; 引擎留 clarify.py)
- ~~cv-194 附带 bug~~ → _sync_with_tools 降级短路 _CARD_CLOSINGS 残留 NameError(已改引单源)
