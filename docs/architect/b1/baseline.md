# B1 行数基线（W0 · 2026-10-10 · tag topo-b1-start）

> 机制说明：BE 行数棘轮**已机制化**——存量文件走 `tests/goldens/line_baseline.json`（+5% 容差），新文件走 `tests/test_file_size_gate.py`（≤400 行软上限，超限登记 `NEW_FILE_WHITELIST` 附理由），再生走 `tests/goldens/regen_baselines.py --confirm`（先 dry-run 过目 diff）。本文件只登记**本批涉改文件快照**与**新增文件行数预算**，供实施对照。

## 1. 涉改存量文件基线（tag 时实测）

### BE（topoone_app_architect/，受 line_baseline 棘轮约束，容差 +5%）

| 文件 | 基线行数 | 本批涉改组 |
|---|---|---|
| agent/cognition/prompt.py | 512 | W1-1/W1-2 |
| agent/execution/context_pack.py | 129 | W1-2/W2 |
| agent/execution/exec_bridge.py | 1047 | W4 |
| agent/turns/context.py | 344 | W3/W6 |
| agent/reflection/repair.py | 248 | W3（模板常量级） |
| agent/tools/registry.py | 72 | W6 |
| agent/tools/req_agent.py | 1504 | W6（_ARCH_SKILLS 读取点，小改） |
| arch_routes/websocket.py | 198 | W1-3 |
| arch_routes/sessions.py | 1256 | W1-3（增量查询口） |
| arch_routes/agents_md.py | 130 | W4 |
| arch_routes/unit_test.py | 131 | W5 |
| arch_routes/asset_tools.py | 188 | W6 |
| store/schema.py | 1089 | W6（arch_assets 表） |
| sem/baseline_refresh.py | 72 | W5（尾步挂扫描） |

### FE（无行数门禁，tsc/vitest 把关；快照供 review 对照）

| 文件 | 基线行数 | 本批涉改组 |
|---|---|---|
| src/services/ws-client.ts | 100 | W1-3 |
| src/stores/conversation-store.ts | 676 | W1-3 |
| src/stores/unit-test-store.ts | 104 | W5 |
| src/services/contract-service.ts | 303 | W4 |
| src/services/unit-test-service.ts | 99 | W5 |
| src/pages/UnitTestPage.vue | 191 | W5 |
| src/components/unit-test/（8 组件合计） | 1514 | W5（零下线，仅加 AdvicePanel） |

## 2. 新增文件行数预算（均 ≤400 软上限，无需豁免登记）

| 新文件 | 预算 | 组 |
|---|---|---|
| sem/graph_context.py | ~200 | W2 |
| sem/test_reach.py | ~150 | W5 |
| src/components/unit-test/AdvicePanel.vue | ~200 | W5 |
| tests/test_prompt_goldens.py | ~120 | W1-1 |
| tests/test_graph_context.py / test_test_reach.py / test_unit_test_advice.py / test_agents_md_rules.py / test_execution_report_tests.py / test_asset_tools.py / test_arch_assets.py / test_skill_routing.py / test_ws_seq.py 等 | 各 ≤150 | 各组 |
| tests/goldens/prompt/*.json | 资产 | W1-1/W3/W6 |

## 3. 回退锚点

- `git tag topo-b1-start`（打于本文件提交后）
- 各片独立开关：`graph_context_injection` / `skill_routing_injection` / `unit_test_advice.*`（见各组实施文档 §5）
