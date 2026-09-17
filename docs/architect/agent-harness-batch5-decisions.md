# 批次 5 决策方案档 —— 专项与拍板项逐项分析

> 状态：待拍板（2026-09-17 编写）
> 上游：`agent-harness-evaluation-2609.md` §8.1 批次 5 行 + 随需行（A6.2/A6.4/M5 经
> 2026-09-17 裁决并入本档）。L 组（训练侧）**搁置，不进行**。
> 性质：本档只做决策支持——每项给出现状证据、外部参照、方案选项、推荐、工作量与
> **拍板问题清单**；拍板通过后各立项再出实施小档。
> 工作量口径：S ≤1 天 / M 2~3 天 / L ≥1 周（含测试与门禁）。

---

## 0. 汇总决策矩阵（先看这张表）

| # | 条目 | 推荐方案 | 工作量 | 依赖 | 风险 | 建议顺序 |
|---|------|---------|--------|------|------|---------|
| 1 | K1 格式版本化 | 表级 `schema_version` 列 + 只追加迁移链 + 版本登记文档 | S | 无 | 低 | ① |
| 2 | A6.4 steer 协议化 | 协议带 `delivery` + B1 能力矩阵降级 queue | S | 无 | 低 | ② |
| 3 | M3 轻重分船 | ~~角色表扩轻任务角色~~ **已落地：资产助理/轻任务模型两域分列**（见 §2 as-built） | S | 无 | 低 | ✅ |
| 4 | K4 @引用不读内容 | 检索返回裁剪（预览+定位符）+ 系统段显式纪律 | S~M | 探针回归 | 中 | ④ |
| 5 | M4 协议健壮性 | 受限生成为终局；前置 B4 文档单源化 + B3 handle_chat 拆解 | B4 S~M, B3 M, 受限生成 M | 网关支持面 | 中 | ⑤ |
| 6 | K3 大纲投影 | 只读大纲端点 + 侧栏跳转；分页回载随 A6.2 | S~M | 无 | 低 | ⑥ |
| 7 | M5 边界透明化 | ~~边界说明卡~~ **已随三维矩阵专项落地**（见 §11 as-built） | S | ✅ | 低 | ✅ |
| 8 | A6.2 Item 投影 | 最小投影（tool_call/file_change）+ conformance 扩展 + UI 守门 | M | conformance kit | 中 | ⑧ |
| 9 | A2 DAG/CAS | **DAG 已落地**（task_graph/就绪下发/fail-fast，depends_source 按 C 档）；writeScopes 告警尾量；CAS 暂缓 | ✅ | 中 | ⑨→尾量 |

**搁置**：L 组训练侧（roadmap Phase 2 末内容，经 2026-09-17 裁决搁置不进行；
本档不展开，M 线合流点保留在主档 §9.3 裁决③）。

---

## 1. M4 小模型工具协议健壮性（含前置 B3/B4）

