# B1 实施文档组（2610-B1 · 裁决落定版）

> 2026-10-10 · 上游计划：[../adoption-batch1-plan-2610.md](../adoption-batch1-plan-2610.md)（任务卡与总量）· 裁决记录：[../tech-debt-ledger-2609.md](../tech-debt-ledger-2609.md) 对标增强轨道节
> 本组文档 = 开工级实施明细：按模块列**新增 / 变更 / 移除**操作与**上下游影响**。本批**无移除操作**（纯增量 + 开关可回退的替换）。

## 文档索引（按建议阅读/实施序）

| 文档 | 组 | 估时 | 依赖 | 一句话 |
|---|---|---|---|---|
| [W1-foundation.md](W1-foundation.md) | W0 前置 + W1 快赢 | 3.5d | 无 | 安全网：prompt 快照 / 转义 / WS 序列号 |
| [W2-W3-context.md](W2-W3-context.md) | W2 + W3 上下文工程 | 5~5.5d | W0 基线 | ★图邻域供给 + 交接单模板 |
| [W4-contract.md](W4-contract.md) | W4 契约与回执 | 2d | 无硬依赖 | 规则链闭环（D-2 方案 A）+ K2 tests 段 |
| [W5-unit-advice.md](W5-unit-advice.md) | W5 单测建议层 | 3~4d | W2、W4 | 缺口建议面板 + 轻事实层 + approval 位 |
| [W6-skills.md](W6-skills.md) | W6 skills 化 | 2~2.5d | 无（test.strategy 需 W5） | 表为真相源（D-1）+ 路由协议 |

## 模块触碰总图（全批）

```
BE  topoone_app_architect/
    agent/cognition/prompt.py        [W1-1 W1-2]  变更
    agent/execution/context_pack.py  [W1-2 W2]    变更
    agent/execution/exec_bridge.py   [W4]         变更
    agent/turns/context.py           [W1-3 W3 W6] 变更
    agent/reflection/repair.py       [W3]         变更(模板常量)
    agent/tools/registry.py          [W6]         变更
    arch_routes/websocket.py         [W1-3]       变更
    arch_routes/sessions.py          [W1-3]       变更(增量查询)
    arch_routes/agents_md.py         [W4]         变更
    arch_routes/unit_test.py         [W5]         变更
    arch_routes/asset_tools.py       [W6]         变更
    sem/graph_context.py             [W2]         新增 ★
    sem/test_reach.py                [W5]         新增
    sem/ 编排(baseline_refresh)      [W5]         变更(尾步挂扫描)
    store/schema.py + store/         [W6]         变更(arch_assets 表)
FE  src/
    services/ws-client.ts            [W1-3]       变更
    stores(会话消息)                 [W1-3]       变更
    services/contract-service.ts     [W4]         变更(类型)
    services/unit-test-service.ts    [W5]         变更
    pages/UnitTestPage.vue           [W5]         变更(原位升级)
    components/unit-test/AdvicePanel.vue [W5]     新增
测试 tests/goldens/prompt/           [W1-1 W3]    新增
    tests/test_prompt_goldens.py 等   [各组建]     新增
```

## 通用纪律（各文档不再重复）

① 新文件登记行数基线；老文件不净增超豁免（超则登记理由）② 测试基线只增不减 ③ prompt 改动过 `ctx_budget` + 成对版本化 ④ 每片独立开关可回退 ⑤ 基调核验：产出=建议视角，无强制步骤 ⑥ i18n zh/en 同步 ⑦ 全量门禁（pytest/tsc/vitest）绿。
