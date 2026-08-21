# TopoOne-UI 工程拆分执行总纲：核心基础框架 + 4 独立子项目

> 版本 v1.1 | 日期 2026-08-21 | 状态：✅ 已完成（M01–M14 全部落地，八项验收门禁全过）
> 上游设计：`docs/plan/remove-electron-architecture.md`（9 进程拓扑已落地 P0–P6）、`docs/plan/restructure-plan.md`
> 本文档为**工程组织拆分**（代码归属 + 目录/包/构建），**不改变进程拓扑**（9 进程、统一端口 3456 保持不变），对浏览器透明。

---

## 1. 目标

将当前单体仓库拆分为 **1 个核心基础框架 + 4 个独立子项目**，Monorepo 组织（npm workspaces + pip 包），每个子项目目录级自包含（前端工程 + 后端薄层 + 测试 + manifest），具备未来拆独立 git 仓库的能力。

| 组成 | 名称 | npm 包 | pip 包 | 说明 |
|---|---|---|---|---|
| 核心框架（后端） | topoone-core | — | `topoone` | 核心引擎 + llm/agent 基础服务 + gateway + 进程治理 + 插件/生态 |
| 核心框架（前端） | web-core | `@topo/web-core` | — | 契约源 / 传输层 / i18n / 共享组件 / 样式 / 门户 |
| 子项目 1 | 主工作台 workbench | `@topo/app-workbench` | `topoone-app-workbench` | src/ 主 SPA + knowledge 薄层 |
| 子项目 2 | 文档浏览 docs | `@topo/app-docs` | `topoone-app-docs` | viewer + web-root SPA + doc 服务 :3481 |
| 子项目 3 | AI Chat chat | `@topo/app-chat` | `topoone-app-chat` | chat SPA + chat 服务 :3483 |
| 子项目 4 | Architect architect | `@topo/app-architect` | `topoone-app-architect` | architect SPA + architect 服务 :3470 |

## 2. 目标目录结构

```
topoOne-ui/
├── packages/
│   ├── core/                        # ★ 核心基础框架（后端）
│   │   ├── pyproject.toml           # pip 包名 topoone-core，import 名 topoone
│   │   ├── topoone/
│   │   │   ├── __init__.py
│   │   │   ├── db/                  # M02 共享内核：MultiDBManager/SQLiteContext/data_layer/state_store
│   │   │   ├── rpc/                 # M02：zmq_server/rpc_ids/service_app/data_api
│   │   │   ├── messaging/           # M02：bus/transport/schema/remote/worker_signal
│   │   │   ├── config.py  logging_config.py  http_logging.py
 │   │   │   ├── engine/              # M03 核心引擎（kb 进程 :3459 主体；service/ 按 RPC 命名空间解构）
│   │   │   ├── llm/                 # M04 llm 服务 :3484
│   │   │   ├── agent/               # M05 agent 服务 :3482
│   │   │   ├── gateway/             # M06 gateway :3456
│   │   │   ├── supervisor/          # M07 supervisor + topo CLI + tui
│   │   │   └── plugins/             # M07 插件系统 + parsers/community/installer；M08 mcp/runner
│   │   └── tests/
│   └── web-core/                    # ★ 核心基础框架（前端）M09
│       ├── package.json             # @topo/web-core
│       └── src/                     # types 契约 / browser-api / i18n / 共享组件 / styles / portal
├── apps/
│   ├── workbench/                   # ★ 子项目 1（M10）
│   │   ├── package.json · vite.config.ts · index.html · tsconfig.json
│   │   ├── manifest.toml            # app manifest（见 M01）
│   │   ├── src/                     # ← 原 src/（扣除上提 web-core 的部分）
│   │   ├── server/                  # knowledge.* 薄层（manifest kind=core，注册进核心进程）
│   │   └── tests/
│   ├── docs/                        # ★ 子项目 2（M11）
│   │   ├── manifest.toml · src/     # viewer + web-root SPA
│   │   └── server/                  # doc 服务：viewer/web_root/diagram/plantuml（:3481）
│   ├── chat/                        # ★ 子项目 3（M12）
│   │   ├── manifest.toml · src/     # chat SPA
│   │   └── server/                  # chat 服务（:3483）
│   └── architect/                   # ★ 子项目 4（M13）
│       ├── manifest.toml · src/     # ← web/architect-src/
│       └── server/                  # ← plugins/architect/（:3470）
├── scripts/                         # serve.sh（manifest 驱动）· setup.sh（editable 安装）
├── docs/plan/split/                 # 本套文档
└── package.json                     # workspaces: ["packages/web-core", "apps/*"]
```

