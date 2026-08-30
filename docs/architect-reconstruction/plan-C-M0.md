# M0 Schema 冻结 · 三组预设清单 + 契约条目 Schema + 存储/API 冻结稿

> 版本 v1.1 | 日期 2026-08-30 | 状态：**第一二批已产出，评审中**（plan-C v1.6 §12 M0 交付物）
> 综合来源：plan-A（§二 认知约束表 / §五 交付物差异化清单）、plan-B（§4.4 档位对契约包的影响）、plan-C（§3.1 tiers / §6.1 契约条目）。
> 评审通过后本文件即冻结为协议基线；后续变更走版本化（framework.version / schema 版本）。
> v1.1 变更：第二批产出——§6 全部存储 schema（DDL 冻结稿）、§7 REST API 端点清单、§8 agent 新增工具清单、§9 设计规则 R1-R7；§4 改批次状态表；评审决议 4 项落格（§5）。

---

## 1. 三组默认预设清单（框架标准）

> 修正说明：plan-C §3.1 草案 low 档为 3 类（entity/process/rule），与 plan-A 低配清单（实体/交互/规则/过程/决策 5 类，仅排除独立事件与状态建模）不一致。本清单按"三方综合"以 **plan-A 档位语义为准**：low = 6 类去 state（状态变更按 plan-A 用枚举字段/过程分支描述，不单独建模状态机资产）。

### 1.1 总表

| 维度 | 低 low（精简） | 中 mid（标准，新项目默认） | 高 high（完整） |
|---|---|---|---|
| **X 分类值域** | entity / contract / rule / process / decision（**5 类，无 state**） | 全部 6 类（+state，显式状态机建模） | 全部 6 类 + **自定义值域开放** |
| **Y 抽象值域** | implementation（仅实现层） | business / logic / implementation（全 3 层值域启用） | 全 3 层 + 自定义粒度开放 |
| **Z 治理条目** | **关**（约束只留在验收 criteria 文本） | 4 类**轻量条目**：observability / resilience / config / security（条目+锚点+约束文本，无校验规则引用） | 4 类**完整条目**（+校验规则引用+达标验证）+ 自定义条目开放 |
| **验收默认** | mode=auto，仅 L1 | L1/L2 自动；**L3 人工主判**（判断困难时按需手动激活模型辅助） | L1/L2 自动；L3 人工主判（按需激活，全量可开） |
| **编码指令（注入 runner 的 AGENTS.md）** | 简化 1 页（本体映射+文件结构） | 完整 5-8 页（+模式选型/反模式/测试策略） | 完整 + 脚手架生成 |
| **提取 profile** | 快管线 | 快管线 | 快管线 + 验收场景严管线 |

### 1.2 YAML 具体化（替换 plan-C §3.1 tiers 段）

```yaml
framework:
  version: 1                      # 框架配置版本化，变更留痕
  activeTier: mid                 # 新项目默认
  tiers:
    low:
      x: [entity, contract, rule, process, decision]   # 无 state（plan-A 低配：状态用枚举/分支描述）
      y: [implementation]
      z: []
      acceptanceDefault: { mode: auto, layers: [L1] }
      directivesDepth: brief        # 1 页
    mid:
      x: [entity, contract, state, rule, process, decision]
      y: [business, logic, implementation]
      z: [observability, resilience, config, security]  # 轻量条目
      acceptanceDefault: { mode: assisted, layers: [L1, L2], l3: human-on-demand }
      directivesDepth: full         # 5-8 页
    high:
      x: builtin-6 + custom         # 自定义值域开放
      y: builtin-3 + custom
      z: [observability, resilience, config, security] + custom   # 完整条目
      acceptanceDefault: { mode: assisted, layers: [L1, L2], l3: human-on-demand }
      directivesDepth: full-scaffold
```

### 1.3 预设通则

1. **值域启用 ≠ 自动提取**：Y 轴多粒度启用只是"允许"，提取仍按需（implementation 默认，business/logic 由需求驱动）——按需不批量原则不受档位影响。
2. **Z 轴依赖**：z=[] 时契约条目 `z_axis` 必须为空数组（校验规则 V5）；切到 low 时未 accepted 条目的 z_axis 自动清空并提示。
3. **低配不建模 state 的验收含义**：状态期望写在 `behavior.branches`（"已发货 → 403"），L2 比对用过程分支，不做状态机比对。
4. **自定义开放仅 high**：mid 用户只能启用/停用内置值域；增删改值（含自定义 kind）须切 high。

