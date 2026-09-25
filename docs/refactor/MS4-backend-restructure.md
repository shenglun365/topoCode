# MS4 细化设计：architect 后端职能归位

> 状态：**评审通过；W1 开发中（WIP 分支）** | 日期：2026-09-24
> W1 物理归位已在 `ms4-w1-wip` 分支推进（198 文件，git mv+规则重写），余项：全量套件顺序依赖挂起（test_direct_commands WS recv_until——单跑绿，属前序泄漏）与残余收敛；dev-1 保持全绿基线。 | 上游：[milestones.md](milestones.md) §2-MS4 · [0924 重构方案](../architecture-refactor-plan-20260924.md) B3
> 事实基线：2026-09-24 全量核证（arch_routes 72 文件全景 / agent→routes 216 import 清单 / 层序门禁立条 / sem 函数族锚点），0905-B1b 蓝图行号已复核。
> 并行性：与 MS5 零文件交集（本 MS 只动 apps/architect + 其测试），可并行推进。

## 1. 目标

1. **结构归位**：arch_routes 从「五层混居」（72 文件 28,853 行：路由+store+sem+DDL+harness+执行引擎+网关）瘦身为**纯 REST/WS 适配层**
2. **断环完成**：agent→arch_routes 的 216 处 import（40 文件）清零——`_R1_INVENTORY` 39 条立条**全部清空**（门禁清单只许缩短的终极形态）
3. **巨石拆解**：sem/engine.py 4,851 行按 0905-B1b 五域拆分（蓝图函数族行号已逐点复核在位）
4. 清偿在途遗留：ctx_usage 的 R1 立条缺口（现行红态根因）、R2 五条「MS4」立条处置

## 2. 范围

**纳入**：W1 物理归位（store/sem/schema/infra 三件提升平级） ‖ W2 req_agent+exec_bridge 移入 agent/ ‖ W3 残余三通道抽取 ‖ W4 sessions 收尾拆分 ‖ W5 tracking 澄清 ‖ W6 tagent 归一 ‖ W7 server 去私有 ‖ W8 sem/engine 五域拆分 ‖ W9 契约注释+收口。

