# B1-W2/W3 实施文档：上下文工程（图邻域供给 + compact 交接单）

> 组：W2(4~5d) + W3(0.5d) · 依赖：W0 基线 · 决策依据：计划 §三 W2/W3；D1 方向（图感知上下文）
> 定位：直接服务**架构分析能力**——分析焦点在图上的邻域供给，替换文件列表式上下文

---

## 1. 模块操作总表

| 模块 | 操作 | 摘要 |
|---|---|---|
| `sem/graph_context.py` | **新增 ★** | `graph_neighborhood()` 查询 + 压缩大纲（~200 行） |
| `agent/execution/context_pack.py` | **变更** | 新增邻域摘要注入段（开关 `graph_context_injection` 缺省开）；文件列表式上下文**替换**为邻域摘要（老路径留开关） |
| mandate 载荷/校验链（context_pack 指令尾 + dispatch 域校验点） | **变更** | 候选符号邻域注入（勾稽依据）；违规回执增强（FileRestrictionError 模式） |
| `agent/turns/context.py` | **变更** | `_overflow_digest_msg` 模板 v2（W3 两段增强） |
| `agent/reflection/repair.py` | **变更** | `summarize_task` 摘要 system 模板加"必须重载清单/第一动作"指引段（模板常量级） |
| `sem/comp_graph.py` / `sem/change_detector.py` | 无改动 | 只读复用（三件套模式参照 / freshness 数据源） |
| 移除 | 无 | 文件列表上下文为**替换**非移除（开关 `graph_context_injection=off` 即回老路径） |

## 2. 逐模块明细

### 2.1 `sem/graph_context.py`（新增，本批核心）

**内容**：
- `graph_neighborhood(focus: symbols|module, depth=2, budget_chars) -> GraphNeighborhood`：从 `arch_graph_node/edge`（数据主权自管面）取 N 跳子图；输出压缩大纲——节点=符号签名行（`arch_ast_cache` 取签名），边=调用/包含关系；总字数受 `budget_chars` 钳制（学 Roo 大纲密度控制）
- **数量上限三件套**（复用 comp-graph 先例 71125e3f/6eb00dfc）：MAX 节点上限截断 + 返回体透出 `truncated/max_nodes` +（FE 消费时的警示条约定）
- freshness：返回体带 `baseline_commit`（`arch_projects.baselineCommit` 锚）；工作区 dirty（change_detector 结论）时附 `baseline_stale: true`
- 纯读、无副作用；多跳查询 BFS + 预算早停

**上游**：`arch_graph_node` / `arch_graph_edge` / `arch_ast_cache` / `arch_projects.baselineCommit` / `sem/change_detector`
**下游**：context_pack 注入段（2.2）、mandate 勾稽（2.3）、W5 `sem/test_reach.py`（图加权复用）、（远期）主 agent 对话轮注入

### 2.2 `agent/execution/context_pack.py`（消费点二：常规注入）

**改动**：载荷新增 `graph_neighborhood` 段——任务卡下发时按焦点模块取邻域摘要，**替换**现文件列表式上下文（开关 `graph_context_injection`，缺省开，关=回老路径）；字数计入 `ctx_budget` 统一装配预算（超预算按既有裁剪序先裁邻域细节行）。

**上游**：`graph_neighborhood()`；任务卡的焦点模块（既有载荷字段）。
**下游**：执行器载荷内容变化（契约无变化，透明）；W3 交接单"必须重载清单"从此段引用面提取。

### 2.3 mandate 载荷/校验链（消费点一：勾稽）

**改动**：① mandate 生成时（P2-T4 配套）：候选符号集的邻域注入 context_pack 指令尾——为"引用的符号必须可解析到 AstNodeRef"提供上下文依据；② 违规回执增强：越界符号回执文本自带**允许的符号集 + 实际引用 + 建议修正符号**（最近邻匹配），让模型一轮自纠（对标 Roo FileRestrictionError 的自纠正信息模式）。

**上游**：`graph_neighborhood()`；mandate 既有 allowedScope（X/Y/Z 轴）结构。
**下游**：P2-T4 验收（mandate 符号勾稽通过率）；执行器收到的违规反馈质量。

### 2.4 `agent/turns/context.py` + `agent/reflection/repair.py`（W3 交接单模板）

**改动**：`_overflow_digest_msg`（context.py:145 一带）与 `summarize_task` 摘要指引（repair.py:76 的 system 模板）协同升级——摘要产出增加两段：**必须重载清单**（context_pack 引用面的资产/规约/AGENTS.md 条目）+ **恢复后第一动作约束**（"恢复后第一且唯一动作=重载上述清单"）。缓存锚点机制（`conv.meta.overflowDigest`）不动；LLM 失败保持现截断降级。

**上游**：context_pack 引用面（2.2 注入段的引用清单）。
**下游**：长会话恢复质量；golden（W1-1 快照族新增摘要分型 golden 锁定两段存在）。

## 3. 数据与契约变更

| 面 | 变更 | 兼容性 |
|---|---|---|
| context_pack 载荷 | 新增 `graph_neighborhood` 段（内容级，schema 可选段） | 执行器透明；开关可回退 |
| 违规回执文本 | 格式增强（允许集+建议） | 纯文本增强，无破坏 |
| 摘要模板 | v2（+2 段） | 模板版本 +1，golden 同步；净增字数 ≤80 核验 |

**无表结构变更**（全部消费既有自管图数据）。

## 4. 测试计划

- `tests/test_graph_context.py`：fixture 用现有 163 文件级测试项目——① 邻域正确性（已知符号的 N 跳集合）② 预算钳制（超限截断 + truncated 透出）③ freshness（baseline 戳/dirty 标注）
- `tests/test_context_pack_graph.py`：注入段开关两态；ctx_budget 超限裁剪序
- mandate 回执：构造越界符号样例，断言回执含允许集与建议
- 摘要：golden 更新（两段存在）；锚点不变不重算回归
- 手测：真实委派任务载荷日志含邻域摘要（DoD 2）

## 5. 回退

| 片 | 回退 |
|---|---|
| 注入段 | `graph_context_injection=off`（回文件列表老路径） |
| 查询函数 | 纯读新文件，无人调用即惰性 |
| 违规回执 | 文案级 revert |
| W3 模板 | 模板 revert；缓存机制不动 |

## 6. 组内验收清单

- [ ] mandate 生成载荷含邻域摘要（日志可查）
- [ ] 违规回执带"允许集 + 建议修正"；构造样例一轮自纠
- [ ] `graph_context_injection` 可关且回退后行为不变
- [ ] 30+ 轮会话溢出摘要含两段；锚点不重算回归绿
- [ ] 大图性能：万级节点项目 depth=2 查询 < 500ms（超则降 depth/加上限）