---

## 2. 契约条目 Schema（定稿）

### 2.1 字段表

| 字段 | 类型 | 必填 | 说明 / 校验 |
|---|---|---|---|
| `id` | string | ✓ | `ci-{项目内序号}`，唯一。**评审决议（2026-08-30）：项目内自增，不带需求前缀**；需求关联走 `reqId` 字段 |
| `reqId` | string? | — | 关联需求 id；独立契约（非需求衍生）可空 |
| `convId` | string? | — | 证据链：产出对话 id |
| `origin` | `{convId, messageId, quote≤200}` | ✓(confirmed 前) | **设计者原话引用**——证据链锚点；V2：无 origin 不得 confirmed |
| `kind` | string | ✓ | **必须在框架当前值域内**（V1）；框架变更时未 accepted 条目标"待复核" |
| `level` | string? | — | 抽象粒度期望；缺省 = implementation |
| `target.file` | string? | △ | 相对路径期望。**V4：file/symbol 至少其一**，均无 → 强制标 `intentOnly: true`（意图级，如实纪律） |
| `target.symbol` | string? | △ | 符号名期望 |
| `target.componentId` | string? | — | 归属组件期望（Y 轴落点） |
| `behavior.fields` | `[{name, type?}]?` | — | kind=entity：期望字段集（L1/L2 比对） |
| `behavior.steps` | `[string]?` | — | 有序步骤（语义级描述，非代码）——L2 序列比对基准 |
| `behavior.branches` | `[string]?` | — | 分支条件（"已发货 → 403"）——low 档状态期望写这里 |
| `behavior.states` / `transitions` | ? | — | kind=state 专用（mid+ 才可用，V7） |
| `behavior.relations` | `[{target, type}]?` | — | 期望调用/引用关系 |
| `z_axis` | `[{category, text, anchor?}]` | ✓ | category ∈ 4 类（§1.1）；**V5：low 档必须为空数组** |
| `acceptance.mode` | `auto \| assisted \| manual` | ✓ | `auto`=L1/L2 通过即过（low 默认）；`assisted`=L1/L2 自动 + **L3 人工主判、按需手动激活模型辅助**（mid/high 默认）；`manual`=逐条人审 |
| `acceptance.criteria` | string? | — | 补充验收说明（Given/When/Then 或自由文本） |
| `acceptance.linkedTests` | `[testSessionId]?` | — | 关联单测（单元测试页展示，M3） |
| `intentOnly` | bool | ✓ | 缺省 false；V4 触发强制 true |
| `status` | enum | ✓ | 状态机见 §2.2 |
| `version` | int | ✓ | 期望修订版本；rejected → 重新确认时 +1，历史保留 |
| `audit` | `{createdBy:{actor,author}, createdAt, confirmedAt, injectedAt, verifiedAt}` | ✓ | 全程留痕 |

### 2.2 状态机

```
draft ──设计者逐条确认──▶ confirmed ──随契约包注入──▶ injected ──runner完成/git diff──▶ verifying
  ▲                        ▲                            │                                │
  │                        │(rejected 后修改期望,        │                                ├─设计者终审通过──▶ accepted(终态)
  │                        │ version+1)                 └──(期望变更重走 confirmed)        └─打回──▶ rejected
  └──────────────────────────────────────────────────────────────────────────────────────────┘
```

- **V3**：未 confirmed 不得进入契约包（injected 前置校验）。
- **V6**：rejected 非终态；修改期望后 version+1 回 confirmed。
- **框架变更联动**：非 accepted 状态条目 → 标记 `staleByFramework: true`，必须重新确认（V8）。

### 2.3 契约包（注入单元）

```yaml
contract_package:
  id: cp-001
  frameworkSnapshot: {version: 1, activeTier: mid}   # ★ 注入时冻结框架版本（档位决定 directivesDepth/z 能力）
  items: [ci-042, …]            # 仅 confirmed+
  assetRefs: [sa-xxx, …]        # 引用的既有语义资产（X 轴基线，不复制）
  componentRefs: [comm-xxx, …]  # Y 轴组件引用
  agentsMd: "…"                 # 生成的词汇表/编码指令（directivesDepth 由快照档位决定）
  injectedAt / injectedTo: runner
```

