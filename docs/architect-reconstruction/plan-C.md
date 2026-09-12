# Architect 重建方案（Plan C）：以源码为核心的认知对齐中枢

> 版本 v1.7 | 日期 2026-08-30 | 状态：**开发前核查稿**（M0 第一二批 schema/API 冻结稿已产出）
> 上游输入：`../archive/plan-A.md`（外部建议 A：三核引擎+动态适配器，已归档）、`../archive/plan-B.md`（外部建议 B：四阶流水线+契约包，已归档）、与需求方的多轮讨论决议。
> 与 A/B 的核心差异：**以源码为唯一事实源**。A/B 均为需求正向出发的 greenfield 蓝图；本方案中元认知框架是给代码现实配的坐标系，不是悬空的建模词汇。
> v1.1 变更：新增 §11 跨模块兼容与影响面（KB 解析构建/文档 viewer/AI CHAT/workbench 逐模块核实结论 + 共享面护栏）；§5.4 补充"主 KB"定义（与 KB 模块消歧）。
> v1.2 变更：界面变化已细化至配套文档 `plan-C-UI.md`（§12 各阶段 UI 落地对照）。
> v1.3 变更（需求方决议）：① 框架标准变更 ≠ 代码变更——**标准变更时资产与命名整体作废、命名继承中断**，代码变更仍走 stale/墓碑/命名继承（§3.2/§5.2）；② 预设清单以 plan-A/B/C 三档定义为源（§13）；③ 规约/术语按**场景加载**注入 agent，禁止默认全量（§4.1/§5.3）；④ 命名治理 UI 归属"项目规约"页（§5.3）；⑤ 界面决议同步 `plan-C-UI.md` v1.1。
> v1.4 变更（开发前核查，8 项）：§3.2 补 canonical_key 指纹机制事实与 status 作废态扩展；§4.1 补双 agent 通道执行载体分工；§10 补 name_alias/renamed_from 复用与前端服务缺口行；§12 M0 补 API 端点清单；配套 `plan-C-UI.md` 同步（chat 内嵌全量提取入口、INCLUDE/CALL 筛选、SpecWorkspace 载体、单元测试挂载位）。
> v1.5 变更（M0 第一批执行）：新增 `plan-C-M0.md` —— 三组预设具体清单（low 依 plan-A 修正为 5 类无 state，§3.1 已同步）+ 契约条目 schema/状态机/契约包/验收报告定稿 + 校验规则 V1-V8；§13#2 关闭。
> v1.6 变更（M0 评审决议）：① 预设清单 low 档 5 类确认、mid 档 Z 轴 4 类全开、契约条目 id=`ci-{seq}`；② **L3 不自动运行/抽样**——人工主判为主，按需手动激活模型辅助（§6.2 已同步，plan-C-M0 §5 决议记录）。
> v1.7 变更（M0 第二批执行）：`plan-C-M0.md` 升 v1.1 —— 全部存储 DDL 冻结稿（§6）+ REST API 端点清单（§7）+ agent 新增 8 工具（§8）+ 设计规则 R1-R7（§9，含"框架作废不写墓碑"存储分界）；§13#1/#6 关闭。

---

## 1. 定位与设计哲学

### 1.1 核心命题

Architect 的本职是：**在"需求/方案"与"实现/验收"两个方向上对齐研发人员的认知**。它不是编码 agent，也不是裁判，而是：

> **本体对齐器 + 保真传输层** —— 翻译官兼信使，只负责把两侧信息翻译到统一本体并如实双向传递，不做决策。

### 1.2 决策权分布（本方案的宪法条款）

| 角色 | 决策权 |
|---|---|
| 设计者（人） | 需求/方案的确认、期望固化确认、验收判定、差异处理（通过/打回/改期望） |
| Coding agent | 实现方式（在契约约束下） |
| **Architect** | **无决策权**。仅执行：本体维护、翻译、机械比对、事实呈现 |

推论：architect 的输出全部是**声明式协议消息**（契约包、差异报告），不含裁决；修复指令可由 architect 起草（作为事实附件），发送与否由设计者决定。

### 1.3 三条保真纪律（"如实"的工程定义）

1. **事实与意见分离**：机械比对结果（存在性/锚点/序列）= 事实；LLM 语义判断 = 参考意见，必须标注来源与置信度。二者在**数据结构层面**即分开（呈现双通道）。
2. **全程证据链**：每条信息可回溯——正向条目 ↔ 设计者原话（对话引用片段），反向条目 ↔ 代码锚点（assetId + astRef），差异报告每行带两侧 id。
3. **保真失败显式化**：翻译不了/锚不住/有歧义 → 显式标"未锚定/意图级/待澄清"，**不静默归一化**。宁可暴露信息丢失，不可假装对齐。

### 1.4 对 Plan A/B 的继承

| 来源 | 继承内容 |
|---|---|
| Plan B | 契约包 schema 骨架、三层验证思想、共享词汇表（AGENTS.md 注入）、验收标准结构化 |
| Plan A | 三机制作为设计原则：越界熔断（契约校验）、隐式显式化（预留扩展点）、**经验回写**（失败模式反哺配置——现有 reconcile/handle_stale 闭环是其原型） |
| 弃用 | LangGraph/CrewAI 编排（自研 tools loop/tAgent 沿用）、多 Coder 并行（小项目负优化）、A/B 的三档约束矩阵先行（先两档落地） |

---

## 2. 总体架构

### 2.1 三层辐射

