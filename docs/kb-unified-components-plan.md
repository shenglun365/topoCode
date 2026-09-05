# KB 组件体系统一方案：双线社区划分合并（待评审）

> 状态：**方案记录，未批准实施** —— 待进一步评估后决策
> 日期：2026-09-05
> 范围：KB 社区分析（INCLUDE/CALL 双线）→ 统一组件交付；影响 workbench / docs / chat / architect 全部消费面
> 关联文档：[architecture-issues-0905.md](architecture-issues-0905.md)（架构优化总表）、[architecture-issues.md](architecture-issues.md)（0902 评估）

---

## 0. 已拍板的约束（决策输入）

1. **依赖与调用保持分别提取、分别分析**——两条原始检测线保留；
2. **合并发生在"划分结果层"**——对两组社区划分结果设计恰当的合并方法（不走边级加权融合，原因：依赖/调用的边级权重难以设计，此前未找到合适的算法与参数配置）；
3. **旧数据不做兼容，直接清除重算**——无回退链、无迁移层；
4. 最终 KB 组件关系交付、LLM 语义、对 architect 的数据支撑，**只有一套组件**。

---

## 1. 现状调研摘要（双线机制全貌）

### 1.1 检测层
- `analyze_communities(task_id, store, edge_type, min_node_cnt)` 每次只处理一线（`community_analysis.py:44`）：
  - INCLUDE：`graph_edge.kind='imports'` → 文件级图，min_node_cnt=6（`config.py:55`）；
  - CALL：`kind='calls'` → 聚合到文件级（剔同文件调用），min_node_cnt=12（`config.py:56`）。
- Step5 先 INCLUDE 后 CALL 各跑一遍（`analyst_runner.py:934-975`）；增量重算两线全量重跑（`incremental_runner.py:299-300`）。
- L0~L5 递归、HUB/ORPHAN 过滤、单子社区 Jaccard 去重、质量分（模块度）两条线完全对称共用。

### 1.2 数据层
- 按 edge_type 分裂的表：`graph_doc`、`community_hierarchy`、`community_llm_results`（UNIQUE 四元组含 edge_type）、`report_subdocs`、`graph_node_positions`（CHECK 限定 4 值）、`community_overrides`（预留未用）、`arch_snapshot_communities`、docs 私有 `web_graph_layout`。
- **comm_id 前缀 `incl`/`call` 成为贯穿全栈的隐式线标识**，后端 7+ 处从 ID 反解线归属（`task_manager.py:3337`、`tool_factory.py:307`、`community_data.py:29` 等）。

### 1.3 消费层（三种不一致姿态）
| 消费方 | 姿态 | 默认线 |
|---|---|---|
| workbench 前端 | 显式切换（四 tab），双线数据全量并行加载同屏 | INCLUDE |
| docs | 前端默认 INCLUDE，**后端 7 个路由默认 CALL**（`viewer.py:68,110,179,201,239,473,495`） | 打架 |
| chat 工具 | 默认 CALL + comm_id 推断兜底；知识搜索**无 edge_type 过滤** | CALL |
| architect | catalog 双线合并去重；architecture.model 及全部下游（需求 agent/design/compare/arch_change/基线）**单线 INCLUDE L1** | 分裂 |
| 语义资产层（sem） | **收敛先例**：资产身份=代码锚点，跨线去重只存一份（`sem/engine.py:972-973`） | 线无关 |

### 1.4 双线并存的代价
1. **两套组件名、用户认知分裂**：同一批代码两份 LLM 名称/摘要；子文档"依赖/调用"两组子组件链接。
2. **LLM 成本翻倍**：管线每层 INCLUDE→CALL 双线取件（`tool_factory.py:531-533`）；AI `/analyze` 无选择时两线全量。
3. **默认口径四处打架 → 已有静默换线 bug**：`knowledge.py:177` 要 CALL 跨社区边，实际走 INCLUDE 默认（`task_manager.py:1797`）。
4. **architect 线漂移**：ComponentPicker 双线 catalog，选到 CALL 组件在单线 INCLUDE 消费点可能未命中。
5. **知识检索噪音**：两线报告成对出现（`web_tools.py:1537-1555`）。
6. **隐式协议脆弱**：comm_id 前缀反解遍布全栈。
7. **检测层既有暗病**：CALL"同文件降权备选方案"是死代码（`intra_file_weight` 参数从未被读取）；incremental 未传 min_node_cnt（默认 10 vs 全量 6/12，粒度漂移）。

---

## 2. 合并方法选型

