# 远端 Coding Agent Worker 接入指南（S3）

architect 主 Agent 可把任务分发到远端机器上的三方 coding agent（opencode serve），
代码经**共享 git 仓库**同步跟踪（内置托管或外部远端）。

## 架构

```
architect 主机                                远端 worker 机器
─────────────────────                        ─────────────────────
工程目录(root) ──push 任务分支──▶ 共享 git 仓 ◀──clone/fetch── worker clone
                                              │ (cwd = opencode serve)
runner RemoteAgentExecutor ──HTTP 会话──▶ 远端 opencode serve
                                              └─编码→commit→push 任务分支
工程目录 ◀──fetch 任务分支────────── 共享 git 仓
branch_service 落地镜像 → 验收(git diff base...HEAD)
```

## 远端 worker 前置（一次性）

1. **Clone 共享仓库**（凭据内嵌 token，见 architect 系统管理 → 执行器 → 内置托管地址）：

   ```bash
   git clone http://<TOKEN>@<architect-host>:3470/git/<project-id>.git worker
   cd worker && git config user.email agent@remote && git config user.name remote-agent
   ```

2. **启动 opencode serve**（工作目录必须是 clone）：

   ```bash
   cd worker && opencode serve --port 4096 --hostname 0.0.0.0
   ```

3. **保证网络可达**：architect → `<worker-host>:4096`；worker → `<architect-host>:3470`。

## architect 侧配置（系统管理 → Coding Agent 执行器）

新增执行器：

| 字段 | 值 |
|---|---|
| 类型 | `远端 agent (共享git同步)` |
| id | 如 `remote-1` |
| 远端 serve URL | `http://<worker-host>:4096` |
| 共享仓库 | `auto`（用内置托管）或外部远端 URL |

保存后 runner 热刷新；创建执行任务时在「执行器」下拉选择该远端执行器。

## 任务分支协议

- dispatch 前：architect 把 `HEAD` 推到共享仓 `arch/{execId}`；
- 远端 agent 指令（自动注入 prompt）：`fetch` → `checkout -B arch/{execId}` → 编码 →
  `commit` → `push origin arch/{execId}`；
- 执行后：architect fetch 任务分支回工程目录（`checkout -B` 到远端 tip），
  变更 = `git diff base...HEAD` → 落地镜像 → 自动验收。

## 内置 Git 托管

- 地址：`http://<architect-host>:3470/git/<project-id>.git`
- 鉴权：非 loopback 必须 Bearer token（`~/.topocode/token`，可内嵌 URL）
- 首个任务落地后镜像仓自动创建；`GET /api/architect/git` 可查已托管列表
- 外部远端（GitHub/Gitea 等）：把执行器「共享仓库」配为外部 URL 即可，协议不变

## 排障

| 现象 | 处理 |
|---|---|
| push 共享远端失败 | 检查 token/网络；外部远端检查凭据 |
| 远端会话超时 | worker serve 是否存活（`GET /global/health`）；超时配置调大 |
| 结果 fetch 失败 | worker 是否真的 push（会话输出有 `git push` 指令回执） |
| codex 远端 | 当前远端通道支持 opencode serve 会话 API；codex server 会话模式走本地执行器，远端 codex 规划中 |
