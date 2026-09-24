# KB 组件体系统一方案：双线划分结果对齐合并

> 状态：**设计定稿；Stage 0~4 已完成（产出方引擎 + 口径切换 + 后端消费端 + 前端收敛，typecheck 零错）；待 Stage 5 清理勾稽**
> 日期：2026-09-06　|　验证样本：6 项目（nginx-C / JS-TS / Java / Python / 小型×2），四语言四形态
> 关联文档：[architecture-issues-0905.md](archive/architecture-issues-0905.md)（已归档，蓝图由 [0924 重构方案](../architecture-refactor-plan-20260924.md) 承接）、[architecture-issues-0902.md](archive/architecture-issues-0902.md)（已归档）

---

## 0. 已拍板的约束

1. **依赖与调用保持分别提取、分别分析**——两条原始检测线保留，各自完整的社区分析流程与算法不变；
2. **合并发生在"划分结果层"**——UNIFIED 是对两线社区划分结果的合并产物，逐层（L0→L5）处理；**不新增 AST/边层面的 UNIFIED 存储**（`graph_edge` 仍只有 imports/calls 两类）；
3. **旧数据不做兼容，直接清除重算**——无回退链、无迁移层；
4. **KB 只有一套组件**：INCLUDE/CALL 划分继续计算并落库，但**止步于算法层**——不产生 LLM 命名/摘要、不对任何消费面交付，仅作合并输入与证据层；
5. **合并在前，LLM 语义在后**：仅对 UNIFIED 组件跑 LLM 命名/摘要，LLM 成本相对双线严格减半；
6. **对齐参数**：τ=0.9、τ_lo=0.6（可配置）；打分等权 s_inc=s_call=1，调用边在**文件对级别二值化**（存在任意调用=1），与 import 边同粒度；
7. **Phase 0 已裁决的数据决策**：消费顺序 A_first（双序对照零差异）；τ_lo=0.6（0.7 破帕累托）；F2 按 |K| 归一化不启用（基础件豁免已消除偏袒）；密度归一权重为可选策略（方向性偏移向更密线，非普适改善）；rI/rC 分母保留落库口径（HUB 落库后复验）。

---

## 1. 现状摘要

### 1.1 检测层
- `analyze_communities(task_id, store, edge_type, min_node_cnt)` 每次只处理一线（`community_analysis.py:44`）：INCLUDE=`graph_edge.kind='imports'`→文件级图，min_node_cnt=6（`config.py:55`）；CALL=`kind='calls'`→聚合文件级（剔同文件），min_node_cnt=12（`config.py:56`）。
- Step5 先 INCLUDE 后 CALL（`analyst_runner.py:934-975`）；增量两线全量重跑（`incremental_runner.py:299-300`）。
- L0~L5 递归、HUB/ORPHAN 过滤、单子社区 Jaccard 去重、质量分两线对称共用。

### 1.2 数据层
- 按 edge_type 分裂的表：`graph_doc`、`community_hierarchy`、`community_llm_results`、`report_subdocs`、`graph_node_positions`（CHECK 限定 4 值）、`community_overrides`（预留未用）、`arch_snapshot_communities`、docs 私有 `web_graph_layout`。
- comm_id 前缀 `incl`/`call` 是贯穿全栈的隐式线标识，后端 7+ 处从 ID 反解（`task_manager.py:3337`、`tool_factory.py:307`、`community_data.py:29` 等）。

### 1.3 消费层（三种不一致姿态）
| 消费方 | 姿态 | 默认线 |
|---|---|---|
| workbench 前端 | 显式切换（四 tab），双线全量并行加载同屏 | INCLUDE |
| docs | 前端默认 INCLUDE，后端 7 路由默认 CALL（`viewer.py:68,110,179,201,239,473,495`） | 打架 |
| chat 工具 | 默认 CALL + comm_id 推断兜底；知识搜索无 edge_type 过滤 | CALL |
| architect | catalog 双线合并去重；architecture.model 及全部下游单线 INCLUDE L1 | 分裂 |
| 语义资产层（sem） | 收敛先例：资产身份=代码锚点，跨线去重只存一份 | 线无关 |

