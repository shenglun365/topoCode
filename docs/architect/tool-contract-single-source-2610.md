# 工具契约单源架构（tool contract single source）— MS-B/C/D 细化设计

> 状态：**待评审** | 日期：2026-10-10 | 上游：harness 全面审计（三路：契约完整性 48 工具 / 提示词装载面 / 执行链硬编码）
> 已落地前置：**MS-A**（commit 2083b0f6/4091f8f2/2308f256/4fe84eb1）——arg_aliases 声明式机制 + S0 写工具契约补齐 + S1/S2 漂移修复 + 错误截断结构化。
> 核心原则：**handler 签名是唯一真相源 → 注册表是唯一契约载体 → 提示词从注册表渲染、执行面从注册表执法**。任何参数知识不允许手写在提示词/调度层。

## 0. 审计事实基线（2026-10-10）

| # | 事实 | 依据 |
|---|---|---|
| F1 | 48 工具中注册点 params_doc 覆盖 3→现 15（MS-A 后），brief 覆盖 2；零教育从 18 降至 3（agents.md.init 无参数无害 + 主面零教育已补） | AST 全量对照 |
| F2 | 「文档教不存在的参数」硬漂移已修（capability.evaluate/execId 两处）；req.amend 双源已对齐 | golden 再生核证 |
| F3 | capability 块 `required=True` 免疫预算裁剪：恒置块 ~7.2K > T2 实际预算 5.6K（26000×0.35），预算防线在最弱模型失效 | prompt.py:32,224 + gears.py:102-133 |
| F4 | GU 限面只裁 capability 块：answer 纯读面仍注入 653+ 字 ir_schema、333 字 skill_catalog；propose-task 面的 REQ_CARD_DISCIPLINE/posture 仍教 req.amend/req.propose——同一条 system 内指令自相矛盾 | render_system 块条件核证 |
| F5 | skill_catalog 恒定全量注入 6 条**非工具**技能 + 「不得绕过可用技能」强制路由指令——模型照目录调用得到「未知工具」 | sem/skill_catalog.py:46-47 |
| F6 | 减载回吐：GU 面批丁目标 1,750 字 → 实测 3,439-4,140 字（read 面恒供 23 工具 + 工具总数 41→48 自然增长），无棘轮约束 | 渲染实测 |
| F7 | 参数别名知识 5 处散落三套实现：req.amend 内联折叠(80 行硬编码)/`_SPEC_FIELD_ALIASES`(声明式先例)/task_plan 4 组 or 链/help.lookup 签名级/units 值形状 | 逐处核证 |
| F8 | 「落卡工具」同族概念 4 模块 4 张表：`_CARD_LANDING_TOOLS`/`CARD_ROUND_CLOSINGS`/`_ARCHIVED_DENY_TOOLS`/`_ARTIFACT_TOOLS` | 语义同源各自维护 |
| F9 | cv-174 重复提案守卫 4 处重复实现，回执文案已漂移（「本次循环」vs「本回合」） | chat.py×3 + req_agent×1 |
| F10 | 协议文案作协议：memory/working.py 按前缀「结构化工具调用未成功」跳信封——改文案即静默破坏；「复制实现」三处耦合（task_plan 定义/exec_bridge 检测+渲染） | 跨文件核证 |
| F11 | 词表双源：`_BUILD_MARK_RE`（goal.py/help_docs.py 逐字重复）；剥标题正则两版已分叉（commands.py:139 vs req_spec.py:429） | diff 核证 |
| F12 | 死代码 4 处：`_GUARD_REPAIR_TOOLS`(含退役 req.finalize)、chat.py:598 "choices" 死条件（tools_used 无 add 点）、`_SPEC_TOOLS` 休眠豁免分支、CTX_CAPABILITY_LINES | 零引用核证 |
| F13 | 声明式标杆已在仓：决策表+toolClasses(fnmatch)、`_RETIRED_TOOLS`、`KB_FACE_TOOLS`、MS-A 的 arg_aliases——MS-B/C/D 全部对齐此风格 | — |

---

## 1. MS-B 契约机械化（签名生成 + 硬门禁 + 双表退役）

### 1.1 目标

1. params_doc 缺省时**从 handler 签名自动生成**（参数名/类型/默认值→必填标注），消灭手写遗漏类漂移的生存空间
2. 契约校验**硬门禁**：CI 机械断言，漂移即红（存量漂移 MS-A 已清零，具备启用条件）
3. `TOOL_PARAM_DOCS`/`TOOL_BRIEFS` 迁移表与 legacy `_CAPABILITY_DOC` 回退通道退役——教育面回到注册表单源

### 1.2 分步设计