## 3. 工作优先级（执行顺序）

优先级依据：**依赖方向**（被依赖者先行）+ **风险递减**（先做可独立验证、可回退的模块）。

| 优先级 | 阶段 | 模块 | 文档 | 预估 |
|---|---|---|---|---|
| **P0（最高）** | 契约与骨架 | M01 | `M01-contracts-skeleton.md` | 1–2 d |
| **P1** | 前端基建 | M09 web-core | `M09-web-core.md` | 2–3 d |
| **P2（后端成包，内部严格按序）** | ① 共享内核 | M02 | `M02-shared-kernel.md` | 1–2 d |
| | ② 核心引擎 | M03 | `M03-core-engine.md` | 3–4 d |
| | ③ llm 服务 | M04 | `M04-llm-service.md` | 1 d |
| | ④ agent 服务 | M05 | `M05-agent-service.md` | 1–2 d |
| | ⑤ gateway | M06 | `M06-gateway.md` | 2 d |
| | ⑥ 进程治理 | M07 | `M07-process-governance.md` | 1 d |
| | ⑦ 生态组件 | M08 | `M08-ecosystem.md` | 0.5 d |
| **P3（子项目切分，内部按序）** | ① workbench | M10 | `M10-workbench.md` | 3 d |
| | ② docs | M11 | `M11-docs-app.md` | 2–3 d |
| | ③ chat | M12 | `M12-chat-app.md` | 2 d |
| | ④ architect | M13 | `M13-architect-app.md` | 2 d |
| **P4（最低，收尾）** | 统一构建与清理 | M14 | `M14-build-cleanup.md` | 1–2 d |

**总预估 20–27 人天。**

依赖图（→ 表示"先于"）：

```
M01 ─→ M09 ─┬─→ M10 ─→ M11 ─→ M12 ─→ M13 ─→ M14
  │         │
  └─→ M02 ─→ M03 ─→ M04 ─→ M05 ─→ M06 ─→ M07 ─→ M08
            （M02–M08 构成 packages/core，P2 内严格顺序）
```

说明：
- P1（M09）与 P2 前半（M02–M05）互不依赖，可并行（不同人/不同日）。
- P3 每个子项目切分完成后必须全量回归，才进入下一个子项目。
- M11 先于 M12：docs 与 chat 共享的 viewer 组件已在 M09 上提 web-core，M12 不再依赖 M11 产物（顺序仅为回归窗口收敛）。

## 4. 阶段门禁（每阶段出口必过）

| 门禁 | 命令/操作 | 适用阶段 |
|---|---|---|
| G1 Python 可导入 | `pip install -e packages/core && python -c "import topoone; from topoone.<module> import *"` | P2 每个模块 |
| G2 RPC 方法集对等 | 核心进程启动后 dump `server.methods` 键集，与拆分前基线 diff 为空（基线在 M01 固化） | M02–M06 |
| G3 后端测试 | `python -m pytest packages/core/tests apps/*/tests -v` 全绿 | P2/P3 每步 |
| G4 前端类型 | `vue-tsc --noEmit`（root + 各 app）无 error | P1/P3 每步 |
| G5 前端构建 | 各 app `vite build` 成功，产物目录符合 manifest.static_dir | P1/P3 每步 |
| G6 进程健康 | `topo serve` 9 进程全 ready，`GET /api/health` 聚合 200 | P2/M06、P3 每步 |
| G7 SPA smoke | 5 个 SPA entry（/app · /viewer · /projects · /chat · /architect）经 3456 可达 + 关键页面可交互 | P3 每步、P4 |
| G8 事件链路 | `/ws/events` 任务进度 + llm 流式（5681/5682/5684 合并）正常 | M06、P4 |
| G9 全量验收 | remove-electron 文档 §4 的 8 项验收门全过 | P4（M14） |