> **as-built（2026-09-17，全部 4 切片落地，全量门禁 920 passed）**
> 拍板回执：A 直接全量 + 单调用/轮；B3/B4 立项先行；B+C 随行。
>
> - **切片 1 B4（`1469d74`）**：`register_architect_tool` 增 `params_doc/brief`
>   元数据参数；`cognition/prompt.py` 存量迁移表（TOOL_BRIEFS/TOOL_PARAM_DOCS，
>   与 `_CAPABILITY_DOC` 逐字对齐）；`capability_doc_from_tools` 补全（层级约定段/
>   图表输出段，diagram.* 归 diagram_skill 块）；**默认切单源**（`single_source:
>   false` 覆盖可回退等价模式）；迁移表归 cognition 层（层序合规：cognition 不反向
>   依赖 tools）。
> - **切片 2 B3（`8aad676`）**：`handle_chat` ~230 行拆为五段管线
>   （`_chat_gate/_chat_route/_chat_context/_run_llm_tool_loop/_chat_land`），
>   行为等价（kb_chat 全绿），结构守卫测试防回内联。
> - **切片 3 B+C（`c65afa9`）**：GearPolicy 增 `tool_rounds`（T0/T1/T2=4 现行为
>   不变，T3=3、T4=2 弱档更早触顶）；`protocol.tool_parse_audit` 纯审计 +
>   `record_tool_parse_fail` 埋点（llm_dataset kind=tool_parse_fail，
>   chat/sync/structured 三面覆盖），样本供探针判分用例库（挂接点接口预留）。
> - **切片 4 A（`307922d`）**：考古结论——主后端 `llm.sync` 已支持
>   `mode=structured+output_schema`（校验重试 2 次），缺口仅在 provider 层未消费
>   `output_schema`。补齐：ollama `format=json_schema` / openai_compat
>   `response_format`（均带 4xx 降级重试，回提示词约束基线）；`TOOL_CALL_SCHEMA`
>   （单调用/轮）；`structured_model_enabled`（CollabConfig `llm.structuredModels`
>   支持位，未配置=现行为）；`structured_tool_round` + `run_tools_loop` 双通道
>   （受限轮 → 空 tool 转终稿 → 失败 nudge 降级）；chat 循环两段式（受限工具轮
>   非流式 + 文本终稿轮流式）。
> - **待办尾巴**：支持位自动写（探针 structured 冒烟用例）、支持位配置 UI、
>   真机 Ollama/LM Studio 冒烟（零代码验证）。

### 1.1 现状（代码证据）

- 主 agent 工具调用是**文本协议**：`agent/tools/protocol.py:20` 的
  `_TOOL_CALL_OPEN` 正则容忍 ```json 围栏/裸块两种形态；`req_agent.py:1237`
  统一工具调用循环，注释明言「两条入参链（[TOOL_CALL] / ```proposal 围栏）」。
- 守卫链现状：`req_agent.py` 1861 行，含 `_repair_json_like`（JSON 修复，
  经 `planning/req_spec.py:60`）与多级格式兜底；**缓解守卫已按用户裁决拆除**
  （cv-175，`orchestrator.py:453` 注释：「缓解守卫已按用户裁决拆除」）。
- `orchestrator.py` 800 行，`handle_chat`（:272 起）约 230 行——闸门/路由/
  上下文组装/挡位/工具循环/落库混在一个函数体（B3 的拆解对象）。
- 工具文档双轨：`@register_architect_tool` 的 description（registry 单源）与
  system prompt 内嵌的工具用法示例（如 `req_agent.py:989`「产出通道二选一…」、
  `:1438` diagram 示例）**各自演化**（B4 的单源化对象）。

### 1.2 问题

弱模型更易错格式：每次换档/换模型版本都可能催生新守卫；守卫链是主 agent
复杂度最大来源（agent-structure-review §三）。cv-175 已裁决「不再堆缓解守卫」，
方向只能是**消灭守卫存在的原因**。

### 1.3 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 受限生成 | provider 支持时按挡启用 json_schema 约束解码（Ollama `format`/LM Studio/llama.cpp `grammar`/vllm guided 均支持），工具调用经结构化通道直达，文本协议退为兼容层 | M（改 LLM 调用面 + 模型目录加 `structured` 支持位 + 探针验证） | 网关/后端代理链是否原样透传 format 参数需实测；不同 provider 行为差异 |
| B. 修复预算按挡 | GearPolicy 增 repair 维度：弱模型 repair 预算更高、工具轮次上限更低（数据驱动，进策略表） | S | 低；与已落地的 M2 五维同构 |
| C. 失败样例回流探针 | 线上真实错误格式样本沉淀为探针判分用例（orchestration-plan §7 已列），探针套件随实战校准 | S | 样本收集需要埋点（llm_dataset 已有 record 通道可复用） |
| 前置 B4 | 工具文档单源化：system prompt 内嵌工具示例全部改为从 registry 渲染 | S~M | 纯重构，回归面为主 agent 行为等价 |
| 前置 B3 | `handle_chat` 拆解：按 闸门/路由/上下文/执行/落库 五段拆为模块函数（不引入新抽象层） | M | 行为等价回归（`test_kb_chat*` 既有测试为门禁） |