**B1 签名自动生成兜底**（`registry.py`）
- 新增 `derive_params_doc(fn) -> str`：`inspect.signature` + 类型注解 → JSON 形状串；无默认值位置参数标 `(必填)`；`root/project` 标注「自动注入」
- `architect_tools_full()` 渲染面：`entry.params_doc or derive_params_doc(handler)`——零教育工具自动获得形状正确（但无语义说明）的兜底文档；语义说明仍鼓励手写

**B2 契约硬门禁**（新增 `tests/test_tool_contract.py`）
- 断言逐工具：①params_doc 中出现的参数名 ⊆ 签名参数 ∪ arg_aliases 键 ②无默认值位置参数在 params_doc 中标「必填」③arg_aliases 目标 ∈ 签名 ④brief 非空（或显式豁免清单）
- 解析 params_doc 用 tolerant JSON-ish 提取（现有条目多为放宽 JSON），失败=漂移红灯
- **豁免清单**入 `tests/goldens/grep_whitelist.json` 同款机制，逐项带理由

**B3 迁移表退役**
- `TOOL_PARAM_DOCS`/`TOOL_BRIEFS` 现存条目逐条迁注册点（27 条中 MS-A 已补大部分语义，剩余以注册点为准对齐）→ 两表删除，`capability_doc_from_tools` 删除表回退分支
- legacy `_CAPABILITY_DOC` 回退通道（`single_source:false`）退役：`_r_capability` 不再回退（注册表渲染已全覆盖），`chat_system_prompt_legacy` 保留为历史 API 但生产链路断开——**连带删 F12 死代码 `CTX_CAPABILITY_LINES`**
- 随附：prompt golden 再生（-3 源删除后渲染等价断言）

### 1.3 验收门禁

1. `test_tool_contract.py` 全绿（硬门禁生效）
2. `grep -rn "TOOL_PARAM_DOCS\|TOOL_BRIEFS" apps/architect/topoone_app_architect` 零命中（迁移完成）
3. golden 再生 diff 过目=仅删除性变化；全量 pytest 绿

---

## 2. MS-C 教育面=执行面（GU 全 block 感知 + 预算恢复 + 减载棘轮）

### 2.1 目标

1. gu_allowed 从「只裁 capability」扩为**全 block 条件装载**——消除 F4 的同 system 自相矛盾
2. capability 块预算化拆分，恢复 T2 防线（F3）
3. skill_catalog 纪律修正（F5）+ GU 面体积棘轮（F6）

### 2.2 分步设计

**C1 GU 全 block 感知**（`render_system`/`_chat_context`）
- ir_schema 块：仅当 allowed 面含 `diagram.*` 或 allowed=None 且 tool_surface 允许时注入；纯读/落卡面不注入（653 字减载）
- skill_catalog/skill_docs 块：仅当 GU action ∈ 需求分析族（clarify-first/propose-requirement/continue）或 allowed=None 时注入
- posture/boundary 的 req 系教育保持恒定（人格判据非工具教育，GU-3 纪律）；REQ_CARD_DISCIPLINE 段按 allowed 面是否含 req.propose/req.amend 条件拼接
- block 条件以注册表数据驱动：新增 PromptBlock 可选参数 `tools_dep: Callable[allowed]→bool`，不写工具名清单

**C2 capability 预算化拆分**
- 拆两段：基础契约（工具名+brief 一行，required）+ 参数文档段（逐工具 params_doc，**可裁剪**，priority 介于 ir_schema 之下）
- `trim_optional_blocks` 先裁参数文档段再裁其它；T2 预算下参数文档收缩为「面内工具子集」（与 gu_allowed 联动）
- 预算刻度核对：恒置块（header/boundary/posture/基础契约）目标 ≤ 3K，T2 实际预算 5.6K 下留出历史+指引空间

**C3 skill_catalog 修正**
- 目录 6 条 `_ARCH_SKILLS` 与可调用工具的关系显式化：目录条目标注「流程技能(指导执行路线)」而非工具；「不得绕过可用技能」改为「按技能路线执行时遵循其步骤」——消除「调用即未知工具」的误导
- 装载条件并入 C1（需求分析族面才注入）

**C4 减载棘轮**（新增 golden 断言）
- `test_prompt_goldens` 增断言：GU 限面场景（模拟 propose-task/answer 面）渲染字数 ≤ 4,100（当前实测上限）——后续只许降不许升；降至 ≤3,500 时收紧刻度
- 对齐批丁「能力文档子集 1,750 字」目标作为长期方向记录，不设激进刻度

### 2.3 验收门禁

1. 模拟 propose-task 面：渲染 system 不含 REQ_CARD_DISCIPLINE 的 req.amend 指令、不含 ir_schema/skill_catalog——grep 断言
2. answer 纯读面：ir_schema/skill_catalog/skill_docs 零注入
3. T2 档渲染总字数 ≤ 5,600（预算防线恢复）——golden 断言
4. 全量 pytest + 前端 smoke 绿

