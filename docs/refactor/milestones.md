# 重构里程碑划分（MS1~MS7）

> 状态：**阶段拆分定稿** | 日期：2026-09-24 | 上游：[architecture-refactor-plan-20260924.md](../architecture-refactor-plan-20260924.md)（五项裁决 + 批次总方案）
> 本文档职责：里程碑总控——只拆阶段、定边界、定验收；**每个里程碑的实施方案由其独立细化设计文档承载**（`MS{n}-*.md`，逐个产出、评审后开发）。

## 0. 工作流（每个里程碑全生命周期）

```
细化设计（MS{n}-*.md） → 人工评审 → 开发（每子项独立 commit） → 验收门禁 → 状态回写本文档 → 进入下一 MS
```

- **先设计后开发**：未评审通过的细化设计，不开工
- **独立可测**：每个 MS 有客观验收判据（命令 + 预期结果），不依赖下一 MS 即可验证
- **完整功能单元**：任一 MS 完成后系统处于可用且一致的状态，可终止、可交付
- **旧代码处置（裁决⑥）**：逐模块「新实现落地 → 门禁全绿 → **同一变更内删除旧实现**」；git 即备份——每 MS 开工前 `git tag pre-MS{n}`，禁止目录拷贝备份；隔离重写仅限模块级指定单元（图栈、chat 上提）
- **模块冻结窗**：MS 涉及的模块在该 MS 周期内暂停产品功能迭代（bugfix 除外），验收后解冻——不设第二代码线
- **细化设计文档模板**：目标 / 范围（含明确排除项）/ 分步设计（文件级） / 测试计划 / 验收门禁 / 风险与回退

## 1. 里程碑总表

| MS | 名称 | 来源批次 | 依赖 | 工作量 | 一句话价值 |
|---|---|---|---|---|---|
| MS1 | 测试安全网与工程缺陷清零 | B0 | 无 | ~5 人日 | 后续一切重构的回归保险 + 依赖声明确性 |
| MS2 | 死代码与残留清零 | B1 | MS1 | ~3 人日 | 代码库净化，消除重构噪声 |
| MS3 | 前端职能归一 | B2 | MS2 | ~8 人日 | 前端架构定型：architect 独立 + KB 系归一 |
| MS4 | architect 后端职能归位 | B3 | MS1（可与 MS3 并行） | ~10 人日 | 后端结构定型：断环 + 分层归位 + 巨石拆解 |
| MS5 | 引擎与外围巨型模块拆分 | B4 | MS1（可与 MS3/MS4 并行） | ~8 人日 | core/chat/docs 可维护性 |
| MS6 | 前端巨型组件拆分 | B5 | MS3 | ~9 人日 | 前端热点可维护性 |
| MS7 | 边界重塑与栈统一 | B6 | MS4+MS5+MS6 | ~12 人日 | 最终形态：chat 并入 + cytoscape 统一 + MCP 边界收口 |

**依赖图**：
```
MS1 ──→ MS2 ──→ MS3 ──┬──────────────→ MS6 ──┐
  │                     │                      ├─→ MS7
  ├─────────────────→ MS4 ────────────────────┤
  └─────────────────→ MS5 ────────────────────┘
```

**建议推进序**：MS1 → MS2 → MS3 ∥ MS4 → MS5 → MS6 → MS7（MS4/MS5 可与 MS3 并行推进；MS5 的 chat 拆分必须先于 MS7 的 chat 迁移完成）

---

## 2. 里程碑卡片

### MS1 测试安全网与工程缺陷清零〔B0〕