### 1.4 双线并存的代价
1. 两套组件名、用户认知分裂；子文档"依赖/调用"两组子组件链接；
2. LLM 成本翻倍（每层双线取件 `tool_factory.py:531-533`）；
3. 默认口径打架 → 静默换线 bug（`knowledge.py:177` 要 CALL 实际走 INCLUDE，`task_manager.py:1797`）；
4. architect 线漂移（ComponentPicker 选到 CALL 组件在 INCLUDE 消费点未命中）；
5. 知识检索噪音（两线报告成对出现）；
6. comm_id 前缀反解协议脆弱；
7. 检测层暗病：CALL"同文件降权备选"为无效重跑（`intra_file_weight` 从未被读取，备选分支 `community_analysis.py:136-182` 与首跑参数等价）；incremental 未传 min_node_cnt（默认 10 vs 全量 6/12）。

---

## 2. 合并方法选型

| 方法 | 原理 | 结论 |
|---|---|---|
| A. 边级加权融合 | imports/calls 合并加权图直接检测 | ❌ 边密度悬殊，权重无原则可循 |
| B. 协同矩阵共识 | 跨线投票建协同图重新聚类 | ❌ 机制复杂；合成图社区不可解释；质量无先验保障 |
| C. 主从树对齐 | 单侧为主，另一侧拆合校验 | ❌ 非对称即选边站队 |
| **E. 结果层对齐合并** | 两线划分逐层双向匹配：等价合并/包含拆分/弱并/争议仲裁 | ✅ **采纳**——证据可审计、无合成图、确定性可复现、复用两线现有算法产出 |

---

## 3. 对齐合并详设（方法 E：五张封闭表）

记号：社区对 (I ∈ INCLUDE线, C ∈ CALL线)，rI = |I∩C|/|I|，rC = |I∩C|/|C|；τ=0.9，τ_lo=0.6。
rI/rC 在各自 HUB/ORPHAN 过滤后的落库成员集上度量（HUB 集差异会低估重合度；生产补落 HUB 后复验，必要时切换过滤前全集口径）。

### 3.1 表 A：社区对关系判定（(rI, rC) 平面完备划分）

| 区域 | 条件 | 关系判定 | 结构动作 |
|---|---|---|---|
| **A 等价** | rI ≥ τ ∧ rC ≥ τ | 两线结构认知一致 | I、C 合并为一个新组件（证据 BOTH） |
| **B C 含于 I** | rC ≥ τ ∧ rI < τ | C 是 I 的子结构 | C 作为基础件；I 待拆解，独有成员进仲裁池 |
| **C I 含于 C** | rI ≥ τ ∧ rC < τ | 对称 | I 作为基础件；C 待拆解 |
| **D1 弱相关** | τ_lo ≤ min(rI,rC) < τ | 两线结构部分一致 | P2.5 并集合并（证据 WEAK） |
| **D2 无关系** | min(rI,rC) < τ_lo | 确无结构关系 | 双方独立候选，交集文件按 F2 仲裁 |

### 3.2 表 B：消费顺序

| 优先级 | 处理对象 | 规则 |
|---|---|---|
| P1 | 区域 A 社区对 | 按 score=min(rI,rC) 降序贪心；双方消耗后退出后续配对；被作废的 B/C 配对中基础件一方保留资格（**R-void**） |
| P2 | 未消耗社区的区域 B/C 对 | 基础件消耗；容器解散拆解（同容器多基础件 → 拆为多个新组件）；**残余走 R-resid（3.3.1）**；被消耗社区参与的其余配对作废 |
| P2.5 | 未消耗社区间的 D1 对 | 按 min(rI,rC) 降序；双方均未消耗 → 并集合并（证据 WEAK）；一方已消耗则作废 |
| P3 | 仍未消耗的社区 | 独立候选（证据=单线）；成员 < min_node_cnt 解散进仲裁池 |

平局链：score 相同 → 成员多者 → comm_id 字典序。

