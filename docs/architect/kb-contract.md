# KB 对外契约 — 版本基线 & 增量更新（P0）

> architect 会话与 KB 会话的对接契约。KB 侧全部能力以 **ZMQ 方法 + `data_api /zmq/{method}` HTTP 代理** 双形态暴露，拓扑无关（单进程 monolith 时 reports 子进程可直连 `multi_db`，多进程时走 HTTP 代理）。

## 语义（KB 版本基线）

- **KB 只向前，不向后**：每次更新产生一个新的基线版本（`project_versions`），索引单调递增，永不回迁旧代码。
- **对比只在 KB 基线之间**：`version.diff(from, to)` 比较两个基线（文件级，P1+ 扩展分析差异），不依赖 git 祖先。
- **分支/head 不绑定固定分支**：更新时清空缓存代码 → 按新 `(branch, head)` 拉取；拉取方式由 KB 用户选 `git pull`（同分支前进）或 `git worktree`（切分支/多工作区）。
- **delta = content-hash 文件级 diff**（A/M/D），对切分支、force-push 鲁棒。
- **更新流程（预览 → 选环节 → 执行）**：
  1. architect 写入待更新标记（`knowledge.pullRequest`）——不执行，不影响使用；
  2. KB 界面确认（`knowledge.updateConfirm`，选 pull/worktree）→ 拉代码 + 返回预览；
  3. 用户勾选环节 → `version.sync` 执行（AST/图节点必更，预摘要建议，组件人工决策）。

## 方法签名

### project.import（导入，含 git 模式）
```
POST /zmq/project.import   (async)
params: { path, mode?: 'static'|'git-local'|'git-remote',
          branch?, head?, repo_url?, local_repo_path? }
result: Project 行（含 import_mode/remote_url/local_repo_path/source_cache_dir/current_version_id）
```
导入完成后自动注册初始基线版本（label=`initial-import`，全部文件=A）。

### version.list
```
POST /zmq/version.list   params: { projectId }   result: ProjectVersion[]
```
### version.get
```
POST /zmq/version.get    params: { projectId, versionId }  result: ProjectVersion + files[]
```
### version.preview（预览，不写数据）
```
POST /zmq/version.preview  params: { projectId, branch?, head? }
result: {
  delta: { added[], modified[], deleted[], addedCount, modifiedCount, deletedCount, total },
  branchSwitched: bool, changeType: 'minor'|'major', risk: 'low'|'medium'|'high',
  impact: { ast:{filesToParse,removedFiles}, graph:{nodeIdsAffected},
            presummary:{filesToSummarize}, community:{affectedCommunities,communities[],reclusterSuggested},
            llm:{filesToResummarize,communitiesToReanalyze} },
  stages: { ast:{suggested,implemented}, graph:{...}, presummary:{...}, community:{...}, llm:{...} },
  latest: { versionId|null, branch, head }
}
```
### version.sync（执行增量更新）
```
POST /zmq/version.sync  params: { projectId, branch?, head?, label?, stages?,
                                  force?, requestId?, taskId? }
result: {
  changed: bool, projectId, version?: ProjectVersion,
  delta?: {added[],modified[],deleted[]}, archivedRows?: int,
  stagePlan?: VersionPreview, stagesRequested?,
  incrementalResults?: {
     ast:    { status, archivedRows, writtenNodes, removedFiles },
     graph:  { status, keptEdges, newEdges, totalEdges },
     presummary/community/llm: { status: 'planned', implemented: false }
  },
  requestId?
}
```
- `stages`: `{ast, graph, presummary, community, llm}` 布尔。**P1 已实现 `ast` + `graph`**（必更）；`presummary`/`community`/`llm` 为 planned 占位（P2/P3）。
- `taskId`（可选）：增量更新的目标分析任务。缺省用该项目最近一个 `done` 任务；无任务时跳过增量环节。
- `requestId` 传入后 sync 完成会把对应待更新标记置为 done。
- `force=true`：无内容变化也记录 (branch, head) 基线标签（用于手工基线设置）。