```
                ┌─────────────────────────────────────┐
                │   基础手段层（已有，持续加强）           │
                │   AST 符号分析 (codegraph)            │
                │   图算法组件划分 (组件目录/L0/L1/边)     │
                │   LLM 语义转化 (规则+LLM提取/伪码/对话)  │
                └──────────────┬──────────────────────┘
                               ▼
                ┌─────────────────────────────────────┐
                │   认知底座：语义图谱（一张图+一套锚点）    │
                │   X 本体：本体类型（默认 6 类，可配置）    │
                │   Y 抽象：business/logic/impl（可配置） │
                │   Z 治理：观测/韧性/配置/安全（新增）      │
                │   锚点：assetId + astRef(file/symbol)  │
                └──────────────┬──────────────────────┘
          ┌──────────┬─────────┼──────────┬──────────┐
          ▼          ▼         ▼          ▼          ▼
       需求分析    结构设计    代码实现    测试/验收   部署/运维
      (检索+影响) (契约包)   (契约注入)  (行为比对)  (后置)
```

关键断言：**每个生命周期环节的产物，要么是语义图谱上的视图/查询，要么是图上带锚点的增量节点，要么是显式标记"未锚定(意图级)"的产物。不存在第四种状态**——这是全流程对齐可被机械校验的前提。

### 2.2 三个闭环

1. **反向（代码→认知）**：提取，已跑通——底座的生成器。
2. **正向（认知→代码）**：需求→契约→编码注入——重建的主体工作。
3. **差分（认知↔代码）**：**每个环节切换时重跑反向提取 + diff**。reconcile 从"新鲜度检查"升格为"全流程校验器"：需求定稿后 diff 验证设计覆盖；编码完成后 diff 自动产出"实际实现了什么"的证据；验收 = 契约条目 ↔ diff 后资产的比对。

### 2.3 范围聚焦

核心闭环 = **需求/方案 ⇄ 实现/验收** 的双向认知对齐（含"coding agent 完成情况是否符合设计者规约与期望"）。测试/验收次之；部署/运维模型本期只定义 schema 占位，实现后置。

---

## 3. 元认知框架标准（框架即配置）

本体不是硬编码 schema，而是**用户可定义的配置+数据**。Architect 是本体引擎，不是本体所有者。

### 3.1 框架配置 schema

```yaml
framework:
  version: 3                      # 框架配置版本化，变更留痕
  axes:
    - id: x                       # 本体轴
      label: 本体
      values:
        - id: entity
          label: 实体
          definition: "承载业务状态的数据结构……"   # 定义文本直接进提取 prompt
          builtin: true
        - id: process   # … 默认 6 类：entity/contract/state/rule/process/decision
        - id: <custom>  # 高级用户可增删改值域
    - id: y                       # 抽象轴：business/logic/implementation（可裁剪）
    - id: z                       # 治理轴：observability/resilience/config/security
  tiers:
    low:    { x: [entity, contract, rule, process, decision],  y: [implementation], z: [] }   # 无 state（综合 plan-A 低配，见 plan-C-M0.md §1）
    mid:    { x: 默认6类, y: 全部3层, z: [4类轻量条目] }   # 新项目默认
    high:   { 全量 + 自定义开放 }
  activeTier: mid
```

### 3.2 规则

- **档位**：高/中/低，项目级设置，手动可调；新项目默认中。
- **自定义分两步**：先做**值域裁剪/扩展**（axis 不变，值可增删改），再做**新轴**。新轴默认只参与**过滤/标注/分组**，不参与图谱视图生成（视图生成器只认内置 kind 映射）。
- **版本化与迁移（两条生命周期，严格区分）**：
  - **标准变更**（切档位/改值域/换预设/载入自建框架）：这是**设计者决策**——变更前弹影响范围（N 个资产将作废）确认后执行；确认后**存量资产整体作废（从工作集清除），命名继承中断**——用户改名/历史名**不跨框架迁移**（新框架下本体定义已变，旧命名无参照意义）；关联旧值域的命名规约标记"待复核"。变更后按需重新提取，覆盖度如实显示空窗。
  - **代码变更（标准不变）**：走既有机制——stale/reconcile、墓碑参考池、命名继承（用户名>历史名>规约生成名）、用户编辑重放（§5）。
  - **机制事实（M0 设计依据）**：现有 `canonical_key` 指纹 = `kind|level|锚点`（db_schema `arch_semantic_assets.canonical_key`，semantic_assets.py `_canonical_key`）。① kind/level 值域变更 → 指纹天然变化，新旧资产不会误合并；② **同值域切档**（如 mid→low 且 kind 子集不变）时指纹不变，旧资产会被 canonicalKey 去重复用——故"标准变更→整体作废"必须是**显式操作**，不能依赖指纹隐式生效；③ 代码变更场景 kind|level 不变，按 canonicalKey 匹配做名称继承成立。
  - **status 枚举扩展（M0 冻结项）**：现有 `active|stale|deleted(+needs_update)` 需新增**作废态**（如 `voided`，含原因=框架变更），与软删 `deleted` 区分（§13#6）。
- **下游参数化**：store 校验、提取 prompt 分类指令、UI 过滤、图谱过滤全部读框架配置；提取 skill 的分类指令由值域定义文本动态生成。

---

## 4. 按需提取（认知底座的生成器）

**不走全量扫描**。提取是"把当前代码事实翻译成本体"的按需动作，由需求/分析任务触发。

### 4.1 执行形态：skills + tools calling（沿用既定路线）