**R-void（作废基础件资格保留）**：社区经 A-对消费时，其被作废 B/C 配对的基础件一方仍以 P3 独立候选存活，成员在 F2 仲裁中享与正式基础件同等豁免——等价合并不吞掉子结构信号。作废基础件与 A-对伙伴同线互斥，无双重豁免冲突。

### 3.3 表 C：文件归属仲裁（每文件恰属一个新组件）

```
score(f, K) = s_inc × |{k ∈ K : f↔k 有 import 边}| + s_call × |{k ∈ K : f↔k 有 call 边}|
（调用边文件对二值化；s_inc = s_call = 1）
```

| 状态 | 文件处境 | 归属策略 |
|---|---|---|
| F1 | 仅属一个存活社区/基础件 | 随社区，确定性 |
| F2 | 属于多个候选/新组件 | **前置**：候选含基础件（含 R-void 保留资格者）→ 随基础件；否则 score 最高者胜。平局链：基础件衍生 → BOTH → WEAK → 成员多 → 字典序 |
| F3 | 所属社区已解散且未成为基础件 | 进仲裁池：score>0 取最高；全 0 → **F3-bis 强制归入级联（3.3.2）** |
| F4 | 仅出现在一条线 | 同 F1/F3（随其线），证据记单线 |
| F5 | 两线均无社区 | HUB 取并集（任一线 HUB 即 HUB）；ORPHAN 对 L0 组件评 score>0 归入 |
| F6 | 子层社区跨父边界 | **裁剪至父成员集交集**；≥ min_node_cnt 参与该层（rI/rC 以裁剪后集合为分母）；不足 → 视为未出现，成员走 F1/F3 |

### 3.3.1 R-resid 条件残余（容器解散规则）

容器解散时残余默认进仲裁池；但池质量远大于组件质量时 F3 打分崩溃（Java 实测：池 1064 文件中 747 零邻接 → 未分配 36%）。残余满足**全部**条件时整体成组（证据=容器所属线）而非进池：

```
1. |leftover| ≥ min_node_cnt
2. leftover 中与「全部潜在组件成员」（已形成组件 + 未消耗候选，
   排除自身）存在任一邻接的文件 < 50%
```

实测：Java 未分配 36%→6.7%、Qinc 比 0.56→0.90；nginx 未分配减半且结构零变化；JS/Python 零触发。

### 3.3.2 F3-bis 强制归入级联（覆盖率 100% 保证）

池文件全零分时不终态 ORPHAN，按信号强度递降级联归入：

| 级 | 策略 | 信号依据 |
|---|---|---|
| 1 | 边数仲裁（F3 原规则） | 直接结构证据 |
| 2 | **出身多数**：来源社区其他已分配成员的多数归属 | 来源社区身份 |
| 3 | **邻居跟随**：双线邻接中已分配成员的多数归属（一跳） | 直接图结构 |
| 2↔3 | **迭代至不动点**（池是连通簇，逐波吸附） | 传染式扩散 |
| 4 | **池级残余成组**：≥ min_node 且内部连通的来源群体 → 独立成组（证据 **FORCED**） | 群体自身内聚 |
| 5 | **终极兜底**：同目录已分配文件目录多数 → 否则最大组件 | 源码树局部性（保证 100%） |

确定性：排序遍历 + 平局链。实测六项目未分配全部归零，质量零劣化、普遍微升（Java Qcall 比 0.63→0.71、存活率 0.84→0.92）。FORCED 组件与兜底文件（`forced='dir'|'largest'`）在证据明细可追溯。关闭级联时退回"UNASSIGNED 终态 ORPHAN"。

### 3.4 表 D：逐层流程（L0 → L5）

| 步骤 | 动作 | 出口 |
|---|---|---|
| D1 | 父范围过滤（F6 裁剪），确定本层两线候选集 | — |
| D2 | 表 A 判定 → 表 B 消费 → 形成新组件 | E4：< min_node_cnt 解散 |
| D3 | 文件落位：F1/F2 定属；F3/F4 解散侧 → 仲裁池 | — |
| D4 | 仲裁池评分归组，余量 → **F3-bis 级联** | 覆盖率 100%；级联关闭时余量 → 该层 ORPHAN 终态，不流入子层 |
| D5 | 每个新组件限定成员集递归 D1–D4，至 L5 或无子社区 | — |

