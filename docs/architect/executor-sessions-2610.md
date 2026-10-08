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
