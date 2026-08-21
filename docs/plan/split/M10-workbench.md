# M10 子项目·主工作台 workbench（P3①）

> 阶段：P3 第 1 步 | 预估：3 d | 前置：M01、M02–M09 | 后续：M11
> 状态：✅ 完成（2026-08-20）
>
> 实施说明：
> - **T10.1 前端迁移**：`src/`（225 文件）+ `index.html`/`vite.config.ts`/`tsconfig.json`/`tsconfig.node.json`/`tailwind.config.js`/`postcss.config.js`/`vitest.config.ts`/`tests/` 整体迁入 `apps/workbench/`（替换 M01 占位）。配置校正：vite `__dirname` 现指 app 目录（`@`→app/src、outDir→app/dist 自动正确）；tsconfig 删 `@web/*`（workbench 0 引用）；tailwind content 的 web-core 路径改 `../../packages/web-core/src`、删 architect 路径；vitest 只跑 app 测试（web-core 测试归 web-core）。import 复核：`@/`(240)+`@topo/web-core`(119)+`@topo-animation`(3)，无 `@web/`。`package.json` 依赖按 import 扫描定稿（14 运行时 + 17 devDeps，版本与根一致）。
> - **T10.2 后端薄层**：`engine/service/knowledge.py`→`apps/workbench/topoone_app_workbench/server/knowledge_service.py`（7 个 CRUD/检索方法）；建 `topoone_app_workbench` 包（`__init__.py`+`server/__init__.py` 的 `register_methods`）+ `pyproject.toml`（name=topoone-app-workbench，deps: topoone-core）+ `pip install -e`。`engine/service/__init__.py` 移除 knowledge 注册；`engine/app.py` `register_all` 末尾新增 `_register_core_app_methods()`（discover_apps→kind=core→importlib 加载 python_entry，try/except 隔离，失败仅降级该 app）。**顺带清除 M03 遗留死代码**：project.py 含 129 行 `register_knowledge_methods` 重复（与 knowledge.py 逐行一致但从未被调用），已删。
> - **knowledge.* 拆分对照**：7 个 CRUD/检索（listDocs/createDoc/getDoc/updateDoc/deleteDoc/getGraph/getDimensions）→ workbench（kind=core）；4 个更新工作流（pullRequest/pendingUpdates/updateConfirm/updateCancel）属引擎 version 命名空间（version.py 注册，非 CRUD），按 plan 留在引擎。合计 11 个，与 G2 基线 204 一致。
> - **T10.3 静态路由**：`/app`→`apps/workbench/dist` 由 `static_sources.main_app_mounts()`（M06 manifest 驱动）自动生效（manifest static_dir 改 `apps/workbench/dist`，零 gateway 代码改动）。workbench 用 **hash 路由**（`createWebHashHistory`），深度路由 `/app/#/xxx` 客户端处理，无需服务端 SPA 回退。根 `dist/` 删除；根 `build:vite`/`dev:vite`/`type-check`/`preview` 转发 `npm run ... -w apps/workbench`（M14 统一脚本前保留转发）。
> - **T10.4 回归**：G2 204 / G3 107 / G4 `vue-tsc --noEmit` 零错 / G5 `vite build` 123 assets / G6 9 进程 / G7 URL 布局（`/`、`/app/`、`/home`、`/projects`、`/doc`、`/viewer`、`/chat`、`/architect` 全 200，`/app` 307→`/app/`）/ 深度 smoke（`knowledge.listDocs` 经网关由 workbench 注册、项目导入→list、`llm.chat` 可达）。
> - **验收**：#1 拆仓库能力——`/tmp` 独立环境（workbench+web-core，`npm install` 456 包 + `vite build` 123 assets）独立构建成功 ✓；#2 G2 一致 + knowledge.* 由 app 模块注册（启动日志 `[manifest] registered kind=core app 'workbench'` 可辨）✓；#3 G3–G7 全过 + /app 全功能 ✓；#4 根目录不再含 src/index.html/vite.config.ts ✓。

## 1. 改造目标