### 3.5 表 E：边界/退化场景

| 场景 | 行为 |
|---|---|
| E1 CALL L0 超连通（1 巨社区，质量分<0.01） | 无需特判：巨社区对每个 incl 有 rI=1、rC≈0 → 全落区域 C，自动按 INCLUDE 社区拆解（日志标注）。六项目未触发 |
| E2 两线层数不同 | 处理至 max(两线深度)；某线该层无社区 → 另一线全为独立候选 |
| E3 同线同层成员重叠（不应发生） | 防御断言，告警并取并集 |
| E4 新组件/候选 < min_node_cnt | 解散，成员进仲裁池 |
| E5 UNIFIED 独立阈值 | `COMMUNITY_MIN_NODE_UNIFIED` 默认 **6**（不复用 6/12，顺带修 incremental 默认 10 漂移） |
| E6 争议平局且零边 | 平局链兜底，全流程确定性 |

---

## 4. LLM 语义管线与增量身份

- **流程**：双线划分（零 LLM）→ 表 A–E 合并 → UNIFIED 树 → 仅对 UNIFIED 跑 LLM 命名/摘要。
- **命名层级范围**：Stage 1 按现有全层命名实现 UNIFIED 取件（行为对齐）；Stage 3 消费面清查后定收敛范围——仅 L1 有下游消费 → 收敛 L1（消除 stable_key 级联失效）。
- 两线不再产生 `community_llm_results` 记录——LLM 成本减半的直接来源。
- **stable_key**（成员文件排序哈希）仅挂 UNIFIED：成员未变的组件增量重跑时复用 LLM 结果；覆盖全量与增量两路径。
- 证据指标：`inc_density`、`call_density`、`agree_ratio`；F4/F5 文件记录 `hub_in` 出身；F3-bis 兜底记录 `forced`。
- comm_id：`comm-{task}-uni-{level}-{i}`；`_infer_edge_type` 增加 `uni→UNIFIED`。

---

## 5. 数据模型

- **UNIFIED 仅存在于划分结果层**：`graph_doc`、`community_hierarchy`、`community_llm_results`（TEXT 列）、`report_subdocs`、`graph_node_positions`（CHECK 增加 UNIFIED）。`graph_edge` 不新增类型。
- **"社区三表" = `community_hierarchy` + `community_llm_results` + `graph_doc`。**

**清库重算逐表处置表**：

| 存储 | 处置 |
|---|---|
| community_hierarchy | 全清重建：INCLUDE/CALL 照常重算（算法层留档），UNIFIED 为交付层 |
| community_llm_results | 全清；此后仅 UNIFIED 写入 |
| graph_doc | 全清重建（同 hierarchy 口径） |
| report_subdocs | 全清，按 UNIFIED 重新生成 |
| graph_node_positions | DROP/CREATE（CHECK 增加 UNIFIED） |
| arch_snapshot_communities | 全清，此后快照仅截 UNIFIED。**既有基线对比历史作废，发布说明须明示** |
| web_graph_layout（docs 私有） | 全清 |
| community_overrides | DROP（预留未用，随 Stage 5 废弃） |
| knowledge_docs | **不动**（用户文档） |

---

## 6. 质量指标与 Phase 0 验证（✅ 6 项目通过）

验证脚本 `scripts/unified_merge_eval.py`（仅 stdlib，不改生产代码）。样本：nginx-C 337 文件 / JS-TS 632 / Java 2037 / Python 1909 / 小型×2，覆盖四种结构形态（双线对等分歧 / 粗细错配半覆盖 / CALL 极低覆盖 / 双线均衡深递归）。

**Gate 裁决**：固定"双侧模块度比 ≥70%"证伪——交叉天花板显示单取任一线当 UNIFIED，另一侧 Q 比仅 0.26~0.68（两线结构分歧是客观属性）。**正式 gate 为帕累托占优**：