### 2.4 验收报告（事实/意见分离落地）

```yaml
acceptance_report:
  id: ar-001
  packageId: cp-001
  trigger: {type: runner_done|git_diff|manual, ref: "…"}
  extractionProfile: strict            # 严管线（tAgent 任务化）
  facts:                               # ── 事实区（机械比对，L1/L2）──
    - {itemId: ci-042, check: L1|L2, verdict: pass|fail|partial,
       evidence: {assetId?, anchors: [{file,symbol,line}], detail: "…"}}
  opinions:                            # ── 参考意见区（LLM，L3，隔离存储与呈现）──
    - {itemId: ci-042, text: "…", confidence: 0.82, model: "…",
       evidence: {assetId?, anchors: [...]},
       trigger: {by: user, at: ts}}    # ★ 仅由设计者手动按需触发生成，无自动运行
  summary: {pass: n, fail: n, l3AwaitingHuman: n}
```

- **facts 与 opinions 分表存储**（arch_acceptance_facts / arch_acceptance_opinions）——纪律"事实与意见分离"在存储层强制。
- opinions 永不参与 verdict 统计；UI 参考区渲染（plan-C-UI §4/§5.1）。

---

## 3. 与框架配置的联动规则汇总

| 规则 | 内容 |
|---|---|
| V1 | `kind` ∈ 当前框架值域（activeTier 快照） |
| V2 | 无 origin 不得 confirmed |
| V3 | 未 confirmed 不得 injected |
| V4 | target 无 file 且无 symbol → intentOnly=true |
| V5 | low 档 z_axis=[] |
| V6 | rejected → 修改后 version+1 回 confirmed |
| V7 | behavior.states/transitions 仅 kind=state（mid+） |
| V8 | 框架变更 → 非 accepted 条目 staleByFramework，需重确认 |

---

## 4. 批次划分与状态

| 批次 | 内容 | 状态 |
|---|---|---|
| 第一批 | 三组预设清单（§1）+ 契约条目 schema/状态机/契约包/验收报告（§2）+ 联动规则 V1-V8（§3） | ✅ 评审关闭（2026-08-30） |
| **第二批** | **全部存储 schema（§6）+ REST API 端点清单（§7）+ agent 新增工具清单（§8）+ 设计规则（§9）** | ✅ 本批产出（待评审） |
| 第三批（实现期） | DDL 落地 `db_schema.py`、索引调优、API 实现与测试 —— 按 §6-§8 冻结稿实施 | ⏳ M1 起 |

> 原第三批（命名规约/术语表 schema）**提前并入第二批**一次冻结——schema 冻结越早越好，实现仍按 M3 排期。

---

## 5. 评审决议记录

| # | 决策点 | 决议 | 状态 |
|---|---|---|---|
| 1 | low 档 5 类（vs plan-C §3.1 草案 3 类） | **确认 5 类**（无 state，综合 plan-A） | ✅ 已决策（2026-08-30） |
| 2 | mid 档 Z 轴范围 | **4 类全开**（observability/resilience/config/security，轻量条目） | ✅ 已决策（2026-08-30） |
| 4 | 契约条目 id 规则 | **`ci-{seq}`**（项目内自增，不带需求前缀；需求关联走 `reqId` 字段） | ✅ 已决策（2026-08-30） |
| 3 | L3 运行策略 | **L3 不做自动运行/抽样**——人工主判为主（基于 L1/L2 事实与代码/资产证据）；判断困难时由用户**手动提交指令激活 L3**（模型辅助，产出参考意见，带来源+置信度+证据）。抽样方案废弃，概念说明保留备查 | ✅ 已决策（2026-08-30） |

### 5.1 决策点 3 概念说明（L3 抽样）

**三层符合性是什么**（plan-C §6.2，验收时对每条契约条目做三层检查）：

