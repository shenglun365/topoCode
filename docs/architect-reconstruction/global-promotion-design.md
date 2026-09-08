# 认知层 → 主库提升策略（G · 设计稿）

> 状态: 设计定稿, 待实现。对应能力对齐第八项(WS8)。
> 前置: WS7 能力提炼闭环(arch_capability_proposals)、语义资产/规约项目库存储已就绪。

## 1. 背景与目标

当前所有认知产出（语义资产、命名规约、提炼能力）都落在**项目库**
（`~/.topocode/architect/<pid>/arch.db`），项目间零共享。大量项目会重复验证
同类模式（命名规律、架构经验、通用实体语义），需要一条**受控的提升通道**：
项目内验证过的认知产出 → 主库全局层，供跨项目检索复用。

KB 服务侧维持「仅项目关联信息」现状（用户确认）；通用知识层（KB 全局）
未来构建时另行预留接口，不在本设计内。

## 2. 提升对象（用户确认：都包含）

| 对象 | 来源表 | 全局层价值 |
|---|---|---|
| 语义资产 | `arch_semantic_assets` | 通用实体/流程语义（如标准容器、协议解析模式），新项目冷启动候选 |
| 命名规约 | `arch_naming_conventions` | 跨项目命名纪律（如「服务以 Service 结尾」） |
| 提炼能力（流程/技巧/skill） | `arch_capability_proposals`(accepted) | agent 工作经验跨项目复用 |

**不提升**: 会话/消息/执行任务（项目过程数据）、墓碑/overlay（项目内编辑留痕）、
锚点 astRefs（源码强绑定，跨项目无意义——提升时**剥离锚点只留语义**）。

## 3. 数据模型（主库全局桶）

复用现有表结构 + `project_id` 哨兵，不建新表：

- 主库已有同 schema 表（PROJECT_TABLES 在主库有默认桶）；全局层用
  `project_id = '__global__'` 哨兵标识。
- 提升产物字段约定：
  - 资产: `scope.type='global'`、`originProjectId=<来源项目>`、`promotedAt`、
    `astRefs` 清空、`meta.originAssetId` 留痕（回溯与去重键）。
  - 规约: `scope='global'`、`source='promoted'`、`originProjectId`。
  - 能力: `status='promoted'`、`originProjectId`。

## 4. 流程（与 WS7 提案队列同构——半自动，设计者裁决）

```
项目内验证成熟(设计者判断)
  → 发起提升(资产页/规约页「提升到主库」按钮 或 会话工具 capability.promote)
  → 冲突预检(见 §5) → 无冲突直接入 pending; 有冲突带对比入 pending
  → 主库管理页(会话中心同款队列 UI)逐条 采纳/忽略
  → 采纳: 写主库全局桶(origin 留痕) ; 来源项目条目不变(只读引用)
```

谁审: **设计者**（pending 队列逐条裁决, 同 convention/capability 提案模式）。
不做自动提升（半自动循环: agent 可提议, 人裁决）。

## 5. 冲突策略（同名/同语义, 不自动覆盖）

预检按「语义指纹」比对全局桶既有条目：

1. 资产: 名称规范化键（沿用 canonicalKey 归一规则）相同 → 冲突；
   冲突时展示两侧 desc/fields 对比，人工三选一: 跳过 / 合并(全局侧吸收差异) / 强制并存(带后缀)。
2. 规约: ruleText 归一(去空白/标点)相同 → 视为重复, 提示跳过（全局已有）。
3. 能力: title 精确相同 → 重复跳过; 不同但 scenarios 重叠 → 并存(注入时按 title 去重)。

## 6. 消费侧（只读、按需、不自动注入）

- 全局层对项目**只读**：项目内不落副本，检索时合并返回
  （`asset.semantic.search`/`map.assets` 增 `include_global` 参数, 默认关；
  规约/能力注入同理按需开关——遵守 R7 禁全量注入）。
- 新项目冷启动: 项目概览页可一键「从全局层导入候选」（复制为本项目库条目，
  origin 留痕），导入后即可参与本项目锚定/编辑。
- KB 通用知识层（未来）: 预留 `promote_to_kb(global_entry)` 接口位，构建时接通。

## 7. 权限与安全

- 提升与采纳均要求设计者身份（与现有 pending 队列一致的本地单用户模型）。
- 主 KB 保护不受影响：`_check_main_kb_policy` 拒绝认知层直写主 KB——本通道
  只写 architect 主库全局桶, 不触碰 KB 服务；未来接通用知识层时走独立审批。

## 8. 实施拆分（待排期）

| 步骤 | 内容 | 依赖 |
|---|---|---|
| S1 | 全局桶读写辅助（`__global__` 哨兵 + store 查询合并） | 无 |
| S2 | `capability.promote` 工具 + 冲突预检/对比 | S1 |
| S3 | pending 队列 UI（会话中心「能力提案」扩展为主库提升队列） | S2 |
| S4 | 检索/注入侧 `include_global` 开关 + 冷启动导入 | S1 |
| S5 | KB 通用知识层接口预留（stub） | 设计确认后 |
