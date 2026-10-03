# 数据主权架构定稿（2026-10-04）——KB 算力化 + architect 自管基线

> 本档为架构转型的正式记录（批 A-E2，提交 58b0d918…3c3fb1d4）。
> 用户裁决链：KB 不应成为 architect 的制约 → KB 取消基线概念（更自由地做
> 架构分析研究学习）→ architect 完全自给（数据主权），KB 转纯算力服务。

## 一、架构总图

```
┌─ architect（数据主权 + 编排 + 消费）────────────────────────┐
│ 自管基线锚 = arch.graphBaseline.<pid> KV（采集完成自记 HEAD）│
│              + arch_projects.baselineCommit 字段             │
│ 基线数据   = arch_ast_cache / arch_graph_node /              │
│              arch_graph_edge（按 project+rev 版本化）         │
│              arch_components / _hierarchy / _naming          │
│ diff 层    = 基线..HEAD ∪ 基线..工作区（baseline_diff 自管   │
│              基准 + change_detector 符号级三级识别）          │
│ 命名       = component_name 作业 → KB llm.chat 通道          │
│ 组件目录   = catalog arch_only 默认（五消费方零改动）        │
│ 编排       = baseline_refresh 一键作业（采集→分组→命名）     │
├─ KB（无基线概念：算力服务 + 自由研究引擎）──────────────────┤
│ 算力口     = analysis.parseFileAst（单文件只读不落库）        │
│            + analysis.communityFromGraph（喂图返回 UNIFIED   │
│              分组, :memory: 即抛, API-156）                   │
│            + workspace.snapshot（base 缺省改空, 纯算力）      │
│            + llm.chat / llm.sync                             │
│ 去基线化   = done 即 ready（挂载退役, unmounted 消亡）        │
│              version.sync/preview/cleanup + knowledge.* 空壳 │
│              catalog/model/rebuildUnified 改最新 done 口径   │
│ 表壳冻结   = project_versions/view_mounts 等保留一版周期     │
└──────────────────────────────────────────────────────────────┘
```

**依赖性质**：算力依赖、数据主权——KB 停机时 architect 不能新解析/重分组，
但存量四类数据（AST/符号/关系/组件）全在自己库中，读路径全部自足。

## 二、关键设计

| 设计点 | 裁决/实现 |
|---|---|
| 解析引擎 | KB parseFileAst 算力（不搬 parsers 6.9k 行）；codegraph 为可选对照源（`ARCH_CODEGRAPH`），双保险 |
| 稳定 ID | 统一符号模型（snake_case、id=cache:file::name::line），与 codegraph 同构 |
| 关系边 | parseFileAst refs → `_rebuild_edges_from_refs`（含 contains 推导）+ imports 文件级边 + file 虚拟节点 |
| 社区分组 | KB 侧新 RPC（算法单源不分叉，KB 升级 architect 直接受益）；architect 只存结果 |
| 快速命名 | 轻约束 prompt（编号引用 num 形态 + 代表符号 top2），指纹=rev+sorted(owns)，无 agentic 循环/继承消歧（KB 全面解读域） |
| rev 语义 | 沿用 `baseline:<commit>` 前缀——与 `arch_semantic_assets.rev` 底座判定 `LIKE 'baseline:%'` 天然兼容，存量 `baseline:<kbVersion>` 行零迁移 |
| 多分区塌缩 | >5000 文件拆多任务的项目 catalog 塌缩为最新 done——已裁决接受（163 文件项目无影响） |

## 三、端点清单（architect 自管面）

| 端点 | 语义 |
|---|---|
| `POST /kb/semantic/collect-graph` | 采集：git ls-files → parseFileAst → arch_graph_node/edge 落库 + 基线锚自记 |
| `POST /kb/semantic/community-group` | 分组：图谱快照 → KB communityFromGraph → arch_components 落库 |
| `POST /kb/semantic/component-name` | 命名：编号清单+代表符号 → llm structured → arch_component_naming |
| `POST /kb/semantic/baseline-refresh` | **一键基线刷新**：采集→分组→命名 三步串行编排（FE 基线管理页入口） |
| `GET …/status` 族 | 各作业状态 + 基线锚/覆盖率/组件目录统计 |

**已下线**：`/kb/semantic/symbol-sync`（假发起）、`/project/baseline/sync`（假完成）、
`/kb/update-request`、`/kb/semantic/naming-status|naming-rerun`、`/arch/baseline/commit`。

## 四、批次索引

| 批 | 提交 | 内容 |
|---|---|---|
| A 数据主权 | 58b0d918 | 五张新表 + collect_graph 作业 + 基线锚自管 |
| B 社区算力 | 16b30697 | communityFromGraph RPC + community_group 作业 + catalog arch_only |
| C 快速命名 | 04eb2de4 | component_name 作业 + 概览命名卡自管口径 |
| D KB 去基线 | ab39e843 | 挂载/版本编排退役（表壳保留）+ 最新 done 口径 + workbench UI 下线 |
| E1 旧链下线 | bd199b82 | 假发起/假完成端点删除 + greenfield 基线自管 |
| E2 一键刷新 | f42a6fd5 | baseline_refresh 编排 + 基线管理页本地版 |
| 清理 | 3c3fb1d4 | 旧命名链死代码 |

## 五、保留项与边界（非遗留）

- `syncExtract`（资产提取管线）与基线链无关，合法活链路。
- KB `project_versions`/`view_mounts` 等表壳冻结一版周期后择期清表（届时需同步
  `packages/core/tests/ddl_golden.py` 全等快照）。
- core `view_service`/`view.*` RPC 为 workbench 内部挂载 UI 保留。
- architect 符号源 `open_symbol_conn` 保持 native(KB 只读增强)∪codegraph(实时主源)；
  arch 快照源降级位（第三保险）留待需要时补。
- 历史 plan 文档（kb-unified-components-plan 等）为当时记录不回改，以本档为准。
