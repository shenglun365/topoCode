# B1-W6 实施文档：skills 化第一批（表为真相源 + 路由协议）

> 组：W6(2~2.5d) · 依赖：无硬依赖（**D-1 已裁决解除阻塞**；`test.strategy` 技能需 W5 先行）· 决策依据：D-1（arch_assets 表为真相源，不做 yaml 导入导出）/ D-9（首批技能随实施定）
> 定位：v2-todo P1"可执行 skills"的落地 + benchmark C 节路由协议（学 Roomote initial_routing/child_registry **协议**，载体为表）

---

## 1. 模块操作总表

| 模块 | 操作 | 摘要 |
|---|---|---|
| `store/schema.py` | **变更** | 新增 `arch_assets` 表（v2-todo P1 规划的表，本批落第一期） |
| `store/`（新存取模块） | **新增** | assets 存取（CRUD + kind 过滤） |
| `arch_routes/asset_tools.py` | **变更** | asset.upsert/list/delete 工具面落地（v2-todo P1 规划），支持 kind=skill |
| `agent/tools/registry.py` + `agent/tools/req_agent.py`（`_ARCH_SKILLS`） | **变更** | 技能注册表读取改为 **arch_assets 优先、内置为缺省源**（增量覆盖） |
| `agent/turns/context.py`（或 cognition/prompt.py 装配段，实现时按 ctx_budget 接缝择一） | **变更** | 会话首轮注入 skills 目录 + 路由指令（开关 `skill_routing_injection` 缺省开，受 ctx_budget） |
| 首批技能定义 | **新增** | `extract.requirement` / `analyze.suggest` / `test.strategy`（W5 后入列） |
| 移除 | 无 | `_ARCH_SKILLS` 内置注册表**保留为缺省源**（回退位） |

## 2. 逐模块明细

### 2.1 `arch_assets` 表（store/schema.py）

**结构（第一期）**：
```
arch_assets(
  id, project, kind,        -- kind: skill | requirement | todo | plan | ...（v2-todo 五类预留，本批只消费 skill）
  name, description,
  payload JSON,             -- skill: {route_hint, child_registry[], instructions_md, enabled}
  created_at, updated_at
)
```
**route_hint**（N 选 1 路由描述——学 Roomote 强制路由协议：会话首轮技能目录带"按任务类型强制选择"指令）；**child_registry**（子技能引用，父子委派协议的最小承载）。

**上游**：asset 工具面（LLM 可写）；内置注册表迁移导入。
**下游**：registry 读取；会话首轮注入；（远期）G 提升 P2-T6（主库三类对象通道——本批只预留 kind 维度，不做提升）。

### 2.2 `arch_routes/asset_tools.py`（工具面）

**改动**：`asset.upsert/list/delete` 三工具落地（v2-todo P1 规划形态）；校验：kind 白名单、payload 按 kind 的 schema 校验（skill 型校验 route_hint 非空）；LLM 经工具面可查询/启用/禁用/新建技能——**agent 可自建技能**（D-1 表形态的核心红利）。

**上游**：LLM 工具调用（回合引擎工具面）。
**下游**：registry；用户在设置面管理（管理 UI 不在本批，REST 即可用——C1 先例：REST 先行 UI 后置）。

### 2.3 `agent/tools/registry.py` / `_ARCH_SKILLS`

**改动**：技能解析顺序 = arch_assets(kind=skill, enabled) **覆盖** 内置 `_ARCH_SKILLS`（同名以表为准）；内置表保留为缺省源（无表数据时行为与现状一致——回退位）。

**上游**：arch_assets。
**下游**：会话首轮注入的技能目录。

### 2.4 会话首轮 skills 目录注入

**改动**：会话首轮装配段注入：技能目录（name + description + route_hint 摘要）+ 路由指令（"按任务类型从上述技能中选择，不得自由发挥绕过"——N 选 1 强制形态的 architect 化）；字数受 `ctx_budget`（技能多时按 description 截断+提示可用 list 查全量）。开关 `skill_routing_injection` 缺省开。

**上游**：registry 解析结果。
**下游**：W1-1 golden 新增注入段快照（golden 变更=模板版本变更，成对纪律）；会话路由行为。

### 2.5 首批技能（D-9）

| 技能 | 来源 | 说明 |
|---|---|---|
| `extract.requirement` | 收编现有 | 需求提取（v2-todo P1 既定） |
| `analyze.suggest` | 收编现有 | 分析建议（v2-todo P1 既定） |
| `test.strategy` | W5 封装 | 缺口建议的技能化入口（`sem/test_reach` 的调用封装）——**若 W6 先于 W5 动工，首批砍掉它**，W5 完成后补录 |

每技能 payload：instructions_md（操作指引）+ route_hint（何时选我）+ child_registry（空或引用）。

## 3. 数据与契约变更

| 面 | 变更 | 兼容性 |
|---|---|---|
| 表结构 | 新增 `arch_assets` | 纯新增表，无 N-1 风险；schema.py 基线登记 |
| 工具面 | +3 工具（asset.upsert/list/delete） | 回合引擎工具注册增量 |
| 会话装配 | 首轮 + 技能目录段 | 开关可关；golden 同步（模板版本 +1） |
| **不做** | yaml 导入导出（D-1 远期）、repo-local 技能发现（远期） | — |

## 4. 测试计划

- `tests/test_arch_assets.py`：表 CRUD；kind schema 校验；同名覆盖解析（表>内置）
- `tests/test_asset_tools.py`：三工具行为与校验失败回喂
- `tests/test_skill_routing.py`：首轮注入段（目录+路由指令）；ctx_budget 截断；开关两态
- golden：注入段入快照族
- 手测 DoD 6：`test.strategy`（若时序允许）可被路由选中；`asset.list` 可见 3 技能

## 5. 回退

| 片 | 回退 |
|---|---|
| 注入段 | `skill_routing_injection=off` |
| 表形态 | 清空 arch_assets 即回内置注册表行为（表为增量覆盖层） |
| 工具面 | 工具注册摘除（表保留无害） |

## 6. 组内验收清单

- [ ] arch_assets 建表 + 基线登记；asset 三工具可用（LLM 实测 list/upsert）
- [ ] 同名技能表覆盖内置；清表回退内置（回退位验证）
- [ ] 会话首轮见技能目录与路由指令；`skill_routing_injection` 可关
- [ ] golden 更新走模板版本 +1
- [ ] 首批技能入列（test.strategy 视 W5 时序）