| 方法 | 原理 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| A. 边级加权融合 | imports/calls 边合并加权图直接检测 | 单次检测 | 两线边密度差异悬殊（调用图远密于依赖图），w(include)/w(call) 无原则可循 | ❌ 已否决（决策输入 2） |
| **B. 协同矩阵共识**（co-association consensus） | 每线对每对文件投一票"是否同社区"，得一致性权重图，在其上重新聚类 | 密度差异被归一化；集成聚类理论支撑；**复用现有 Leiden/Louvain 检测器**；参数极少且可解释 | O(同社区文件对) 内存需稀疏化；层级需逐层构建 | ✅ **推荐** |
| C. 主从树对齐 | 选一条线为骨架，另一线做拆分/合并校验（Jaccard 匹配 → split/merge） | 直观、保主树形状 | 非对称——实质"选边站队"，重新引入两线之争；拆合规则本身要调参 | ⚠️ 保底方案 |
| D. 求交细化 | 组件 = 两线社区非空交集 | 实现最简 | 严重碎片化，须再接合并回填（绕回 B） | ❌ 不可单独用 |

---

## 3. 推荐方法：双层投票共识划分（方法 B 详设）

### 3.1 核心机制

```
第一步（输入选择）：每条线取"有信息量"的划分层
  P_inc*  = INCLUDE 线在层级 k_inc 的划分（k 自动选择，见 3.3）
  P_call* = CALL   线在层级 k_call 的划分

第二步（投票建图）：
  对每对文件 (i,j)，若在任一线中同社区，连边：
    w(i,j) = s_inc · [i,j 同社区 in P_inc*] + s_call · [i,j 同社区 in P_call*]
  默认 s_inc = s_call = 1（两线等权投票）
  边上记录证据来源 {INC, CALL, BOTH}（供组件证据指标）

第三步（共识检测）：
  在协同图上跑现有检测器（Leiden/Louvain，激活 weights 参数）→ UNIFIED L0

第四步（递归细化 L1~L5）：
  对每个 UNIFIED 社区：把两线划分限制到该社区文件子集，
  重建子协同图 → 检测 → 子社区；
  复用现有 min_node_cnt 递归终止、单子社区 Jaccard 去重、质量分——全部原样复用
```

### 3.2 为什么避开了权重设计痛点

1. **票数归一化消灭密度差异**：边级融合时"一条 import 边抵几条 call 边"无解。投票法中每条线对每对文件只投一票，与该线内部边数（3 条还是 300 条）无关——密度差异进入权重前已被归一化。
2. **权重取值域极小**：边权只可能 {1, 2}（单线认可 / 双线认可）。检测器只需区分这两种信号，比连续权重鲁棒得多，无需调 α。
3. **唯一旋钮是两线票权 (s_inc, s_call)**，默认 (1,1)。若验证发现调用线噪声偏大，调 (1, 0.8) 是划分层面全局决策，可解释、可复盘。

### 3.3 输入层的自动选择（避免"巨社区票污染"）

CALL 线存在超级连通场景（L0 只得 1 社区，质量分 <0.01 已有检测分支）——该层"同社区"投票对全部文件对为真，零信息量。规则：

```
k = 每线自动选取满足「最大社区节点数 < 总节点数 × 50%」的最小层级
    （第一个"有区分度"的层；若都不满足，取社区数最多的层）
```

HUB/ORPHAN 文件：两线都被过滤 → 沿用特殊标记（union：任一线 HUB 即 HUB）；只在一线正常的文件 → 只投该线的票。

### 3.4 共识质量指标（Phase 0 验证 gate）

统一划分 U 相对**两个输入**同时度量：

| 指标 | 含义 | 通过标准（建议） |
|---|---|---|
| NMI(U, P_inc*) / NMI(U, P_call*) | U 与两线输入的一致性 | 两者均 ≥ 0.5 且差值 ≤ 0.25（防单线主导） |
| Q_inc(U) / Q_call(U) | U 在两张**原始图**上的模块度 | min(Q_inc, Q_call) ≥ 两线各自最优划分模块度的 70% |
| 组件数 / 层级深度 | 粒度 sanity | 与 INCLUDE 线同数量级（×0.5~1.5） |
| 抽样人工比对 | L1 组件成员 vs 目录结构 / LLM 命名合理性 | 3 个样本项目人工评审 |

NMI/ARI 用 numpy 手写（约 50 行，不引 sklearn）。**不达标 → 切方法 C（INCLUDE 主树 + CALL 拆合校验）重新过 gate**。

### 3.5 数据模型

- `edge_type='UNIFIED'`（三张核心表 TEXT 列无需改表）；comm_id：`comm-{task}-uni-{level}-{i}`；`_infer_edge_type` 增加 `uni→UNIFIED`。
- `community_hierarchy` 增加 `stable_key`（成员文件排序哈希）——增量重跑时成员未变的组件复用 LLM 结果（现有 comm_id 序号漂移会导致 LLM 结果全量失效，双线时代已有此暗病，交付单套后影响面放大，须一起修）。
- 每组件写入证据指标：`inc_density`（组件内 import 边密度）、`call_density`、`agree_ratio`（成员对双线同票占比）——供前端徽章与 architect 展示。
- `graph_node_positions` CHECK 增加 UNIFIED——**清库策略下直接 DROP/CREATE，免迁移脚本**。