### 1.4 推荐

**A 为终局方向 + B/C 立即可做；A 的第一步是支持面实测**（不改代码，先对目标
provider 跑 format=json_schema 冒烟，确认网关透传与行为）。B4/B3 作为独立重构
先行——它们同时服务可维护性，不依赖 A 的拍板结果。

### 1.5 拍板问题

1. B3/B4 两个前置重构是否立项（与 M4 主线解耦，随时可开工）？
2. 受限生成的 provider 覆盖目标定哪些？（建议：Ollama + LM Studio 为主，
   vllm 次之；目标外 provider 保持文本协议现状）
3. 修复预算按挡（B）的初版参数表是否授权我按探针档位拟定、以配置数据先行？

---

## 2. M3 轻重任务分船（mixed-fleet）

> **as-built（2026-09-17 落地，`d24984b`，全量门禁 926 passed）**
> 拍板回执：域 1 改名「**资产助理**」、域 2 新增「**轻任务模型**」（按领域分列
> 命名——现有六角色属数据资产·语义分析管线，编排侧轻任务不复用「角色」词，
> 避免与已清退的会话角色产生认知混淆）；含 ConfigPage UI。
>
> - **域 1 资产助理**（显示层改名，零行为变化）：`cognition/roles.py` docstring
>   重写（两代角色切割声明：与 T4 清退的会话角色无涉）；ConfigPage/i18n 分区
>   标题与说明同步；代码标识符、REST `/agent/roles`、存储键不动。
> - **域 2 轻任务模型**（新增）：`governance/light_tasks.py` **纯函数层**
>   （词表 summary/probe——标题与摘要同一次调用故不设 title 死键；
>   `normalize_light_tasks` 词表外键忽略+越界 modelId 剥离〔cv-168 同源教训〕；
>   `resolve_light_task_model` 宽容读取绝不抛出）；存储读写/模型目录校验留
>   适配层 `agent_roles.py`（`GET/PUT /agent/light-tasks`）——**R1 棘轮合规，
>   零新冻结条目**。
> - **接线（仅 2 处，消费方注入 cfg）**：`memory/units.summarize_conversation` →
>   `summarize_task(model_id=...)`（原语本就支持 model_id）；`scope_probe` →
>   `llm_sync(model_id=...)`。空配置 = 现行为零变化。
> - **裁剪**：原 B 项（GearPolicy `lightTask` 联动）不做——显式配置已足够，
>   挡位联动属多余间接层。原 C 项（步骤级异档）随 A2 DAG 合流（不变）。
> - 配置入口：设置页「模型分派」tab 两个分区（资产助理/轻任务模型）+ REST。

### 2.1 现状

- **角色模型路由已存在**：`agent/cognition/roles.py:110 resolve_role_model`
  （explicit > 角色注册表 > 回退全局偏好；per-call 参数不写全局配置），
  6 个默认角色（extract/verify/induce/pseudo/evaluate/mine，
  `arch_routes/agent_roles.py:21`），REST `GET/PUT /agent/roles`。
- **能力档案已存在**：`model_profile.get_profile_or_lazy` 在 `handle_chat`
  每轮懒探测（`orchestrator.py:400-405`）；GearPolicy 五维（批次 2 M2）。
- **缺口**：编排侧轻任务——会话标题/摘要（`sessions.py:348 summarize_session`
  → `context_registry.summarize_conversation`）、范围探针
  （`planning/scope_probe.probe_scope`）、任务链 brief 等调用**未走角色路由**，
  全部落主对话模型（可能是强档）。
- 任务卡已可绑定执行器（异档执行存在）；步骤级异档无载体（依赖 A2）。

### 2.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 角色表扩轻任务角色 | 新增 `title`/`summarize`/`probe` 三个角色（默认空=现行为），上述调用点接 `resolve_role_model` | S | 极低：默认空不改变任何现有行为 |
| B. 挡位驱动建议 | GearPolicy 加 `lightTask` 字段：按挡建议轻任务模型档（strict 档允许轻任务走小档） | S | 低 |
| C. 步骤/角色级异档 | taskPlan 节点带 executor+model 标注 | M~L | 依赖 A2 立项 |