| 层 | 检查什么 | 怎么查 | 成本 | 结果性质 |
|---|---|---|---|---|
| **L1 覆盖性** | 契约要求的实体/过程/规则是否**存在**、锚点是否落在期望文件/符号 | 在提取资产里机械查找比对（如契约要 `cancel_order` 过程 → 找 symbol=cancel_order 的资产） | 零（纯代码比对） | 事实 |
| **L2 行为符合性** | 步骤顺序/分支/状态转移与契约写的**行为是否一致** | 契约的 steps/branches vs 提取资产的 steps/branches 做序列比对 | 零（纯代码比对） | 事实 |
| **L3 语义符合性** | 命名是否达意、业务语义是否符合设计者**意图**、Z 轴约束是否真落实 | **必须 LLM 按规约评审**——机械方法查不出"实现存在、步骤也对、但理解跑偏" | 高（每条一次 LLM 评审） | 参考意见（设计者终审） |

**为什么要"抽样"**：L1/L2 免费，可以每条都查；L3 每条都要花一次 LLM 评审。契约包若有 50 条条目，全量 L3 = 50 次强模型调用，验收又慢又贵。抽样 = 只对一部分条目跑 L3，其余条目仍保有 L1/L2 事实结果，标注"L3 未抽样"（如实呈现，不假装评审过）。

**"L1/L2 fail 项 + 随机 20%"的精确含义**——以 20 条条目、机械比对后 15 过 5 挂为例：

1. **fail 项全量**（5 条）：机械比对失败的条目**全部**跑 L3。原因：失败说明实现与期望已有出入，L3 能帮助区分"实现真错了"还是"提取失真/期望过严"，给设计者完整的差异画像——高风险条目不抽检，全检。
2. **通过项随机抽 20%**（15×20%≈3 条）：从 L1/L2 通过的条目里随机抽一小部分也跑 L3。原因：防止"机械全过但语义跑偏"的系统性盲区（如职责理解错位、命名与意图偏离——L1/L2 天生检测不到这类问题）。这是质量抽检：**抽查的存在本身就是威慑**，使每条条目都可能被抽到。
3. **其余 12 条**：不消耗 LLM，标"L3 未抽样"；设计者在验收区块可对**任何**条目手动补跑 L3（人工兜底，决策权在人）。

**效果**：20 条条目的 L3 成本从 20 次降到 8 次（-60%），fail 项全覆盖 + 通过项有随机抽检防盲区。20% 只是初始参数，M2 实现期可调（如项目小可全量，项目大可降）。

> **★ 决议（2026-08-30）**：需求方裁定——**L3 不自动化、不抽样**。理由：L3 本质是"是否符合设计者意图"的判断，应由人基于 L1/L2 事实主判；模型只在人判断困难时按需提供辅助（参考意见）。上述抽样方案废弃，本节概念说明保留备查。落地：验收 UI 每条条目提供「激活模型辅助」入口，opinions 仅由用户触发生成（§2.4）。

---

## 6. 第二批：存储 Schema（SQLite DDL 冻结稿）

> 命名沿用既有 `arch_` 前缀；迁移走既有 `_add_cols`/建表机制（db_schema.py）。所有表含 `project_id`（项目库隔离，落 `architect/<pid>/arch.db`；全局配置类落主库 `architect.db`，见 §6.3 注）。

### 6.1 命名墓碑表 `arch_name_tombstones`（参考池）

```sql
CREATE TABLE IF NOT EXISTS arch_name_tombstones (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    file_path TEXT DEFAULT '',          -- 相对路径（锚定键之一）
    symbol TEXT DEFAULT '',             -- 符号名（锚定键之二；纯意图资产可为空）
    name TEXT NOT NULL,                 -- 保留的历史命名
    source TEXT DEFAULT 'llm',          -- user | llm | rule（一视同仁，同通道）
    reason TEXT DEFAULT 'anchor_gone',  -- anchor_gone | partial_fail | reconcile_deleted
    asset_id TEXT DEFAULT '',           -- 来源资产（失效时可能已软删，仅追溯用）
    note TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_arch_tombstone_lookup
    ON arch_name_tombstones(project_id, file_path, symbol);
CREATE INDEX IF NOT EXISTS idx_arch_tombstone_name
    ON arch_name_tombstones(project_id, name);
```