把主工作台（门户卡片"知识库解析和管理"）切为独立子项目 `apps/workbench/`：
- **前端**：原 `src/`（80 vue + 157 ts）+ 根构建配置整体迁入，成为独立 vite 工程（5173），共享代码全部走 `@topo/web-core`
- **后端薄层**：`knowledge.*` RPC 命名空间（knowledge_docs CRUD/检索）从引擎解出为 `topoone-app-workbench` 包，**kind=core** —— 由核心进程按 manifest 在进程内注册（workbench 无独立进程）

## 2. 功能边界

**包含（In）**
- 主工作台全部页面：`/`（Home）· `/home`（门户内嵌）· `/code` · `/analysis` · `/knowledge` · `/user` · `/settings` · 登录/注册/重置
- 组件域：project/analysis/knowledge/report/ai（内嵌 AI 助手面板，经 RPC 调 core 的 llm/agent 服务）/visualization（topo-animation）/shell/settings/user/resource/onboarding/debug
- 21 个 Pinia store、workers、i18n 词表（25 命名空间）
- 后端：`knowledge.*` 方法（register_knowledge_methods）+ knowledge.db 主写
- 构建产物 `apps/workbench/dist` → gateway 挂载 `/app`

**不包含（Out）**
- 引擎 RPC（project.*/analysis.*/version.*/module.* 等，仍属 core，workbench 经 `/api/rpc` 调用）
- llm/agent 能力实现（core 服务；workbench 仅消费）
- 门户页 AppHome（已属 web-core，M09）

**依赖方向**：workbench FE → @topo/web-core；workbench server → topoone-core（db 层 + 方法注册约定）。workbench 不直接依赖其他 app。

## 3. 源码归属（文件映射）

### 3.1 前端

| 现有路径 | 目标路径 |
|---|---|
| `src/`（整目录，扣除 M09 已上提文件：types/{ipc,window-api,zmq}、services/{ipc,browser-api}、utils/{http,logger,device-id,time,fileColors,statusBadge}、styles/、components/shared/、i18n/index.ts 工厂部分） | `apps/workbench/src/` |
| `index.html`（根） | `apps/workbench/index.html` |
| `vite.config.ts`（根） | `apps/workbench/vite.config.ts`（root 改 app 目录；outDir=`apps/workbench/dist`；alias `@`→`apps/workbench/src`；保留 dev 代理 `/api`+`/ws`→3456；scss additionalData 指向 web-core） |
| `tsconfig.json` + `tsconfig.node.json`（根） | `apps/workbench/tsconfig.json` + `tsconfig.node.json` |
| `tailwind.config.js`、`postcss.config.js`（根，content 指向 src/） | `apps/workbench/`（content 改 app 内路径） |
| `tests/`（smoke.test.ts + unit 剩余：M09 已迁 4 个 utils 测试） | `apps/workbench/tests/` + `vitest.config.ts`（root 的 vitest.config.ts 迁入 app 并改 include/alias） |
| 根 `package.json` dependencies 中 workbench 所用（vue/pinia/vue-router/vue-i18n/@heroicons/d3/pixi.js/mermaid/cytoscape*/marked*/markdown-it/highlight.js/plantuml-encoder/qrcode 等，按 import 分析定稿） | `apps/workbench/package.json` dependencies |

### 3.2 后端薄层

| 现有路径 | 目标路径 |
|---|---|
| `packages/core/topoone/engine/service/knowledge.py`（M03 解构产物） | `apps/workbench/server/knowledge_service.py`（`git mv`，包名 `topoone_app_workbench`） |
| —（新建） | `apps/workbench/server/__init__.py`、`pyproject.toml`（name=`topoone-app-workbench`，deps: `topoone-core`）、`server/main.py` 不需要（kind=core 无进程） |
| `topoone/engine/service/__init__.py` 中 knowledge 注册调用 | 改为 manifest 加载（见 4.2） |
| `apps/workbench/manifest.toml` | M01 骨架值 → 校正：`kind="core"`、`python_entry="topoone_app_workbench.server:register_methods"`、`static_dir="apps/workbench/dist"`、`static_mount=["/app"]`、`rpc_namespaces=["knowledge"]` |