### 2.3 推荐

**A+B 组合**（合计 S~M）：先让「分船」在角色表+策略表两层有数据载体，
调用点逐个接入；C 不单独立项，随 A2 DAG 合流（DAG 节点带执行器+挡位标注
本就是 A2 的设计的一部分）。这与 opencode `getSmallModel`、dsh roster
按成员指定模型同构，但我们已有更好的载体（角色表），不需要新机制。

### 2.4 拍板问题

1. 轻任务清单范围确认：标题/摘要/范围探针/链路 brief 之外，是否含
   KB 摘要写入、验收简报生成？（建议含——「KB 供数两端小模型可承担」）
2. 轻任务角色的 UI 配置入口：复用现有角色配置页还是暂走 REST？
3. 是否要求「轻任务强制小档」（省算力优先）还是「可配但默认回退主模型」
   （稳妥优先）？建议后者。

---

## 3. A2 taskPlan 升级 DAG/CAS

### 3.1 现状

- `taskPlan` 为 JSON 列：`[{seq, title, instruction, taskId, status}]`
  （`planning/task_plan.py:257`），**顺序下发**（seq 递进，第一步建卡 →
  完成回填 → 预填下一步），无依赖字段。
- `arch_tasks` 无依赖表；互斥保护是声明级 `check_mutex`（边界文件交集）。
- dsh 参照（主档 §四已核实）：`blockedBy` 边 + DFS 环检测
  （`assertTaskGraphCandidate` 拒 self/duplicate/missing/cycle）、
  状态机 + `expectedRevision` CAS、`writeScopes` 建议性路径前缀（明确「不是锁」）。

### 3.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 最小 DAG | taskPlan 项加 `depends: [seq]`；建下一步前校验（环检测 + 依赖完成判定）；顺序下发改**就绪下发**（依赖全完成才建卡）；失败语义 = 阻塞后继（fail-fast），waiting_input 不算失败 | S~M | 计划卡 UI 需展示依赖关系（可先用文本标注） |
| B. 完整 CAS 状态机 | 独立 task-board 表 + revision 整快照 + 乐观并发 + 8 action | L | 并发冲突场景在「单用户确认制 + architect 单编排者」下基本不存在——CAS 收益低、复杂度高 |
| C. writeScopes 告警 | 步骤声明路径前缀与既有边界做重叠告警（确认前提示，与执行中 `check_mutex` 互补） | S | 低；纯提示不拦截 |

### 3.3 推荐

**A + C，B 暂缓**。理由：本系统任务编排的并发写入口只有 architect 编排层与
用户确认（人在环），dsh 的 CAS 是为多 agent 自主认领的并发场景设计的
（那部分自主权我们明确不采）；只采数据结构（DAG）与校验机制（环检测）。
若未来出现多编排者，再升 B 不迟——A 的 `depends` 字段与 B 的边模型兼容。

### 3.4 拍板问题

1. 失败依赖语义：步骤失败 → 后继全部阻塞等待人工（推荐），还是允许
   标记「跳过后继继续」？（决定状态机分支数量）
2. DAG 可视化是否本期做（前端 taskPlan 卡升级）还是文本标注先行？
3. C 的告警展示位置：任务确认卡内（推荐）？

---

## 4. K1 知识资产格式版本化

