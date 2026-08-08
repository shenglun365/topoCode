# Agent 连接配置 / 运行实例与连通性测试 API

> 契约对象：agent设置面板 `web/architect-src/pages/OverviewPage.vue` + `AgentConfigDialog.vue`
> 所属服务：`plugins/architect`(独立 FastAPI，端口 `3470`，前缀 `/api/architect`)
> 传输：JSON，`{code, message, data}` 包络(见 `conventions.md`)。

## 四层模型

```
AgentConfig(连接模板)   driver: adapter/host/port/url/username/models —— 与具体项目无关
AgentInstance(运行实体) (project, adapter, host) 维度 —— 连接模板 × 具体项目
    ├ 项目绑定: projectId / workDir(=arch_projects.rootPath)
    ├ 运行: managed(架构师 spawn serve)|external(直连已有/远程 serve)，state/pid/port
    ├ git 身份: repoUrl / baseBranch / baseCommit / taskBranch
    └ 生命周期: 懒启动、引用计数、空闲回收、health 崩溃标记、后端退出全停
AgentSession          挂在实例上，多轮 keepContext
ExecutionTask         instanceId + taskBranch + branchMode(auto|manual)
```

**host 是实例的一等字段**：支持未来不同 IP 的远程实例；远程实例的代码交接靠
`repoUrl + baseBranch + baseCommit`(外部 git 仓库统一管理)，architect 不触碰远程机文件系统。

## 三份独立代码副本

| # | 副本 | 路径 | 权限 | 角色 |
| --- | --- | --- | --- | --- |
| 1 | 工程实现目录(原件) | `arch_projects.root_path`(用户现有仓库) | 读写 | agent 就地建 task 分支提交并 push |
| 2 | ARCHITECT 分析副本 | `~/.topocode/arch/<proj>/analysis` | 只读 | 按 task 分支 pull → 架构快照/验收 diff |
| 3 | KB 源码缓存 | `~/.topocode/source-cache/{kb_id}/worktree` | 只读 | 既有 git_service + version_sync |

## 设计原则

- **architect 不存三方 agent 的密码/模型密钥**：仅保存连接参数(host/port/username/url)。
- **模型由 agent 自身配置提供**：选用模型来自 agent 自身已配好认证(auth)的模型；
  多模型时需指定默认模型。
- **连通性测试为真实探测**：opencode server 模式下 `GET /global/health` + `GET /provider`
  (仅取 `connected` 提供商，即已配好 auth 的模型来源)。
- **任务执行**：经 `/ws/coding-agent` 实际跑 agent，真实 opencode 优先、服务端模拟兜底
  (见 `api-execution.md` §5)。

## 存储

`arch_agent_configs`(architect.db，`sqlite_ctx.py` 迁移)：
`id / adapter / name / mode / host / port / username / url / models(JSON) / default_model /
last_status / last_detail / last_check_at / instance_mode(managed|external) / created_at / updated_at`。

`arch_agent_instances`(architect.db)：
`id / project_id / adapter / host / mode / state / pid / port / work_dir / repo_url /
base_branch / base_commit / task_branch / last_commit / ref_count / idle_until / error /
created_at / updated_at`。

KB 连接配置存于 `arch_collab_config` key-value：`kb.dataApiUrl` / `kb.mcpUrl` / `kb.lastStatus` 等。

## Agent 连接配置端点

| 端点 | 说明 |
| --- | ---- |
| `GET /agent/adapters` | 当前已适配的适配器(见下表 adapter 清单) |
| `GET /agent/opencode/env` | 本机 opencode 安装/适配验证(可执行 + 版本 + 配置) |
| `GET /agent/configs` | 列出已保存配置(含最近测试状态) |
| `POST /agent/configs` | 新建。Body: `{adapter, name?, host?, port?, username?, url?, models?, defaultModel?, instanceMode?, mode?}` |
| `PATCH /agent/configs/{id}` | 更新(可只传部分字段) |
| `DELETE /agent/configs/{id}` | 删除 |
| `POST /agent/configs/{id}/test` | 真实连通性测试，写回 `lastStatus/lastDetail/lastCheckAt` |
| `POST /agent/configs/preview` | 未保存前的连通性预测试(弹窗内「测试连通性」) |

### opencode 本机安装/适配验证(`GET /agent/opencode/env`)

验证本机 opencode **安装完整性**，返回：

