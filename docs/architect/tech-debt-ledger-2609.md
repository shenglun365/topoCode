# 技术挂账台账(tech-debt ledger) — topoOne architect

> 单源备忘录: 所有「已登记、未偿还」项集中在此。每项含来源/现状/触发条件/验收口径。
> 规则: 偿还一项勾一项; 新挂账必须附理由与归属轨道(禁止无主挂账)。
> 更新: 2026-09-20(初版, 源自 §14.8 架构审计)。

## D4 · 行数棘轮抬升的偿还(未做, 绑定重构轨道)

**现状**: chat.py 620 / dispatch.py 700 / req_agent.py 1311(豁免持续上调, 有理由登记, 零偿还)。

| 轨道 | 内容 | 触发条件 | 验收 |
|---|---|---|---|
| ChatTurn 接缝重构 | turns/context.py 六块接线全量 Provider 化(ToolSurfaceProvider 模式, 补偿管线装配点归位) | 消费清单(R1)再扩 ≥2 项, 或 context.py 再增接线块 | context.py 回到 <150 行纯装配; Provider 登记即消费门禁 |
| DispatchTurn 拆分 | execution/dispatch.py(590→700)按 propose/confirm/input/stop/ignore 域拆分 | 再增 ≥1 个任务生命周期动作 | 拆后单文件 ≤500, 豁免撤销 |
| req_agent 拆分 | req_agent.py(1311)按 工具面/提示面/通道 域拆分(工具面已迁 impl/) | 文档/协议改动被迫频繁动它 | capability 文档单源彻底脱离该文件 |

## D5 · 澄清策略库可配置化(未做, 扩展点)

**现状**: 7 类目标策略(每类 4 问)硬编码于 `agent/requirements/clarify.py::STRATEGIES`;
双词汇正交声明**已做**(§14.8: 策略"目标"词汇 vs Purpose 词表 D10, 互不替换)。

- **触发条件**: 出现「改一条澄清问题要发版」的真实诉求, 或策略数 >10 类。
- **验收**: 策略库经存储(CollabConfigStore 或独立表)加载, 代码只留引擎(match/gap/directive);
  澄清引擎测试不依赖具体策略条目。

## 其它已登记未偿还项

| 项 | 来源 | 现状 | 触发/验收 |
|---|---|---|---|
| 需求忽略前端按钮 | cv-186 遗留 | REST `/requirements/{id}/ignore` 就绪; 需求卡为流内 markdown 无独立组件承载, 暂无 UI | 需求台账面板立项时补按钮列 |
| task-21 存量 pending_confirm 迁移 | cv-186 遗留 | 按「存量原状」裁决保留确认按钮流程 | 用户主动要求迁移时写一次性脚本 |
| task.propose tasks 列表折叠 | cv-188 遗留 | 可读参数错误已能让模型一轮自纠; 多卡连发折叠未做 | 审计表再现高频 `tasks` 误传时加 |
| KB 关联口径放宽评估 | cv-187 注意点 | 判定单源 = kb_degraded(无项目或无 baselineId); 「仅看 kbProjectId 关联」未采纳 | 出现「已关联未建基线却需 kb 检索」的真实用例时评估(影响全插件 KB API 口径) |
| 提示级/执行级执法边界收窄 | 审计 B1 | 澄清指令仍是提示级(挡位引擎 §14.7 声明); KB 面与落卡收尾已执法级 | 澄清误触发率可测后, 评估 propose 前置确定性门 |

## 已偿还(索引)

- ~~D1 文案单源偏离~~ → providers/builtin 收编(card_closing/clarify_* 取文函数)
- ~~D2 mcp.call 字面量散落~~ → KB_FACE_TOOLS 单源
- ~~D3 synthetic 标记游离~~ → collab/cards.MSG_FLAG_SYNTHETIC 登记
- ~~cv-194 附带 bug~~ → _sync_with_tools 降级短路 _CARD_CLOSINGS 残留 NameError(已改引单源)