- **消费方**：API 归一化管线 step1（§5.5 plan-C）——LLM 命名前查“该符号曾名 X”；代码重生（同名符号回归）捞回历史命名。
- **★ 关键裁决**：**框架标准变更作废的资产不写墓碑**（§9 规则 R1）——墓碑仅服务“标准不变的代码变更”生命周期。

### 6.2 用户编辑层 `arch_user_overlays`

```sql
CREATE TABLE IF NOT EXISTS arch_user_overlays (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    seq INTEGER NOT NULL,               -- 全项目编辑序号（重放顺序）
    author TEXT DEFAULT '',             -- 编辑人（多人协作 schema 留位：main-KB 模式即 MR 主体）
    op TEXT NOT NULL,                   -- rename | merge | split | edit_desc | edit_detail
    target_asset_ids TEXT NOT NULL,     -- JSON: 操作对象资产 id 数组（merge=被并方, split=原资产）
    payload TEXT,                       -- JSON: rename{newName} / merge{intoId,targetName} / split{parts:[{name,anchorKeys[]}]} / edit_desc{desc}
    anchor_basis TEXT,                  -- JSON: 操作时目标资产锚点快照 [{file,symbol}] —— 重放匹配依据
    reason TEXT DEFAULT '',             -- 为什么（审计三要素之一）
    status TEXT DEFAULT 'active',       -- active | orphaned(锚点失配,提示裁决) | rolled_back
    approval_status TEXT DEFAULT '',    -- 多人留位: pending | approved | rejected（standalone 恒空）
    approved_by TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    applied_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_arch_overlay_proj ON arch_user_overlays(project_id, seq);
CREATE INDEX IF NOT EXISTS idx_arch_overlay_target ON arch_user_overlays(project_id, target_asset_ids);
```

- **重放引擎（M1 实现）**：按 `seq` 升序把 active overlay 应用到事实层；`anchor_basis` 与重算后资产锚点匹配 → 自动重放；失配 → 置 `orphaned` 并提示设计者裁决（不静默丢弃）。

### 6.3 框架配置表 `arch_framework_configs`（版本行即变更审计）

```sql
CREATE TABLE IF NOT EXISTS arch_framework_configs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version INTEGER NOT NULL,           -- 项目内自增（从 1 起）
    config TEXT NOT NULL,               -- JSON: plan-C-M0 §1.2 框架结构（axes/tiers/activeTier）
    change_kind TEXT DEFAULT 'init',    -- init | tier_switch | values_edit | custom_load
    affected_summary TEXT,              -- JSON: {voidedAssets: n, voidedKinds: [...], note} —— 变更影响摘要（审计）
    executed_by TEXT DEFAULT '',
    note TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    UNIQUE(project_id, version)
);
CREATE INDEX IF NOT EXISTS idx_arch_fwcfg_active ON arch_framework_configs(project_id, active);
-- active 标志列:
--   _add_cols(db, "arch_framework_configs", [("active", "INTEGER DEFAULT 0")])
--   约束：每 project 至多一行 active=1（应用层保证，切换在同一事务内）
```

- **落库位置**：项目级配置 → `architect/<pid>/arch.db`；若未来“主 KB 下发”角色/框架 → 主库共享层读（本期预留）。
- **变更流程**：preview（dry-run 计算影响 N 资产）→ 设计者确认 → 事务内：插入新 version 行(active=1) + 旧行 active=0 + 批量 `UPDATE arch_semantic_assets SET status='voided'...`。

### 6.4 `arch_semantic_assets` 列扩展（作废态）

```sql
_add_cols(db, "arch_semantic_assets", [
    ("voided_reason", "TEXT DEFAULT ''"),      -- framework_change（预留其它原因）
    ("voided_at", "INTEGER DEFAULT 0"),
    ("voided_by", "TEXT DEFAULT ''"),
    ("voided_framework_version", "INTEGER DEFAULT 0"),  -- 作废时的框架版本（可溯源）
    ("stale_by_framework", "INTEGER DEFAULT 0"),          -- 契约条目联动标记（plan-C-M0 §2.2 V8 同名语义）
])
-- status 枚举扩展: active | stale | deleted | voided   （应用层校验同步放行 'voided'）
```