- 规约模板（本体判定/detail 结构规约/desc 白话规范/行序流程重建/验收清单）沉淀为 **skill 文档**，注入对话 agent 的 system prompt。
- **规约按场景加载（防上下文污染）**：agent 只注入**当前场景相关**的规约子集（提取场景→本体判定/detail 规约；验收场景→符合性规约；命名场景→命名规约），**禁止默认全量加载**项目规约。规约条目带场景标签（§5.3），注入按标签过滤。
- 执行经 **tools calling**：`code.read_symbols`（读源码片段）、`asset.semantic.draft`（可选，规则管线出草稿）、`asset.semantic.save`（校验+落库）等。
- **执行载体分工（现有双 agent 通道，不合并）**：
  - **对话内提取/整理** → `req_agent` tools loop（提取/保存/改名/合并/拆分工具，提议制）；
  - **后台任务**（stale 批量修复、运行中任务恢复）→ 保留 `tAgent` agentic_loop（phase=kb_analysis，任务化+进度恢复机制现成）；
  - **严 profile 验收提取** → tAgent 任务化（触发源是异步 git diff/runner 完成事件，需要进度与恢复能力）。
- **触发提议制**：需求/分析对话中 agent 检索发现资产缺失或过期 → 提议提取（范围+理由）→ 设计者确认 → 执行。提取永远是被请求的动作。

### 4.2 两档提取 profile

| | 对话场景 | 验收比对场景 |
|---|---|---|
| 速度/成本 | 快管线 | 严管线（更强校验、规则提取与 LLM 提取**互证**） |
| 产出 | 常规资产 | 资产 + **置信度标注**（供符合性报告引用） |

### 4.3 复用与覆盖度诚实

- 已提取资产带锚点+内容哈希，未变更文件直接复用（reconcile 哈希机制现成），按需 ≠ 重复劳动。
- **覆盖度诚实标注**：按需提取意味着图谱是部分真相。UI 必须显式呈现"哪些组件/文件从未被提取、哪些资产已过期"——把局部图谱当全量事实本身违反如实原则。

---

## 5. 命名与术语治理

解决的核心问题：多次生成对同一资产/同类资产的命名不一致造成混淆。

### 5.1 身份与名称分离

```yaml
asset:
  identity:
    canonicalKey: "sym:OrderService.create"   # 代码结构决定，稳定
    anchors: [{file, symbol, startLine, endLine}]
  names:                                       # 名称 = 身份上的属性，带历史
    - {name: "采购订单", source: user,  status: active,  since: …}
    - {name: "订单实体", source: llm,   status: history, until: …}
```

- `name` 是业务名（认知层），`symbol/astRefs` 是代码事实（事实层）。改名只动认知层，不动锚点。
- 名称继承优先级：**用户手改名 > 历史名 > 规约生成名**。重新提取按 canonicalKey/锚点重叠匹配旧身份继承名称。
- LLM 提取时注入当前名作上下文（"当前名为 X，无充分理由不改名"）；改名永远是 LLM 的**提议**，生效需确认。

### 5.2 失效转参考池（墓碑，独立表）

- 锚点失效/部分失效 → 资产标失效，名称**不删除**，转入**独立墓碑表**（键 = symbol+文件，带来源/时间/失效类型）。user 名称与 LLM 名称走同一通道（一视同仁）。
- 部分失效：名称留在存续侧身份上继续生效，失效侧符号名进参考池并标"部分失效来源"。
- 新提取先查参考池——代码重生（同名符号回归）可捞回历史命名；LLM 命名前先查（"该符号曾名 X，语义未变则沿用"）。

### 5.3 规约与术语表（两个分立对象）

| | 命名规约 | 术语表 |
|---|---|---|
| 性质 | 模式规则（"过程资产用动宾结构"） | **词典**（"Order单→订单"），纯参考、非逻辑约束 |
| 作用 | 约束新生成的**结构**；合并门禁（见 §8） | 引导首次生成的**词汇**；UI 展示对齐沟通 |
| 来源 | agent 归纳用户改名模式**提议**（默认开启）→ 设计者确认固化；或手写 | 可从项目文档导入生成 |
| 作用域 | project / component（锚定组件） | project |
| 生命周期 | 作用组件代码结构大变时提示复核；**框架标准变更时，关联旧值域的规约标记"待复核"** | 随项目文档演进 |
| **UI 归属** | **"项目规约"页**（`/workbench/assets`）新增"资产命名规约"区块——与既有架构规约同页分区块，规约条目带**场景标签**（提取/验收/命名/通用） | 同页"术语表"区块 |
| **agent 消费** | **按场景标签加载**（提取对话只注入提取相关规约），**禁止默认全量注入**——防止上下文污染 | 注入为词典参考（同按需） |

> 注意：既有"项目规约"（架构规约/编码规约）与新增"资产命名规约"是**不同对象**，同页分区块管理，不混用。

优先级链：**用户单点改名 > 规约 > LLM 默认**。用户改名违反规约时提示但不阻止（规约是约定不是法律）。

### 5.4 写入口唯一（本节为命名治理的宪法）

> **"主 KB"定义（消歧）**：本方案中的"主 KB"指**architect 侧的多用户共享权威库**（项目级共享语义资产+规约+术语表，本期即 architect 主库 `architect.db` 的共享层），**不是** KB 解析构建服务（core engine kb :3459）。KB engine 全程无感知、零改动；"主 KB 在场"仅是 architect 内的授权策略开关（见 §11）。

- **单机（无主 KB）**：用户可自由改名/合并/拆分（本人即权威）；规约提示不阻止。
- **主 KB 在场**：**提取/写入 API 给出的命名不可修改**；改名、合并、拆分等一切认知层编辑**收口到主 KB 界面**操作。agent 可准备提案（预填新名/理由/涉及资产）并深链跳转主 KB 编辑界面——**决策始终在人，传输可由 agent 代劳**。
- API 是唯一通道、无旁路；单机/主 KB = 同一套 API 两种授权策略（standalone 策略：授权=本人；main-KB 策略：编辑=主 KB 界面）。不是两套代码路径，是策略开关。

