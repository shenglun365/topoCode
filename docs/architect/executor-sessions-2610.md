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