- **voided 行为**：**保留不物理删除**（审计 + 溯源）；列表/图谱/统计默认过滤 `status='voided'`；不参与 canonicalKey 去重复用；**不写墓碑**（R1）。

### 6.5 命名规约表 `arch_naming_conventions`（项目规约页·资产命名规约区块）

```sql
CREATE TABLE IF NOT EXISTS arch_naming_conventions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    scope TEXT DEFAULT 'project',       -- project | component
    component_id TEXT DEFAULT '',       -- scope=component 时锚定组件
    applies_kinds TEXT,                 -- JSON: 适用的本体 kind 数组（空=全部）
    rule_text TEXT NOT NULL,            -- 规则文本（动宾结构等）
    source TEXT DEFAULT 'manual',       -- induced(agent 归纳) | manual
    scenarios TEXT NOT NULL,            -- JSON: ["extract","accept","naming","general"] 场景标签——agent 按场景加载，禁全量注入
    status TEXT DEFAULT 'active',       -- active | disabled | pending_review(框架变更待复核)
    author TEXT DEFAULT '',
    framework_version INTEGER DEFAULT 0, -- 固化时框架版本（标准变更 → pending_review 的判定依据）
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_arch_conv_proj ON arch_naming_conventions(project_id, status);
CREATE INDEX IF NOT EXISTS idx_arch_conv_scenario ON arch_naming_conventions(project_id, status, scenarios);
```

### 6.6 术语表 `arch_glossary`（词典，纯参考非约束）

```sql
CREATE TABLE IF NOT EXISTS arch_glossary (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    term TEXT NOT NULL,                 -- 规范词（"订单"）
    alias TEXT,                         -- JSON: 别名/英文对应（"Order单"/"Order"）
    definition TEXT DEFAULT '',         -- 释义（可空）
    source TEXT DEFAULT 'manual',       -- doc_import | manual
    source_ref TEXT DEFAULT '',         -- 导入来源（文档 id/路径）
    author TEXT DEFAULT '',
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_arch_glossary_term ON arch_glossary(project_id, term);
```

### 6.7 契约/验收表（第一批 schema 的物理落表定义）

```sql
CREATE TABLE IF NOT EXISTS arch_contract_items (
    id TEXT PRIMARY KEY,                -- ci-{seq}（项目内自增，决议 2026-08-30）
    project_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    req_id TEXT DEFAULT '',
    conv_id TEXT DEFAULT '',
    origin TEXT,                        -- JSON: {convId, messageId, quote}（V2）
    kind TEXT NOT NULL,                 -- V1: 框架值域内
    level TEXT DEFAULT 'implementation',
    target TEXT,                        -- JSON: {file?, symbol?, componentId?}
    intent_only INTEGER DEFAULT 0,      -- V4
    behavior TEXT,                      -- JSON: fields/steps/branches/states/transitions/relations
    z_axis TEXT,                        -- JSON: [{category,text,anchor?}]（V5: low 档空数组）
    acceptance TEXT,                    -- JSON: {mode, criteria?, linkedTests?}
    status TEXT DEFAULT 'draft',        -- draft|confirmed|injected|verifying|accepted|rejected（V3/V6）
    stale_by_framework INTEGER DEFAULT 0,   -- V8
    version INTEGER DEFAULT 1,          -- rejected→重确认 +1
    created_by TEXT DEFAULT '',         -- JSON 或 "designer:xxx"
    created_at INTEGER DEFAULT 0,
    confirmed_at INTEGER DEFAULT 0, injected_at INTEGER DEFAULT 0, verified_at INTEGER DEFAULT 0,
    UNIQUE(project_id, seq)
);

CREATE TABLE IF NOT EXISTS arch_contract_packages (
    id TEXT PRIMARY KEY,                -- cp-{seq}
    project_id TEXT NOT NULL,
    framework_snapshot TEXT NOT NULL,   -- JSON: {version, activeTier}（注入时冻结）
    item_ids TEXT NOT NULL,             -- JSON: 仅 confirmed+
    asset_refs TEXT,                    -- JSON: 引用语义资产 id（X 轴基线）
    component_refs TEXT,                -- JSON: Y 轴组件引用
    agents_md TEXT,                     -- 生成的词汇表/编码指令（directivesDepth 由快照档位决定）
    status TEXT DEFAULT 'created',      -- created | injected | superseded
    injected_to TEXT DEFAULT '',        -- runner 任务 id
    created_at INTEGER DEFAULT 0, injected_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arch_acceptance_facts (     -- 事实区（机械比对 L1/L2）
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    check TEXT NOT NULL,                -- L1 | L2
    verdict TEXT NOT NULL,              -- pass | fail | partial
    evidence TEXT,                      -- JSON: {assetId?, anchors:[{file,symbol,line}], detail}
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arch_acceptance_opinions (  -- 参考意见区（L3，仅用户手动触发）
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    report_id TEXT NOT NULL,
    item_id TEXT NOT NULL,
    text TEXT NOT NULL,
    confidence REAL DEFAULT 0,          -- 0~1
    model TEXT DEFAULT '',
    evidence TEXT,                      -- JSON: 同 facts 结构
    trigger_by TEXT DEFAULT '',         -- 触发用户（仅人工，无自动运行）
    created_at INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS arch_acceptance_reports (
    id TEXT PRIMARY KEY,                -- ar-{seq}
    project_id TEXT NOT NULL,
    package_id TEXT NOT NULL,
    trigger TEXT,                       -- JSON: {type: runner_done|git_diff|manual, ref}
    extraction_profile TEXT DEFAULT 'strict',
    summary TEXT,                       -- JSON: {pass, fail, l3AwaitingHuman}
    created_at INTEGER DEFAULT 0
);
```

