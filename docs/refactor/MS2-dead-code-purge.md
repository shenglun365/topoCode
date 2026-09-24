# MS2 细化设计：死代码与残留清零

> 状态：**待评审** | 日期：2026-09-24 | 上游：[milestones.md](milestones.md) §2-MS2 · [0924 重构方案](../architecture-refactor-plan-20260924.md) B1
> 事实基线：2026-09-24 两路代码核证（前端逐项引用核证 / 后端 shim 与空目录核证），全部结论带 文件:行号。
> 纪律：**只删零引用物**；有真实引用者移交后续 MS 随消费者共改（裁决⑥同款逻辑）。

## 1. 目标

1. 删除全部已核证零引用的前端死代码（**~6,600 行**，高于 0905 估的 ~4,700）与后端 8 个兼容 shim（80 行，41 处生产引用 + 28 处测试引用改直达真身）
2. 退役 KnowledgePage（裁决：默认退役，含路由/导航/i18n 解耦）
3. 清理 3 个空目录（chat/docs/**architect** 的 `server/`——第三个为本次计划外发现）
4. **约束**：删除后系统行为零变化（除 `/knowledge` 路由按裁决退役外）；全部门禁零新增红灯

## 2. 范围

**纳入**：K1 后端 shim 八件套迁移 ‖ K2 architect 前端死码（17 文件+级联） ‖ K3 workbench 死码（5 文件+alias） ‖ K4 KnowledgePage 退役集群 ‖ K5 web-core 两件+空目录+收口。

**排除**（核证后裁决移出/保留）：
- **`web-core/src/components/DiagramRebuildDialog.vue`（306 行）移出 MS2**——0905 判死有误：被 `DiagramViewer.vue:6`（import）与 `:392`（模板）真实引用。移交 MS6 随 DiagramViewer 共改（届时按 UI 可达性再裁决去留）
- **`arch_routes/agent_roles.py` 不在 8 shim 内**——自带 router 与端点，仅部分 re-export（agent/__init__.py:17 docstring 列 9 名含它，纯 shim 实为 8）
- **`baseline-service.ts` 保留**——`arch-change-service.ts:3` 存活引用
- 后端 `agent/`→`arch_routes` 其余反向依赖（store/ctx/req_agent/exec_bridge 等 ~134 行）——属 MS4 断环，不混入
- 不动 CI/lint 存量红灯（MS1 已豁免备案）

## 3. 现状事实基线（核证结论）

| # | 事实 | 依据 |
|---|---|---|
| F1 | architect services 5 件全部零引用（405 行）；`blueprint-agent`/`extract-service` 仅 `greenfield.py:4` docstring 字符串提及（非 import） | 逐项 grep 核证 |
| F2 | architect stores：`collaboration`/`git-sync` 零引用；`kb-query-store` 仅被同批删除的 KbQueryView/History 引用（同批删即归零）；级联：删后 `services/kb-query-agent.ts`（58 行）、`types/index.ts` 的 `KbQuery*` 四类型（:1223/1226/1252/1265）与 `Blueprint`（:1290，`ArchitectureModel` 多方使用保留）变零引用 | 核证 |
| F3 | architect 组件 9 件零引用（2,136 行）；architect 无 auto-import/全局注册；`DesignPanel` 级联 `design-service.ts`（77 行）；`PseudoExplainer` 仅 `agent/cognition/roles.py:33` 注释字符串 | 核证 |
| F4 | workbench：`agent-usage-store`/`plugin-store`/`analysis/TaskCard`/`project/ProjectList`/`constants/providers.ts`（目录仅此一件）全部零引用；**同名异物坑**：architect 的 `chat/TaskCard.vue`（存活，被 AnalysisChat 用）与 docs 的 `pages/ProjectList.vue`（存活）**不可误删**——删除必须按完整路径 | 核证 |
| F5 | `utils/mock.ts`（828 行）引用方 7 处全部在删除集内（KnowledgePage 集群 + analysis/TaskCard）→ K3 删 TaskCard 后仍剩 K4 引用，**mock.ts 放 K4 末尾删** | 核证 |
| F6 | `@topo-animation` alias：定义 4 处（workbench vite.config:17 / tsconfig:28,29 / vitest.config:18），import 引用 **0**，指向目录不存在——纯失效配置 | 核证 |
| F7 | web-core：`fileColors.ts` 仅测试引用（连带删 `tests/fileColors.test.ts` 34 行）；`types/zmq.ts` 零引用（ipc.ts 有平行定义互不相干）；exports 为通配无需改 package.json | 核证 |
| F8 | KnowledgePage 集群（页面 504 + knowledge/ 组件 5 件 917 + store 213 + i18n 146 ≈ 1,780 行）；外部耦合 8 处：router:56-61/:105、ActivityBar:26/:33(注释入口)、AppShell:37/:82、navigation.ts:25、funcGroup.ts:12,26,37、types/index.ts:6、RightPanel:23、i18n 注册 zh/en index:15,46 + nav.ts:9 + shell.ts:49 | 核证 |
| F9 | 8 个 shim 均为纯 re-export（合计 80 行）；`context_registry` 是唯一双真身（`agent.memory.units` + `agent.memory.dossier`）；`prompt_registry` 真身模块名是 `agent.cognition.prompt`（非 prompt_registry），改写勿照抄名字 | arch_routes/ 逐文件头核证 |
| F10 | shim 引用面：生产 41 处 + 测试 28 处；**成对陷阱**：`test_comp_m5.py:102` 字符串 monkeypatch `"arch_routes.llm_dataset.record"` 与 `agent/turns/context.py:56` 的 shim 引用必须同步迁移，否则打桩失效 | 核证 |
| F11 | shim 删除随附必改：`tests/goldens/line_baseline.json` 8 条目（:88~:172，`test_file_size_gate.py:71` 明示删文件须收缩基线——跑 `goldens/regen_baselines.py` 重生成）；`agent/__init__.py:17-20` shim 边界 docstring 改写；grep 门禁白名单不含 8 shim（无需改） | 核证 |
| F12 | 空目录实为 **3 个**：`apps/{chat,docs,architect}/server/` 均仅 .gitkeep（同批 commit `1c657d8` 入库）；全仓字符串零引用；三 app 的 pyproject `packages.find` 只收 `topoone_app_*`，删除对打包/安装零影响 | 核证（architect/server 为计划外发现，方案 :77 只列了两个） |

## 4. 分步设计（文件级，五批独立 commit）

### K1 后端 shim 八件套（最高风险，独立成批先行）

**删除**（8 文件 80 行）：`arch_routes/{adaptation,capability_mining,context_registry,evaluator,llm_dataset,model_profile,prompt_registry,ws_events}.py`

**引用方改直达**（真身映射表，逐处替换；完整 41+28 处清单见核证记录，此处按文件归并）：

| 引用文件 | 处数 | 目标真身 |
|---|---|---|
| `arch_routes/__init__.py`（:22,:23,:42,:56） | 4 | `from ..agent.reflection import mining as capability_mining, dataset as llm_dataset`；router 注册同名换真身 |
| `arch_routes/sessions.py`（:23,:466,:736,:784,:997,:1027,:1212） | 7 | `..agent.collab.sse as ws_events`；units/dossier/repair 按名拆 |
| `arch_routes/{dev_digest,session_docs,req_agent,asset_map_tools,mcp_collab}.py` | 14 | repair/mining/dataset/cognition.model_profile/cognition.prompt/memory.units 按名拆 |
| `server.py:138` | 1 | `.agent.reflection.mining.start_periodic_mine` |
| `agent/` 内 8 文件（orchestrator/turns×5/planning/memory×2/req_spec/coding/distill） | 15 | 相对真身（`from ..reflection.repair import ...` 等；req_agent 部分不动属 MS4） |
| tests 6 文件（test_model_profile/test_light_tasks/test_msg_digest/test_sessions_center/test_distill_errors/test_probe_dossier/test_context_registry/test_flow_policy/test_exec_implement/test_comp_m5） | 28 | monkeypatch 接缝随迁（如 `adaptation`→`agent.reflection.repair`；`"arch_routes.llm_dataset.record"` 字符串→`"agent.reflection.dataset.record"` 与 context.py:56 成对） |

**随附**：regen `line_baseline.json`；改写 `agent/__init__.py:17-20` docstring（shim 已撤）。

**验证**：`grep -rnIE "arch_routes[./](adaptation|capability_mining|context_registry|evaluator|llm_dataset|model_profile|prompt_registry|ws_events)" --include='*.py' apps packages` 零命中；`python -m pytest apps/architect/tests -q` 全绿。

### K2 architect 前端死码（17 文件 + 级联 2 服务 + 类型清理）

**删除**：services 5（asset-validator/blueprint-agent/extract-service/guide-patterns/mainkb-service）+ stores 3（collaboration/git-sync/kb-query-store）+ 组件 9（BaselineSummaryBar/ComponentListView/KbQueryView/KbQueryHistory/PseudoExplainer/DesignPanel/ProjectSetupDialog/AssetDetailModal/ScopeProposalModal）+ 级联（services/kb-query-agent.ts、services/design-service.ts）。

**类型清理**（`types/index.ts`）：删 `Blueprint`（:1290）与 `KbQuery*` 四类型（:1223-1265 段）——删除后 grep 复核零引用，vue-tsc 兜底。

**验证**：附录 A1 命令组零命中；`npx vue-tsc --noEmit -p apps/architect` + vitest 全绿。

### K3 workbench 死码 + 失效 alias

**删除**：`stores/agent-usage-store.ts`、`stores/plugin-store.ts`、`components/analysis/TaskCard.vue`、`components/project/ProjectList.vue`、`constants/providers.ts`（含 constants/ 目录）。
**alias 摘除**：vite.config.ts:17、tsconfig.json:28,29、vitest.config.ts:18 的 `@topo-animation`。
**验证**：附录 A2 零命中（**按完整路径**匹配，防同名异物误删）；type-check/vitest 绿。

### K4 KnowledgePage 退役集群（含 mock.ts 终点删除）

**删除**：`pages/KnowledgePage.vue`、`components/knowledge/` 整目录（BaselinePanel/CategoryManager/KnowledgeDocCard/KnowledgeDocEditor/KnowledgeGraph）、`stores/knowledge.ts`、`utils/mock.ts`（此时唯一引用方已全部消失）、`i18n/{zh-CN,en-US}/knowledge.ts`。

**解耦 8 处**：router/index.ts:56-61 路由条目 + :105 routePageMap；ActivityBar.vue:33 注释入口行 + :26 iconMap.knowledge；AppShell.vue:37/:82 两映射表条目；navigation.ts:25 pageNames；funcGroup.ts:12,26,37（FuncGroupId 联合与初始 context）；types/index.ts:6 PageType 去 `'knowledge'`；RightPanel.vue:23 panelTitleKeys；i18n index.ts:15,46 注册行 ×2 + nav.ts:9 `nav.knowledge` + shell.ts:49 `shell.activityBar.knowledge`。

**注意**：`visualization.ts:34` 的 `knowledge:'知识点'`（图例）与 `analysis.ts:161` `extractKnowledge`（分析页键）**非**页面耦合，保留。
**验证**：附录 A3 零命中；`/knowledge` 路由 404（如需行为断言）；type-check/vitest 绿。

### K5 web-core 两件 + 空目录 + 收口

**删除**：`utils/fileColors.ts` + `tests/fileColors.test.ts`；`types/zmq.ts`；`apps/{chat,docs,architect}/server/`（git rm .gitkeep ×3）。
**验证**：附录 A4/A5；打包抽验 `python -m build --wheel`（architect）无 server/ 条目。

## 5. 测试计划

- 每批 commit 前后各跑一次该批影响面：K1 → `pytest apps/architect/tests -q`（1102 例含 monkeypatch 接缝迁移正确性）；K2~K4 → `npm run type-check` + 各 app vitest；K5 → web-core vitest
- 收口全量：`npm run test:py && npm run test:fe`；lint 允许存量红灯但**问题数不得净增**（记录前后数）
- 行为抽查：`/knowledge` 路由 404、workbench 主功能冒烟（登录/项目列表/图渲染）

## 6. 验收门禁（对 milestones §2-MS2 判据）

| # | 命令 | 预期 |
|---|---|---|
| 1 | `npm run type-check`；`npm run test:py`（architect 1102 例 + 其余域）；`npm run test:fe` | 全绿（lint 存量红灯豁免同 MS1，问题数净减不增） |
| 2 | 附录 A1~A5 零引用验证命令组 | 逐组零命中 |
| 3 | `git diff pre-MS2..HEAD --shortstat` + 分批 stat | 净减与 §4 清单一致（预计 ≈ −6,600 行 FE / −80 行 shim+引用改写 / 删 .gitkeep ×3） |

## 7. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| R1 shim 迁移破坏测试打桩接缝（28 处） | 每处按核证清单成对迁移；K1 独立 commit，跑全量 architect 测试 | revert K1 单 commit |
| R2 同名异物误删（TaskCard/ProjectList/KbQueryHistory） | 删除按完整路径执行；附录命令按路径匹配 | git checkout 恢复 |
| R3 KnowledgePage 退役误伤存活 i18n/类型 | F8 耦合清单逐处处理；visualization/analysis 键明确保留 | revert K4 |
| R4 类型清理引发连锁 type 错 | vue-tsc 即时捕获；类型删除放批末 | 补回类型定义 |
| R5 删除后出现新零引用孤儿（二级级联） | 收口时跑 `npx depcruise`/ts-prune 类扫描不可行（未安装）——以 vue-tsc noUnusedLocals 与 grep 抽查替代；发现的孤儿记 MS6 候选 | — |

## 8. commit 序列（每批独立可 revert）

| 序 | 内容 | 预估 |
|---|---|---|
| K1 | shim 八件套 + 69 处引用迁移 + golden 重生成 + docstring | 1d |
| K2 | architect 17+2 文件 + 类型清理 | 0.5d |
| K3 | workbench 5 文件 + alias ×3 配置 | 0.25d |
| K4 | KnowledgePage 集群 + 8 处解耦 + mock.ts | 0.75d |
| K5 | web-core ×2 + 空目录 ×3 + 收口验收回写 | 0.5d |

合计 ~3 人日。开工前 `git tag pre-MS2`。

---

## 附录：零引用验证命令组（收口时逐组执行，均应零命中）

```bash
# A1 architect 前端死码（K2 后）
grep -rn --exclude-dir=node_modules --exclude-dir=dist -e "asset-validator" -e "blueprint-agent" -e "extract-service" -e "guide-patterns" -e "mainkb-service" -e "collaboration-store" -e "git-sync-store" -e "kb-query-store" -e "kb-query-agent" -e "BaselineSummaryBar" -e "ComponentListView" -e "KbQueryView" -e "PseudoExplainer" -e "DesignPanel" -e "ProjectSetupDialog" -e "AssetDetailModal" -e "ScopeProposalModal" -e "design-service" apps packages

# A2 workbench 死码（K3 后；路径精确匹配防同名异物）
grep -rn --exclude-dir=node_modules --exclude-dir=dist -e "agent-usage-store" -e "plugin-store" -e "components/analysis/TaskCard" -e "components/project/ProjectList" -e "constants/providers" -e "@topo-animation" apps packages

# A3 KnowledgePage 集群（K4 后）
grep -rn --exclude-dir=node_modules --exclude-dir=dist -e "KnowledgePage" -e "'/knowledge'" -e "utils/mock" -e "stores/knowledge" apps packages
grep -rn --exclude-dir=node_modules --exclude-dir=dist -e "nav.knowledge" -e "activityBar.knowledge" apps/workbench/src

# A4 web-core（K5 后）
grep -rn --exclude-dir=node_modules --exclude-dir=dist -e "fileColors" -e "types/zmq" apps packages

# A5 后端 shim + 空目录（K1/K5 后）
grep -rnIE "arch_routes[./](adaptation|capability_mining|context_registry|evaluator|llm_dataset|model_profile|prompt_registry|ws_events)" --include='*.py' apps packages
grep -rnI -e 'apps/chat/server' -e 'apps/docs/server' -e 'apps/architect/server' --exclude-dir=.git --exclude-dir=node_modules .
git ls-files apps/chat/server apps/docs/server apps/architect/server
```
