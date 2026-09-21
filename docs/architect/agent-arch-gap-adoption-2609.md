# Architect Agent 架构差距评审·采纳方案与驱动架构细化

> 日期：2026-09-21 · 性质：裁决记录 + 实施方案（已确认待实施）
> 评审源：`agent-arch-gap-review-2609.md`（其 9 处代码主张已逐条事实核查，全部属实，见附录 A）
> 前置依赖：会话流程相位机已落地（`agent/governance/flow.py` + `test_flow_states.py`，2026-09-21）——本方案在其小内核+行为注册制之上构建。
> 产品方向基线：D6（探测不动态升挡）/ cv-175（不静默纠错）/ cv-152（指令确定性）/ mining 人审 / 挡位分数解耦（2026-09-18）/ 真相源纪律（cv-194, P6）/ prompt 瘦身纪律（cv-189/196/203）。

---

## 一、采纳裁决总表

| # | 评审方案 | 裁决 | 批次 | 形态约束 |
|---|---|---|---|---|
| 1 | 修复经验回填工作记忆 | **采纳** | P0 (S1) | repair_note 单元按签名去重、限额注入、受统一装配预算裁剪 |
| 2 | llm_dataset 消费口 | **采纳**（含评审遗漏的吞错计数） | P0 (S2) | 纯读侧；聚合/吞错规则走 policy 配置 |
| 4 | 工作记忆溢出摘要 | **拆半采纳**：溢出摘要+缓存=采纳；MemoryStore=**退役**；dossier 进主链=缓议 | P0 (S3) | 摘要装配期瞬态注入不落消息流；按溢出锚点缓存 |
| 3 | 失败数据喂回 gears | 有条件采纳（仅"建议值+人审"） | P1 | tierSuggested 只展示永不自动写（D6 三重防线） |
| 5 | 意图识别 LLM 兜底 | 有条件采纳（先遥测后兜底） | P1 | LLM 意图只建议不触发不可逆动作；不入硬闸 |
| 6 | 评估域扩展 | 缓议 | P2 | 依赖 #2 数据先行 |
| — | 知识图谱层（评审缺陷7） | 不采纳 | — | 接口位保留（`mining.py` 已锚定独立设计文档） |
| — | 称谓口径（评审 §4.4） | 采纳 | 随文档 | "反思层的纠错子循环（机械域、有界、隔离）" |

**改造原则**（延续既有裁决精神）：经验回填与消费口只"告知"，不自动改写业务决策；涉及策略变更（#3）保留人审接口。

---

## 二、明确不做清单（旧内容标记）

以下内容**明确不做**或**本批不做**——每项附理由与重开条件，防止无裁决复活：

| 旧内容 | 裁决 | 理由 | 重开条件 |
|---|---|---|---|
| #3 的自动升挡形态（失败数据自动修正挡位） | **永不**（除非新裁决推翻 D6） | D6 明文只记遥测；挡位分数解耦裁决；"人的意志优先"（人工 capability 不封顶） | D6 裁决本身被重新裁决 |
| #5 的 LLM 意图直接触发 transfer/confirm | **不做** | cv-152 确定性路由方向；误路由不可逆（task_input 已投递无法撤回）；人在环路 | 出现可撤销的 transfer 机制 |
| LLM 意图结果进入相位硬闸（phase_guard） | **不做** | G1 裁决：守卫意图复用正则单源；硬闸必须确定性可测试 | #5 落地后另议，且须独立特征测试 |
| 缺陷7：KB 通用知识层/多跳推理 | **不做**（接口位保留） | 产品级决策非 architect 层职责；`mining.py::promote_to_kb` 注释已锚定 `global-promotion-design.md §6` | 该设计文档立项 |
| 缺陷4：A2A 自动移交协议 | **不做** | "人工移交"（用户选史 digest、双收件人）**是产品方向本身**，不是缺陷；共享记忆自动化违背人在环路 | 产品方向变更 |
| dossier 接入主对话链（#4 重半） | **本批不做** | 重装配（收集→裁剪→装配）直接进 chat 回合与 ctx_budget 冲突；"下一步"职能已由 flow-hints/guide 承担 | 溢出摘要通道稳定后评估是否经其接入 |
| MemoryStore 接线为统一读面 | **不做，改为退役删除** | 零调用方已验证；悬空门面误导维护者；working.py 长成事实门面 | 出现第二个记忆消费域时重建 |
| **状态迁移（derive）配置化** | **不做** | 迁移语义是防双源的根基（meta.jobs 教训）；配置它=制造第二真相源；可测试性依赖固定纯函数 | 无（架构红线） |
| 挡位刻度表（gears `_TIERS`）进 policy 配置 | **本批不做** | 策略表单源裁决+特征测试锚点（test_gears.py 按表断言）；配置化会失去可测试基线 | 单独裁决（须先设计挡位配置的等价测试方案） |
| 全局清洗 `except Exception: pass` | **不做**，只在点名路径换吞错计数 | 全量替换 diff 面失控；业务不阻塞语义必须保留 | 吞错计数稳定运行一个周期后再评估扩面 |
| mining 人审自动化（在线学习） | **不做** | 既有裁决：能力提案必经设计者采纳；学习周期天级是有意取舍 | 产品裁决变更 |
| /flow-policy 前端管理页 | **本批不做**（只出 REST） | 配置编辑属低频管理面；UI 立项另行排期 | 策略编辑频次成为真实诉求 |
| 项目级 flow policy 覆盖 | **本批不做**（schema 预留 merge 点） | 项目级 config 存储未建（roles 三级覆盖同为预留先例） | 项目级 config 基座立项 |

