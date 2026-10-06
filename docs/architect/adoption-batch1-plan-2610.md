# 对标增强首批实施计划（2610-B1）——方案与任务拆解

> 2026-10-10 · 性质：**实施方案（待评审后开工）**
> 上游：[benchmark-adoption-assessment-2610.md](benchmark-adoption-assessment-2610.md)（评估通过，§五归位表）· [agent-benchmark-roo-roomote-2610.md](agent-benchmark-roo-roomote-2610.md)（借鉴清单）· [unit-test-repositioning-2610.md](unit-test-repositioning-2610.md)（单测方案）
> 轨道衔接：roadmap **P2-T4**（mandate 加固，本批 W2 为其上下文供给）· **P2-T5**（V 组门禁，本批 W5 为其策略层）· **v2-todo P1**（skills，本批 W6）· L 组（native tool calling **不在本批**，绑 L4 门禁后）
> 裁决依赖：tech-debt-ledger **G1**（skills 载体，阻塞 W6）/ **G2**（timeout，本批只带缺省关开关）/ G3·G4（不在本批）
> 代码载体已实证：`tests/goldens/`（金样目录在）· `agent/cognition/prompt.py` · `agent/execution/context_pack.py` · `agent/turns/context.py:145`（overflowDigest）· `agent/execution/exec_bridge.py:500`（execution_report）· `arch_routes/{agents_md,unit_test,tagent_utgen,test_runner,websocket}.py` · `src/services/ws-client.ts`

---

## 一、范围裁决

### 1.1 本批做什么（评估 §五归位表的净新增项全部收入）

| 组 | 内容 | 对应评估条目 |
|---|---|---|
| W1 | P0 快赢三件：prompt 快照测试 / `<request>` 转义 / WS 序列号 | P0 行 |
| W2 | **图邻域上下文供给**（D1 第一步行，挂 P2-T4） | P1 首行（修订后） |
| W3 | compact 交接单模板增强 | P1 |
| W4 | AGENTS.md 规则链闭环 + K2 回执测试段 | P1 |
| W5 | **单测策略层**（追溯矩阵 / 事实层 / 缺口清单 / UnitTestPage 原位升级） | P1（单测文档 §7） |
| W6 | skills 化第一批（路由协议 + 资产表升级） | P1（阻塞于 G1 裁决） |

### 1.2 本批明确不做（防蔓延）

| 项 | 理由 | 重开条件 |
|---|---|---|
| native tool calling 迁移 | 绑 L 组 L4 评测门禁（结构化输出合法率 ≥99% 先行） | L4 通过后单独立项 |
| judge subagent（D2 漂移裁决的 LLM 面） | G3 未裁决；红线"LLM 不入硬闸" | G3 裁决 + D2 立项 |
| D5 学习路径 | G4 建议砍/后置 | Phase 3 规划 |
| timeout 自动采纳 | G2 未裁决 | 本批 W5 只带**缺省关**的开关位 |
| actor-scoped turns | 多人场景 roadmap 后置（用户排序第 3） | 团队版立项 |
| 双历史/rewind 体系 | architect 已有等价物（specVersions append），不照搬 Roo 形态 | 出现会话级回退诉求时评估 |

### 1.3 纪律继承（每任务卡默认遵守，不再逐条重复）

① 五锚约束（评估 §二）② CONV-04 G1~G8 门禁 ③ 行数棘轮：新文件登记基线，老文件不净增超豁免 ④ 测试基线只增不减 ⑤ prompt 改动过 `ctx_budget` 统一装配预算 + 成对版本化（模板 diff 触发回归）⑥ 表面收敛：不新开页面，UnitTestPage 原位升级 ⑦ 每片独立可回退（开关缺省值策略）

---

## 二、批次依赖与排序

```
W0 前置(0.5d) ──┬─→ W1 快赢组(3d)      [独立，可并行]
                ├─→ W2 图邻域供给(4~5d) ──→ W5 单测策略层(4~5d)   [W5 缺口清单消费 W2 的图查询]
                ├─→ W3 交接单模板(0.5d)  [独立]
                └─→ W4 规则链+K2(2d) ──→ W5                      [W5 事实层消费 K2 测试段]
W6 skills(3d)：G1 裁决后插入，与 W2~W5 无强依赖，可并行
```

**建议开工序**：W0 → W1（热身+安全网）→ W2+W3+W4 并行 → W5 收口 → W6（G1 裁决节奏决定）。
**总量**：14.5~16 人日（不含 W6 则 11.5~13）；与评估净新增 12~16 人日吻合。

---

## 三、任务卡

### W0 · 前置准备（0.5d）