**排除**：
- R2 四条「memory/planning/sessions→reflection」上行立条——**非 routes 环**，属 agent 内部层序债，随 W1 后 store 通道消失仅剩语义依赖；移交 agent 层序专项（挂 MS6 前置，回调注入方案另议），本 MS 不动
- asset_extract/asset_framework 的路由本体保留在 arch_routes（sem/engine 对其 2 处惰性引用为已知残留，R1 只扫 agent/**，不受门禁约束；记录在案）
- sem/context.py 内 `kb_gateway` 依赖随 W1 提升后改 `..arch_routes.kb_gateway` 的回指——见 W1 决策 D

## 3. 现状事实基线（核证结论）

| # | 事实 | 依据 |
|---|---|---|
| F1 | arch_routes 72 py/28,853 行；混居证据：store/ 12 文件 3,099、sem/ 14 文件 8,049、DDL `db_schema.py` 899（21 表 :18-393）、harness（req_agent 1,465/test_runner/websocket）、执行引擎（agent_executors 864/cline_engines/exec_bridge 1,030）、网关 kb_gateway 161 | 全量 wc + 头注 |
| F2 | **断环真实规模**：agent→arch_routes import 共 **216 条/40 文件**（模块级仅 8 条/6 文件，余为惰性）；通道分布：store ~91、req_agent ~50、exec_bridge ~26、sem.engine 4、asset_map_tools 5、zmq_stream/asset_skill 各 1 | 逐条 grep |
| F3 | **判据 1 原文形态失真**：`grep "from ..arch_routes"` 只匹配 agent/ 根层文件（子目录用三点形）——orchestrator 三处经 MS2 已改，现行近零；真实断环须以 `grep -rn "arch_routes" agent/` 全形态计（216） | grep 语义核证 |
| F4 | milestones 判据 1 与 R1 门禁的**现行红态**：`ctx_usage.py:45` 惰性引 arch_routes.store 触发 R1，但立条只落在 _R2（:111 空集）未入 _R1_INVENTORY——MS3 合入时的缺口 | test_agent_layering 实测 FAILED |
| F5 | req_agent（1,465）：无 router、未挂载；26-71 行本就是 agent.* 五模块的 re-export 面；消费方 routes 9 文件+agent 15 文件+**tests 42 文件**。exec_bridge（1,030）：无 router；含任务泵本体+dispatch/merge/recover 三域 re-export；消费方 sessions 20 处+agent 10 文件+**tests 31 文件** | 逐文件核证 |
| F6 | sessions.py 1,456 行；尾部 L1224-1456 为「12 条 /tasks/* 路由簇 + units 读侧」连续段，可整体切出 | 行区间核证 |
| F7 | tracking 同名：`arch_routes/tracking.py`（120，REST）vs `arch_routes/store/tracking.py`（352，存储层）——`from .store import tracking as TR`（:14）同模块内两名相撞 | 核证 |
| F8 | tagent 四件（507 行）：se=基座（197，被复用）；extract 的 `run_extraction_agentic` **无生产调用方**（仅测试打桩）、`_extraction_registry` 被 chat/utgen 复用；chat（54）**无生产调用方**且其注释所提 `/ws/coding-agent` 端点已不存在（仅 test_chat_tagent.py 消费）；utgen（71）被 unit_test.py 消费 | 调用面核证 |
| F9 | server.py 私有引用三处：`project._resolve_project`（:62）、`agent.orchestrator._register_session_tools`（:132）、`__main__._default_cors`（:116） | 核证 |
| F10 | sem/engine.py 4,851；B1b 五域函数族全部在位（现行号）：reconcile(:48/:183)、extract_primary(:540/:568)、extract_scope(:1122)、aggregate(:1357/:1534/:1662/:1787)、edge_derive+_cg_ 族(:1824-2076)、query 门面(:165/:2267/:4664)；既有子包先例 incremental/compare/codegraph/context | 逐函数核证 |
| F11 | symbols.py(526)/codegraph.py(254) 头注仍是「双后端+auto 开关」旧表述，**裁决⑤ SLA 表述（codegraph=主源/native=基线+兜底）未落** | grep 零命中 |
| F12 | 平级归位重写面实测：`arch_routes.store` 绝对引用 220 线（tests 128/73 文件 + agent 91 + routes 1）；arch_routes 内部相对 77 条；sem 内部 `..store` 11 条；`arch_routes.sem` 精确 20 条/8 文件；semantic_assets 门面 32 线 | 全量 grep |

## 4. 分步设计（文件级，九批独立 commit）

### W1 物理归位（最大机械批，先行）

**提升**（git mv，全部平级化）：
- `arch_routes/store/`（12 文件）→ `topoone_app_architect/store/`；`arch_routes/db_schema.py` → `store/schema.py`（DDL 归存储层）
- `arch_routes/sem/`（14 文件）→ `topoone_app_architect/sem/`
- **infra 三件随迁**（决策 D：store/sem 的横向依赖，不随迁则平级包反向引 arch_routes）：`arch_routes/ctx.py` → `topoone_app_architect/ctx.py`；`arch_routes/common.py` → `topoone_app_architect/common.py`；`arch_routes/kb_gateway.py` → `topoone_app_architect/kb_gateway.py`

**import 重写**（脚本化，模板化三类）：
1. agent/**（91 线/13 子层）：`from ...arch_routes import store` → `from ... import store`；`from ...arch_routes.store import X` → `from ...store import X`（ctx/common/kb_gateway 同理）
2. arch_routes 内部（77+11 条）：`from .store` → `from ..store`；`from . import store` → `from .. import store`；sem 内 `from ..store` → `from ..store`（深度恰好不变：sem 从嵌套变平级，`..store` 语义随迁正确）；`from .ctx/.common` → `from ..ctx/../common`；`from ..req_agent`（sem/engine 7 处）暂留至 W2 改 `...agent.tools.req_agent`? 否——sem 平级后 `from ..arch_routes.req_agent import` 过渡一拍，W2 落地后改终态 `from ..agent.tools.req_agent import`
3. tests（128 线/73 文件）：`topoone_app_architect.arch_routes.store` → `topoone_app_architect.store`（ctx/common/sem/db_schema 同理；db_schema 改 `topoone_app_architect.store.schema`）

**arch_routes 残留骨架**：纯路由文件 + harness 面（test_runner/websocket/git_host）+ 资产路由族 + `__init__.py` 挂载表（挂载行改指新位置：store 无 router 不涉及；semantic_assets 门面改引 `..sem`）。
**验证**：`python -c "import topoone_app_architect.arch_routes"` + architect pytest 全量 + line_baseline.json 重生成（文件路径大变）。

### W2 req_agent + exec_bridge 移入 agent/

- `arch_routes/req_agent.py` → `agent/tools/req_agent.py`（工具运行时+回路+skills 注册归 tools 层；其 26-71 的 agent.* re-export 面保留——消费方 routes/tests 依赖该面）
- `arch_routes/exec_bridge.py` → `agent/execution/exec_bridge.py`（任务泵+三域 re-export 归 execution 层）
- 重写面：arch_routes 内 9+31 处（`from . import req_agent` → `from ..agent.tools import req_agent` 等）；agent 内 15+10 文件的 `...arch_routes import req_agent/exec_bridge` → 层内相对；tests 42+31 文件改新绝对路径；`exec_cline.py:14`/`agent_executors.py:40` 的 `_runner` 私有引改 `agent.execution.runner_client` 直引；tools/impl 5 处 logger 名与 `__main__:122` 同步
- **效果**：F2 的 req_agent/exec_bridge 两通道（~76 处）全部转 agent 内部 → R1 立条可删 25+ 条

### W3 残余三通道抽取（断环收口）

| 通道 | 抽取 | 去向 |
|---|---|---|
| zmq_stream.iter_llm_events（turns/chat:734） | 纯 SSE 迭代工具（101 行整件） | `agent/collab/zmq_stream.py`；arch_routes 原位若仍有路由引用则留薄壳（核证：仅 agent 消费 → 整件移） |
| asset_skill.skill_docs（cognition/prompt:209） | 文档函数抽 `sem/skill_docs.py`（资产域语义） | 路由 `asset_skill.py` 保留调用 |
| asset_map_tools.run_tool（memory/dossier:81 + tools/impl/map ×5） | 工具执行器抽 `sem/map_tools.py` | 路由薄壳保留 |

完成后 **`grep -rn "arch_routes" agent/ --include='*.py'` 仅剩注释零 import** → `_R1_INVENTORY` 39 条全删（清单清空）；`_R2_INVENTORY` 的 ctx_usage 条目随 store 通道消失同步删除。

### W4 sessions 收尾拆分

L1224-1456（12 条 /tasks/* 路由 + units 读侧，~233 行）切出 `arch_routes/sessions_tasks.py`（同前缀挂载 `__init__.py`），sessions.py 降到 ~1,220。文件内 exec_bridge 引用按 W2 新路径。

### W5 tracking 澄清

`arch_routes/tracking.py` → `arch_routes/tracking_api.py`（路由层后缀约定；路径 `/tracking/*` 不变）；`from .store import tracking as TR` 随 W1 变 `from ..store import tracking`——同名撞名即除。挂载行+tests 引用同步。

### W6 tagent 归一

- 删除 `tagent_chat.py`（54 行，无生产调用方+引用已不存在端点）及其唯一测试 `test_chat_tagent.py`
- `tagent_extract.py` 收缩：删 `run_extraction_agentic` 死路径（185→~110 行），`_extraction_registry`/`build_extraction_context` 保留供 utgen/asset_extract——或并入 `tagent_se.py` 成单件（若 utgen 依赖面允许）
- 终态：tagent_se（基座）+ tagent_utgen 两件；归一后行数 ~280（原 507）

### W7 server 去私有

`project._resolve_project`→`resolve_project`（public 化，project.py 内改名+全引）；`agent.orchestrator._register_session_tools`→`register_session_tools`；`__main__._default_cors`→`default_cors`。各 1-3 处引用同步。

### W8 sem/engine 五域拆分（0905-B1b，行号已复核）

```
sem/
├── engine.py            # 门面（~900 行）：_lazy_reconcile 入口 + api_search/semantic_graph/api_graph/api_reconcile/refresh_scope + 公共 re-export
├── reconcile.py         # reconcile_semantic(:183) + 新鲜度判定（依赖既有 incremental.py:69）
├── extract_primary.py   # _primary_kind_for_node(:540)/_heuristic_extract_primary(:568)/_is_route_handler/_config_carrier_signal/_is_contract_boundary_node/_branch_dense
├── extract_scope_impl.py# extract_scope(:1122)/save_agent_assets/_save_assets + 字段抽取族
├── aggregate.py         # _leaf_components(:1357)/_postorder_component_nodes/_aggregate_one_batch(:1534)/_aggregate_high(:1662)/_aggregate_high_best_effort(:1787)/_link_parent/_inherit_ast_refs
└── edge_derive.py       # _cg_* 族(:1824-1874)/_derive_project_edges(:1889)/_derive_project_edges_kb(:1962)/_derive_indirect_edges(:2076)/_cached_derived_edges
```
依赖单向 `engine → 五域`，五域互不 import（纯物理切分，0905 已核「现在也基本无交叉」）。每拆一域跑 architect pytest。sem 拆分后单文件 <1,500 行（engine 门面 ~900 ✓）。

### W9 契约注释 + 收口

symbols.py/codegraph.py 头注升级为裁决⑤ SLA 表述（codegraph=architect 主源【实时符号事实，ARCH_CODEGRAPH auto=可用即用】；native/KB=基线认知源【组件归属/划分/命名】+主源不可用兜底）；sem/__init__ 与 semantic_assets 门面关系说明；验收 grep 组 + 状态回写。

## 5. 测试计划

- 每 W 批：`python -m pytest apps/architect/tests -q`（1101+ 全绿，R1 红态随 W1/W3 转绿——F4 缺口在 W1 后消失，届时立条删除即闭环）
- W1/W8：line_baseline.json 重生成（`goldens/regen_baselines.py`）
- W2：monkeypatch 接缝成对迁移（tests 73 文件，K1 同款纪律）
- 烟测：`python -c "from topoone_app_architect.server import build_app"` + TestClient `/health`（architect conftest 已有）
- 全量收口：四域 349 + architect 全量 + `npm run test:py`（MS1 套件防 docs/chat 侧零波及——本 MS 不动那些包，跑通即证）

## 6. 验收门禁（对 milestones §2-MS4 判据的执行口径）

| # | 命令 | 预期 |
|---|---|---|
| 1 | `grep -rn "arch_routes" apps/architect/topoone_app_architect/agent/ --include='*.py'` | **零 import 命中**（仅注释；判据原文的两点形 grep 升级为全形态） |
| 2 | `python -m pytest apps/architect/tests -q` | 全绿（含 R1/R2 门禁——_R1_INVENTORY 清空后门禁自动收紧为零容忍） |
| 3 | 目录落位：`ls topoone_app_architect/{store,sem}` 平级存在；`arch_routes/` 内无 store//sem//db_schema.py/ctx.py/common.py/kb_gateway.py/req_agent.py/exec_bridge.py | ✓；sem 拆分后单文件 <1,500 |
| 4 | `python -c "from topoone_app_architect.server import build_app"` + `/health` | import OK + 200 |

## 7. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| R1 216 处重写漏改/错深度 | 脚本化+断言计数（K1 纪律）；import 烟测+全量 pytest 兜底 | 每 W 独立 commit revert |
| R2 测试打桩接缝失效（73 文件） | 成对迁移清单先行；K1 已验证方法论 | 同上 |
| R3 平级后 store/sem 反向依赖 arch_routes（req_agent 7 处/asset_extract 2 处/kb_gateway 1 处） | W2 落地消 req_agent；asset 两处记录为已知残留（不在 agent，无门禁约束）；kb_gateway 已随 W1 提升消解 | — |
| R4 line_baseline 与实际漂移 | regen 脚本重生成+diff 审阅 | 保留旧基线回退 |
| R5 W8 切分引发私有函数交叉引用 | 0905 已核「基本无交叉」；逐域拆+逐域测试 | 单域 revert |
| R6 tagent_chat 删除误伤 | 调用面核证为零（仅测试）；删除 commit 独立 | revert |

## 8. commit 序列（预估 ~9 人日）

| 序 | 内容 | 预估 |
|---|---|---|
| W1 | store/sem/schema/infra 提升平级 + ~420 处 import 重写 + golden 重生成 | 2.5d |
| W2 | req_agent/exec_bridge 移入 agent/ + 89 文件消费面重写 | 1.5d |
| W3 | 三通道抽取 + **_R1_INVENTORY 清空 + R2 两条删除** | 1d |
| W4 | sessions 尾段切出 sessions_tasks.py | 0.5d |
| W5+W6+W7 | tracking 更名 / tagent 归一 / server 去私有 | 0.75d |
| W8 | sem/engine 五域拆分（逐域 commit） | 2.5d |
| W9 | 契约注释升级 + 收口验收回写 | 0.25d |

开工前 `git tag pre-MS4`；与 MS5 并行（零文件交集）。


---

## 9. W1 实施记录（WIP，ms4-w1-wip 分支 e5d33c4）

已完成的机械批与陷阱清单（供续作参考）：
- git mv：store→顶层、sem→顶层、db_schema→store/schema、ctx/common/kb_gateway→顶层
- 规则重写 159+ 文件：agent 三点形、arch_routes 两点形、tests 绝对形、multi-name 拆分（`from .. import store, arch_git` 型）、`# noqa` 尾注剥离后重分组
- 已修陷阱：① 缩进压扁（正则重排丢缩进）② `# noqa` 尾注致 moved 判定失败 ③ sem 内三点相对深度方向（app/sem 应为两点）④ latent-broken imports（dossier/units 的 `..arch_routes.common` 在拆分前即不可达，顺手改真身）⑤ kb_gateway 越顶 `..agent` → `.agent` ⑥ ctx.py 的 `.schema` 应为 `.store.schema`
- 余项：**顺序依赖挂起归因（复现配方已锐化）**——`pytest tests/test_direct_commands.py tests/test_design.py` 反序即挂（direct 全过后，design 的 WS chat 用例收不到事件帧；单文件/正序/孤立用例全绿）。定性：direct 文件遗留状态阻断后续 WS 会话（嫌疑：turn/pump 全局态或 ctx 单例时序），与 V3 挂起同族（asyncio/线程时序 × 模块组织）。归因入口：对 design WS handler 埋 faulthandler.dump_traceback_later + 对比 direct 前后 `ctx`/`store` 单例与 exec_bridge._TASK_PUMPS 状态
- 其余 W2~W9 按本设计继续


---

## 10. 实施记录（2026-09-24/25）

| 批 | commit | 内容 |
|---|---|---|
| W1 | 33ddde4(merge) | store/sem/db_schema/ctx/common/kb_gateway 提升平级(198 文件)；**挂起根因**: commands.py:55 多人名 from-import 残留 store 名→arch_routes.store 半初始化第二实例→WS 回合 AttributeError 被吞；另修缩进/`# noqa` 尾注/三点深度/latent-broken imports 等 6 类陷阱 |
| W2 | cc4ef06(merge) | req_agent→agent/tools、exec_bridge→agent/execution + 86 消费面文件重写 + 引用数据门禁全对齐(golden/白名单/hotspot/层序权威重算) |
| W3 | 8834c8d | zmq_stream→agent/collab、asset_skill→sem/skill_docs(整文件, 本无路由)、asset_map_tools→sem/map_tools(同) |
| 收尾 | 8834c8d+ | skill_docs 惰性导入升 ..arch_routes、baseline 重建(sem/store 纳入) |

**W3 后残余 agent→arch_routes 通道（thick, 属 W3b/后续）**: project(kb_degraded/_resolve_project ×7)、agent_executors(registry ×4)、execution.conv_root_project ×4、cline_engines.resolve_engine、semantic_assets 门面 ×8、agent_roles ×2。这些是厚路由模块, 抽取需连带 REST 面设计——与 W4(sessions 拆分)/W6 合并考量。