| 指标 | 通过标准 | 实测 |
|---|---|---|
| **帕累托 vs 交叉天花板** | Q_inc(U) 比 ≥ CALL 划分在 inc 图 Q 比，且 Q_call(U) 比 ≥ INCLUDE 划分在 call 图 Q 比 | 6/6 主跑通过；边界扫描 22/24（唯 nginx τ_lo=0.7 破 → 0.6 定版） |
| 未分配率 / 覆盖率损失 | = 0（F3-bis 开启） | 6/6 = 0%（原 0~9.5% 全部消除） |
| 小组件存活率 | ≥30% | 6/6（0.65~0.92） |
| 组件数粒度 | 介于两线 L0 组件数之间（"vs INCLUDE ×0.5~1.5"证伪） | 6/6 落于两线之间 |
| 确定性 | 双跑逐字节 diff | 6/6 通过 |
| τ / τ_lo / 消费顺序扫描 | 结构稳定 | τ∈[0.8,0.9] 稳健（0.95 劣化）；顺序 6/6 零差异 |
| E1 巨社区退化 | 记录评审 | 未触发（样本无巨社区，特判扩展位保留） |
| L1 抽样人工比对 | 成员 vs 目录结构 | ⏳ Stage 1 验收时执行 |

诊断指标（常驻输出，不设红线）：线间 NMI（0.55~0.88）、交叉天花板（−0.07~0.68）、证据分布、单线率（34~95%）、HUB 差异率（待 HUB 落库）。
不达标 → 回本文档修订合并规则，重新过 gate。

---

## 7. 改造计划（按依赖顺序五阶段）

### 7.0 总原则

1. **依赖顺序**：产出方（KB 构建）→ 口径切换点（接口默认层）→ 消费端后端 → 消费端前端 → 清理；每阶段独立验收，默认值切换点集中、可回滚。
2. **双线基础数据永久保留**：`graph_edge`（imports/calls）、`call_chains`、两线算法社区划分照常产出落库；`get_dep_edges`/`get_call_edges` 等原始数据接口不变。**各类分析与 agent 的 skills/tools calling（知识检索、调用链查询、依赖分析）继续依赖原始数据，不随组件口径切换受影响**——切换仅改变"组件划分"的交付口径，不删除任何原始数据与数据接口。
3. 旧数据清库重算，无兼容层（§5 处置表）。

### 7.1 消费面清单（逐文件触点，已核实）

**A. KB 构建层（产出方）**
- `plugins/community/community_analysis.py`（引擎 + 删 intra_file_weight 死代码与 CALL 备选空转分支）
- 新增 `plugins/community/unified_merge.py`（表 A–E + R-void/R-resid/F3-bis）
- `engine/analyst_runner.py`（Step5 三段式）、`engine/incremental_runner.py`（增量接线 + min_node_cnt 漂移）
- `agent/agent_workflow/tool_factory.py`（**LLM 取件收敛**：`_pipeline_get_level_components` 双线遍历 → 仅 UNIFIED，属分析管线）
- `engine/store/analysis_store.py`（HUB/ORPHAN 成功路径落库）
- `db/manager.py`（**schema 预备**：`graph_node_positions` CHECK 扩 UNIFIED——Stage 1 产出写入前必须就绪）
- config（§9 参数键）

**B. 口径切换点（接口默认层）**
- `engine/task_manager.py`（RPC 默认值、:1797 默认线、:3337 前缀反解）
- `engine/community_data.py`（`_infer_edge_type` 增 uni、默认查询）
- `engine/analysis_context.py`（project/community layer 默认）
- `engine/service/project.py`（overview/external_stats/热力图）

