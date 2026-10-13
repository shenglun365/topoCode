# 执行器会话机制拓展（2610）

> 2026-10-08 · 已实施 A/B 两期 + C 核实收敛。裁决：全量一次做完 / architect 自持留痕 /
> 只护入口 / 仅局域网（可跨网段）。

## 形态

```
[浏览器·任意网段] ──Bearer/?token──> [architect :3470 (默认 0.0.0.0)]
  ├ TokenAuthMiddleware: /api/**+WS 校验, 本机豁免, 静态壳豁免(FE #token= 引导)
  ├ /arch/runner-proxy/** 受限反代(→RUNNER_BASE_URL/api/implement/*, SSRF 钳制)
  ├ arch_exec_events 留痕(pump 双写, job+seq 幂等)
  └ FE: /workbench/exec-sessions 会话浏览器(档案+事件时间线+live)
[执行机: runner+执行器同机] ← localhost(RUNNER_BASE_URL 可指远程机)
```

## 分期交付

| 期 | 提交 | 内容 |
|---|---|---|
| A | `03421395` | 口令中间件(Bearer+?token/环回豁免/rotate REST) + runner 反代 + MCP URL 注入；核实 approval_request 协议已在 |
| B | `174fd844` | arch_exec_events + pumps 双写 + 会话档案 REST(任务关联) + 会话浏览器 FE(18 kind 分色/live/新标签窗口) |
| C | 增量提交 | 连通既有面：会话行↗跳会话流；执行器分布统计 |

## C 期核实结论（大量已有，未重复建设）

| 项 | 现状 | 位置 |
|---|---|---|
| C1 会话聚合/新建直通 | 会话页 quick 挡直通(创建/输入/续话) | SessionsPage + proxy.py |
| C2 对话交互(流式/停止) | 直通消息流 + job.stop | ChatFeedPanel workState |
| C3 diff 视图 | 验收卡 diffSummary(通过率/待人工/前三差异) | ChatFeedPanel acceptance |
| C4 审批双向化 | approval 卡片按钮(批准/拒绝→/approval 应答) | ChatFeedPanel respondApproval |
| C5 checkpoint | **降级不做**：runner 无 checkpoint 事件 kind | —（协议出现后补） |

## 运维备忘

- 口令获取：本机 `GET /api/architect/arch/security/token`；远程首访 `http://<ip>:3470/architect.html#token=<tok>`
- 轮换：`POST /arch/security/token {action:"rotate"}`（旧口令即时失效，含已注入的 MCP URL）
- 留痕清理钩子：`exec_events.delete_before(ts)`
- 跨网段：防火墙放行 :3470 即可；token 是唯一应用层防线（LAN 明文 HTTP，自签 HTTPS 未做）

## 会话中心并入与子会话模型（2026-10 二期）

**模型**：主会话 → 多个 coding 子会话（独立上下文=独立消息流）→ 每个子会话
各绑执行器（可同可不同、可换绑）；主会话级 `activeCodingSession` 单值活跃槽。

