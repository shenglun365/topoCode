# B1 遗留项实施计划（2610-B1-deferred）

> 2026-10-10 · 性质：**实施方案（执行进度见文末）**
> 来源：[adoption-batch1-plan-2610.md](../adoption-batch1-plan-2610.md) 执行进度遗留登记
> 载体已实证：`exec_bridge.py:200-218`（越界检测现点）· `parse_scope_files`（req_agent）· `store/component.py`（arch_components: owns/source + hierarchy.level）· `ConfigPage.vue` 子 tab 体系（instance/executors/roleModels/other）

---

## L-1 · mandate 违规回执增强（原 W2-④，挂 P2-T4）

**现状**：越界检测已是**事后验收材料**（`_acceptance_brief` 一带：`overrun = 改动文件 - allowedScope 前缀集` → "⚠️ 越界改动…请核查" + 文件清单）；符号级勾稽（P2-T4"引用符号必须可解析到 AstNodeRef"）尚无落地点。

| 项 | 内容 |
|---|---|
| 目标 | ① 事后回执从"报错"升级为"自纠正信息"（FileRestrictionError 模式）；② 符号勾稽前置到下发时（P2-T4 配套，消费 W2 邻域） |
| 载体 | `exec_bridge.py` overrun 分支（回执增强）；`execution/context_pack.py` / `execution/dispatch.py`（前置勾稽）；`sem/graph_context.py`（邻域/符号解析已就绪）；`req_agent.parse_scope_files`（前缀解析，需区分符号条目） |
| 关键动作 | ① **回执增强**：overrun 分支追加"允许范围全集（前缀清单）+ 每个越界文件的最近允许前缀建议（最长公共路径匹配）"，模型/用户可一轮修正；② **符号勾稽**：`parse_scope_files` 扩展识别符号条目（非路径形态，如 `file.py::symbol`）；context_pack 组装时对符号条目调 `GraphStore.nodes` 验证可解析——不可解析 → 载荷附"⚠️ 符号 X 未在基线图中解析到，请修正规约或刷新基线"（提示级，不阻断下发，基调修正①）；③ 勾稽通过时附该符号一跳邻域（W2 注入已有，确保 focus 覆盖符号条目） |
| 交付物 | 回执增强 + 符号条目解析/勾稽 + 提示注入 + 测试（构造越界样例断言建议文本；构造幽灵符号断言警告） |
| 门禁 | G3 + G4；验收材料文本变化走 `test_acceptance_closure` 扩展 |
| 依赖 | P2-T4 排期对齐（可先行落①，②随 P2-T4） |
| 回退 | ①文本级 revert；②符号条目不识别时行为与现状一致（纯前缀） |
| 估时 | ①1d（可独立先行）／②1.5d（随 P2-T4） |

## L-2 · 资产/技能管理 UI（REST 先行的补面，C1 先例）

**现状**：`/arch/assets` REST 已落（W6），FE 无管理面；技能自定义目前只能 curl/工具面写。

| 项 | 内容 |
|---|---|
| 目标 | ConfigPage 新增「技能与资产」子 tab：arch_assets 的列表/新建/编辑/启停/删除 |
| 载体 | `ConfigPage.vue` 子 tab 体系（新增 `skills` tab，第 5 个）；新组件 `src/components/config/AssetsCard.vue`；service 复用 W6 REST（新增 `asset-assets-service.ts` 薄适配） |
| 关键动作 | ① 列表（kind 过滤：skill/requirement/todo/plan/analysis；source 标记 builtin 的内置技能只读展示——目录可见性）；② 编辑器：name/description/enabled + skill 型 payload 三字段（route_hint 必填校验对齐 REST、instructions_md 文本域、child_registry 逗号清单）；③ 保存走 upsert（同名覆盖提示）；④ 删除带确认；⑤ i18n zh/en |
| 交付物 | AssetsCard + ConfigPage tab + service + smoke 测试（列表渲染/route_hint 校验/启停） |
| 门禁 | G7（前端）；tsc/vitest |
| 依赖 | 无（W6 REST 已就绪） |
| 回退 | tab 独立，摘除零影响 |
| 估时 | 1.5~2d |

## L-3 · W5 组件域乘数（图加权升级）

**现状**：`test_reach_gaps` 权重 = fan_in × kind 权重；`arch_components` 有 `owns`（文件清单）与 `hierarchy.level`（L0 原子/L1/L2 聚合）可作域信号。

| 项 | 内容 |
|---|---|
| 目标 | 缺口权重加入组件域维度：聚合层（架构核心域）组件内的符号权重更高 |
| 载体 | `sem/test_reach.py`（weight 计算）；`store/component.py` ComponentStore.list_rev + hierarchy（只读） |
| 关键动作 | ① 文件 → 组件映射：遍历 components `owns` 匹配节点 file_path（前缀/等值）；② 层级乘数：无组件 1.0 / L0 1.0 / L1 1.5 / L2 2.0（层级取 hierarchy 中该组件的 level）；③ weight = fan_in × kind × level_mult，evidence 增 `component` 字段（组件名+层级，建议卡可显示"属核心域组件 X"）；④ 无基线组件数据时乘数全 1（行为与现状一致，回退位） |
| 交付物 | 映射+乘数+evidence 字段 + 测试（同文件两符号不同层级组件 → 权重序正确；无组件数据回归） |
| 门禁 | G3 |
| 依赖 | 无硬依赖（组件目录由 baseline_refresh 已产出） |
| 回退 | 乘数查不到即 1.0，纯增量 |
| 估时 | 0.5~1d |

---

## 建议排期

```
独立可先行（无依赖）: L-3(0.5~1d) → L-2(1.5~2d)        合计 ~3d
随轨对齐:            L-1①(1d 可独立) / L-1②(1.5d 随 P2-T4)
总量: 4.5~5.5d
```

三项均不阻塞 B1 验收；L-1② 与 P2-T4（mandate 质量加固）同批做可共用符号解析与测试夹具，建议捆绑排期。

---

## 执行进度（2026-10-10）

| 项 | 状态 | 提交 | 备注 |
|---|---|---|---|
| L-3 组件域乘数 | ✅ | `1983b8d2` | 层级 1.0/1.5/2.0 + component 字段 + FE 徽标；查不到恒 1 回退位验证 |
| L-1① 越界回执自纠正 | ✅ | `62f41ce0` | 允许集全集 + 最近前缀建议（零共享=明确指引）；`_nearest_scope` |
| L-2 资产/技能管理 UI | ✅ | `94b6051e` | ConfigPage 第 5 子 tab + AssetsCard（route_hint 校验对齐 REST） |
| L-1② 符号勾稽前置 | ⬜ | — | **随 P2-T4 同批**（共用符号解析与测试夹具，捆绑排期） |

门禁终态：pytest **1406** / vitest **89** / tsc 0 / vite build ✓ / 棘轮绿。
过程修复：`b614800a`（SFC 属性引号嵌套，vite build 捕获）。