### 5.5 API 归一化管线（LLM 多样性的机械消解）

```
提取/写入请求（唯一通道）
      │
      ▼
┌─ API 层（归一化裁决，机械执行）────────────────────┐
│ 1. 注入：规约 + 术语表(词典) + 该资产历史名/参考池     │
│ 2. LLM 受约束生成（提议名称/资产）                   │
│ 3. 裁决：继承优先(用户名>历史名>规约生成名)           │
│    → 规约结构校验（术语表仅参考不校验）               │
│    → 授权策略判定(standalone 直过 / main-KB 拒改名) │
└──────────────────┬────────────────────────────┘
                   ▼
            落库（main 或个人 overlay）
```

本体一致性不靠 LLM 自觉，靠协议：LLM 只提议，API 用确定性规则裁决。

### 5.6 同步与晋升

- 名称带版本号；主 KB 界面改名 bump 版本 → 各 architect 实例 reconcile 式刷新（避免"改了名但图谱/对话还是旧名"）。
- **单机 → 主 KB 晋升**：接入主 KB 时，单机积累的用户命名**整体晋升为初始权威命名**（不被重新生成覆盖）——与"用户编辑重放"同一精神。

---

## 6. 期望固化与验收闭环（核心章节）

### 6.1 契约包与验收单同源

设计者的"期望"必须有显式承载物，否则验收没有标尺。正向产物与验收标尺是**同一份**，只差"验收方式"字段：

```yaml
contract_item:                       # 契约条目 = 验收条目
  id: ci-042
  origin: "对话引用片段#12"           # 证据链：设计者原话
  kind: process                      # 本体类型（引用框架配置值域）
  target: {file?: "order/svc.py", symbol?: "cancel_order"}   # 锚点期望
  behavior:                          # 行为期望（L2 比对基准）
    steps: ["校验取消窗口", "调用支付网关退款", "状态→CANCELLED"]
    branches: ["已发货 → 403"]
  z_axis: {resilience: "网关超时3s重试2次"}    # Z 轴治理约束（新增轴）
  acceptance: {mode: auto|assisted|manual, criteria: "…"}
  status: draft → confirmed → injected → verifying → accepted/rejected
```

- **生成方式（对话式固化）**：方案讨论中 agent 边聊边把期望转成结构化条目 → 设计者**逐条确认**后生效。未确认条目不得进入契约包。
- 契约包 = 增量契约条目 + 引用的既有语义资产 id（X 轴不造第二套本体）+ 组件目录引用（Y 轴）+ Z 轴治理条目。
- 注入 coding agent 的规约与留给验收的标尺同源——消除"设计文档"与"验收标准"两张皮。

### 6.2 三层符合性比对

| 层次 | 判什么 | 手段 | 判定性质 |
|---|---|---|---|
| **L1 覆盖性** | 契约要求的实体/过程/规则/决策是否存在、锚点是否落在预期位置 | 资产 id/符号/文件机械比对 | 事实 |
| **L2 行为符合性** | 步骤顺序、分支、状态转移、调用关系与设计是否一致 | 提取的 steps/branches（行序重建）与契约条目做序列/图比对；图谱 flow/seq/state 视图做"期望 vs 实际"双图对照 | 事实 |
| **L3 语义符合性** | 命名、业务语义、Z 轴约束是否符合期望 | **人工主判**（基于 L1/L2 事实与代码/资产证据）；判断困难时由设计者**手动激活** LLM 评审——产出参考意见（带来源/置信度/证据），非判定 | **参考意见**（隔离呈现，证据必须引用锚点/资产 id） |

触发：runner 任务完成 / git diff 变更文件（`changed_files` 现成）→ 对 diff 文件跑**严 profile** 增量提取 → L1/L2 自动；**L3 不自动运行**——人工主判，按需手动激活模型辅助（plan-C-M0 §5 决议）。

### 6.3 差异报告与反馈（architect 不设自动修复循环）

- 差异报告每条带证据链：`契约条目 id + 实际资产 id + 锚点 + 差异描述`（如"契约要求 3 步流程，实际提取到 2 步，缺 X"）。
- 修复指令由 architect **起草**（事实性差异描述），**发送与否由设计者决定**。
- 设计者可**预先授权**部分类别自动回传（如仅 L1 覆盖性缺失自动打回）——授权留痕，是设计者让渡决策权，不是 architect 自主决策。
- 收敛：全条目通过 → 设计者终审 → 契约条目转正为新资产入库（认知正向沉淀，图谱即文档）。

---

## 7. 细粒度资产管理

- **操作语义**：改名（只动认知层）；合并（锚点并集 + detail 冲突标记 + 关系重定向到新 id）；拆分（锚点划分，agent 提议划分方案 → 用户确认）。全部留审计（谁/何时/为什么）。
- **用户编辑重放（三层模型）**：

```
事实层(extraction)    代码→资产，随时可重算
用户编辑层(overlay)   改名/合并/拆分/描述修订，带锚点依据 + author
呈现层 = 事实 ∪ 重放的用户编辑
```

  重放规则：锚点仍匹配 → 自动重放用户编辑；锚点消失（代码删除）→ 资产标失效并**提示设计者裁决**，不静默丢弃。
- **主 KB 模式**：结构编辑（合并/拆分）与改名同规则，收口主 KB 界面（§5.4）。
- agent 辅助工具：`asset.semantic.update / merge / split`（提议 → 确认 → 执行）。

---

## 8. 多人协作（本期 schema 留位，协议后置）

```
主 KB(main)          共识认知：资产 + 规约 + 术语表，只经显式合并变更
个人 overlay(branch)  每用户一份：命名/整理编辑，他人不可见
呈现层 = main ∪ 我的overlay
```

