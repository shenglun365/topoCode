# 归档文档索引（docs/archive）

> 归档日期：2026-09-11 | 维护规则：本目录文档**已过期或已被取代**，仅作历史追溯，不再维护；引用时请注明归档状态。
> 所有归档件在 git 历史中均有原始路径记录（`git log --follow <file>` 可溯源）。

| 归档件 | 原路径 | 归档原因 | 取代者 |
|---|---|---|---|
| [architecture-issues-0902.md](architecture-issues-0902.md) | `docs/architecture-issues.md` | 0902 全仓评估快照；其 P0/P1 问题经 [0905 评估](../architecture-issues-0905.md) §1 逐项核验已基本修复，评估结论由 0905 承接 | [architecture-issues-0905.md](../architecture-issues-0905.md) |
| [plan-A.md](plan-A.md) | `docs/architect-reconstruction/plan-A.md` | 外部建议 A（三核引擎+动态适配器）——architect 重建的早期构想输入；未被采纳为实施蓝本，其认知框架（X/Y/Z 轴、CODING_MANDATE、"认知前额叶"定位）已被 plan-C 以"源码为唯一事实源"的方式吸收 | [plan-C.md](../architect-reconstruction/plan-C.md) |
| [plan-B.md](plan-B.md) | `docs/architect-reconstruction/plan-B.md` | 外部建议 B（四阶流水线+契约包）——同上；"从自由生成变为约束求解"哲学与 Task_Graph 原子化设计仍被现行方案引用 | [plan-C.md](../architect-reconstruction/plan-C.md) |

## 未归档但在 git 历史中的已删文档

代码注释中仍引用、实际已删除的契约文档（如需查阅请走 git 历史）：

- `docs/architect/api-unit-test.md` —— 单测工作台契约（`unit_test.py` 头注释引用；删除于 0821 前后的清理提交）
- `docs/architect/api-knowledge-greenfield.md` —— greenfield 路由契约（`greenfield.py` 头注释引用）