```json
{ "status": "ok|partial|fail", "installed": true,
  "binary": "/…/opencode", "version": "1.18.15",
  "config": ["~/.config/opencode/opencode.json"],
  "detail": "opencode 1.18.15 已完整安装并适配",
  "checks": { "binary": true, "version": true, "config": true } }
```

判定：可执行文件在 PATH + `opencode --version` 可运行 + 存在全局/工作区配置文件 = `ok`；
缺配置 = `partial`；无可执行文件 = `fail`。连通性测试前先做此验证。

### 连通性测试返回

```json
{ "status": "ok|fail", "detail": "…", "version": "1.18.14",
  "models": [ {"id": "…", "name": "…"} ], "connected": ["providerId", …] }
```

### opencode 探测逻辑

1. `GET {base}/global/health`(超时 3s，可带 Basic auth username) → `{healthy, version}`
2. `GET {base}/provider` → 取 `connected` 提供商(已配好 auth)，聚合其 `models` 为可用模型。

## Agent 实例端点

| 端点 | 说明 |
| --- | ---- |
| `GET /agent/instances` | 列出全部实例((project, adapter, host)) |
| `GET /agent/instances/{id}` | 单条 |
| `POST /agent/instances/{id}/stop` | 停止(managed terminate / external 置 stopped) |
| `POST /agent/instances/{id}/restart` | 重启(managed 重新 spawn / external 重新探测) |

实例由 `AgentInstancePool`(见 `agent_server.py`)在任务执行时懒创建并落库；
`refCount` 引用计数、空闲超时(默认 5min)回收、health 崩溃标记、跨项目有界并行(`max_instances` 默认 2)。

## KB 连接配置端点

| 端点 | 说明 |
| --- | ---- |
| `GET /kb/config` | 获取 KB 连接配置(`dataApiUrl`/`mcpUrl` + 最近状态) |
| `PUT /kb/config` | 保存。Body: `{dataApiUrl?, mcpUrl?}` |
| `POST /kb/config/test` | 连通性测试(data_api `/health` + MCP `/health`)，写回状态 |

## 实现

- 后端：`plugins/architect/arch_routes/agent_config.py`(agent 配置 + opencode 探测)、
  `agent_server.py`(`AgentInstancePool` + `OpencodeClient` + SSE)、`arch_git.py`(只读分析副本 + 真实 git)、
  `mcp_collab.py`(KB 配置/测试)、`store.py`(`AgentConfigsStore`/`AgentInstancesStore`)、`overview.py` 聚合
- 前端：`services/agent-service.ts`、`services/kb-service.ts`、
  `types/index.ts`(`AgentConfig`/`AgentInstance`/`AgentProbeResult`/`KbConfig`)、
  `components/project/AgentConfigDialog.vue`、`pages/OverviewPage.vue`

## 接入说明

adapter 清单(`GET /agent/adapters`，来自 `agent_adapters.list_adapters()`)：

| adapter | 形态(mode) | 探测/验证 | 任务执行 |
| --- | --- | --- | --- |
| `opencode` | server(daemon) | env_check(可执行+版本+配置) + `/global/health`+`/provider` | `opencode serve` SSE `/event` |
| `qwen` | server(daemon) | env_check + `GET /health`(`status==ok`) | `qwen serve --no-web` ACP `/session/:id/events` |
| `codex` | cli | env_check + 二进制存在 | `codex exec --json` 一次性进程 |
| `cline` | cli | env_check + 二进制存在 | `cline --json` 一次性进程(需引擎登录态) |

- **daemon(server)**：architect 负责启动/连接常驻 serve；`mode='server'`。
- **cli(进程型)**：无常驻进程，`mode='cli'`；`host=cli`、`port=0`；
  每次任务起新进程，resume 走引擎自身参数(如 `cline --resume`)。
- **密码/密钥**：架构师一律不存第三方密码；codex 若需指向本地 OpenAI 兼容服务，
  可在配置的 `models`/连接参数外携带 `baseUrl`/`apiKey`/`model`，
  `CodexSession.build_env` 动态生成临时 `CODEX_HOME` 注入。

新增适配器时：
- 在 `agent_adapters.py` 定义 `AgentAdapter` 子类并 `_register()`(自动加入 `list_adapters()`)；
- 在 `AgentAdapter` 实现 `env_check/probe/addr/spawn/health/make_client`，
  cli 型额外实现 `ProcessSession.build_argv/map_line`(或 `process_events`)；
- 前端 `AgentConfigDialog.vue` 直接读取 `GET /agent/adapters` 渲染切换(无需硬编码)。