> **as-built（2026-09-17，4 commits `c3751da`→`b8f3857`，971 passed）**：
> 原推荐 B（arch_assets 加版本列）被**知识资产体系收敛专项**取代（需求重对齐裁决：
> L1 语义资产=基础 / L2 词典=外围映射 / L3 会话派生=主战场 / L4 严格 SWE 工件=降级退役）。
> 落地：P0 arch_assets 退役（回执→execution_report/里程碑→analysis/错误→error 单元，
> asset.* 工具→artifact 单元，REST /assets→/units，AssetsPanel 切换；顺带修复存量 bug：
> failed 回执因 rid 未定义从未沉淀）；P1 错误提炼（distill.py build/land 分离，手动触发
> `POST /sessions/{id}/distill-errors`，error_pattern 项目级单元，签名=粗类别+project，
> 归因以 coding agent 失败回执为准）；P2 ctx.search 词典检索侧扩展（glossary_map 纯函数，
> 外围独立循环不进提示词）；P3 K1 版本化对象改为新持久四表（schema_version+只追加迁移链+
> 惰性迁移，登记文档 `kb-schema-versions.md`，含 P2-T6 提升通道预留）。
> 需求/验收合并方案：**另开专项讨论**（主业务链暂保留原状）。

### 4.1 现状

- `arch_assets`（2026-09-17 批次 4 K2 建立）：`meta TEXT`（JSON 载荷，键随
  沉淀来源演化——task_receipt 携 changedFiles/verifyOverall，milestone 携
  files/merged，llm 自由）。**无版本字段**；kind/source 词汇表常量在
  `store/assets.py`（ASSET_KINDS/ASSET_SOURCES）。
- 迁移先例已在库内：requirements 的 `spec_versions` + `active_ver` 初始化
  迁移（`db_schema.py:623-663`）、`_add_cols` 列迁移模式（:567）。
- dsh 参照（主档 §三）：双权威版本常量、不可变代际 + 流式迁移、Catalog
  静态校验；但 dsh 为 jsonl 文件模型，**明确指出与 SQLite 冲突**——
  TopoCode 应取「表内版本字段 + 只追加迁移链」形态。

### 4.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. meta 内嵌版本 | meta JSON 首键 `v: 1`，读时惰性迁移 | S | meta 由 llm 自由写入时易丢键 |
| B. 表级版本列 + 迁移链 | `arch_assets` 加 `schema_version INTEGER DEFAULT 1`；`store/assets.py` 增只追加迁移函数链（vN→vN+1 注册制）；版本登记表写进本档附录（变更 meta 键必须 bump + 写迁移 + 测试） | S | 低 |
| C. dsh 全套（双权威/Catalog/代际不可变） | 过度设计 | L | 与 SQLite 行式模型冲突 |

### 4.3 推荐

**B**。一条纪律即可立起来：**meta 键结构变更 = bump schema_version + 注册
迁移函数 + 快照测试**；读路径惰性迁移（旧行读时补默认键，不批量刷库）。
是否扩散到 KB 文档表/语义资产：**本期只登记不迁移**（在版本登记文档中为
各表预留版本语义，实际迁移待对应表首次破坏性变更时启用）——避免为未发生
的变更建机制（负面空间纪律）。

### 4.4 拍板问题

1. 覆盖范围确认：仅 arch_assets 落迁移链，其余表只登记？（推荐是）
2. 迁移时机：读时惰性（推荐）vs 写时批量？

---

## 5. K3 turn-outline 式大纲投影

### 5.1 现状

- 会话消息全量拉取：`GET /sessions/{id}/messages` 返回全部消息，前端一次性
  渲染；长会话（数百轮+回执卡）无导航手段。
- dsh 参照：`session-turn-outline` pure-fold 出 `{seq, prompt 预览 50 字符,
  response 预览 120 字符}`，seq 即分页回载目标。

### 5.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 只读大纲端点 + 侧栏 | `GET /sessions/{id}/outline`（O(turn) fold：role/时间/首行预览/消息 id）；前端会话详情加大纲侧栏，点击滚动定位 | S~M | 纯只读投影，零协议变更 |
| B. seq 分页回载 | 消息窗按 seq 分页懒加载 | M | 涉及消息窗虚拟化改造，应随 A6.2 前端改造合流 |
| C. 文档目录树 | session-docs 列表已有，补文档内 H2 大纲 | S | 低 |

### 5.3 推荐

**A 起步（+C 顺带），B 随 A6.2 合流**。纯只读投影符合「零新协议」原则；
分页回载是前端架构工程，不该由 K3 单独触发。

