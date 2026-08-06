# Agent 连接配置与连通性测试 API

> 契约对象：agent设置面板 `web/architect-src/pages/OverviewPage.vue` + `AgentConfigDialog.vue`
> 所属服务：`plugins/architect`(独立 FastAPI，端口 `3470`，前缀 `/api/architect`)
> 传输：JSON，`{code, message, data}` 包络(见 `conventions.md`)。

## 设计原则

- **architect 不存三方 agent 的密码/模型密钥**：仅保存连接参数(host/port/username/url)。
- **模型由 agent 自身配置提供**：选用模型来自 agent 自身已配好认证(auth)的模型；
  多模型时需指定默认模型。
- **连通性测试为真实探测**：opencode server 模式下 `GET /global/health` + `GET /provider`
  (仅取 `connected` 提供商，即已配好 auth 的模型来源)。
- **任务执行**(经 `/ws/coding-agent` 实际跑 agent)后续阶段再做，本轮仅配置 + 连通性测试。

## 存储

`arch_agent_configs`(architect.db，`sqlite_ctx.py` 迁移)：
`id / adapter / name / mode / host / port / username / url / models(JSON) / default_model /
last_status / last_detail / last_check_at / created_at / updated_at`。

KB 连接配置存于 `arch_collab_config` key-value：`kb.dataApiUrl` / `kb.mcpUrl` / `kb.lastStatus` 等。

## Agent 连接配置端点

| 端点 | 说明 |
| --- | ---- |
| `GET /agent/configs` | 列出已保存配置(含最近测试状态) |
| `POST /agent/configs` | 新建。Body: `{adapter, name?, host?, port?, username?, url?, models?, defaultModel?}` |
| `PATCH /agent/configs/{id}` | 更新(可只传部分字段) |
| `DELETE /agent/configs/{id}` | 删除 |
| `POST /agent/configs/{id}/test` | 真实连通性测试，写回 `lastStatus/lastDetail/lastCheckAt` |
| `POST /agent/configs/preview` | 未保存前的连通性预测试(弹窗内「测试连通性」) |

### 连通性测试返回

```json
{ "status": "ok|fail", "detail": "…", "version": "1.18.14",
  "models": [ {"id": "…", "name": "…"} ], "connected": ["providerId", …] }
```

### opencode 探测逻辑

1. `GET {base}/global/health`(超时 3s，可带 Basic auth username) → `{healthy, version}`
2. `GET {base}/provider` → 取 `connected` 提供商(已配好 auth)，聚合其 `models` 为可用模型。

## KB 连接配置端点

| 端点 | 说明 |
| --- | ---- |
| `GET /kb/config` | 获取 KB 连接配置(`dataApiUrl`/`mcpUrl` + 最近状态) |
| `PUT /kb/config` | 保存。Body: `{dataApiUrl?, mcpUrl?}` |
| `POST /kb/config/test` | 连通性测试(data_api `/health` + MCP `/health`)，写回状态 |

## 实现

- 后端：`plugins/architect/arch_routes/agent_config.py`(agent 配置 + opencode 探测)、
  `mcp_collab.py`(KB 配置/测试)、`store.py`(`AgentConfigsStore`)、`overview.py` 聚合 `agentConfigs`/`kbConfig`
- 前端：`services/agent-service.ts`、`services/kb-service.ts`、
  `types/index.ts`(`AgentConfig`/`AgentProbeResult`/`KbConfig`)、
  `components/project/AgentConfigDialog.vue`、`pages/OverviewPage.vue`

## 接入说明

当前仅 **opencode**(server 模式)已适配；codex/claude/cursor/copilot/gemini/windsurf
在「新建agent配置」弹窗中展示但标记**待适配**。新增适配时在 `agent_config.probe_adapter`
增加分派分支并实现对应探测即可。