| 项 | 内容 |
|---|---|
| 目标 | 裁决就位 + 基线登记，防开门即返工 |
| 关键动作 | ① G1 裁决会（skills 载体，建议结论已在台账：表为真相源/文件为交换格式）；② 登记本批行数基线（新增文件清单 + 涉改老文件当前行数）；③ `git tag topo-b1-start` 打回退锚点 |
| 交付物 | G1 裁决记录（台账勾销）+ 基线登记 |
| 验证 | 台账 G1 状态更新；tag 存在 |
| 回退 | — |

### W1 · P0 快赢组（3d，三片独立）

#### W1-1 prompt 快照测试（1d）

| 项 | 内容 |
|---|---|
| 目标 | prompt 漂移 CI 可见（Roo `__snapshots__/system-prompt` 模式，学形不学量） |
| 载体 | `agent/cognition/prompt.py`（组装单源）+ `tests/goldens/`（金样目录已在） |
| 关键动作 | ① 按 prompt 分型（chat 角色 / 任务角色 / 摘要 / 命名）各出一组 golden；② 断言维度：分段结构 + 关键契约句（如"执行前先读"强指引）+ 字数预算区间（接 `prompt_sections` 分层字数遥测，批丁已布点）；③ 快照再生成走显式命令（`pytest --regen-goldens`），防静默漂移 |
| 交付物 | `tests/test_prompt_goldens.py` + `tests/goldens/prompt/*.json` |
| 门禁 | G3；与成对版本化纪律挂钩——golden 变更必须对应模板版本号变更 |
| 回退 | 删测试文件即可 |

#### W1-2 `<request>` 转义防注入（0.5d）

| 项 | 内容 |
|---|---|
| 目标 | 用户需求文本进入 prompt 信封时包标签转义（Roomote `standardTask.ts:578-614` 模式） |
| 载体 | `agent/cognition/prompt.py` 的用户内容装配段；`agent/execution/context_pack.py` 指令尾契约段 |
| 关键动作 | ① 抽 `wrap_user_request(text) -> "<request>…</request>"`（内部 `</request>` 出现时改全角或计数闭合）；② 两处装配点接线；③ 对抗样例入测试（含伪 `</system>` 提前闭合攻击） |
| 交付物 | 转义函数 + 2 装配点接线 + 对抗测试 |
| 门禁 | G3 |
| 回退 | 函数级 revert |

#### W1-3 WS 事件流序列号防竞态（1~1.5d）

| 项 | 内容 |
|---|---|
| 目标 | SSE/WS 重连、多标签页下流式消息不回退不乱序（Roo `clineMessagesSeq` 模式） |
| 载体 | `arch_routes/websocket.py`（后端事件面）+ `src/services/ws-client.ts`（前端 ArchWs）+ `src/stores`（会话消息 store） |
| 关键动作 | ① 后端每会话事件附单调 `seq`（会话级计数器，Redis 不引入——单进程内存即可，重启后以 DB max(seq) 续）；② 前端 store 合并时丢弃 `seq <= lastSeq` 的事件；③ 重连补偿：带 lastSeq 请求增量（后端会话消息表已有落库，补增量查询口）；④ 顺带修 v2-todo 已知小问题（msgCount 含 reasoning 的粗粒度统计） |
| 交付物 | seq 协议（前后端）+ 重连增量通道 + 回归测试（模拟乱序/重连） |
| 门禁 | G3 + G7（前端 store 改动） |
| 回退 | seq 字段前端兼容忽略（老客户端不受影响），可独立回退 |

### W2 · 图邻域上下文供给（4~5d）★本批核心

| 项 | 内容 |
|---|---|
| 目标 | D1 第一步：把自管图数据变成 agent 上下文的一等供给（评估定为 P2-T4 的上下文面）；对标 Roo `environment_details`"每轮新鲜+尾部追加"与 `parseSourceCodeDefinitionsForFile`"大纲喂上下文" |
| 载体 | 数据：`arch_graph_node/edge`、`arch_ast_cache`（数据主权自管面，1004 已定）；编排：`arch_routes/sem/` 既有作业；注入：`agent/execution/context_pack.py`（P2 ✅ 已落地的载荷结构化）；预算：`agent/turns/context.py` 的 `ctx_budget` |
| 关键动作 | ① **图邻域查询函数** `graph_neighborhood(symbols|module, depth, budget)`：按符号/模块取 N 跳子图，输出压缩大纲（节点=符号签名行，边=调用/包含），总字数受预算钳制（学 Roo 大纲的密度控制）；② **消费点一（mandate 锚定勾稽）**：mandate 生成/校验时（P2-T4）注入候选符号的邻域，使"引用的符号必须可解析到 AstNodeRef"有上下文依据；③ **消费点二（context_pack 常规注入）**：任务卡下发时载荷含焦点模块邻域摘要（替换现在的文件列表式上下文），走 `ctx_budget` 裁剪；④ **mandate 违规回执增强**（FileRestrictionError 模式）：越界符号的回执文本自带"允许的符号集 + 实际引用 + 建议修正"，让模型一轮自纠；⑤ freshness：邻域数据带 `baseline_commit` 戳，工作区 dirty 时标注"基线可能过期"（change_detector 结果轻量注入） |
| 交付物 | `sem/graph_context.py`（查询+压缩，新文件~200 行内）+ context_pack 注入段 + 回执增强 + fixture 测试（用现有 163 文件级测试项目） |
| 门禁 | G2（core 管线）+ G3；行数：graph_context.py 登记基线 |
| 依赖 | W0 基线 |
| 回退 | context_pack 注入段开关 `graph_context_injection`（缺省开，可关）；查询函数纯读无副作用 |