### 5.4 拍板问题

1. 大纲面板入口：会话中心详情页（推荐，空间充足）还是 dock 内浮层？
2. 大纲颗粒度：每条消息 vs 仅 user/assistant 回合对（dsh 是回合对）？
   建议回合对 + 回执卡单独标注。

---

## 6. K4 @引用不读内容原则

### 6.1 现状

- 前端 @引用按钮（`AnalysisChat.vue:1843` AtSymbolIcon）插入的是
  「名称+ID」**纯文本**——引用本身已不携带内容 ✓。
- KB 检索工具（arch.* 工具面）返回**含全文内容**的结果块进上下文；
  范围探针/任务链 brief 组装时也整块注入。
- workspaceFiles 规约落盘（`_build_workspace_files`）：内容进 worktree
  文件而非上下文——已符合「引用不倾倒」精神，但未成文为统一纪律。
- dsh 参照：`file-reference` 只插文本，内容必须经 read 工具按需取
  （可观测、可计费、上下文有界）。

### 6.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 检索返回裁剪 | KB 检索/资产列表工具返回「预览（首 N 字符）+ 定位符（assetId/路径）」，模型要看全文必须调 `asset.get`/读文件工具 | S~M | **行为变更**：现有 agent 提示词与习惯依赖检索即得全文；需探针回归验证弱模型能正确二次取用 |
| B. 系统段显式纪律 | 系统提示词注入「引用=指针，内容按需取用」纪律段（弱模型需要显式指令，dsh FILE_REFERENCE_PROMPT 同理） | S | 低 |
| C. 引用对象类型化 | `@asset:`/`@doc:`/`@file:` 前缀 + 后端解析器统一路由 | M | 随 A6.2/A2 前端改造合流更划算 |

### 6.3 推荐

**A+B，C 缓**。这是「分析→使用」的边界纪律成文化；关键是 A 的回归验证——
建议先以探针套件加「两跳取用」（检索→定位符→取全文）用例再切。

### 6.4 拍板问题

1. 是否接受检索工具行为变更（预览+定位符）？——这是对 agent 使用习惯的
   真实改变，需要探针数据背书。
2. 裁剪阈值：预览长度与单次返回条数按挡收缩（M2 上下文预算维度）是否
   本期一并落？（建议一并，数据同源）

---

## 7. A6.2 Item 投影（随需并入）

### 7.1 现状

- 前端渲染按事件卡分支：`meta.kind`（task_card/task_approval/task_input/
  task_verify…）+ ChatMessageBlocks + progress 轮询浮层
  （`useChatProgress` ToolTrailItem）——执行器差异目前被泵层吸收，但
  渲染层无统一投影，新执行器 = 新卡片分支风险。
- codex 参照：Thread/Turn/Item 三原语 + `as_legacy_events()` 兼容桥
  （主档 §四）；UI 守门规则已定：「前端只渲染统一投影，禁止按
  executorType 分支渲染，特有能力经 B1 矩阵显式开关」。

### 7.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 全量投影 | runner 侧 Item 投影器（tool_call/file_change/plan/reasoning 四类）+ SSE/REST 暴露 + 前端 ItemTimeline 全量替换 | L | 一步到位但回归面大 |
| B. 最小投影先行 | 先做 tool_call + file_change 两类 Item 投影器（纯函数 + conformance kit 扩展断言映射语义），前端以并列组件渐进替换，存量卡片走 legacy 通道不动 | M | 分步替换期两套渲染并存（以 legacy 桥约束一致性） |
| C. 不立项 | 维持事件卡 | 0 | 新执行器/新前端改造时技术债加重 |

### 7.3 推荐

**B**。投影器先以纯函数 + 契约测试落地（不改任何现有渲染），前端替换
作为独立切片随下次前端改造窗口进行。UI 守门规则（禁 executorType 分支）
自投影器落地之日起生效为验收标准。

### 7.4 拍板问题

1. 立项范围：B（推荐）还是 A？
2. 前端替换节奏：并存渐进（推荐）还是一次性切换？