- **功能单元属性**：为全系统补齐回归测试安全网（docs/workbench/chat/core 四处盲区）+ 修复依赖声明与产物入库缺陷。完成后即使重构终止，系统测试覆盖也实质性提升。
- **范围**：docs 全路由 smoke（36 条业务路由） / workbench knowledge.* RPC 测试 / chat 核心路径测试 / core 6 步管线集成测试 / architect package.json 补声明 `@topo/web-core`（临时） / `static/architect.html` 出 git / CI backend job 补装 app 包 / viewer.py:852 悬空 import 修复 / 进程口径核对（实测 9 进程，方案文档笔误修正；render-worker untrack 已天然完成转验证）——细则见 [MS1-safety-net.md](MS1-safety-net.md)
- **独立可测判据**：
  1. `python -m pytest apps/docs/tests apps/chat/tests apps/workbench/tests packages/core/tests -v` 全绿（新增四套测试可见）
  2. `npm run type-check && npm run lint && npm run test` 全绿
  3. `git ls-files | grep -E "render-worker-bundled|static/architect.html"` 零命中
  4. `topo serve && topo status` 实测进程数与文档口径一致（当前 9）；`grep -rn "10 进程" docs/ README.md` 命中仅限归档件（docs/archive/）与勘误记录本身——活跃文档零「改 10」待办
- **细化设计文档**：[MS1-safety-net.md](MS1-safety-net.md)（已产出，待评审）

### MS2 死代码与残留清零〔B1〕

- **功能单元属性**：删除全部已验证零引用的死代码（~4,700 行 FE + 8 个后端 shim + 空目录 + 失效 alias），代码库回到最小真实态。
- **范围**：前端死代码三批（architect services/stores/组件、workbench stores/组件/mock 600 行、web-core 3 文件）/ 后端 8 兼容 shim（引用方改直达 `agent/`）/ `apps/{chat,docs}/server/` 空目录 / KnowledgePage 退役（默认裁决：退役）
- **独立可测判据**：
  1. 删除后 `npm run type-check && npm run lint && npm run test` 与 `python -m pytest apps/architect/tests -q` 全绿
  2. 每个删除物附零引用验证命令（细化设计中逐条列出），执行零命中
  3. 前端文件数/行数净减统计与清单一致
- **细化设计文档**：`MS2-dead-code-purge.md`（待产出）

### MS3 前端职能归一〔B2〕

- **功能单元属性**：前端架构定型——architect 彻底独立（裁决①），KB 系（workbench/chat/docs）基建归一，web-core 瘦身到正确职责。
- **范围**：architect 12 处 web-core import 自持替换 + `SYNC-WITH` 锚点 + 移除依赖声明；KB 系 token key 统一 `topocode:token`；useConfirm→useDialog；StarLogoMark/svg/auth-service/Markdown 合一；web-core 越位物（ipc/types/ipc/browser-api/useComponentId/statusBadge）下沉 workbench；图域逻辑归口 graph-kernel；agent-sidecar 改名 `@topo/cline-sidecar`
- **独立可测判据**：
  1. `grep -rn "@topo/web-core" apps/architect/src` 零命中；architect 独立 `npm run build` 成功
  2. `grep -rn "topocode_token" packages apps --include=*.ts --include=*.vue` 零命中（token key 单一）
  3. KB 系三 app 功能回归：现有测试全绿 + 登录/图渲染/聊天收发手动清单
  4. `web-core` 中 workbench 专用物清零（ipc 系列下沉后 grep 消费者仅 workbench）
- **细化设计文档**：`MS3-frontend-unification.md`（待产出）

### MS4 architect 后端职能归位〔B3〕

- **功能单元属性**：architect 后端结构定型——arch_routes 五层混居解体、agent↔routes 循环依赖清零、sem/engine 巨石拆解。
- **范围**：routes/store/sem/schema 平级归位；req_agent+exec_bridge 移入 agent/；sessions.py 收尾拆分；tracking 同名澄清；tagent_* 四件归一；server.py 去私有引用；sem/engine.py 五域拆分（0905-B1b 蓝图）；symbols.py/codegraph.py 契约注释升级（裁决⑤）
- **独立可测判据**：
  1. `grep -n "from ..arch_routes" apps/architect/topoone_app_architect/agent/ -r` 零命中（延迟 import 环清零）
  2. `python -m pytest apps/architect/tests -q` 全绿（35 测试文件即安全网）
  3. 目标目录结构落位（routes/ 不再含 store/sem/DDL/harness）；sem 拆分后单文件 <1,500 行
  4. 服务启动烟测：`python -c "from topoone_app_architect.server import build_app"` + `/health` 200
- **细化设计文档**：`MS4-backend-restructure.md`（待产出）

### MS5 引擎与外围巨型模块拆分〔B4〕