- 合并 = MR 式流程：diff（overlay vs main）→ 冲突检测（同 canonicalKey 异名）→ 裁决（管理者人工，或按规约自动仲裁）→ 合并留痕；命名不合规约可打回（规约的合并门禁用途）。
- **本期落点**：overlay 表带 `author` 键、资产编辑与规约带 `author/时间`。未来多人 = overlay 之上加同步/合并协议，底座不动。
- 统一从 **API 层**执行（§5.5/§5.6）：不在客户端散点治理，否则 LLM 分析的多样性无法消除。

---

## 9. tAgent 角色体系

不同认知工作绑不同模型/API——**用什么模型做哪类认知工作也要统一**（模型差异也是术语多样性的渗入源）。

```yaml
role = {name, model_id | api_profile, prompt_profile, 权限级别}
```

- 初始角色集：**提取**（快模型，API 层会裁决）/ **验收比对**（强模型，严 profile）/ **归纳**（中档，规约术语提议）/ **伪码解释**（快模型）。
- 配置三级：全局偏好 < 项目级 < **主 KB 下发**（主 KB 在场时角色表由它授权定义）。
- 实现：`llm_sync` 调用点按 role 取路由，改动集中在 agent 循环入口。

---

## 10. 与现状的映射（复用清单——不推倒重来）

| 重建概念 | 现有基建 | 缺口 |
|---|---|---|
| X 轴本体 | 语义资产 6 kinds + detail schema（fields/steps/branches/relations/states/transitions/constraints） | 框架配置化（值域可裁剪/扩展） |
| Y 轴抽象 | business/logic/implementation + 组件目录（L0/L1） | 同上 |
| Z 轴治理 | —（无承载） | **新增**：治理条目（轻结构：条目+锚点+校验规则引用） |
| 需求卡 | RequirementAnalysis（functionalScope/entityBoundary/assetScope）+ req harness（clarify/collect/assess/spec/plan） | XYZ 映射字段、验收标准结构化 |
| 契约包/验收单 | — | **新增**（§6.1），定稿链路末梢生成 |
| 反向提取 | 规则+LLM 管线（top-N、行序重建）、extract_scope(files/symbols/comm) | 转 skills+tools、严 profile、置信度 |
| 差分校验 | reconcile/handle_stale（哈希比对、changed_files） | 升格为全流程校验器 |
| 认知还原可视化 | 图谱 7 视图 + diagram.build IR 管线 + PseudoExplainer | "期望 vs 实际"双图对照 |
| 命名治理 | canonicalKey、`name_alias`（历史语义名 JSON）、`renamed_from`（改名溯源）——names[] 历史演进自这两列而非从零建；merge_seed_enrichment 语义保留 | 身份/名称分离、墓碑表、规约/术语表（落项目规约页+场景标签）、API 归一化、标准变更/代码变更双生命周期、status 作废态扩展 |
| 编码对接 | runner（execution.assign）+ MCP 出向雏形（mcp.call） | 契约→AGENTS.md 词汇表注入 |
| agent 编排 | 自研 tools loop（req_agent，对话通道）/ tAgent agentic_loop+ContextManager（后台任务通道，进度/恢复现成）——**分工见 §4.1** | 角色注册表路由；`asset.semantic.save/update/merge/split`、`code.read_symbols` 新工具 |
| 前端服务 | semantic-asset-service.ts（search/searchPage/detail/pseudo/extract/refresh/status/stats/reconcile/assetDiagram/批量清理/提取任务恢复） | 新增：framework CRUD、规约/术语 CRUD、merge/split/rename、契约条目 CRUD、验收报告 API（M0 定端点清单，走既有 `/api/architect` 前缀） |
| 验收比对 | codegraph AST 锚点 | L1/L2 比对器、符合性报告 |

---

## 11. 跨模块兼容与影响面（逐模块核实结论）

Monorepo 共 5 个模块群：core（kb :3459 / llm :3484 / gateway :3456 / runner :3458 等）、web-core、workbench、docs（文档 viewer :3481）、chat（AI CHAT :3483）、architect（:3470）。本方案重建范围 = **architect 单模块内部**，对外仅消费、不修改。逐模块影响面（已按代码核实）：