`register_methods(server, multi_db)` 签名与引擎注册函数一致（`from knowledge_service import register_knowledge_methods` 包装）。

## 4. 执行任务

### 任务 10.1 前端迁移
- `git mv` §3.1 前端项；`apps/workbench/src/` 内 import 复核（M09 已把共享引用改 `@topo/web-core`，本步确认无遗漏 + `@/` 别名仍指向 app 内 src）
- workbench `package.json`：按 `src/` import 扫描确定 dependencies（与根 package.json diff，根保留 devDeps + workspaces 脚本）
- **验证**：G4（`vue-tsc --noEmit` in apps/workbench）；`vite build` 产物 `apps/workbench/dist/index.html`（G5）

### 任务 10.2 后端薄层切出 + manifest 注册
- `git mv knowledge.py → apps/workbench/server/knowledge_service.py`；建 pyproject；`pip install -e apps/workbench/server`
- `engine/service/__init__.py`：`register_all_engine_methods` 移除 knowledge 注册；`engine/__main__.py` `register_all` 末尾新增 manifest 加载：
  ```
  for app in discover_apps(repo_root):
      if app.kind == "core":
          mod = importlib.import_module(app.python_entry.rsplit(":",1)[0])
          mod.register_methods(server, multi_db)   # try/except 隔离，失败仅降级 knowledge 功能并记 ERROR
  ```
- **验证**：G2（方法集与基线一致——knowledge.* 仍被注册，只是注册方变为 app 模块）；故意把 manifest 注释掉 → 核心进程正常启动、knowledge.* 缺失（隔离性验证）

### 任务 10.3 静态与路由
- gateway manifest 静态：`/app` → `apps/workbench/dist`（构建后生效；未构建回退 legacy 根 `dist/`）
- 根 `dist/` 目录从构建目标移除（`npm run build` 的 `build:vite` 改为 `apps/workbench` 内构建，M14 统一脚本前先保留根脚本转发）
- **验证**：`GET /app` 200 + 主工作台首页渲染（G7）

### 任务 10.4 测试与回归
- `git mv tests/` → `apps/workbench/tests/` + vitest.config 迁入；root vitest 移除（或改转发）
- 全量：G2+G3+G4+G5+G6+G7（5 SPA 中 /app 深度 smoke：项目导入→分析页→知识页各 1 次交互；内嵌 AI 面板 1 轮对话走 llm.* RPC）
- **验证**：全绿后提交；README §7 更新 M10 状态

## 5. 验收标准

1. `apps/workbench/` 自包含：`git mv apps/workbench /tmp/` 后（配合 web-core + core 包）可独立 `npm install && vite build`（**拆仓库能力验证**，拷回原位）
2. G2 方法集基线一致；knowledge.* 由 app 模块注册（启动日志可辨）
3. G3–G7 全过；`/app` 工作台全功能不变（含 AI 助手面板、设置页、资源中心）
4. 根目录不再含 `src/`、`index.html`、`vite.config.ts`（根 vite.config 若保留须仅为转发，M14 删除）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| workbench 是最大 SPA（237 文件），import 面大 | M09 已完成共享引用改造，本步仅整体移动 + 别名校正；G4 全量 typecheck 兜底 |
| 内嵌 AI 面板（components/ai + report/ChatView）与 chat 子项目功能重叠 | 不在本次拆分范围消重（restructure-plan 已标记后置整合）；本步保持双实现，均经 core 的 llm/agent 服务 |
| kind=core 的 app 注册失败拖垮核心进程 | importlib + try/except 隔离（任务 10.2 显式验证）；日志 ERROR 明示 |
| 根 package.json 依赖拆分误删（web SPA 与 workbench 共用依赖） | 依赖定稿按"各 app import 扫描 + 全量 build 验证"双重确认；根 package.json 暂保留原 dependencies 至 M14 再删 |
| `zeromq` 等不确定归属的依赖 | M10–M13 各步按 import 扫描归属；无引用者 M14 删除 |