---

## 4. 实施计划（旧数据清库重算，无兼容层）

| 阶段 | 内容 | 出口标准 | 工作量 |
|---|---|---|---|
| **Phase 0 共识验证**（硬 gate） | 独立脚本：3 个真实项目（小/中/大）→ 跑双线 → 共识合并 → 输出 3.4 全指标报告 + 票权不敏感性验证（(1,1) vs (1,0.8)） | 指标达标进 Phase 1；不达标切方法 C 重过 gate | 2-3 天 |
| **Phase 1 检测层** | `_detect_communities` 激活 weights（Leiden `weights=` / Louvain `weight=`），删 `intra_file_weight` 死代码；新增 `analyze_unified(task_id, store)`；Step5 改 INCLUDE→CALL→UNIFIED(merge)；修 incremental min_node_cnt 漂移；config：`COMMUNITY_VOTE_INCLUDE/CALL`(默认 1/1)、`COMMUNITY_MIN_NODE_UNIFIED` | 新任务产出 UNIFIED 树 | 3-4 天 |
| **Phase 2 交付面统一** | 所有 edge_type 默认值 → UNIFIED（task_manager RPC、community_data、docs viewer、chat web_tools、architecture.model、catalog、tool_factory、analysis_context、overview）；**删除**两线回退/合并读取逻辑（无兼容包袱，清库策略最大简化点）；修 knowledge.py:177（核心流程改 `graph_edge kind='calls'` 按 UNIFIED 组件归组直查）；LLM 管线只跑 UNIFIED（成本减半）；external_stats/热力图挂 UNIFIED；清库重算入口 `analysis.rebuildUnified`（清社区三表 + LLM 结果 + positions + report_subdocs，触发全部项目重跑） | architect 全链路消费 UNIFIED；LLM 成本减半可观测 | 3-4 天 |
| **Phase 3 前端收敛** | workbench：CommunityArchitecturePanel 四 tab → 「组件 / 外部依赖 / 外部调用」，community-store 双线全量加载改单线，SubDocViewer 双组链接消失，AIAssistant 删 `--include/--call`；docs：etOptions 简化、默认 UNIFIED；chat：web_tools 默认 UNIFIED；architect：ComponentPicker 移除线筛选、徽章改证据指标（inc/call 密度），sem 引擎组件树天然统一 | 用户只见一套组件 | 4-5 天 |
| **Phase 4 清理与文档** | 删死代码（CommunitySection 遗留组件等）、重生成 `rpc-method-baseline.json`、CONV 规约更新、0905 文档勾稽 | 文档-代码一致 | 1-2 天 |

合计约 **14-18 人日**。前置依赖：Phase 1 前建议先完成 0905 文档 A1（分析管线集成测试，安全网）。

---

## 5. 风险表

| 风险 | 缓解 |
|---|---|
| 共识被粗线主导 / 指标不达标 | Phase 0 硬 gate + NMI 平衡性判据；保底方法 C |
| 协同图内存（同社区文件对爆炸） | 输入层自动选择（3.3）排除巨社区层；稀疏 dict；>5000 节点沿用 Label Propagation 分支 |
| 增量重跑组件树抖动 → LLM 全量重跑 | stable_key 成员哈希身份 |
| 大项目共识耗时 | 共识图边数 ≪ 两线原始边数之和（同社区对去重后）；Phase 0 大样本实测 |
| 两线检测信息量不足（某线划分质量差拖累共识） | 3.4 的 Q_inc/Q_call 双侧下限；极端时可对该线降票权 (s=0.8) 或剔除（退化为单线交付，需人工决策） |

---

## 6. 待确认假设（评审时逐条确认）

1. 两线原始检测结果**继续计算并落库**，但不对前端/architect 交付，仅作证据层；
2. 两线票权默认等权 (1,1)，不引入先验偏好；
3. "清除重算"范围 = 社区三表（graph_doc / community_hierarchy）+ community_llm_results + graph_node_positions + report_subdocs；用户文档 knowledge_docs 不动；
4. Phase 0 样本项目待定（建议：一个小型工具库、一个中型业务项目、一个大型开源项目）；
5. 前端不再暴露 INCLUDE/CALL 切换（若需保留"双视角对比"研究视图，另立需求）。

---

> 本文档仅为方案记录。是否实施、何时实施、采用方法 B 或保底方法 C，待评估后另行决策；批准前不动任何代码。