| 模块 | 与 architect 的实际耦合 | 是否受影响 | 护栏（必须遵守） |
|---|---|---|---|
| **KB 解析构建**（core engine kb :3459） | KB engine 不感知语义资产（无任何引用）；architect 只经 `KbGateway` **只读**消费 `knowledge.*` RPC（kb.asset.search/组件/ER/流程/代码映射）与 llm 透传 | **否** | ① 语义资产/框架配置/契约包/墓碑表/overlay 一律只落 architect 本地库，**不写 knowledge.db 与任何 KB 库**；② "主 KB"是 architect 内授权策略（§5.4），不是 KB engine 的新能力；③ 不改动 `KbGateway` 双通道契约（kb-contract.md §1） |
| **文档 viewer**（docs :3481） | `/api/diagram/*`（build/validate/ir-docs）挂载在 docs（`viewer.py`），底层是**共享核心模块 `packages/core/topoone/diagram/`**（DiagramSchema IR + builder + validator + legacy 兼容）；`/api/topo`（PlantUML 渲染）也在 docs。architect 的 `diagram.py` 是薄代理（单一起源，不拷贝建图逻辑） | **间接** | ① "期望 vs 实际"双图对照、契约可视化**复用**现有 7 视图 + `diagram.build` 管线，**不 fork 第二套 IR**；② 任何 IR 扩展必须走共享核心模块 `packages/core/topoone/diagram/`，并过 **docs 图编辑器 / AI CHAT / architect 三方消费方**兼容验证；③ 不改 `/api/topo` PlantUML 渲染路径 |
| **AI CHAT**（chat :3483） | 拥有 `diagram_editor` skill + `web_diagram_build`/`web_diagram_validate` 工具，**同样消费共享 diagram 模块与 docs `/api/diagram/*`**；chat 数据在 topoone.db/sessions.db，不感知语义资产；llm 服务（:3484）三方共享 | **间接** | ① tAgent 角色模型路由（§9）必须实现为 **per-call `model_id` 参数**，**不得写入全局 llm 配置**（现有优先级链：architect 配置 > 会话 modelId > 主后端全局默认，保持不动）；② 共享 diagram 模块的改动同样受上一条 docs 护栏约束；③ 不动 chat 的 `/api/chat*` 数据面 |
| **workbench**（主工作台） | 无直接代码依赖（仅 i18n 文案提及）；runner（:3458）的消费方是 architect（execution.assign），runner 本身无需改 | **否** | 不改 runner 任务协议；契约注入走 runner 已有的任务载荷扩展字段，不改 runner 核心 |
| **core 共享件**（gateway/llm/mcp） | gateway 动态反代（manifest `api_prefixes`）；MCP 入向：KB mcp_server(:3460) 把外部 agent 调用转发进 architect `/mcp/calls`（`mcp_collab` 仅记录，非执行面） | **否** | ① 新增 REST 端点走 architect manifest 既有前缀，不新增 gateway 反代规则；② 对外暴露的工具面（tools 列表/`[TOOL_CALL]` 协议）保持向后兼容，新增工具只增不改；③ 不触碰 gateway 鉴权/静态路由 |

**总护栏（M0 起生效）**：
1. **零 KB 写入**：重建全部产物落 architect 本地库；KB 解析构建、knowledge.* 契约、llm 服务配置面一律不动。
2. **共享 diagram 单一起源**：`packages/core/topoone/diagram/` 的改动是**跨模块变更**，必须三方（docs/chat/architect）回归；默认不改，IR 扩展优先用既有 type 组合表达"双图对照"。
3. **模型路由局部化**：角色→模型映射只存在于 architect 配置（全局偏好<项目级<主 KB 下发），以 per-call 参数生效。
4. **工具面只增不改**：`[TOOL_CALL]` 协议、既有 17 个注册工具签名保持兼容，新能力用新工具名。

---

## 12. 实施路线

- **M0（schema 冻结）**：定契约条目/验收单 schema（含 Z 轴轻结构与部署拓扑占位）、框架配置 schema、墓碑表/overlay schema、**`arch_semantic_assets.status` 作废态扩展**、**新增 API 端点清单**（framework/规约/术语/契约/验收，走 `/api/architect` 既有前缀）。**schema 即协议，是唯一必须先冻结的东西**。冻结清单同时锁定 §11 四条总护栏（零 KB 写入 / diagram 单一起源 / 模型路由局部化 / 工具面只增不改）。
  - **第一批已评审关闭**：`plan-C-M0.md` §1-§3 —— 三组预设具体清单（§1，low 修正为 5 类无 state）+ 契约条目 schema/状态机/契约包/验收报告（§2，facts/opinions 分表）+ 联动校验规则 V1-V8（§3）。
  - **第二批已产出（评审中）**：`plan-C-M0.md` §6-§9 —— 全部存储 DDL 冻结稿（墓碑/overlay/框架配置/voided 列扩展/规约+术语/契约验收五表）、REST API 端点清单（§7，`/api/architect` 前缀）、agent 新增 8 工具（§8）、设计规则 R1-R7（§9：框架作废不写墓碑/overlay 有序重放/版本行即审计/facts-opinions 分表/场景标签 NOT NULL 等）。