---

## 7. REST API 端点清单（`/api/architect` 既有前缀，M0 冻结）

> 响应沿用项目惯例；鉴权走 gateway 既有 token 中间件。**命名治理/契约/验收端点同时是 agent 工具的内部传输**（§8），保证“写入口唯一”。

### 7.1 框架标准（概览 tab）

| 方法+路径 | 用途 | 关键参数/行为 |
|---|---|---|
| `GET  /framework` | 当前生效框架配置 | 返回 {config, version, activeTier} |
| `POST /framework/preview-change` | **dry-run 影响预览** | body: {tier?/config?} → {voidedAssets: n, byKind: {...}}（作废确认流数据源） |
| `POST /framework/switch` | 执行标准变更 | 事务：新版本行 + 旧行 active=0 + 批量 voided（不写墓碑，R1）→ 返回新 version |
| `PUT  /framework/custom` | 保存自建框架草稿 | body: config JSON（high 档能力） |
| `GET  /framework/versions` | 版本历史（变更留痕） | 分页，含 affected_summary |

### 7.2 语义资产（对话提取 / 资产管理操作）

| 方法+路径 | 用途 |
|---|---|
| `POST /semantic/assets/save` | agent 产出落库（**API 归一化管线全量执行**：规约注入→继承裁决→授权策略） |
| `POST /semantic/assets/draft` | 规则管线出草稿（不落库，可选辅助） |
| `POST /semantic/assets/rename` | 改名（standalone 直改；main-KB 拒绝→指向主 KB 界面） |
| `POST /semantic/assets/merge` | 合并（锚点并集+detail 冲突标记+关系重定向；写 overlay 审计） |
| `POST /semantic/assets/split` | 拆分（agent 提案方案为入参；写 overlay） |
| `GET  /semantic/coverage` | 覆盖度统计（概览徽标/覆盖度图层：已提取 n/覆盖组件 m/过期 k/未提取清单） |
| `GET  /semantic/assets/{id}/names` | 命名历史（name_alias/renamed_from + overlay 重放视图） |

### 7.3 命名治理（项目规约页）

| 方法+路径 | 用途 |
|---|---|
| `GET/POST/PUT/DELETE /naming/conventions` | 命名规约 CRUD（场景标签 scenarios 为必填之一） |
| `GET  /naming/conventions?scenario=extract` | **按场景检索**（agent 注入用，禁全量） |
| `POST /naming/conventions/induce` | agent 归纳提议（生成 pending 提案，设计者确认后 active） |
| `GET/POST/PUT/DELETE /naming/glossary` | 术语表 CRUD |
| `POST /naming/glossary/import` | 从项目文档导入（source_ref 记来源） |
| `GET  /naming/tombstones` | 参考池查询（管理视图） |