**P1 增量语义（ast/graph）**：
- AST：只解析 A/M 文件，符号 `INSERT OR REPLACE` upsert；D 文件删除符号；被覆盖/删除的旧符号行归档到 `graph_node_history`（δ 归档）。
- 图：AST 更新后，保留"两端符号仍存在"的旧边；对新解析出的变更文件重新做引用解析（未变符号从 `graph_node` 重建 stub 参与解析）；旧边清空后写回保留边 + 新边。
- 已知限制（文件粒度增量）：`未变文件 → 变更文件` 的跨文件符号边可能缺失；`目标为空的模块/调用边` 在源文件未变时保守保留（可能残留指向已删模块的边）。需要完整正确的图时走全量任务重跑（`analysis.runTask`）。

### version.diff（基线间文件级差异，architect R3 消费）
```
POST /zmq/version.diff  params: { projectId, fromId, toId }
result: { fromVersion, toVersion, added[], modified[], deleted[], *Count }
```
### version.materialize（重建任意基线 head 的完整文件清单）
```
POST /zmq/version.materialize  params: { projectId, versionId }
result: [{ file_path, content_hash, language, size, file_name }]
```
> 实现：`活表(version_from<=V) UNION 历史表(version_from<=V AND version_to>V)`，保证快速重建任意已归档 head。

### knowledge.pullRequest（architect 发起基线更新请求 —— 仅写待更新标记）
```
POST /zmq/knowledge.pullRequest
params: { projectId, repo_url?, local_repo_path?, branch?, head?, note? }
result: { requestId, projectId, status: 'pending' }
```
### knowledge.pendingUpdates
```
POST /zmq/knowledge.pendingUpdates  params: { projectId? }   result: UpdateRequest[]
```
### knowledge.updateConfirm（KB 确认：拉代码 + 返回预览，不执行分析）
```
POST /zmq/knowledge.updateConfirm  params: { requestId, method?: 'pull'|'worktree' }
result: VersionPreview + { projectId, requestId, branch, head }
```
### knowledge.updateCancel
```
POST /zmq/knowledge.updateCancel  params: { requestId }   result: { cancelled: bool }
```
### project.saveBaseline（手工设置版本基线）
```
POST /zmq/project.saveBaseline
params: { projectId, remote_url?, local_repo_path?, branch?, head? }
result: { ok, projectId, remoteUrl, localRepoPath, version? }
```

## 数据形状

### ProjectVersion
```json
{ "id", "projectId", "parentVersionId", "label", "branch", "head",
  "changeType": "minor|major", "fileCount", "addedCount", "modifiedCount",
  "deletedCount", "isBaseline", "createdAt", "files"? }
```
### UpdateRequest
```json
{ "id", "projectId", "source": "architect|kb", "repoUrl", "localRepoPath",
  "branch", "head", "status": "pending|confirmed|done|cancelled",
  "method", "resultVersionId", "note", "createdAt", "updatedAt" }
```

## architect 消费指引

- 需求分析/设计（R2）：读 `version.materialize`（某基线文件清单）+ P1+ 的社区/摘要查询，作为知识基线的支撑知识。
- 架构迁移/数据资产变化（R3）：`version.diff(fromBaseline, toBaseline)` —— 仅限 KB 基线之间。
- 基线更新请求（R4）：调 `knowledge.pullRequest` 写待更新标记；实际拉取/增量由 KB 界面确认执行。

## P0/P1 范围声明

- ✅ 落地：多模式导入（static/git-local/git-remote）、源码缓存目录、版本基线注册、source_files δ 归档 + `source_files_history`、`version.preview/sync/list/get/diff/materialize`、待更新标记状态机、**AST/图环节增量执行**（`ast`/`graph` 的 `implemented=true`）。
- ⏳ P2-P3：`presummary`/`community`/`llm` 增量执行（`implemented=false`）；历史视图 UI；`version.diff` 扩展分析级差异。历史表镜像已由 `ensure_history_table` 就位。