- **M1（认知底座配置化 + 按需提取）**：框架配置（三组预设+自建，UI 在资产概览 tab；变更作废确认流）落地；语义/组件 tab 合并为组件树挂资产；提取转对话式 skills+tools（`code.read_symbols`/`asset.semantic.save`）；覆盖度标注；角色注册表；规约场景标签。
  - **后端已完成**（2026-08-30，289 tests passed）：M0 全部 DDL 落地 `db_schema.py`（10 表+voided 列迁移）；stores（FrameworkConfig/NameTombstone/UserOverlay/NamingConvention/Glossary）；`asset_framework.py`（预设/switch/preview/coverage + REST `/framework*`、`/semantic/coverage`）；agent 工具 `code.read_symbols`+`asset.semantic.save`（归一化管线：值域校验/名称继承/墓碑承接/复用 `_save_assets` 去重与幻影拒绝）。
  - **前端已完成**（bundle `architect.CcPMBPq6.js`）：资产 tab 四→三（语义+组件合并为组件树挂资产，组头带覆盖度徽标+对话提取+owns tooltip）；概览新增框架标准面板（三档卡片+preview→confirm→switch 确认流）与覆盖度面板；**全量提取入口退役**（头部按钮→对话提取、chat 内嵌按钮 `show-extract=false`、组件复选批量模式 UI+函数整体移除，任务恢复指示器保留）；INCLUD/CALL 与 L0/L1 组件口径假筛选移除（合并 tab 无作用，如实原则）；i18n zh/en。
  - **后端补齐 + 前端配置**（bundle `architect.BTlz_9Am.js`，297 tests passed）：角色注册表 `agent_roles.py`（默认四角色 extract/verify/induce/pseudo + REST `/agent/roles` + `role_model_id()` per-call 解析助手，三级覆盖留位）；`asset_skill.py` 规约按场景注入（builtin extract/accept/naming 规约 + 项目规约库按 scenarios 标签过滤，R7 落地）——WS `skillScenarios` 链路打通，资产管理对话恒传 `['extract']`；ConfigPage 新增「角色模型映射」卡片。
  - **M1 关闭**。顺延 M2：命名历史 API+行内徽标（行内已有 renamedFrom/alias 展示，完整历史随 overlay）、merge/split UI、`role_model_id` 接入 tAgent 循环入口（当前 helper 就绪未接线）。
 - **M2（正向闭环）**：方案对话中期望固化 → 契约包生成 → runner 消费（AGENTS.md 注入）→ git diff 触发严 profile 提取 → L1/L2 比对 + 差异报告 → **局部验收 UI 落单元测试页** → 主 KB 界面（命名/结构编辑收口）。
   - **M2 后端已完成**（314 tests passed）：`store.py` 追加 `ContractItemStore`/`ContractPackageStore`/`AcceptanceStore`（facts/opinions 物理分表 R6）；`contracts.py` 契约条目状态机（V1-V8 校验：值域/origin/入包/意图级/low 档 z/state 专用/rejected 改期望/框架变更 stale 重确认）+ 契约包（框架快照随行冻结 + agentsMd brief/full/full-scaffold 三档详略 + inject 条目→injected）+ REST 10 端点（含 draft 修改 PUT/删除 DELETE）；`acceptance.py` 验收执行（变更范围→严 profile 提取→L1 覆盖性/L2 行为符合性机械比对→facts 落库→条目 verifying）+ 手动激活 L3（模型辅助参考意见，`triggerBy=user`，无自动写入方）+ 修复指令起草（只起草不发送）；`asset_framework._apply_change` 补 V8 联动（非 accepted 条目标 staleByFramework + 切 z 空值域清 zAxis）；`req_agent` 新增 `contract.propose` 工具（ctx 回填 origin.convId 证据链）+ 能力文档；`asset_skill` 新增 `contract` 场景规约（🧾 注入）。
   - **M2 前端已完成**（vue-tsc 零错误 · build `architect.BlnwQx3G.js`）：`contract-service.ts`（契约/验收全端点适配）；`useContractSkill` composable（🧾 会话级开关）；`AnalysisChat` 契约条目固化卡（逐条 确认/修改/删，仅 draft 可操作——判定统一在验收区块）+ 🧾 开关按钮；`RequirementWorkspace` 接线（`skillScenarios:['contract']` + tool_result 钩子按新增 draft 追加卡片回合 + 会话首发送前快照旧草稿防误报）；`RequirementsPage` 需求详情契约条目只读区（状态机展示）；`UnitTestPage` 新增固定「局部验收」tab → `AcceptancePanel.vue`（契约包选择 + 触发验收 + 报告展开 L1/L2 事实徽标/证据 + 设计者通过/打回 + 激活 L3 参考意见 + 修复指令草稿复制）；i18n zh/en。
    - **M2 剩余（顺延）→ 已收尾**：~~runner 完成自动触发验收~~ → M3 完成（verify 端点后台钩子，trigger=runner_done）；~~`role_model_id` 接入 tAgent 循环入口~~ → **B1 完成**（`resolve_role_model` per-call 接线 websocket/execution/extract/generate_pseudo）；~~命名历史完整 API~~ → M3 完成（`GET /semantic/assets/{id}/names`）；~~merge/split~~ → M3 完成（端点+工具+overlay 审计，UI 入口随 rename 同区扩展位）；~~"期望 vs 实际"双图对照~~ → **B2 完成**（§13.5 评估：无需扩展 IR；`acceptance.dual_diagram` + 前端双 DiagramCard 并排 + 差异 style 高亮）；~~差异报告通知卡~~ → **A5 完成**（对话内轮询新报告→通知卡+摘要+深链验收区块，判定动作仍在验收区块）。
 - **M3（验收收敛 + 治理完备）**：L3 语义评审（人工主判 + 按需模型辅助入口）、L1/L2/L3 事实与参考意见双通道呈现、经验回写（失败模式反哺规约/默认值）、**命名规约/术语表落"项目规约"页（场景化加载）**、术语表导入、单机→主KB晋升。
   - **M3 后端已完成**（2026-08-30，333 tests passed）：`naming.py`（M0 §7.2/§7.3 全部端点：命名规约 CRUD+induce 提案（pending→active 设计者确认）+场景检索、术语表 CRUD+文档导入（JSON/行式解析、realpath 越界校验、512KB/500 条上限、source_ref 溯源）、墓碑参考池查询、`GET /semantic/assets/{id}/names` 命名历史（墓碑+overlay 改名重放+行内溯源，pid 以资产行自身为准））；`semantic_assets.py` 就地认知编辑三端点 `POST /semantic/assets/rename|merge|split`（rename：旧名入 renamedFrom/nameAlias；merge：锚点并集+目标行 deleted+mergedInto；split：按 anchorKeys 锚点组拆新资产+原行 splitInto；均 overlay 审计 op=rename/merge/split）；**R5 策略开关在端点层**（`MainKbEditRejected`：main-KB 关联项目 409 拒绝+深链 `/kb/{pid}/assets`，standalone 直过）；`req_agent` 新增 3 工具 `asset.semantic.update`（{assetId, patch{name?,desc?}}）/`asset.semantic.merge`/`asset.semantic.split` + 能力文档（含补 contract.propose 参数行）；`execution.py` **M3-6 runner 完成自动触发验收**（verify 端点=runner 完成信号 → 后台线程按 reqId 关联契约包 → `run_acceptance(trigger=runner_done, ref=taskId)`；判定仍唯一归设计者）；`acceptance.run_acceptance` 补状态机守卫（仅 confirmed/injected/verifying 条目进入 verifying，draft/accepted/rejected 不受触碰）；`store.py` 补 `NamingConventionStore.get/delete`、`GlossaryStore.get`。
   - **M3 前端已完成**（vue-tsc 零错误 · build `architect.CpYOVqb3.js`）：`naming-service.ts`（规约/术语/墓碑/命名历史全端点适配）；`NamingGovernancePanel.vue`（三子 tab：命名规约——新增/场景标签多选/pending 确认/停用启用/删除、术语表——搜索/新增/文档导入/删除、命名历史——墓碑参考池搜索）；SpecWorkspace 第三 tab「命名规约」挂载；`semantic-asset-service.ts` 补 rename/merge/split；`SemanticAssetsView` 资产行内改名（铅笔→inline 输入→确认/取消，main-KB 409 弹错误消息）；i18n zh/en（`naming.*`、`architecture.tab.naming`、`semanticAssets.rename`、`common.loading`）。
    - **M3 剩余（顺延）→ 已收尾**：~~经验回写（失败模式反哺规约/默认值）~~ → **A1 完成**（打回→后台归纳 pending 规约 + skill_docs accept 场景注入）；单机→主KB晋升 → **A2' 完成（仅预留对接 API 层）**：新增 `mainkb.py`（`GET /mainkb/status` 授权策略开关/深链/晋升预留位 + `POST /mainkb/promote` 预留 501 不静默）+ 前端 `mainkb-service.ts`；**晋升本体**（用户命名整体晋升为初始权威）仍后置独立服务化（§后置）；~~merge/split 独立 UI 操作位~~ → **A3 完成**（SemanticAssetsView 行内 split 编辑器 + 多选 merge 操作条）；L3 自动触发策略 → **维持仅手动激活**（保真纪律，不实现自动触发）。