## 5. 关键设计决策（本拆分新增）

| # | 决策 | 选择 | 理由 |
|---|---|---|---|
| S1 | 组织形态 | Monorepo（npm workspaces + pip editable） | 用户确认；契约同源、联调零成本，保留拆仓库能力 |
| S2 | 子项目定义 | 产品模块：workbench / docs / chat / architect | 用户确认；与门户 4 卡片一致 |
| S3 | 分析引擎归属 | 核心框架（topoone.engine，kb 进程 :3459） | 用户确认；引擎是平台根基 |
| S4 | 子项目独立机制 | **App Manifest**（`apps/<name>/manifest.toml`）：声明 python_entry/static_dir/api_prefixes/rpc_namespaces/port/pub_port/health；gateway 据 manifest 挂静态+配代理，supervisor 据 manifest 拉起进程，核心进程据 manifest 注册 kind=core 的子项目方法 | 子项目自描述 → 网关/监督者零硬编码；新增子项目不改核心代码 |
| S5 | 契约归属 | DB 表所有权 + `rpc_ids.py` + 网关命名空间路由 → topoone-core；`types/ipc.ts` + browser-api → @topo/web-core | 单一契约源，子项目只可声明命名空间、不可改路由表 |
| S6 | 前端共享件 | 跨 app 复用件（api 客户端/i18n/Mermaid·PlantUML viewer/dialogs/logo/门户）上提 web-core；域内件随 app | 消除 src/↔web/ 交叉引用 |
| S7 | 部署 | 保持单 Docker 镜像（core + 全部 apps），manifest 支持按需挂载子集 | 沿用 P4 决策（单后端包+单 Dockerfile） |
| S8 | 进程拓扑 | 不变（9 进程）；workbench 薄层 kind=core 注册进核心进程，docs/chat/architect 为独立服务进程 | 复用 P3 拆分成果，对浏览器透明 |
| S9 | core_service.py 处置 | 按 RPC 命名空间解构：engine 留 engine/；knowledge.*→workbench；render.*/report.*→docs | 3952 行注册中枢是最大单文件，必须拆 |
| S10 | plugins/reports 处置 | 不再是插件：gateway 骨架入 topoone.gateway；viewer/chat/web_root/diagram 入对应 app；`.deps`（vendored 依赖）随 gateway 声明为 core pyproject 依赖，删除 `.deps` 目录 | 报告插件 = 当前 gateway+doc+chat 的混合体，拆分后各归其位 |

## 6. 执行纪律

1. **每模块一个 commit 组**：完成一个 M 模块 → 跑该模块门禁 → 提交；不跨模块混合提交。
2. **移动优先，改写最小**：P2/P3 以 `git mv` + import 批量替换为主；除 S9（core_service 解构）与 web-core 上提外，不做逻辑改写。
3. **每步全量回归**：G3+G6 为硬门禁；前端改动追加 G4+G5+G7。
4. **旧路径不保留双份**：文件移动即删除旧路径（monorepo 内无兼容期需求）；`.gitignore` 同步更新。
5. **文档随动**：每模块完成后更新本文档状态列 + 模块文档"状态"头。

## 7. 模块文档索引

