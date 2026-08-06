# Architect Overview API — 概览页聚合接口

> 契约对象：概览页 `web/architect-src/pages/OverviewPage.vue`
> 所属服务：`plugins/architect`(独立 FastAPI，端口 `3470`，前缀 `/api/architect`)
> 传输：JSON，`{code, message, data}` 包络(见 `conventions.md`)。

## `GET /overview`

概览页四组栏目的**聚合数据接口**。一次请求返回启动信息、近期项目、
coding agent 联通性、知识库关联与引导任务，避免前端多次并发小请求。

### 请求

| Query | 类型 | 说明 |
| --- | --- | --- |
| `mode` | `string?:` | 引导任务模式(`existing`/`greenfield`)。缺省跟随 `launch.mode`。 |

### 响应 `data`

| 字段 | 类型 | 说明 | 对应栏目 |
| --- | --- | ---- | --- |
| `launch` | `LaunchInfo` | 启动命令：`execRoot`/`kbRoot`/`mode`/`productForm`/`scaffold` | 顶栏 ① |
| `recent` | `ProjectInfo[]` | 近期项目(`arch_projects` 按最近更新倒序) | ② |
| `adapters` | `OverviewAdapter[]` | coding agent 适配器 + `conn`(ok/fail) | ③ |

> **agent 适配器为真实数据**：清单来自 `plugins/installer/targets` 注册表(全部已知 agent)，
> 联通性 `conn` 由各 target 的 `detect()` 真实判定(检测到配置=已安装→`ok`)，不再返回模拟数据。
| `kb` | `{count, linked, projects}` | KB 项目计数 / 是否已关联 / 关联项目列表 | ③ |
| `missions` | `OverviewMission[]` | 引导任务(`id`/`title`/`desc`) | ④ |

### 示例

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "launch": {
      "execRoot": "/home/dev/topo-projects/order-service",
      "kbRoot": "/home/dev/topo-kb",
      "mode": "existing", "productForm": "web", "scaffold": null
    },
    "recent": [ { "id": "proj-…", "name": "…", "rootPath": "…", "mode": "existing" } ],
    "adapters": [
      { "id": "opencode", "name": "OpenCode", "desc": "…", "conn": "ok" },
      { "id": "codex", "name": "Codex", "conn": "fail" }
    ],
    "kb": { "count": 3, "linked": true, "projects": [ /* KbProject[] */ ] },
    "missions": [ { "id": "mission-1", "title": "需求澄清", "desc": "…" } ]
  }
}
```

## 实现

- 后端：`plugins/architect/arch_routes/overview.py`
- 前端：`web/architect-src/services/overview-service.ts`(`getOverview()`)、
  `types/index.ts`(`LaunchInfo` / `OverviewData` / `OverviewAdapter` / `OverviewMission`)。

## 兼容说明

`/overview` 聚合了下列**既有端点**的逻辑(复用其模块级 helper)，这些端点**保留不变**，
仍可被其他页面/组件单独调用：

| 既有端点 | 被聚合到 |
| --- | ---- |
| `GET /launch` | `launch` |
| `GET /project/list` | `recent` |
| `GET /agent/adapters` + `GET /agent/adapters/{id}/connectivity` | `adapters` |
| `GET /project/kb/list` | `kb.projects` / `kb.count` |
| `GET /guide/missions` | `missions` |

## 近期项目排序与维护

`GET /project/list` 返回 `arch_projects` 全部项目，排序为**置顶 → 收藏 → 最近更新倒序**
(`pinned`/`favorite` 布尔列，缺省 0)。另有两个维护端点：

| 端点 | 说明 |
| --- | ---- |
| `POST /project/flag` | 置顶/收藏切换。Body `{root?, project?, pinned?, favorite?}` |
| `POST /project/delete` | 删除项目列表记录。Body `{root?, project?, deleteData?}`。`deleteData=true` 时同时删除该项目的 architect 相关数据(如 `arch_snapshot_records` 中 `root_path` 匹配的架构快照)；缺省只删列表记录 |

> `arch_projects` 的 `pinned`/`favorite` 由 `sqlite_ctx.py` 迁移列(`_ARCH_PROJECT_MIGRATION_COLS`)提供；
> `arch_snapshot_records` 新增 `root_path` 列以便项目级数据删除。删除**不影响**宿主机源码/工作目录。

> `project-store.load()` 仍供其他页面取 `status`/`snapshots`;概览页不再触发它(减少 `/project/status`、`/project/snapshots` 冗余载入)。