---

## 三、驱动架构细化（状态·规则·策略）

### 3.1 设计原则

**配置化的是行为面（每个状态里发生什么），不是迁移面（状态如何流转）。**

- 词表冻结在代码（states.py）——状态值域是类型系统的一部分，防状态爆炸（既有裁决）。
- 行为数据化——note/guard/hint/overlay/注入限额/聚合窗口全部进 `agent.flow.policy` 配置；代码只保留**版本受控的缺省值**与执行引擎。
- 三级覆盖：代码缺省 < 全局配置（CollabConfigStore）；项目级预留（同 roles 先例）。
- 写侧严格校验（fail-fast），读侧坏值回落代码缺省（fail-soft）——与 `normalize_light_tasks`/`read_overrides` 同款纪律。
- 全部行为开关并入 `agent.comp.overrides` 白名单（可逐项回退）。

### 3.2 驱动要素映射

| 要素 | 载体 | 变更方式 |
|---|---|---|
| 状态值域（6 相位/安全等级） | `states.py` 冻结词表 | 裁决+代码 |
| 状态迁移（derive） | `flow.py` 纯函数+特征测试 | 代码（架构红线，见 §二） |
| 规则（守卫意图集/回执文案/注入限额/聚合窗口/吞错路径） | `agent.flow.policy` | REST 编辑，回合级生效 |
| 策略（相位 note/P 轴 overlay/hint 模板/注入预算） | `agent.flow.policy` | 同上 |
| 挡位刻度（T0-T2 表） | `gears.py`（本批不动） | 代码 |

### 3.3 驱动基座 S0：`agent/governance/flow_policy.py`（新，~200 行）

```python
DEFAULT_FLOW_POLICY = {            # 现 flow.py 硬编码值全部迁此(代码缺省, 版本受控)
  "version": 1,
  "phases": {
    "clarifying": {"note": "<现 _PHASE_NOTES.clarifying>", "elementHints": "high"},
    "armed":      {"note": "...", "elementHints": None},
    "executing":  {"note": "...", "elementHints": None},
    "reviewing":  {"note": "...", "elementHints": None},
    "interrupted": {"note": "...",
                    "guards": [{"intents": ["generic_exec", "dispatch_extra"],
                                "reply": "<现硬闸文案>"}]},
  },
  "hintTemplates": {"armed": "有 {n} 张任务卡待执行——…", "reviewing": "...", ...},
  "injections": {
    "repairNotes":   {"enabled": True, "maxPerTurn": 3, "keepLatest": 5,
                      "weakTierMax": 1},
    "overflowDigest": {"enabled": True, "windowCap": 20, "overflowTrigger": 30,
                       "maxChars": 1200}},
  "aggregation": {"windowDays": 14},
}
def load_flow_policy(getter) -> dict       # 读配置→深合并→校验→坏值回落缺省
def validate_flow_policy(p) -> (ok, errs)  # 写侧严格: 相位名∈词表/数字钳界/意图名∈注册表/未知键拒绝
```

关键设计：

- **意图按名引用，不内嵌正则**：`generic_exec`/`dispatch_extra` 是注册名（匹配器在代码单源，`perception/intent.py` 与 flow.py），配置只选择"哪些意图被哪个相位守卫"；自定义正则写入时 compile 校验，防坏正则炸运行时。
- **REST**：`GET/PUT /flow-policy`（新 `arch_routes/flow_policy.py` 路由，~70 行）。存 CollabConfigStore 键 `agent.flow.policy`；读走每回合读模式（与 `read_overrides` 同款，无缓存失效问题）。
- **flow.py 改造**：`_PHASE_NOTES`/守卫意图选择/hint 模板委托 flow_policy（函数带 policy 参数，缺省自动 load），既有调用方零改动；flow.py 减重约 60 行（现 400 顶格，腾出余量）。

### 3.4 切片 S1-S3

**S1 = #1 修复经验回填（注入规则走 policy）**

- 写侧 `reflection/repair.py::run_repair_loop` 收尾：`ContextUnitsStore` 落 `type=repair_note`，`refs={sig, tool, ok, count}`；**按错误签名去重**（同签名→原位 update 计数+时间，不增行）；超 `keepLatest` 修剪最旧。
- 读侧 `memory/working.py` 装配：按 `injections.repairNotes` 注入 system 段（`maxPerTurn`；`model_profile.tier_of ≥ 2` 时收 `weakTierMax`）。
- 开关：`agent.comp.overrides` 键 `repair_note_injection`（缺省启用）。