**C. 下游后端消费端**
- docs：`apps/docs/topoone_app_docs/viewer.py`（7 路由默认 CALL→UNIFIED）
- chat/agent：`apps/chat/topoone_app_chat/web_tools.py`（默认线、推断兜底、检索过滤）、`agent/agent_workflow/tool_factory.py`（:307 前缀反解、agent 工具默认线——LLM 取件部分已随 Stage 1）、`toolkits/graph_tools.py`、`tools_executor.py`、`tagent_host.py`、`worker.py`、`router.py`
- architect 后端：`arch_routes/knowledge.py`（:177 改 UNIFIED 归组直查 calls）、`engine/architecture_model_service.py`（INCLUDE L1→UNIFIED L1）、`arch_routes/req_agent.py`、`asset_skill.py`、`asset_framework.py`、`common.py`（catalog 双线合并去重 → 单套）
- 其他后端：`analysis_utils.py`、`report_tree_service.py`、`report_service.py`、`version_sync_service.py`、`ingest/consumer.py`、`service/version.py`、`service_common.py`、`supervisor/cli.py`、`db/data_layer/duckdb_reader.py`（schema 预备已随 Stage 1）

**D. 前端消费端**
- workbench：`stores/community-store.ts`（双线加载→单线）、CommunityArchitecturePanel（四 tab →「组件/外部依赖/外部调用」）、SubDocViewer（双组链接→单组）、`components/ai/AIAssistantPanel.vue`（删 `--include/--call`）、`utils/communityLabel.ts`、`stores/report-store.ts`、`pages/CodePage.vue`、`pages/AnalysisPage.vue`、`llmClient.ts`
- docs：`pages/DocViewer.vue`、`composables/useDocState.ts`、`composables/useGraphState.ts`（etOptions 简化，默认 UNIFIED）
- architect 前端：ComponentPicker（移除线筛选、徽章改 inc/call 密度证据）、组件树/需求 agent 消费点
- 横切：`rpc-method-baseline.json` 重生成、CONV 规约更新

### 7.2 阶段表（严格按依赖顺序执行）

| 阶段 | 内容 | 依赖 | 出口标准 |
|---|---|---|---|
| **Stage 0 安全网** | 分析管线集成测试（0905 文档 A1）；留存 6 项目现有分析产物作对照基线 | — | 测试可跑 |
| **Stage 1 产出方** | schema 预备（positions CHECK 扩 UNIFIED）；`unified_merge.py` + `analyze_unified`；Step5 与增量路径改三段式（INCLUDE→CALL→UNIFIED）；`tool_factory` LLM 取件收敛至 UNIFIED（全层命名）；HUB/ORPHAN 落库；删死代码；config 六键（§9） | Stage 0 | 新分析任务产出 UNIFIED 树；双跑 diff 空；两线照常落库且零 LLM 记录；L1 人工比对过 |
| **Stage 2 口径切换** | B 层默认值 → UNIFIED；`_infer_edge_type` 增 uni；`analysis.rebuildUnified` 清库重算入口（按 §5 处置表，触发全部项目重跑）。**内部顺序：先重算完成、后切默认值**（或同批按项目粒度灰度），避免消费面读到空 UNIFIED | Stage 1 | 新 RPC 面只交付 UNIFIED；RPC 回归过；各项目 UNIFIED 树就绪 |
| **Stage 3 消费端后端** | C 组逐个改造：docs viewer → chat web_tools/graph_tools/tool_factory → architect knowledge/architecture_model/catalog/req_agent → analysis_utils/report_*/version_*；**原始数据接口与 agent 工具的底层查询不动，仅组件口径参数换 UNIFIED**；**LLM 命名层级清查**（消费面盘点更深层名称消费点 → 决定收敛 L1 或保留全层） | Stage 2 | 各后端 smoke 通过；agent skills/tools 全量回归（应零破坏）；命名层级决策落定 |
| **Stage 4 前端** | workbench → docs → architect 前端（依赖 Stage 2/3 新默认） | Stage 3 | 用户只见一套组件；三应用 typecheck + 构建过 |
| **Stage 5 清理** | 死代码、community_overrides DROP、rpc-method-baseline 重生成、CONV 规约、0905 文档勾稽 | Stage 4 | 文档-代码一致 |

### 7.3 工作量

