# 对标增强首批实施计划（2610-B1）——方案与任务拆解

> 2026-10-10 · 性质：**实施方案（裁决已落定，细节确认后开工，未开工）**
> 上游：[benchmark-adoption-assessment-2610.md](benchmark-adoption-assessment-2610.md)（评估通过，§五归位表）· [agent-benchmark-roo-roomote-2610.md](agent-benchmark-roo-roomote-2610.md)（借鉴清单）· [unit-test-repositioning-2610.md](unit-test-repositioning-2610.md)（单测方案）
> **裁决记录（2026-10-10，D-1~D-9 全部落定）**：skills 表为真相源（D-1）· AGENTS.md 生成基线+项目规则追加（D-2）· 追溯矩阵延后（D-3）· 不做审批流程预留扩展位（D-4）· 人工终审+多角度辅助展示（D-5）· native/本地模型优化暂缓（D-6）· 学习路径降级实施细节（D-7）· 覆盖率暂缓至 CI/CD 整合（D-8）· 首批技能随实施定（D-9）——详见 [tech-debt-ledger-2609.md](tech-debt-ledger-2609.md) 对标增强轨道节
> 轨道衔接：roadmap **P2-T4**（mandate 加固，本批 W2 为其上下文供给）· **P2-T5**（V 组门禁，本批 W5 为其建议层）· **v2-todo P1**（skills，本批 W6）
> 代码载体已实证：`tests/goldens/`（金样目录在）· `agent/cognition/prompt.py` · `agent/execution/context_pack.py` · `agent/turns/context.py:145`（overflowDigest）· `agent/execution/exec_bridge.py:500`（execution_report）· `arch_routes/{agents_md,unit_test,tagent_utgen,test_runner,websocket}.py` · `src/services/ws-client.ts` · `sem/comp_graph.py`（D2 多视图扩展的地基）

---

## 〇、本批目标定位（整体目标对齐声明）

**architect = 以人为核心、需求和架构驱动的 AI 编程工具；以代码为事实锚点，协助开发者通过高效准确掌控需求和架构来驱动 AI 编程。**

本批增强的目的是提升 architect 的**需求分析、架构分析、架构设计**能力——在 agent/harness/skills/tools 层面学习成熟产品（Roo Code / Roomote）的机制优点，但按 architect 自身的架构与目标改造，**不照搬机制**。

## 一、范围裁决

### 1.1 本批做什么

| 组 | 内容 | 对应评估条目 |
|---|---|---|
| W1 | P0 快赢三件：prompt 快照测试 / `<request>` 转义 / WS 序列号 | P0 行 |
| W2 | **图邻域上下文供给**（D1 第一步行，挂 P2-T4） | P1 首行（修订后） |
| W3 | compact 交接单模板增强 | P1 |
| W4 | AGENTS.md 规则链闭环（D-2 方案 A）+ K2 回执测试段 | P1 |
| W5 | **单测建议层**（缺口建议面板 / 轻事实层 / approval 扩展位 / UnitTestPage 原位升级） | P1（单测文档 §7，按 D-3/D-4 收窄） |
| W6 | skills 化第一批（表为真相源 + 路由协议 + 首批技能） | P1（D-1 已裁决，解除阻塞） |

### 1.2 本批明确不做（防蔓延，含裁决依据）

| 项 | 裁决依据 | 重开条件 |
|---|---|---|
| native tool calling 迁移 | **D-6**：先依托大中规模模型建立完整流程，流程完善后再优化本地模型；**L 组优先级整体下调** | 全流程跑通后，与 L 组重启一并评估（届时 L2 语料按目标协议采集，口径问题自然消解） |
| judge LLM 门禁 | **D-5**：LLM 永不做门禁；多角度辅助展示（流程图/结构图/代码/影响评估/LLM 语义分析）+ **人工终审** | 无需重开——多视图展示归 **D2 立项（comp-graph 扩展）**，非本批 |
| D5 学习路径 | **D-7**：降级为实施细节（W5 缺口清单排序键），完整功能 Phase 3 复审 | Phase 3 规划 |
| 审批流程（timeout 自动采纳） | **D-4**：不做严格流程审批；模式 = **执行前规划 + 执行后审核**；预留 `approval` 扩展位（未来挂人工审批/主控 agent 审批） | 用户需要审批能力时按扩展位接入 |
| 追溯矩阵（验收↔用例关联） | **D-3**：避免过度严谨限制系统自由发挥；不影响 W5 核心能力（缺口靠图加权不靠矩阵）；`linkedTests` 预留位不动 | 出现真实追溯诉求（如合规场景）时再评 |
| 覆盖率采集 | **D-8**：未来与自动化测试 CI/CD **跨系统服务整合**，届时数据来自外部系统 | CI/CD 整合立项时 |
| actor-scoped turns | 多人场景 roadmap 后置（用户排序第 3） | 团队版立项 |
| 双历史/rewind 体系 | architect 已有等价物（specVersions append），不照搬 Roo 形态 | 出现会话级回退诉求时评估 |