| 项 | 交付 |
|---|---|
| 列表并入 | SessionsPage 左栏三标签（会话列表/需求跟踪/**执行器会话**）；`ExecSessionListPanel` 双形态复用（panel=点行右侧打开关联会话；page=独立页）；独立页保留为「新 tab」形态（`?job=` 定位） |
| 子会话执行器域 | create 收 `executorId`（缺省继承主绑定）；换绑 `POST /sessions/{sub_id}/executor`（清 sessionRef，下回合新执行器 start_session 重建，对话连续；在跑拒绝）；dock 弹层按执行器分组 + 行内换绑 + 新建选执行器 |
| 主 agent 通讯面 | `coding.sessions` / `coding.feed` 注册进 map_tools（内部接口，非 MCP）——主 agent 对话可查可投 |
| 窗口唯一性 | `useConvWindowLock`（BroadcastChannel + localStorage 心跳 3s/过期 10s）；跨 tab 冲突 → 接管确认；dock 单实例天然唯一 |
| 实时感知 | SSE conv-message → `arch:conv-message` 广播 → dock 子会话行闪动 + 池刷新 |
| **统筹调度** | `execution/executor_scheduler.py`：内存注册表 + admit 仲裁（同会话重复启动 reject；**isolated 并行 / inplace 同 root 排队**；执行器并发上限 `maxConcurrent` 默认 2 + 全局 8）；排队 FIFO，前序终态 → `relaunch` 自动续跑（产出经 pump+SSE，不依赖发起 WS）；用户主动停止不续跑。proxy 全链路接线；任务链由既有脏工作区门禁（cv-282）间接覆盖 |

门禁：pytest 1449（+8 test_coding_subs）/ vitest 89 / tsc 0 / build ✓

## 执行器统一模型增补（2026-10-11，2610 裁决二期）

> 裁决与全景见 `agent-session-flow.md`「执行器统一模型」节。本节仅记执行器会话面的增量。

- **子会话可绑 architect**：kind=coding 保留为「子会话」标记（与绑哪个执行器
  无关）；architect 子会话=主会话下的独立分析上下文（回合走分析管线，
  无 runner 下发面），子会话池按执行器分组天然呈现 architect 组。
- **主会话解禁换绑**：`POST /sessions/{id}/executor` 主/子通用（在跑拒绝、
  清 sessionRef、模型重置、对话连续）；原「一次绑定不可换(换=克隆)」退役，
  克隆收窄为上下文分叉。
- **feed-up 上投**：`POST /sessions/{sub_id}/feed-up`——architect 子会话产出
  → 主会话活跃执行器子会话/作业（交付核心 `agent/sessions/feeds.py`）。
- **运行态聚合**：直通作业 workState/runningRole 补齐（注册置 running，终态经
  `process_stream.proxy_finish` 单点回落）——会话列表/执行器会话页/删除守卫
  同口径。
- **状态域拆分**：`execution/proxy_state.py`（句柄表/查询/停止/JobCard 回写，
  自 proxy.py 机械迁出，转发导入保路径不变）。

## 统一列表（2026-10-11 二期，会话管理 UI 同步改造）

> 裁决：主行展开子会话树；「执行器会话」标签并入统一列表后移除；作业删除=档案+终态任务行。

- **主+子树**：会话列表主行 chevron（`subCount`，过滤前按 parent 聚合零额外查询）懒加载
  展开 `/coding-sessions`；子行=执行器徽标（architect 显式）+ 运行态脉冲（`execution`
  字段，守卫单源 `active_execution_of`）+ 打开/作业历史/删除（非执行态）。
- **作业历史弹窗**（`SessionJobsDialog`）：按 conversationId 过滤 `/arch/exec-sessions`；
  ↗ 时间线深链（/exec-session-view 保留）；终态作业可删。
- **作业删除**：`DELETE /arch/exec-sessions/{job_id}`——活跃拒绝（无终态事件或任务
  非终态）；删除=留痕档案（exec_events）+ 关联终态任务行（`TasksStore.delete`/
  `by_runner_job` 新增）；会话行/消息不动（job≠会话）。
- **标签移除**：SessionsPage 三标签→两标签（会话列表/需求跟踪）；`ExecSessionListPanel`
  孤儿组件删除；原执行器会话浏览/删除职责由统一列表承接。
- **守卫修复**：`list_coding_sessions.runningRole` 恒空 stub → `execution` 真实运行态
  （dock 子会话池删除禁用判定同步接真数据）。

## 运行时同步与调度增补（2026-10-12，cv-6~cv-18 弧线）

### 调度器 idle 让坑（裁决 A）
- `_entry_mark` running→idle 转换即 `scheduler.release_conv(conv_id)`——**等待输入的保活会话让出工作区槽位**，同 root 排队会话立即续跑（此前 keep-alive 永不终态 → inplace 会话永久排队无反馈，cv-7 事故）。
- 保活会话的回复经 `/input` 分支**占用仲裁**：同 root 有其它会话真执行中 → 排队（`busy_by_other`），轮到自动转达（`scheduler.release_conv` / `state_of_conv` / `busy_by_other`）。
- 排队反馈：卡片 meta `queued`+位次、`proxy_state.queued`、列表 ⧗ 排队中 chip、⏳ 回执文案。

### 直通状态同步链（cv-15 主诉修复）
```
发送 ─0ms→ 乐观置位(optimisticRole, 独立 ref 不污染 activeMeta) → 两位置翻▶
  ≤3s → conv-message 节流窗 refreshActiveMeta 权威校验
  收束 → done 帧 + turnEnd → syncRunningState 相位回落(权威)
SSE 断连 → realtimeDegraded → dock/SessionsPage 10s 轮询保底 + 黄条提示
```
- 执行期 5s 固定轮询已撤销（S2）——`syncRunningState` 由 `arch:turn-end` 事件驱动。
- JobCard 按钮跟随状态：running=⏸暂停+⏹结束（`/proxy-stop` mode 显式覆盖）/ idle=仅⏹结束会话 / ended=无按钮。
- 会话列表请求合并：`sessionService.list` 在飞共享+250ms 合并窗；SessionsPage 事件 400ms 防抖；`rehydrateProposals` 门控（无需求卡不拉 /requirements）。

### MCP 面（cv-6~cv-14 修复链）
- `/mcp` 挂载修复：`server.py` 路由提升（FastMCP 内部裸 Route /mcp，Mount 双前缀致 404——cv-6 事故）。
- opencode 注册形状归一：`_opencode_headless_config` 补 `type:"remote"/"local"`+`enabled`（官方 schema type 必填，缺型静默忽略）。
- opencode 输出流三层保障：SSE v1/v2 形状自适应（`_diff_part`）+ 轮内 REST 快照兜底（1s）+ 零流式保底 flush；角色过滤（用户提示词不回显）+ 收束扫尾（最终回答不丢）。
- `map_tools` 两修复（overview 无参清单 `.all()` / graph 补 import）；`mcp.py` 描述补 project 强提示；`_mcp_tools_brief` 统筹升级（map.*/project 内联/命名形态，直通+任务链同源注入）。
- cline 工具名实测形态：`topo-architect__<tool>_<hash>`（cline）/ `topo-architect_<tool>`（opencode）。