| 文档 | 模块 | 阶段 | 状态 |
|---|---|---|---|
| `M01-contracts-skeleton.md` | 契约与骨架 | P0 | ✅ 完成（2026-08-20：manifest 8 测试绿、RPC 基线 204 方法、9 进程健康、build/32 测试零回归） |
| `M02-shared-kernel.md` | 共享内核 | P2① | ✅ 完成（2026-08-20：db/rpc/messaging/config 迁入 topoone 内核；32 文件 import 改写；RPC 基线 204 方法一致；pytest 95/95；9 进程健康） |
| `M03-core-engine.md` | 核心引擎 | P2② | ✅ 完成（2026-08-20：core_service.py 3952 行解构为 engine/service/{project,dir,version,knowledge,settings,backend,module,render,report}+_common；19 引擎模块+store+ingest+plantuml/report_tree 迁入 engine/；plugins/{parsers,community} 提前迁入 topoone/plugins；kb 入口 `python -m topoone.engine`；22+5 文件 import 改写；RPC 基线 204 方法一致；pytest 95/95+architect 145/145；9 进程健康、SPA 入口全通） |
| `M04-llm-service.md` | llm 服务 | P2③ | ✅ 完成（2026-08-20：llm_service/prompt_manager/instruction_manager/providers/context + 3 个 provider 插件迁入 topoone.llm/topoone.plugins；`python -m topoone.llm` 独立与 supervisor 双路径验证；RPC 204 一致；pytest 98/98；9 进程健康；顺带修复 session.delete 跨库 FK 存量 bug） |
| `M05-agent-service.md` | agent 服务 | P2④ | ✅ 完成（2026-08-20：agent_workflow 整包（保留原包名）+ agent_worker/tools_executor 迁入 topoone.agent；`python -m topoone.agent` 独立与 supervisor 双路径验证；RPC 204 一致；pytest 100/100；9 进程健康；agent 包零凭据读取） |
| `M06-gateway.md` | gateway | P2⑤ | ✅ 完成（2026-08-20：gateway 5 文件 + 新增 static_sources 迁入 topoone/gateway；路由表/静态挂载/RPC/健康/事件桥全改 manifest 驱动（discover_apps+validate_registry，冲突即启动失败）；代理改 httpx 流式（chat SSE 逐块透传）；viewer/chat 业务 router 摘出 gateway 进程（代理至 docs/chat 服务），web_root_router 暂留（TODO M11）；删 dead plugin.json/plugin_entry.py/.deps；pyproject 加 httpx/websockets；新增 test_gateway_manifest 7 测试；G2 204/G3 95/G6 9 进程/G7 URL 布局/G8 ws/events 全过） |
| `M07-process-governance.md` | 进程治理 | P2⑥ | ✅ 完成（2026-08-20：supervisor/main_cli→cli/tui/plugin_manager→manager 迁入 topoone.supervisor + topoone.plugins；`python -m topoone.supervisor.cli` 入口（`__main__` 转发）；进程注册表 manifest 驱动（固定核心 kb/gateway/llm/agent + 生态 mcp/runner + kind=service app 动态注册）；`plugins/installer` 迁入 topoone/plugins（插件发现含 installer）；scripts/serve.sh + cleanup-stack.sh 切 `-m topoone.supervisor.cli`；engine/app.py 修 db_service/agent_worker 入口 + supervisor/plugin_manager import；G2 204/G3 107/G6 9 进程+崩溃重启/G7 URL 全过） |
| `M08-ecosystem.md` | 生态组件 | P2⑦ | ✅ 完成（2026-08-20：mcp/runner 迁入 `topoone/plugins/{mcp,runner}`（server.py + `__init__`/`__main__`，入口 `python -m topoone.plugins.{mcp,runner}`，删 backend-core sys.path hack）；cli.py 固定表 + `_make_cmd` 改 `-m`；engine/app.py 两处 mcp spawn/register 同步；删 `plugins/{mcp_server,coding_agent_runner}`；G2 204/G3 107/G6 9 进程（mcp/runner 新入口）/G8 ws/events/doctor 新路径/E2E（导入→解析 ast→社区图→summary）全过；pyproject 依赖收敛确认（pytest 为 test 可选依赖）；**fresh venv `pip install -e packages/core` 全量安装成功**（69 包，topoone+全核心依赖+mcp/runner+全进程入口可导入，P2 出口硬要求达成）。**注**：docs/chat service app（M11/M12）、architect（M13）按 manifest 注释仍处过渡态，验收#1「7 入口来自 core/apps」与 #2「backend-core 无业务 .py」随 P3（M10–M13）收敛 |
| `M09-web-core.md` | 前端基建 | P1 | ✅ 完成（2026-08-20：契约/传输层/i18n/共享组件上提 web-core；src↔web 零交叉 import；root typecheck 首次全绿；build+9进程+5 SPA dev smoke 全过） |
| `M10-workbench.md` | 子项目·主工作台 | P3① | ✅ 完成（2026-08-20：前端 src/ 225 文件 + index.html/vite/tsconfig/tailwind/postcss/vitest/tests 整体迁入 apps/workbench（独立 vite 工程 5173，共享走 @topo/web-core，删 @web/ 别名）；package.json 依赖按 import 扫描定稿（14 deps+17 devDeps）；后端薄层 knowledge.py→topoone_app_workbench/server（7 CRUD，kind=core 进程内注册）+ engine register_all 末尾 manifest 加载（importlib+try/except 隔离）+ 删 project.py 129 行 knowledge 死代码重复；静态 /app→apps/workbench/dist（manifest 驱动 main_app_mounts，零 gateway 代码改动，hash 路由无需 SPA 回退）；根 build:vite/dev:vite/type-check/preview 转发 app；G2 204/G3 107/G4 vue-tsc 零错/G5 build 123 assets/G6 9 进程/G7 URL 全 200/深度 smoke（knowledge.*+项目导入+llm.chat）/拆仓库独立 build 通过） |
| `M11-docs-app.md` | 子项目·文档浏览 | P3② | ✅ 完成（2026-08-21：viewer/web-root 双 entry 迁入 apps/docs（独立 vite 5174，base=/docs/）+ topoone_app_docs 服务 :3481（render.* RPC）；gateway /docs 资产挂载 + vue_routes 页面路由；G2 204/G3 107/G6 9 进程/G7 URL 全过） |
| `M12-chat-app.md` | 子项目·AI Chat | P3③ | ✅ 完成（2026-08-21：chat SPA 迁入 apps/chat（独立 vite 5175，base=/chat/）+ topoone_app_chat 服务 :3483（会话/技能/草稿）；gateway /chat 资产挂载 + 页面路由；G2 204/G3 107/G6 9 进程/G7 URL 全过） |
| `M13-architect-app.md` | 子项目·Architect | P3④ | ✅ 完成（2026-08-21：63 vue 迁入 apps/architect/src（独立 vite 5176）+ topoone_app_architect 服务 :3470（171 路由，独立 architect.db）；manifest python_entry/static_dir；arch_routes import 改写；G2 204/G3 core107+arch145=252/G6 9 进程/G7 /architect+WS kb-analysis 101 全过） |
| `M14-build-cleanup.md` | 统一构建与清理 | P4 | ✅ 完成（2026-08-21：根 package.json §4 scripts + 依赖下沉 apps；build/CI/setup.sh 终态；gateway legacy 回退 + sys.path 残留清零；§3 清单全删；**T14.4 八项门禁全过**（9 进程/RPC 全链路/ws/events/5 SPA/pytest252+vitest32/architect+WS/runner+agent/鉴权）；修复门户资产挂载 + agent_task_history 库路由两 bug；新增 topo CLI 入口；README 中英更新 + MCP 接入 + remove-electron 指引） |