### 1.3 纪律继承（每任务卡默认遵守，不再逐条重复）

① 五锚约束（评估 §二；"人在环上"按 2026-10-10 细化诠释执行，见 0926 文档附录）② CONV-04 G1~G8 门禁 ③ 行数棘轮：新文件登记基线，老文件不净增超豁免 ④ 测试基线只增不减 ⑤ prompt 改动过 `ctx_budget` 统一装配预算 + 成对版本化（模板 diff 触发回归）⑥ 表面收敛：不新开页面，UnitTestPage 原位升级 ⑦ 每片独立可回退（开关缺省值策略）

### 1.4 基调三修正（贯穿本批所有实现）

1. **辅助视角 ≠ 强制流程**：策略产出（缺口清单/建议卡）是供人参考的视角，不是必须清零的工单；不设"必须先 X 才能 Y"的硬步骤。
2. **跨系统整合定位**：重感知（覆盖率/CI 结果/回归基线）默认未来从 CI/CD 管线接入，architect 只做轻事实层 + 消费扩展位。
3. **对标方法论**：学外部方案在需求分析/架构分析/架构设计上的**优点**（证据呈现方式/上下文供给方式/路由协议），机制按 architect 目标改造。

---

## 二、批次依赖与排序

```
W0 前置(0.5d) ──┬─→ W1 快赢组(3d)      [独立，可并行]
                ├─→ W2 图邻域供给(4~5d) ──→ W5 单测建议层(3~4d)   [W5 缺口清单消费 W2 的图查询]
                ├─→ W3 交接单模板(0.5d)  [独立]
                └─→ W4 规则链+K2(2d) ──→ W5                      [W5 事实层消费 K2 测试段]
W6 skills(2~2.5d)：D-1 已裁决解除阻塞，与 W2~W5 无强依赖，可并行
```

**建议开工序**：W0 → W1（热身+安全网）→ W2+W3+W4 并行 → W5 收口；W6 视人力与 W2~W5 并行。
**总量**：**12~14.5 人日**（不含 W6 则 10~11.5）；较原案 −2（W5 砍追溯矩阵、W6 砍导入导出）。

---

## 三、任务卡

### W0 · 前置准备（0.5d）

| 项 | 内容 |
|---|---|
| 目标 | 基线登记，防开工即失锚 |
| 关键动作 | ① 登记本批行数基线（新增文件清单 + 涉改老文件当前行数）；② `git tag topo-b1-start` 打回退锚点；（裁决已全部落定，无裁决会） |
| 交付物 | 基线登记 |
| 验证 | tag 存在；台账对标增强轨道全部 ✅ |
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
| 目标 | D1 第一步：把自管图数据变成 agent 上下文的一等供给（评估定为 P2-T4 的上下文面）；对标 Roo `environment_details`"每轮新鲜+尾部追加"与 `parseSourceCodeDefinitionsForFile`"大纲喂上下文"——**直接服务架构分析能力**（分析焦点在图上的邻域供给） |
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

### W4 · AGENTS.md 规则链闭环 + K2 回执测试段（2d，D-2 方案 A 已裁决）

| 项 | 内容 |
|---|---|
| 目标 | ① 规则文件从"生成"到"分层加载合并"闭环（Roo 优先级洋葱模式）；② execution_report 增加测试段（单测主张层的字段地基） |
| 载体 | `arch_routes/agents_md.py`（`build_project_agents_md`/`sync_agents_md` 已在）+ `agent/execution/exec_bridge.py:500`（execution_report 单元已在） |
| 关键动作 | ① 规则链（**D-2 裁决：方案 A**）：生成基线段用**定界符包裹** + 项目规则段来源 `.topo/rules/` 目录（分文件，按名排序，追加在基线段后=更近用户）；**手改保护**：sync 时检测基线段被手改 → 问询卡（cv-282 模式，不静默覆盖）；② K2 扩展：execution_report schema 加 `tests` 段（`files: [{path, target_symbols}]`、`run_result`、`uncovered_reason?`——coverage 字段**不采**，D-8 暂缓），done/failed 回执落库时写入；③ 测试清单**不新造文件**——清单即 K2 `tests.files` 字段；④ 前端 contract-service.ts 类型同步 |
| 交付物 | 规则合并+定界+手改问询 + execution_report.tests 段 + 类型同步 + 测试 |
| 门禁 | G3 + G4（契约变更走 CONV-04） |
| 依赖 | 无硬依赖（与 W2 并行） |
| 回退 | tests 段 schema 可选字段，老回执无此段不炸；规则合并可退回纯生成模式 |