**S2 = #2 消费口 + 吞错计数（聚合规则走 policy）**

- `reflection/dataset.py`：`aggregate_failures(window_days)`——按 kind/tool/model 聚合失败率+修复成功率；`stats()` 并入该维度与**吞错计数**。
- 吞错计数：dataset 内 `swallow(tag)` 进程计数器（不写盘，stats 快照）；替换范围收敛为评审点名的 `turns/context.py` + `reflection/repair.py` 装配路径 `except: pass`（约 8 处）；业务语义零变化。
- `aggregate_failures` 暴露为 mining/治理只读 API（#3 数据地基，本期不接消费端）。
- 开关：`swallow_counters`（缺省启用）。

**S3 = #4 溢出摘要 + MemoryStore 退役（预算统一收口）**

- 溢出摘要：`turns/context.py` 装配段——历史超 `overflowTrigger` 时，溢出段经 `adaptation.summarize_task` 压缩（msg_digest 同款确定性降级：LLM 失败→保持现截断行为，绝不 5xx）；**按溢出锚点缓存**于 conv meta `{overflowDigest: {anchorId, digest}}`，锚点不变不重算。
- **统一装配预算 `_apply_assembly_budget`**：repair_notes + overflow_digest + 相位注入全部过 `ctx_budget` 裁剪（总字数上限按挡位系数）——防守线③的机制化，一处管全部。
- 摘要只做装配期瞬态注入，**不落消息流**（"落库不动，真相源保留"，cv-194）。
- `agent/memory/store.py` 删除 + `memory/__init__.py` 导出清理（零调用方已验证）+ 行数基线同步删条目。
- 开关：`overflow_digest`（缺省启用）。

### 3.5 防守线（固化为特征测试）

| # | 防守线 | 对应方向 | 测试 |
|---|---|---|---|
| 1 | LLM 意图不入硬闸：`evaluate_guards` 仅消费注册的确定性匹配器 | cv-152 确定性路由 | S0 特征测试（#5 落地时同测扩展） |
| 2 | tierSuggested 永不自动写 tier/capability；人工已设时让位 | D6 + 人的意志优先 | 随 P1 #3 落地 |
| 3 | 注入预算统一：超预算裁剪、弱挡更紧、overflowDigest 不入消息表 | prompt 瘦身纪律 + 真相源 | S1/S3 特征测试 |
| 4 | policy 坏值回落代码缺省（读侧 fail-soft）；写侧严格拒绝 | 单源+fail-soft 纪律 | S0 特征测试 |

---

## 四、实施顺序与回退

S0 → S1 → S2 → S3，每片独立可回退（开关缺省启用，显式 false 关闭）。新增测试约 15 例；`memory/store.py` 删除后全量回归 + 行数棘轮/分层棘轮复验。

## 五、验收口径

1. 改一条相位 note / 守卫文案 / 注入限额 → `PUT /flow-policy` 后**下一回合生效**，零代码改动（S0 验收主句）。
2. 修复成功后的会话，下回合装配含 repair_note；同签名错误不重复注入（S1）。
3. `/llm-dataset/stats` 含失败聚合 + 吞错计数维度（S2）。
4. 30+ 轮会话：溢出段以摘要注入，锚点不变不重算；消息表无 digest 行（S3）。
5. 全量测试绿 + 棘轮门禁绿（分层/行数/grep）。

---

## 附录 A：评审事实核查（2026-09-21 复核）

| 评审主张 | 核查 | 位置 |
|---|---|---|
| comp_gap 只记遥测无消费者 | ✅ | `turns/context.py::_record_comp_gap`（D6 注释明文） |
| llm_dataset 只写不读 | ✅ | `reflection/dataset.py`——`record()`+`stats()`+`/llm-dataset/stats` 观测端点，无聚合消费 |
| 修复经验落 dataset 不回填 | ✅ | `reflection/repair.py::run_repair_loop` 收尾仅 `llm_dataset.record` |
| 工作记忆定长截断无溢出压缩 | ✅ | `memory/working.py::history_window cap=20`；`summarize_conversation` 存在但 working/turns 零引用 |
| MemoryStore 零调用方 | ✅ | 仅 `memory/__init__.py` re-export |
| dossier 仅 REST 消费 | ✅ | `sessions.py:978`（/assemble）；turns/context 零引用 |
| 意图纯正则、P5 未实现 | ✅ | `perception/intent.py`——GENERIC_EXEC_RE + DEFLECT_RE 补丁 |
| KB 通用知识层接口位 | ✅ | `mining.py::promote_to_kb` 返回 not_implemented |
| 装配路径系统性吞错 | ✅ | `turns/context.py` 多处 `except: pass` |