### 7.4 契约与验收（需求方案页只读区 / 单元测试页局部验收区块 / 影响分析）

| 方法+路径 | 用途 |
|---|---|
| `GET/POST /contracts/items` | 契约条目列表 / 创建 draft（固化卡确认走 confirm） |
| `POST /contracts/items/{id}/confirm` | 设计者逐条确认（draft→confirmed，V2 校验） |
| `POST /contracts/items/{id}/verdict` | **设计者判定**：通过/打回/改期望（accepted/rejected，唯一判定入口） |
| `POST /contracts/packages` | 由 confirmed 条目创建契约包 |
| `POST /contracts/packages/{id}/inject` | 注入 runner（agentsMd 生成；框架版本快照） |
| `GET  /acceptance/reports?packageId=` | 验收报告（facts/opinions 分区返回） |
| `POST /acceptance/reports/{id}/items/{itemId}/opinion` | **手动激活 L3**（用户提交指令 → 模型辅助 → opinions 落库） |
| `POST /acceptance/items/{id}/fix-instruction` | 起草修复指令（architect 只起草） |

### 7.5 角色注册表

| 方法+路径 | 用途 |
|---|---|
| `GET/PUT /agent/roles` | tAgent 角色→模型/API 映射（三级：全局<项目<主 KB 下发；per-call 生效） |

---

## 8. agent 新增工具清单（`[TOOL_CALL]` 只增不改，M1 实现）

| 工具名 | 参数 | 行为 | 对应端点 |
|---|---|---|---|
| `code.read_symbols` | `{file, symbol?, startLine?, endLine?}` | 读源码片段（限长），供 agent 看代码按规约产出 | （直读，不落库） |
| `asset.semantic.draft` | `{scope, kinds?}` | 规则管线草稿（不落库） | `/semantic/assets/draft` |
| `asset.semantic.save` | `{assets: [...]}` | 归一化管线+落库 | `/semantic/assets/save` |
| `asset.semantic.update` | `{assetId, patch}` | 认知层编辑（改名/描述）→ overlay | `/semantic/assets/rename` 等 |
| `asset.semantic.merge` | `{assetIds, targetName?}` | 合并提案 → 用户确认后执行 | `/semantic/assets/merge` |
| `asset.semantic.split` | `{assetId, plan}` | 拆分提案 → 用户确认后执行 | `/semantic/assets/split` |
| `contract.propose` | `{items: [draft]}` | 方案对话中产出契约条目固化卡（draft，待确认） | `/contracts/items` |
| `naming.proposeConvention` | `{ruleText, scope, appliesKinds, scenarios}` | 归纳提议卡（pending） | `/naming/conventions/induce` |

> 既有 17 个工具签名不动；新工具只增。所有写类工具内部走同一 API 归一化管线——无旁路。

---

## 9. 第二批设计规则（关键裁决）

| 规则 | 内容 |
|---|---|
| **R1 框架作废不写墓碑** | 标准变更 → 资产 voided 且命名**不**入 `arch_name_tombstones`（命名不跨框架迁移）；墓碑仅服务标准不变的代码变更生命周期。两套生命周期的存储分界就此锁定 |
| R2 overlay 重放有序 | 按 `seq` 升序重放；`anchor_basis` 失配 → `orphaned` + 提示设计者，不静默丢弃 |
| R3 框架版本即审计 | `arch_framework_configs` 每次变更新增版本行（含 affected_summary），无独立日志表——版本行即变更留痕 |
| R4 voided 保留 | 作废行不物理删除，默认过滤展示；`voided_framework_version` 可溯源到具体框架版本 |
| R5 写入口唯一落到表级 | agent 工具与前端操作共用 §7 端点；main-KB 策略下 rename/merge/split 端点直接拒绝并返回主 KB 深链（standalone 直过）——策略开关在端点层，无旁路 |
| R6 facts/opinions 分表 | `arch_acceptance_facts` 与 `arch_acceptance_opinions` 物理分表——事实/意见分离在存储层强制，opinions 无自动写入方（仅 §7.4 手动激活端点） |
| R7 场景标签必填 | `arch_naming_conventions.scenarios` NOT NULL——规约从数据结构上就不可能被“全量默认注入”（查询必须带场景条件） |