### W5 · 单测建议层（3~4d）★挂 P2-T5（按 D-3/D-4 收窄）

| 项 | 内容 |
|---|---|
| 目标 | 单测重定位 §7 按 D-3/D-4 收窄后落地：**建议面板**（非强制工作台）+ 轻事实层 + approval 扩展位；UnitTestPage 原位升级不新开页面 |
| 载体 | REST：`arch_routes/unit_test.py`（在）；缺口：W2 `graph_neighborhood` 复用；UI：`UnitTestPage.vue` + `AcceptancePanel.vue` |
| 关键动作 | ① **轻事实层（弱感知）**：`test_runner.py` 既有执行结果 + 增量扫描测试文件模式（`*.test.ts`/`test_*.py`/`*_test.go`/`*.spec.ts`，挂 baseline_refresh 编排尾步，复用 change_detector 判"新引入测试"）；⚠️ 变更态判定**复用 comp-graph 的 cached_compare 口径**（71125e3f 已有文件变更态+变更资产 strong/weak，勿另起通道）；② **主张层对账**：K2 `tests.files`（W4）∩ 事实层扫描集，差异记待核验事件（复用 arch_tracking_items）；③ **缺口建议清单**（核心）：图加权（扇入×域标记×无测试可达）产出 Top-N 高风险无测试符号——**建议视图**，排序键默认取图中心度（D-7 学习路径变体的零成本落地），走既有提案卡管道（naming 同款：pending → 用户确认 → 委派复用 propose→confirm 单源，载荷=context_pack + W2 邻域 + KB 测试风格样本）；④ **最小证据视图**（D-5 多角度呈现的最小落地）：提案卡内嵌变更统计 + 关联符号 + 邻域摘要（完整多视图审核面板归 D2/comp-graph 扩展，不在本批）；⑤ **approval 扩展位**：提案卡配置加通用 `approval` 对象（`{mode: none|human|agent, policy?}`，**缺省 `none`=无行为**——未来对接人工审批或主控 agent 审批，D-4 预留）；⑥ UnitTestPage 信息架构调整：上半屏**建议面板**（缺口+对账状态）/下半屏执行会话（现状保留） |
| 交付物 | 事实层扫描 + 对账 + 缺口建议卡（含最小证据视图与 approval 位）+ UnitTestPage 原位升级 + 测试 |
| 门禁 | G3~G7；表面收敛合规（原位升级，无新页面）；基调核验：无强制步骤（①→③ 无前置依赖，建议面板可独立使用） |
| 依赖 | **W2**（图查询）+ **W4**（K2 测试段） |
| 回退 | 各自独立开关（`unit_test_advice.*`），建议面板 UI 可隐藏 |

### W6 · skills 化第一批（2~2.5d，D-1 已裁决：表为真相源）

| 项 | 内容 |
|---|---|
| 目标 | v2-todo P1 的"可执行 skills"升级，叠加 benchmark C 节路由协议（学 Roomote 的 initial_routing/child_registry **协议**；**载体已裁决：arch_assets 表**，yaml 导入导出降为远期不做） |
| 载体 | `arch_routes/asset_tools.py`（asset.upsert/list/delete 面）+ `_ARCH_SKILLS` 注册表 + 提取钩子（轮后 draft 入库） |
| 关键动作 | ① skills 定义入 `arch_assets`（kind=skill），字段含 `route_hint`（N 选 1 路由描述）与 `child_registry`（子技能引用）；② 会话首轮注入 skills 目录（受 ctx_budget），路由指令学"强制 N 选 1"形态；③ 首批技能（D-9 随实施定）：`extract.requirement` / `analyze.suggest` / `test.strategy`（W5 缺口建议的技能化封装——**需求分析/架构分析能力的直接载体**，若 W6 先于 W5 动工则首批砍掉它） |
| 交付物 | skill 资产化 + 路由注入 + 首批 3 技能 |
| 门禁 | G3 + G5 |
| 依赖 | 无硬依赖（D-1 已解除）；`test.strategy` 依赖 W5 |
| 回退 | `_ARCH_SKILLS` 旧注册表保留为缺省源，资产表为增量覆盖 |