### 看门狗与热修流程
- `_progress_check` chat 角色豁免（只读排查回合天然无文件进展——cv-12 误杀；活动停滞看门狗仍兜底）。
- 引擎热修标准路径：`POST /agent/executors/cline/engines/refresh-dist`（仓库 dist→引擎原位刷新，**保留 data/**）；`verify_engine.distStale` 陈旧标记（sha256 比对）——替代手工 cp 引擎目录。
- `ARCH_REQ_LOG=1`（默认开）全量请求行 `[req] method path?query status ms`——轮询流量评估面。

## 核心资产守护（2610 P1+P2，2026-10-12 裁决落地）

裁决: 三层标记(asset|component|file) / 先确定性量化 / 任务链自动+直通轻量自动(会话 UI 可关) / 规约=skill 式自由文本。

- **标记域**: `arch_asset_marks`(项目库) + REST `/arch/asset-marks`(CRUD+config 开关) + dock 工具栏 🛡 → AssetMarksDialog。
- **引擎**(`sem/core_guard.py`): 三层匹配(文件精确/后缀 + 组件 owns + 资产锚点) → pre-flight 契约段 / 直通轻量段 / post-flight 确定性报告(命中清单+程度轻中重+**资产影响(stale 徽标)+组件影响半径**)。门控 `core_guard_injection`(overrides, 缺省开)。
- **MCP**: `map.core`(核心清单+规约) + `task.receipt` 扩展确定性评估段。
- **P2 自动评估**: 双通道执行终态(proxy 泵 finally / 任务链 on_finished) → runner 就地 diff → `land_core_assessment`(agent/execution/core_assess.py): 会话评估卡(kind=asset_assess, cards 词汇表已注册, 三联动渲染 AssetAssessCard) + units 沉淀(type=core_assess, critical→importance=2)。

## 资产管理模块接入（2610，2026-10-13）

核心资产守护的标记入口全部落进资产管理模块（AssetManagementWorkspace → 语义树面板）：

- **★ 三层标记入口**：语义树资产行（diff 徽标同位）、组件目录头行、文件叶节点——点击即标记/取消（`useAssetMarks` composable，项目经路由上下文解析，`/arch/asset-marks` CRUD）。
- **仅核心筛选**：树顶部 checkbox，comp/file/asset 三行级过滤（上下文保留）；与 dock 会话域标记同源。
- **🛡 管理弹窗**：树顶部入口复用 dock 同款 `AssetMarksDialog`（规约编辑/删除/自动注入开关）。
- **手动建语义资产**：文件行 ➕ 内联表单（名称/类型六选/起止行/符号/描述/规约）→ `POST /semantic/assets/manual`（与 rename/merge/split 同族路由，无 `/kb` 前缀）。适配未被提取的 ast 节点/跨节点代码段：status=active 直入语义树、`meta.manual=1`、行区间锚点；rulesMd 非空同步创建核心标记（一站式守护接入）。守卫：root/project 双缺 → 400（禁入幻影项目）。
- **图谱评估复用**（预估确认）：组件影响半径 = P2 评估卡数据源（catalog owns+依赖度数）；契约图邻域注入（graph_neighborhood，焦点=允许范围首符号）；map.graph（mermaid 组件/语义图）——新增仅剩图节点 ★ 高亮（见 backlog P3）。