- **后置**：部署/运维模型实现、多人合并协议、外部 coding agent（Cursor/Devin）适配器、"主 KB"独立服务化（如需，届时作为新模块立项，仍不改 KB engine）。

---

## 13. 遗留待定项

1. ~~墓碑表/overlay 表的具体 schema 与索引~~ → **已冻结**：`plan-C-M0.md` §6.1/§6.2。
2. ~~低/中/高三组默认预设的 kind/粒度组成清单~~ → **已定稿评审关闭**：见 `plan-C-M0.md` §1（综合 plan-A §五 / plan-B §4.4 / 本方案，low 修正为 5 类无 state）。
3. ~~术语表导入格式（从项目文档/词汇表文件）~~ → **已实现**（M3）：JSON 数组/对象 或 行式「- 术语: 定义」「术语 | 定义」，source_ref 记录来源文件，越界路径/超大文件/超条数拒绝。
4. ~~Z 轴条目与 acceptance `mode=auto` 的可授权清单细则~~ → **已定稿（C1）**：可授权清单 = 当前 `acceptance.mode` 下**哪些校验可自动授权、哪些必须人工**。**可自动授权（机械可比）**：L1 覆盖性、L2 行为符合性、**带锚点的 Z 轴条目**（锚点存在性）；**必须人工**：意图级 Z 轴条目（无锚点，机械查不出"理解跑偏"）、L3 语义（永远不自动）。mode 语义：`auto`=L1/L2 通过即过（low 默认，不跑 L3）/`assisted`=L1/L2 自动+L3 人工主判按需激活（mid/high 默认）/`manual`=逐条人审（机械项也不自动）。**`autoPassable`** = 条目结构上可被 `mode=auto` 自动授权（`mode=auto` 且无意图级 Z 轴条目）。判定权仍归设计者（contracts.verdict 唯一入口），清单只是"可自动授权边界"的显式化。实现：`contracts.authorization_list` 核心 + `POST /contracts/items/{item_id}/authorization` 端点 + 前端验收面板「可授权清单」卡（逐条标 可自动授权/需人工 + autoPassable 结论）。
5. ~~"期望 vs 实际"双图对照是否需要扩展共享 IR（`packages/core/topoone/diagram/`）~~ → **评估完成（B2）**：**无需扩展 IR**。双图 = 两个独立 `DiagramSchema`（期望侧/实际侧各一，`type=flowchart`，复用 11 种既有 type），并排渲染；差异高亮用**既有字段**表达——`DiagramNode.style.stroke/fill`（期望侧"实现缺失"红、实际侧"实现多余"琥珀）+ `DiagramEdge.kind`/`label`，不新增任何 IR 字段/type，不 fork 第二套 IR（§11 护栏 ① 守住）。实现：`acceptance.dual_diagram` 端点产出两份 schema，前端经共享转译器 `toMermaid`（`@topo/web-core/topoOne`）转码后由既有 `DiagramCard` 渲染。
6. ~~标准变更作废的物理存储策略~~ → **已冻结**：`plan-C-M0.md` §6.3/§6.4（版本行即审计 + voided 列扩展）+ §9 R1/R4。

---

## 14. 设计原则总结

| 原则 | 体现 |
|---|---|
| **源码是唯一事实源** | 反向提取生成认知底座；差分闭环做全流程校验 |
| **architect 不决策** | 决策权在设计者；输出=声明式协议消息；修复指令只起草不发送 |
| **如实传递** | 事实/意见分离、全程证据链、保真失败显式化 |
| **本体即配置** | 框架档位化+值域/轴可自定义；X 轴复用语义资产不造第二套本体 |
| **一致性靠协议不靠 LLM 自觉** | API 归一化管线：LLM 提议、API 机械裁决、名称写入口唯一 |
| **按需不批量** | 提取由任务触发+提议制；哈希复用；覆盖度诚实标注 |
| **人工整理优先** | 用户编辑重放（锚点匹配自动重放）；单机命名晋升为权威 |
| **brownfield 差异化** | 存量系统的契约基线可从代码反提取——通用方案没有的能力 |