---

## 8. A6.4 steer 协议化（随需并入）

### 8.1 现状

- `implement.py:257 user_input(text, steer)`：busy 时 steer=true 且
  `adapter.steer` 存在才直达（**仅 cline 实现**）；否则落输入队列
  （回合尾注入）。`steered` 标志已进事件。
- 差异未协议化：architect 侧不知道「这次输入是直达还是排队」，用户体验
  与排错都靠猜测。opencode V2 `delivery: "steer"` 是现成协议先例。

### 8.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 协议语义分离 | 输入请求带 `delivery: "steer"\|"queue"`；B1 能力矩阵加 `steer` 位；不支持 steer → 显式降级 queue + 回执说明（「已排队，当前回合结束后送达」） | S | 低 |
| B. 补齐 opencode/codex 原生 steer | M~L | 依赖执行器原生能力（codex 无 steer 语义），违反「通道在契约层」原则 |

### 8.3 推荐

**A**。批次 3 已落 ServerRequest 形态与 pending_requests 登记，本项是其
自然补齐（`requestId` 已在，加 delivery 语义即可）。B 不做——runner 对下
仍用原生协议。

### 8.4 拍板问题

1. 降级提示文案与展示位置（回执卡 vs 任务卡状态行）——默认建议回执卡。

---

## 9. M5 能力边界前端感知（随需并入）

### 9.1 现状

- 已有：探针 REST（`agent_executors.py:299-360` 启动/状态/一次性 probe）、
  档位 chip（`ConversationDock.vue:368` tier==='t4' 分支）、
  `model_profile` 懒探测落档。
- 缺：边界说明（该模型不擅长什么）、探针历史曲线、运行时降档提示。
- M1 演进（运行时信号回流：loopguard 触发率/repair 频次按模型累计）是
  降档提示的数据前提，M1 本身未立项。

### 9.2 方案选项

| 选项 | 内容 | 成本 | 风险 |
|------|------|------|------|
| A. 边界说明卡 | model_profile 档案 → 前端展示「实测 T2 (4/5) + 不擅长类型 + 建议」hover 卡/详情块 | S | 低（数据已有） |
| B. 探针历史 | 每次探测落历史行 + 前端曲线（模型能力随版本漂移可见） | S~M | 低；需小表或复用注册表 history 键 |
| C. 降档提示 | M1 运行时信号回流 → 异常升高提示重探/降档 | M | **依赖 M1 立项**；阈值需实测校准 |

### 9.3 推荐

**A+B 先行（合计 S~M），C 随 M1**。C 无数据源不立项；A+B 让「模型是可分析
对象」主张先可见。

### 9.4 拍板问题

1. 展示位置：执行器配置页（推荐）+ 会话头 chip 悬浮卡，是否认可？
2. B 的历史保留策略（建议：全量保留，单执行器行数可控）。

---

## 10. 建议实施顺序与拍板回执格式

**建议顺序**（依赖与风险排序，非强制）：K1 → A6.4 → M3 → K4 →
M4（B4/B3 前置可与任意项并行）→ K3 → M5(A+B) → A6.2(B) → A2(A+C)。

**拍板回执格式**（每项回三条即可）：

```
#   条目   : 立项 / 缓 / 不做
  方案选项 : 认可推荐 / 指定其他选项
  拍板问题 : 1.x 2.y 3.z（逐条答）
```

**跨项依赖备注**：
- M2 五维（已落地）是 M4-B、K4-裁剪阈值、M3-B 的策略表载体——三项均以
  「进策略表一行」方式落地，不新增散落分支。
- A6.2(B) 的 conformance 扩展与批次 3 `adapter_conformance.py` 同文件演进。
- A2(A) 的 `depends` 字段与未来 DAG 节点执行器标注（M3-C）兼容。
- K1 的版本登记文档建议落 `docs/architect/kb-schema-versions.md`。

---

## 附录：批次 4 关闭快照（2026-09-17）