- **功能单元属性**：core/chat/docs 三处巨型模块拆分，RPC 218 基线冻结下的纯内部重构。
- **范围**：task_manager.py 五域拆分（0905-B1a 蓝图）；db/manager DDL 外置 + 全等契约测试；chat.py/web_tools.py 拆分（**先拆后迁**——为 MS7 铺路）；docs viewer/ 子包拆分（0905-A2 蓝图）
- **独立可测判据**：
  1. `git diff packages/core/rpc-method-baseline.json` 为空（拆分前后基线零变化）
  2. DDL 拼接全等契约测试通过（五段 SQL 与旧常量字符串全等）
  3. `python -m pytest packages/core/tests apps/chat/tests apps/docs/tests -q` 全绿
  4. docs 27 路由行为不变（MS1 smoke 套件全绿）；拆分后单文件 <1,500 行
- **细化设计文档**：`MS5-engine-splits.md`（待产出）

### MS6 前端巨型组件拆分〔B5〕

- **功能单元属性**：六个迭代热点文件拆为「子组件+composable」，键位/行为零变化。
- **范围**：architect（AssetManagementWorkspace/SemanticGraphView/AnalysisChat）+ workbench（ReportHome/ProjectCard/community-store 抽 useComponentAnalysis）；ChatSession 归 MS7（拆+上提同做）
- **独立可测判据**：
  1. 现有 vitest 全绿 + 各页核心交互手动回归清单（细化设计中列全）
  2. 拆分后单文件 <1,500 行；props/emits 边界清单化
  3. i18n 键零丢失（键集合前后对比脚本）
- **细化设计文档**：`MS6-component-splits.md`（待产出）

### MS7 边界重塑与栈统一〔B6〕

- **功能单元属性**：最终边界形态——chat 并入 workbench（裁决②）、节点图栈一步到位统一 cytoscape（裁决④）、native 直读合法化与 MCP 边界收口（裁决①⑤）、CONV 治理落笔。
- **范围**：ChatSession 拆 useChatStream/useMessageActions/useChatCommands 后上提 workbench（与 AIAssistantPanel 收敛为一套）；docs/portal 跳转改址；topoone_app_chat 迁 workbench 域托管（保留独立进程 :3483，目录迁移）；项目列表三处归一；`useNodeGraph`（cytoscape，性能 gate：5k 节点 <3s、拖拽 ≥30fps）+ 同变更删 d3/render-worker/bundle-worker；native 直读合法化（ro+WAL+manifest+open_project_ro，限符号兜底与 docs viewer）；C2/C3 入 CONV；architect 独立化收尾验证
- **独立可测判据**：
  1. chat 并入：docs 两处跳转与 portal 入口回归通过；`:3483` 服务在 workbench 域内正常起停
  2. 图栈：性能 gate 实测达标（记录数据）；`grep -rn "\"d3\"\|@types/d3" apps/workbench/package.json package.json` 零命中；大图交互手动回归
  3. 边界：architect 网络调用清单仅剩 MCP + 只读 HTTP；`grep -rn "@topo/web-core" apps/architect` 仍为零
  4. CONV-03/CONV-04 更新落笔；`architecture-review-YYYYMMDD.md` 归档产出
- **细化设计文档**：`MS7-boundary-finalization.md`（待产出）

---

## 3. 状态跟踪

| MS | 细化设计 | 评审 | 开发 | 验收 |
|---|---|---|---|---|
| MS1 | ✅ 已产出（[MS1-safety-net.md](MS1-safety-net.md)，待评审） | ⬜ | ⬜ | ⬜ |
| MS2 | ⬜ 待产出 | ⬜ | ⬜ | ⬜ |
| MS3 | ⬜ 待产出 | ⬜ | ⬜ | ⬜ |
| MS4 | ⬜ 待产出 | ⬜ | ⬜ | ⬜ |
| MS5 | ⬜ 待产出 | ⬜ | ⬜ | ⬜ |
| MS6 | ⬜ 待产出 | ⬜ | ⬜ | ⬜ |
| MS7 | ⬜ 待产出 | ⬜ | ⬜ | ⬜ |

> 规则：状态变更须附证据（测试输出链接 / commit hash / 评审批注日期）。