---

## 3. MS-D 声明式收编（散落特判归一 + 死代码清理）

### 3.1 目标

机制与契约分离贯彻到全部散落点（F7-F12）；不改变任何运行行为（纯等价重构+删死码）。

### 3.2 分步设计

**D1 注册表标志位**（`register_architect_tool` 增 `flags`）
- `landing_card=True`：统一 `_CARD_LANDING_TOOLS`(chat.py:30)/`CARD_ROUND_CLOSINGS`(builtin.py)/`_ARTIFACT_TOOLS`(units.py)；`deny_archive=True` 收编 `_ARCHIVED_DENY_TOOLS`——四处消费改读 `entry.flags`
- `idempotent=True` + 守卫机制化：cv-174 重复提案守卫从 4 处重复实现收编为 run_arch_tool/工具环单点（文案单源，消除「本次循环/本回合」漂移）
- `hidden=True`：diagram.build/validate 的 capability 排除元组（prompt.py:431）改标志位；`doc_after` 字段收编 map.graph 层级约定锚定（:445）

**D2 前置条件声明**（`requires`）
- goal.py:397-399 的 `"req.amend" in tools and not boundReq → 剔除` 改注册声明 `requires="boundReq"`；GU 接线层读声明统一剔除

**D3 协议文案常量化**
- `STRUCTURED_NUDGE_PREFIX`（「结构化工具调用未成功」）：req_agent/chat.py 产出方与 memory/working.py 消费方同引常量
- `NEED_INPUT`/`IMPLEMENT_DONE`/`DECLARED_REPLICATION`(「复制实现」)：task_plan DoD 定义处 → exec_bridge 检测/清洗处同引
- exec_bridge.py:700/805 runner 回声清洗正则提模块常量（同文件两重复）

**D4 词表单源化**
- `_BUILD_MARK_RE` 单源化（help_docs.py 引 goal.py 或下沉 perception/vocab.py）
- 剥标题正则统一（commands.py:139 与 req_spec.py:429 两版分叉，择一为单源，行为以 req_spec 版为准——其更严格且服务规约快照）

**D5 死代码清理**（F12 四处 + 顺带）
- `_GUARD_REPAIR_TOOLS`（req_spec.py:30）、chat.py:598 "choices" 死条件、`_SPEC_TOOLS` 休眠豁免（req_agent.py:232，语义并入注册 flags）、`CTX_CAPABILITY_LINES`（units.py:38，随 B3 一并）
- task_plan.py:55-57 字面量三元组改 `import _SPEC_SCHEMA_KEYS`（双源已实际存在的最低成本修复）

### 3.3 验收门禁

1. 行为零变化：全量 pytest 绿 + 关键路径 smoke（req.amend 误传自纠/重复提案守卫/归档禁写）
2. `grep -rn "_CARD_LANDING_TOOLS\|_ARCHIVED_DENY_TOOLS\|_ARTIFACT_TOOLS\|CARD_ROUND_CLOSINGS"` 于消费逻辑零命中（数据定义处仅注册 flags）
3. line_baseline 棘轮：chat.py/req_agent.py 净减（收编后）；regen 过目 diff

---

## 4. 实施序与依赖

```
MS-A(已落地) ──→ MS-B(契约机械化) ──→ MS-C(双面对齐, 依赖 B3 的单源渲染)
                    └──────────────→ MS-D(声明式收编, 与 C 并行可行)
```

- MS-B 先行：硬门禁越早启用，后续 C/D 的契约变更越受保护
- MS-C 依赖 B3（capability 单源渲染后才谈块拆分）
- MS-D 独立，可穿插；D1 的 flags 与 B2 门禁互补（flags 也入契约断言）

## 5. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| 签名自动生成文档语义贫瘠（只有形状无用途） | 仅作兜底非替代；语义说明保留手写位；golden 过目 | derive 层独立函数，一行禁用 |
| 硬门禁误伤（params_doc 放宽 JSON 解析失败） | tolerant 提取 + 豁免清单机制（带理由） | 豁免单项 |
| GU 全 block 感知改变模型行为（教育少了） | golden 全场景快照 + 弱模型遵从遥测对比（prompt_sections 已恒开） | block 条件独立开关 |
| idempotent 守卫收编漏路径 | 四处现状先加等价断言再收编；每步独立 commit | 单 commit revert |

## 6. 挂账联动

- 技术债台账：MS-B/C/D 各自落地后勾销对应事实条目（F1-F13 逐步失效）
- `arg_alias` 遥测命中率观察一个周期后再决定是否扩展别名面（req.propose 反向等）