- 批次 4 全项（V1~V5 / K2 后端 / jest-vitest 适配器 / 验收配置 UI /
  AssetsPanel / A1 增强）已落地，全量门禁 900 passed，commit 至 `87310c0`。
- 本档并入的随需三项（A6.2/A6.4/M5）自主档随需行移入；L 组搁置。

---

## 11. 三维能力矩阵专项 as-built（2026-09-17，7 切片全落地）

> 本专项由 A2 粒度讨论 + M5 并入讨论升级而来（用户架构裁决），收编 M1 完整版/
> M5/M4 structured 位/A2 depends_source。**全量门禁 951 passed**（8 commits：
> `a652231`→`61bfe45`）。

### 定则（用户逐条拍板）

1. **双维分立**：A 轴（architect 模型能力）与 C 轴（coding agent 模型能力）是
   两个维度——**统一测评标准（同探针维度/同刻度/同准入），分立档案**；
2. **刻度收敛 T0-T2**：语义由规则细则定义（策略表注释），旧 T2/T3/T4→T2 读路径
   归一，别名兼容一个版本；
3. **职责归属**（无综合评分）：一个策略字段一个职责方，值=职责方能力档直推——
   C 弱 → A 在需求分析/方案设计/任务编排补（拆更细/结构化/核心逻辑图）；
   A 弱 → 调度机制（确定性管线）+ 用户要素提示 + KB grounding 补；
4. **U 轴不测评用户**：A 弱 → **要素框架提示**（按五要素清单展开澄清，引导用户
   喂全信息）；override 通道 = 既有会话挡位钉死 + 任务卡执行器切换；
5. **准入机制**：测评不足明确提示但不强制退出（可按 T2 最低档全面补偿运行）；
6. **补偿组件复用**：组件与挡位解耦（挡位只定启用+强度），如隔离修复循环。

### 落地明细

| 切片 | Commit | 内容 |
|---|---|---|
| 1 刻度收敛 | `a652231` | gears T0-T2 三行全字段重排 + depends_source/logic_diagram 新字段 + 旧值归一（resolve/REST/执行器写侧）+ probe_hard_cap 新刻度（兼容旧「上限T3」文本）+ 前端档位选项 |
| 2 双维档案 | `f3e04e2` | `probe_suite.py` 统一标准（维度权重/刻度/准入/structured 判据）；**用例接系统实际能力**（真实注册工具+系统基本指令，parse_fn 注入保持层序）；A 档案 structured 位+admission 字段；C 轴刻度归一+probeStructured |
| 3 双轴 resolve | `8ba9ce8` | GearPolicy 增 A 轴字段 schedule_discipline/element_hints；`resolve_gear(mode, c_cfg, architect_model_id)` 职责直推；chat/task 消费接线；R2 横切豁免修正 |
| 4 补偿组件 | `a947ff8` | `repair_tasks.py` 修复任务注册表（register_repair 扩展点）；tool_call 隔离修复（未知工具名幻觉，每调用限 1 次，失败如实）；三处执行点接入；样本落 llm_dataset |
| 5 U 轴 | `e83a0c1` | ELEMENT_HINT_HIGH/MID（五要素=既有约束项，非新词汇）；按 element_hints 密度注入对话系统段 |
| 6 A2 接入 | `4723878` | `task_graph.py` 纯函数（validate 自依赖/悬空/重复/环 + ready + linear）；split_tasks_llm depends 声明（llm 挡）；弱挡线性链兜底；就绪下发+fail-fast（waiting_input 不解锁，失败阻塞后继等人工） |
| 7 M5 投影 | `61bfe45` | A 轴：档位徽标+structured+T2 准入 ⚠+历史时间线；C 轴：实测 T2 ⚠ 准入标注——均提示不拦截 |

### 尾量

- A2 writeScopes advisory 告警（确认卡内重叠提示）
- M2 尾维消费深化（reasoning_effort→provider 参数；tool_surface→MCP 注入裁剪实接）
- runtimeSignals 运行时信号回流（M1 预留字段已置，降档自动提示待数据积累）