### W3 · compact 交接单模板增强（0.5d）

| 项 | 内容 |
|---|---|
| 目标 | overflowDigest 从"摘要"升级为"交接单"（Roomote compact 模式：必须重载清单 + 恢复后唯一动作） |
| 载体 | `agent/turns/context.py:145` `_overflow_digest_msg`（缓存/降级机制已在，只动模板）+ `adaptation.summarize_task` |
| 关键动作 | ① 模板加两段：**必须重载的资产/规约/AGENTS.md 清单**（从 context_pack 引用面提取）+ **恢复后第一动作约束**；② golden 纳入 W1-1 快照族；③ 过成对版本化（模板版本号 +1） |
| 交付物 | 模板 v2 + golden 更新 |
| 门禁 | G3；prompt 瘦身核验（净增字数 ≤80，超出走裁剪） |
| 回退 | 模板 revert，缓存锚点机制不动 |

### W4 · AGENTS.md 规则链闭环 + K2 回执测试段（2d）

| 项 | 内容 |
|---|---|
| 目标 | ① 规则文件从"生成"到"分层加载合并"闭环（Roo 优先级洋葱模式）；② execution_report 增加测试段（单测文档 §3.1 主张层的字段地基） |
| 载体 | `arch_routes/agents_md.py`（`build_project_agents_md`/`sync_agents_md` 已在）+ `agent/execution/exec_bridge.py:500`（execution_report 单元已在） |
| 关键动作 | ① 规则链：加载优先级定为 **项目 `.topo/rules/` 目录（分文件，按名排序）> `.topo/agents.md` 生成基线**，`build_project_agents_md` 产出时合并两源（项目规则在后=更近用户）；② K2 扩展：execution_report schema 加 `tests` 段（`files: [{path, target_symbols}]`、`run_result`、`coverage?`、`uncovered_reason?`），done/failed 回执落库时写入；③ `.topo/tests.yaml` **不新造文件**——清单即 K2 `tests.files` 字段（评估 §三简化建议落地）；④ 前端 contract-service.ts 类型同步 |
| 交付物 | 规则合并逻辑 + execution_report.tests 段 + 类型同步 + 测试 |
| 门禁 | G3 + G4（契约变更走 CONV-04） |
| 依赖 | 无硬依赖（与 W2 并行） |
| 回退 | tests 段 schema 可选字段，老回执无此段不炸 |

### W5 · 单测策略层（4~5d）★挂 P2-T5

| 项 | 内容 |
|---|---|
| 目标 | 单测重定位文档 §7 落地：策略工作台三件套（追溯矩阵 / 缺口清单 / 事实层），UnitTestPage 原位升级不新开页面 |
| 载体 | REST：`arch_routes/unit_test.py`（在）；追溯：`arch_routes/{requirements,acceptance}.py` + `arch_acceptance_facts`；缺口：W2 `graph_neighborhood` 复用；UI：`UnitTestPage.vue` + `AcceptancePanel.vue`（局部验收 tab 已在，plan-C-M0 冻结稿 `acceptance.linkedTests` 预留位） |
| 关键动作 | ① **追溯矩阵**：验收条目 ↔ 单测用例关联表（复用 `linkedTests` 预留），API `GET /unit-tests/trace?reqId=`，UI 在 AcceptancePanel 加"证据"列（无证据条目高亮=追溯缺口）；② **事实层（弱感知）**：`test_runner.py` 既有执行结果 + 增量扫描测试文件模式（`*.test.ts`/`test_*.py`/`*_test.go`/`*.spec.ts`，挂 baseline_refresh 编排尾步，复用 change_detector 判"新引入测试"）；③ **主张层**：对账 = K2 `tests.files`（W4）∩ 事实层扫描集，差异记待核验事件（落库轻量表或复用 arch_tracking_items）；④ **缺口清单 L0 提案卡**：图加权（扇入×域标记×无测试可达）产出 Top-N 高风险无测试符号，走既有提案卡管道（naming 提案同款：pending → 用户确认）；确认后 L1 委派复用 propose→confirm 单源（载荷=context_pack + W2 邻域 + KB 测试风格样本）；⑤ **timeout 开关位**：提案卡配置加 `auto_approve_after_ms` 字段——**缺省 null=关**（G2 裁决前不启用，只留位）；⑥ UnitTestPage 信息架构调整：上半屏策略区（缺口+追溯）/下半屏执行会话（现状保留） |
| 交付物 | trace API + 事实层扫描 + 对账 + 缺口提案卡 + UnitTestPage 原位升级 + 测试 |
| 门禁 | G3~G7（涉及面广）；表面收敛合规（原位升级，无新页面） |
| 依赖 | **W2**（图查询）+ **W4**（K2 测试段） |
| 回退 | 三件套各自独立开关（`unit_test_strategy.*`），策略区 UI 可隐藏 |

