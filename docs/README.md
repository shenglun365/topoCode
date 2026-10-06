# docs 文档索引

> 2026-09-24 重构前清理后建立。目标：只保留**现行有效**文档，历史件一律入 [archive/](archive/README.md)（附归档原因与取代者，git 可溯源）。

## 现行主方案与路线

| 文档 | 状态 | 说明 |
|---|---|---|
| [architecture-refactor-plan-20260924.md](architecture-refactor-plan-20260924.md) | **已评审待实施** | 系统架构重构主方案：现状分析 + 五项裁决 + B0~B6 批次计划 |
| [refactor/milestones.md](refactor/milestones.md) | **阶段拆分定稿** | 里程碑总控 MS1~MS7：每阶段独立可测判据 + 状态跟踪；各 MS 细化设计逐个产出评审 |
| [refactor/MS1-safety-net.md](refactor/MS1-safety-net.md) | 已实施完成 | MS1 细化设计+实施记录：四套测试（78 例）+ 缺陷 D1~D7 清零，验收全绿 |
| [refactor/MS2-dead-code-purge.md](refactor/MS2-dead-code-purge.md) | 已实施完成 | MS2 细化设计+实施记录：净删 −7,006 行（shim 迁移/死码/KnowledgePage 退役） |
| [refactor/MS3-frontend-unification.md](refactor/MS3-frontend-unification.md) | 已实施完成 | MS3 细化设计+实施记录：architect 彻底独立 + token 统一 + 对话框合一 + web-core 瘦身下沉 + sidecar 更名 |
| [refactor/MS4-backend-restructure.md](refactor/MS4-backend-restructure.md) | 🔶 开发中(W1-W3 落地) | MS4 细化设计+实施记录：W1 平级归位/W2 双巨石入 agent/W3 三通道抽取（全绿）；W4/W5/W6/W7 落地，W8 八域拆分留专项，W9 待 W8 |
| [refactor/MS5-engine-splits.md](refactor/MS5-engine-splits.md) | 🔶 部分完成 | MS5 细化设计+实施记录：V0 DDL/V1 task_api 六域/V2 viewer/V3-StepA web_tools 落地；StepB chat_api 挂账专项(py-spy 归因) |
| [product-iteration-roadmap-2026-09.md](product-iteration-roadmap-2026-09.md) | 现行 | 产品迭代路线图（2026-09，含 L 组/各线任务排期） |
| [architect-v2-todo.md](architect-v2-todo.md) | 现行 | architect v2 重构待办（P0 遗留/P1 资产表/P2 旧机制清退/P3 引擎打磨） |
| [kb-unified-components-plan.md](kb-unified-components-plan.md) | Stage 5 待办 | KB 组件双线统一方案（Stage 0~4 已完成） |
| [runner-verify-gate-design.md](runner-verify-gate-design.md) | 设计定稿待实现 | runner 程序化验收门禁 V1~V5（roadmap P2-T5） |
| [architect-repositioning-20260926.md](architect-repositioning-20260926.md) | **治理单源** | 主 agent 定位裁决：三原则 + 职责白名单/负面清单 + 执行器协作演进（cv 批次日志） |
| [handover-20260925.md](handover-20260925.md) | 现行 | 重构程序移交清单（MS1~MS7 完结）：剩余任务/验证方法/文档索引唯一入口 |
| [architect-reconstruction/global-promotion-design.md](architect-reconstruction/global-promotion-design.md) | 设计定稿待实现 | 认知层→主库提升策略（WS8） |

## 设计参考

| 文档 | 说明 |
|---|---|
| [database-design.md](database-design.md) | 全仓持久化存储设计参考（KB 核心 + architect） |
| [diagram-build-animation-design.md](diagram-build-animation-design.md) | 图示构建动画设计方案（源码剥离版，跨项目参考） |
| [oss-reference-landscape.md](oss-reference-landscape.md) | 开源参考项目清单（按 topocode 层分类，含接入纪律） |

## architect 领域文档（docs/architect/）

| 文档 | 角色 |
|---|---|
| [error-contract.md](architect/error-contract.md) | 错误契约（cv-175，分层固定） |
| [kb-schema-versions.md](architect/kb-schema-versions.md) | 知识资产格式版本发布记录（K1，运行时权威在 migrations.py） |
| [agent-session-flow.md](architect/agent-session-flow.md) | 会话流转全景导航图（流转变更须同步本图） |
| [agent-arch-gap-adoption-2609.md](architect/agent-arch-gap-adoption-2609.md) | 架构差距采纳方案（架构采纳轨道单源） |
| [agent-harness-evaluation-2609.md](architect/agent-harness-evaluation-2609.md) | 外部 Agent 源码评估与采纳路线（多线状态归位表） |
| [agent-structure-review-2609.md](architect/agent-structure-review-2609.md) | agent 结构评估（批次 A/B/C，部分已被 adoption 改道） |
| [agent-capability-design-2609.md](architect/agent-capability-design-2609.md) | agent 能力整体设计 v1（待评审实施） |
| [agent-benchmark-roo-roomote-2610.md](architect/agent-benchmark-roo-roomote-2610.md) | Roo Code/Roomote 双项目对标分析 × Architect 能力定位（借鉴清单 + 差异化方向，输入型） |
| [unit-test-repositioning-2610.md](architect/unit-test-repositioning-2610.md) | 单测能力重定位与感知补位机制设计（策略/执行/验收三层切分 + 事实层感知 + L0~L3 补位，输入型待评审） |
| [compensation-strategy-requirements-2609.md](architect/compensation-strategy-requirements-2609.md) | 模型能力分级补偿策略需求规格 |
| [goal-understanding-2609.md](architect/goal-understanding-2609.md) | 目标理解层归一设计（v0 讨论稿，A1/D5 挂账） |
| [tech-debt-ledger-2609.md](architect/tech-debt-ledger-2609.md) | 技术挂账台账（单源备忘录） |
| [remote-agent.md](architect/remote-agent.md) | 远端 Coding Agent Worker 接入指南（S3） |

## 治理规约（docs/conventions/）

CONV-00 总纲与分工矩阵 · CONV-01 topoone-core · CONV-02 web-core · CONV-03 子项目开发规约 · CONV-04 API 契约与验证门禁

## 归档

历史文档一律入 [archive/](archive/README.md)，索引含原路径/归档原因/取代者。归档规则：已被取代或已落地冻结的方案文档，在对应新方案定稿或工作完成后归档。
