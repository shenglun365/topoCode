# 2610 技术债与挂账台账（集中页）

> 偿债顺序与来源记录。新增挂账一律落此页，禁止散落对话。
> 最后更新: 2026-10-13（遗留排查: 缺陷修复+图谱高亮批已偿）

## 批2（已排期，等语义作业事件面）

| 项 | 内容 | 收益 | 备注 |
|---|---|---|---|
| 语义作业 SSE 事件面 | naming/extract/sync/aiJob 四处 FE 轮询（2.5–5s）转事件驱动 | −13 req/min 基线 | 需 KB/semantic 侧 emit 改造 |

## 功能挂账

| 项 | 内容 | 优先级 |
|---|---|---|
| KB 基线 id MCP 面 | `map.overview` 附基线行（基线 commit/id 不可经 MCP 查——cv-9/11 执行器两轮绕路取证） | 中 |
| KB 资产文件清单空 | map_assets/map_component 的文件列全空（topo-animation 实测）——数据质量专项 | 中 |
| M6 会话详情聚合 | 需求/任务呈现聚合（删除预览已覆盖大部分价值） | 低 |

## 技术债（审计 2026-10-12）

| 项 | 内容 | 级 |
|---|---|---|
| P3-LLM 符合性评语 | convention_check 复用, 限定命中资产与绑定规约 | P3 |
| P3-core_guard 技能 | 会话域技能 core_guard(手动触发完整评估报告→草稿) | P3 |
| 真图 diff 量化 | post-flight 组件依赖图 before/after 边差(需基线快照, P2 用静态影响半径替代) | P3 |
| B3 conversation-store 拆分 | 740 行单体（SSE/缓冲/降级/节流/乐观态/rehydrate 门控）——拆：事件消费 vs 会话状态 vs 发送流 | P3 |
| C3 ARCH_BASE 告警 | 默认 `127.0.0.1:3470` 单实例成立，双实例/远程即错——启动时多实例检测告警 | P3 |
| C4 FastMCP 路由耦合 | server.py 路由提升依赖内部 path=="/mcp"——**有回归测试锁定**（test_mcp_http），接受 | 记录 |
| C5 listCoalesced 250ms | 首调用者也被延迟的搭车窗取舍——敏感时改"首发立即+窗内共享" | 记录 |
| 0.0.82 陈旧引擎 | 仍是旧 POST 代码；`refresh-dist` 路由已建，未装用即无碍，或直接 remove | 低 |
| ARCH_REQ_LOG 默认开 | 全量请求行日志（评估面）——观测期后可切 `ARCH_REQ_LOG=0` | 运维 |

## 已偿（2026-10-13 图谱高亮批）

- ~~图节点 ★ 高亮~~ → coreMarks 纯 helper（三层匹配+分隔符归一后缀对齐+svg 后处理黄描边/★徽标，8 例单测）+ 语义图谱（asset 层：数据级仅核心过滤/焦点豁免/工具栏 ★chip+计数）+ 组件图（comp/file 层：mermaid idMap 反查高亮/空命中回落全图防下钻留空）

## 已偿（2026-10-13 资产管理模块接入批）

- ~~资产管理入口~~ → 语义树 ★ 三层标记（资产行/组件头/文件行）+ 仅核心筛选（comp/file/asset 三行级）+ 🛡 管理弹窗（复用 dock AssetMarksDialog）+ 手动建语义资产（文件行 ➕ 内联表单 → `POST /semantic/assets/manual`，未提取 ast 节点/跨节点代码段，rulesMd 非空同步核心标记；端点补幻影项目守卫 + 四分支回归）
- ~~图谱评估复用~~ → 确认三条现成链（组件影响半径=评估卡数据源 / 契约图邻域注入 / map.graph）；图节点 ★ 高亮随后批已偿(见上)

## 已偿（2026-10-12 弧线）

- ~~核心资产守护 P2~~ → post-flight 量化增强（资产影响+stale 徽标、组件影响半径）+ 执行终态自动评估卡（三联动: 文字/结构/代码锚点, AssetAssessCard）+ units 沉淀（type=core_assess）+ 双通道自动触发（proxy 泵 finally / 任务链 on_finished, runner 就地 diff）

- ~~引擎外科补丁~~ → `POST /engines/refresh-dist`（保留 data/）+ `distStale` 健康标记（C1）
- ~~三层 job↔conv 回退映射~~ → 泵事件留痕带 conversationId（B1，回退层降级为存量兼容）
- ~~FE 乐观态直改 activeMeta~~ → `optimisticRole` 独立 ref（B2，activeMeta 回归纯权威）
- ~~docs 未同步~~ → 两份核心文档 + 本页（D1/D3）