### W6 · skills 化第一批（3d，G1 裁决后）

| 项 | 内容 |
|---|---|
| 目标 | v2-todo P1 的"可执行 skills"升级，叠加 benchmark C 节路由协议（学 Roomote 的 initial_routing/child_registry **协议**，载体按 G1 裁决） |
| 载体 | `arch_routes/asset_tools.py`（asset.upsert/list/delete 面）+ `_ARCH_SKILLS` 注册表 + 提取钩子（轮后 draft 入库） |
| 关键动作 | ① 若 G1=表为真相源：skills 定义入 `arch_assets`（kind=skill），字段含 `route_hint`（N 选 1 路由描述）与 `child_registry`（子技能引用）；② 会话首轮注入 skills 目录（受 ctx_budget），路由指令学"强制 N 选 1"形态；③ 首批技能从现有服务收编：`extract.requirement` / `analyze.suggest` / **`test.strategy`**（W5 缺口提案卡的技能化封装，一子两吃）；④ 导出/导入文件格式（D8 可分享性的地基，yaml） |
| 交付物 | skill 资产化 + 路由注入 + 首批 3 技能 + 导入导出 |
| 门禁 | G3 + G5 |
| 依赖 | G1 裁决（W0）；`test.strategy` 技能依赖 W5 |
| 回退 | `_ARCH_SKILLS` 旧注册表保留为缺省源，资产表为增量覆盖 |

---

## 四、整体验收口径（批次 DoD）

1. **W1**：CI 上 prompt golden 漂移即红；对抗注入样例全绿；WS 乱序/重连回归绿
2. **W2**：mandate 生成载荷含邻域摘要（日志可查）；违规回执带"允许集+建议"；`graph_context_injection` 可关
3. **W3**：30+ 轮会话溢出摘要含"必须重载清单"段；缓存锚点不重算行为不回归
4. **W4**：`.topo/rules/` 项目规则出现在生成 AGENTS.md 尾部；execution_report 含 tests 段（委派任务实测）
5. **W5**：AcceptancePanel 见"证据"列与缺口高亮；一张缺口提案卡走完 确认→委派→回执→对账 全链；`auto_approve_after_ms` 缺省关
6. **W6**（若入批）：`test.strategy` 技能可被路由选中；skill 资产可导出 yaml
7. **全局**：测试基线只增不减；行数棘轮无新豁免（或豁免附理由）；全量门禁绿

## 五、风险与缓解

| 风险 | 缓解 |
|---|---|
| W2 邻域查询大图性能（万级节点） | 预算钳制 + depth≤2 起步；163 文件项目先验证，大项目按需 lazy |
| W5 事实层扫描与 KB 算力争用 | 挂 baseline_refresh 尾步（错峰）；扫描为纯文件名模式，成本极低 |
| context_pack 注入膨胀违反瘦身纪律 | 全部新注入走 `ctx_budget`；W1-1 golden 含字数区间断言兜底 |
| K2 tests 段对执行器（cline/opencode/codex）的回传依赖 | 段为可选+缺失降级（对账记"主张缺失"事件，不阻塞） |
| UnitTestPage IA 调整动大组件 | 只加 tab/区块不动既有会话面板；B2 拆分纪律（下线优先于拆分） |

## 六、开工检查单

- [ ] G1 裁决（阻塞 W6）
- [ ] 基线 tag + 行数登记（W0）
- [ ] 评估文档/本计划评审通过（本批以本计划为实施单源，偏差回写）
- [ ] W1-1 golden 再生成命令入 README/CONV-03（开发者须知）
