# 归档文档索引（docs/archive）

> 归档日期：2026-09-11（首批）/ 2026-09-24（重构前清理批）| 维护规则：本目录文档**已过期或已被取代**，仅作历史追溯，不再维护；引用时请注明归档状态。
> 所有归档件在 git 历史中均有原始路径记录（`git log --follow <file>` 可溯源）。

| 归档件 | 原路径 | 归档原因 | 取代者 |
|---|---|---|---|
| [architecture-issues-0902.md](architecture-issues-0902.md) | `docs/architecture-issues.md` | 0902 全仓评估快照；其 P0/P1 问题经 [0905 评估](architecture-issues-0905.md) §1 逐项核验已基本修复，评估结论由 0905 承接 | [architecture-issues-0905.md](architecture-issues-0905.md)（亦已归档） |
| [plan-A.md](plan-A.md) | `docs/architect-reconstruction/plan-A.md` | 外部建议 A（三核引擎+动态适配器）——architect 重建的早期构想输入；未被采纳为实施蓝本，其认知框架（X/Y/Z 轴、CODING_MANDATE、"认知前额叶"定位）已被 plan-C 以"源码为唯一事实源"的方式吸收 | [plan-C.md](plan-C.md)（亦已归档） |
| [plan-B.md](plan-B.md) | `docs/architect-reconstruction/plan-B.md` | 外部建议 B（四阶流水线+契约包）——同上；"从自由生成变为约束求解"哲学与 Task_Graph 原子化设计仍被现行方案引用 | [plan-C.md](plan-C.md)（亦已归档） |
| [architecture-issues-0905.md](architecture-issues-0905.md) | `docs/architecture-issues-0905.md` | 全仓结构债评估与 A/B/C/D 方案——决策与蓝图（A1/A2/B1a/B1b/B2/B3/C1-a/C2/C3）已被 0924 重构方案承接归一为 B0~B6 批次 | [architecture-refactor-plan-20260924.md](../architecture-refactor-plan-20260924.md) |
| [architect-review.md](architect-review.md) | `docs/architect-review.md` | architect 专项评估历史快照（2026-08-30 基线；文内执行机制已退役；god-file 拆分等有效条目经 0905 转入 0924 方案） | [architecture-refactor-plan-20260924.md](../architecture-refactor-plan-20260924.md) |
| [architect-ui-prototype-design.md](architect-ui-prototype-design.md) | `docs/architect-ui-prototype-design.md` | UI/UE 与原型生成旧规划（2026-08-30 基线）；该方向已由 OpenDesign 工作流组件决策接棒（2026-09-24 评审） | OpenDesign 集成评审结论 + [0924 重构方案](../architecture-refactor-plan-20260924.md) |
| [local-small-model-finetune.md](local-small-model-finetune.md) | `docs/local-small-model-finetune.md` | 产品方向讨论归档（自标性质）；结论已并入 roadmap L 组 | [product-iteration-roadmap-2026-09.md](../product-iteration-roadmap-2026-09.md) |
| [plan-C.md](plan-C.md) | `docs/architect-reconstruction/plan-C.md` | architect 重建方案 v1.7——M0~M3 已全部落地；作为冻结决策记录归档 | 代码 + CONV-00~04（现行架构由其承载） |
| [plan-C-M0.md](plan-C-M0.md) | `docs/architect-reconstruction/plan-C-M0.md` | M0 schema/DDL/API 冻结稿（评审通过即冻结为协议基线）；已落地 | `arch_routes/store/migrations.py`（运行时唯一权威） |
| [plan-C-UI.md](plan-C-UI.md) | `docs/architect-reconstruction/plan-C-UI.md` | 界面变化明细——M1~M3 前端已全部落地 | 代码（AssetManagementWorkspace / NamingGovernancePanel 等） |
| [nine-layer-refactor.md](nine-layer-refactor.md) | `docs/architect-reconstruction/nine-layer-refactor.md` | agent 九层重构实录（已完成，456+172 tests 全绿） | `apps/architect/topoone_app_architect/agent/`（现行九层结构） |
| [agent-arch-gap-review-2609.md](agent-arch-gap-review-2609.md) | `docs/architect/agent-arch-gap-review-2609.md` | 架构对照评审——裁决回执（2026-09-21）明示「后续以 adoption 为准」 | [agent-arch-gap-adoption-2609.md](../architect/agent-arch-gap-adoption-2609.md) |
| [architecture-review-20260925.md](architecture-review-20260925.md) | `docs/architecture-review-20260925.md` | MS7 收官评审记录（自题"归档"的历史快照，判据已全部 ✅ 结案）——2026-10-10 文档清理时按治理规则移入 archive | [handover-20260925.md](../handover-20260925.md)（移交入口）+ MS7 判据见 [refactor/milestones.md](../refactor/milestones.md) |

## 未归档但在 git 历史中的已删文档

代码注释中仍引用、实际已删除的契约文档（如需查阅请走 git 历史）：

- `docs/architect/api-unit-test.md` —— 单测工作台契约（`unit_test.py` 头注释引用；删除于 0821 前后的清理提交）
- `docs/architect/api-knowledge-greenfield.md` —— greenfield 路由契约（`greenfield.py` 头注释引用）