---

## 四、整体验收口径（批次 DoD）

1. **W1**：CI 上 prompt golden 漂移即红；对抗注入样例全绿；WS 乱序/重连回归绿
2. **W2**：mandate 生成载荷含邻域摘要（日志可查）；违规回执带"允许集+建议"；`graph_context_injection` 可关
3. **W3**：30+ 轮会话溢出摘要含"必须重载清单"段；缓存锚点不重算行为不回归
4. **W4**：`.topo/rules/` 项目规则出现在生成 AGENTS.md 尾部；基线段手改触发问询卡（不覆盖）；execution_report 含 tests 段（委派任务实测）
5. **W5**：建议面板可见缺口 Top-N 与对账状态；一张缺口建议卡走完 确认→委派→回执→对账 全链；`approval.mode` 缺省 `none`；**无强制步骤**（建议面板独立可用）
6. **W6**：`test.strategy` 技能可被路由选中；skill 资产可经 asset 工具面读写
7. **全局**：测试基线只增不减；行数棘轮无新豁免（或豁免附理由）；全量门禁绿

## 五、风险与缓解

| 风险 | 缓解 |
|---|---|
| W2 邻域查询大图性能（万级节点） | **复用 comp-graph 先例**（71125e3f/6eb00dfc）：MAX 上限截断 + `truncated` 透出 + FE 警示条 三件套模式（file-graph MAX_FILE_NODES=200 已验证）；预算钳制 + depth≤2 起步；163 文件项目先验证，大项目按需 lazy |
| W5 事实层扫描与 KB 算力争用 | 挂 baseline_refresh 尾步（错峰）；扫描为纯文件名模式，成本极低 |
| context_pack 注入膨胀违反瘦身纪律 | 全部新注入走 `ctx_budget`；W1-1 golden 含字数区间断言兜底 |
| K2 tests 段对执行器（cline/opencode/codex）的回传依赖 | 段为可选+缺失降级（对账记"主张缺失"事件，不阻塞） |
| UnitTestPage IA 调整动大组件 | 只加建议面板区块不动既有会话面板；B2 拆分纪律（下线优先于拆分） |
| 建议层被用户当作"必须清零的工单"（基调走样） | UI 文案与 i18n 明示"建议/参考"语义；DoD 5 的"无强制步骤"为验收项 |

## 六、开工检查单与进度

- [x] D-1~D-9 裁决落定（2026-10-10，台账对标增强轨道节）
- [x] **实施文档组编写完成**：[b1/](b1/README.md)（W1 快赢 / W2-W3 上下文 / W4 契约 / W5 单测建议 / W6 skills——模块级新增/变更/移除 + 上下游影响）
- [x] 细节确认（2026-10-10 用户确认后开工）
- [x] 基线 tag（`topo-b1-start`）+ 行数登记（[b1/baseline.md](b1/baseline.md)）
- [ ] W1-1 golden 再生成命令入 README/CONV-03（开发者须知）

### 执行进度（2026-10-10，批次收口）

| 组 | 状态 | 提交 |
|---|---|---|
| W0 前置 | ✅ | `14fce8e1`（基线）· tag `topo-b1-start` |
| W1 快赢组 | ✅ 全三件 | `56be154e`（golden/信封/seq，附生产修复：工具清单按名排序） |
| W3 交接单模板 | ✅ | `fb80fedc` |
| W4 规则链+K2 | ✅ | `146cb632`（指纹定界/规则追加/手改问询/tests 段） |
| W2 图邻域供给 | 🔶 核心已落 | `117e4a35`（graph_neighborhood + context_pack 注入）；**余 W2-④ mandate 违规回执增强**（随 P2-T4 勾稽链下轮） |
| W5 单测建议层 | ✅ | `ec2c2076`（缺口建议面板/轻事实层/对账挂账/approval 位） |
| W6 skills 化 | ✅ | `b337631c`（arch_assets 表为真相源/目录强制路由/test.advice+test.strategy） |

门禁基线推移：pytest 1364 → **1403**（+39）；vitest 80 → **86**；tsc 0；行数棘轮全程绿。
遗留（下轮）：W2-④ mandate 违规回执（挂 P2-T4）；asset 管理 UI（REST 先行，C1 先例）；W5 组件域乘数（components 目录接入后）。