Stage 1 约 3-4 人日；Stage 2 约 2-3 人日；Stage 3 约 4-5 人日（消费端 27 文件逐个适配）；Stage 4 约 4-5 人日；Stage 5 约 1-2 人日。**合计 14-19 人日**。

---

## 8. 风险表

| 风险 | 缓解 | 状态 |
|---|---|---|
| 合并质量上限受两线质量约束 | 帕累托 gate（vs 交叉天花板） | **已验证 6/6** |
| 仲裁对 τ/权重敏感 | 扫描完成；参数配置化；顺序零敏感 | **已验证** |
| F2 富者愈富 | 基础件豁免 + R-void；存活率 65~92% | **已验证** |
| 池崩溃（池质量≫组件质量） | R-resid（Java 36%→6.7%）+ F3-bis（→0%） | **已消除** |
| 合并覆盖率损失 | F3-bis 级联（0~9.5% → 全部 0%，质量零劣化） | **已消除** |
| 两线全集差异低估重合度 | 单线率已度量；过滤前全集口径备选 | 度量完成，切换未触发 |
| E1 巨社区退化 | 六项目未触发；表 E 保留特判扩展位 | 遗留观察 |
| 增量抖动 → LLM 全量重跑 | stable_key（仅挂 UNIFIED，覆盖两路径） | 实施项 |
| LLM 层级收敛 UX 回归 | Stage 3 清查后决策；Stage 1 全层命名 | 实施项 |
| `uni` 前缀切换遗漏 → 静默错线 | Stage 2/3 逐点清单核销（§7.1 已枚举） | 实施项 |
| HUB 不落库 → F5/HUB 差异率无法验证 | Stage 1 补落库 | 实施项 |
| 消费端漏改（27+16 触点） | §7.1 逐文件清单 + Stage 3/4 逐个核销 + agent 工具全量回归 | 已核销 |
| 框架宿主项目（如 Spring）覆盖率天然偏低 | 初判"提取层无缺陷"后经系统排查被推翻：解析引擎存在 6 处缺陷（Java 点分 import 失配/静态类调用无策略/参数无 variable 节点/函数体不分发变量提取/组合名被 export 守卫拦截/kotlin import+body 字段错位），已全部修复（resolver.py/walker.py + ts/py/kotlin/go 钩子）。修复后 calls 解析率：Java 39→55%、TS 52→57%、PY 51→57%、Go 42→50%；覆盖边界仍由 P3 显式暴露 | 已修复（2026-09-06） |

---

## 9. 参数与待定项

**已定（Phase 0 裁决）**：τ=0.9、τ_lo=0.6、s_inc=s_call=1 等权默认（密度归一可选）、`COMMUNITY_MIN_NODE_UNIFIED`=6、A_first、F2 归一化不启用、清库范围（§5）、两线止步算法层、合并在前 LLM 在后、帕累托 gate、R-void/R-resid/F3-bis。

**config 键（Stage 1 落地）**：
| 键 | 默认值 | 说明 |
|---|---|---|
| `COMMUNITY_UNIFIED_TAU` | 0.9 | 强阈值 τ |
| `COMMUNITY_UNIFIED_TAU_LO` | 0.6 | 弱阈值 τ_lo（D1 弱并） |
| `COMMUNITY_UNIFIED_SCORE_INC` / `COMMUNITY_UNIFIED_SCORE_CALL` | 1.0 / 1.0 | 打分权重（密度归一时按两线文件对数比设置） |
| `COMMUNITY_MIN_NODE_UNIFIED` | 6 | UNIFIED 独立最小节点数 |
| `COMMUNITY_UNIFIED_FORCE_ASSIGN` | on | F3-bis 强制归入级联开关（关闭退回 ORPHAN 终态） |

**Stage 1 实施项**：HUB/ORPHAN 落库；L1 抽样人工比对。
**Stage 3 清查决策（已裁决）**：LLM 命名**保留全层**——`llm/context/ingredients/parent_chain.py` 消费更深层名称（agent 父链上下文），收敛 L1 会造成上下文回归；stable_key 级联以增量触发频率观察。
**待定**：是否保留"双视角对比"研究视图（若需，另立需求）。
