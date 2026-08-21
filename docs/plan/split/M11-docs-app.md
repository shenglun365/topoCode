# M11 子项目·文档浏览 docs（P3②）

> 阶段：P3 第 2 步 | 预估：2–3 d | 前置：M01–M10 | 后续：M12
> 状态：⬜ 未开始

## 1. 改造目标

把文档浏览（门户卡片"知识库文档浏览"）切为独立子项目 `apps/docs/`：
- **前端**：viewer SPA + web-root（/projects）SPA 从 `web/` 迁入，独立 vite 工程（5174，2 个 entry）
- **后端**：doc 服务（:3481）= `viewer.py` 24 路由 + `web_root.py` 业务 API + `diagram/`+`diagram_tools/` + plantuml/report_tree + `render.*`/`report.*` RPC 方法，整体迁入 `apps/docs/server/`（包名 `topoone-app-docs`，独立进程）
- **gateway 收敛**：`web_root` 业务 API 从 gateway 进程移入 docs 服务（gateway 只留门户 index 静态），gateway 成为纯基础设施

## 2. 功能边界

**包含（In）**
- 前端：`/viewer`（社区文档·文件摘要·图·热力图·Mermaid/PlantUML 渲染）+ `/projects`（项目列表·任务文档·导入/导出/校验门户）
- 后端 HTTP 路由（迁后全部挂在 docs 服务 :3481，gateway 反代）：
  - viewer 24 路由：`/doc` `/code` `/api/community-doc` `/api/community-files` `/api/community-children` `/api/community-graph` `/api/file-graph` `/api/file-summary` `/api/file` `/api/cascade-levels` `/api/heatmap` `/api/external-graph` `/api/external-stats` `/api/plantuml*`（4）`/api/mermaid/rebuild` `/api/diagram*`（4）`/api/diagram-editor/process` `/api/graph-layout`（3）
  - web_root 业务 API：`/api/projects` `/api/tasks` `/api/docs/{doc_id}` `/api/export*`（3）`/api/import*`（2）`/api/projects/{id}/verify-files` `/api/verify/{id}/status`
- 后端 RPC：`render.*` / `report.*` 命名空间（原 `engine/service/{render,report}.py`）
- 数据：project.db **只读**（graph/doc/summary 表）+ plantuml 缓存

**不包含（Out）**
- 门户 index `/`（home.html，gateway + web-core）
- chat 路由（M12）；knowledge.*（M10）；图布局算法之外的引擎数据写入（docs 不写 project.db）

**依赖方向**：docs server → topoone-core（service_app 脚手架 + db 只读 + service_common）；docs FE → @topo/web-core。

## 3. 源码归属（文件映射）

### 3.1 前端（`web/` → `apps/docs/`）

| 现有路径 | 目标路径 |
|---|---|
| `web/viewer.html`、`web/web-root.html`、`web/index.html`（web-root 别名，迁入后删除） | `apps/docs/src/{viewer,web-root}.html` |
| `web/{AppViewer,AppWebRoot}.vue`、`web/{entry-viewer,entry-web-root}.ts` | `apps/docs/src/`（同名） |
| `web/pages/{DocViewer,ProjectList}.vue` | `apps/docs/src/pages/` |
| `web/components/{NoteDetailDialog,SaveAsDocDialog,RenameDialog,DiagramRebuildDialog,DiagramSubagentDialog}.vue`、`web/components/graph/GraphContextMenu.vue` | `apps/docs/src/components/`（保留 graph/ 子目录） |
| `web/composables/{useDocState,useGraphState,useHeatmap,useNotes,useGraphLayout}.ts` | `apps/docs/src/composables/` |
| `web/services/{parseContent,render,diagramStateStore}.ts` | `apps/docs/src/services/` |
| `web/env.d.ts` | `apps/docs/src/env.d.ts` |
| `vite.web.config.ts`（viewer/web-root 两个 entry 部分） | `apps/docs/vite.config.ts`（root=apps/docs/src；outDir=`apps/docs/dist`；entryFileNames 保持 `[name]/assets/...` 分目录模式；dev 端口 5174 + 代理 `/api`→3456） |
| `web/` 中 docs 域 svg 资源 | `apps/docs/src/assets/` |
| —（新建） | `apps/docs/package.json`（deps 按 import 扫描：vue + marked + marked-highlight + highlight.js + mermaid + plantuml-encoder 等）、`manifest.toml` 校正 |

共享件（api/i18n/MermaidViewer/PlantUmlViewer/AppDialog/useDialog/useToast/useFloatDrag/StarLogoMark）已在 M09 上提 web-core，本步 import 已是 `@topo/web-core/...`，仅确认。

### 3.2 后端（→ `apps/docs/server/`，包 `topoone_app_docs`）

| 现有路径 | 目标路径 |
|---|---|
| `plugins/reports/viewer.py`（1185） | `apps/docs/server/viewer.py` |
| `plugins/reports/web_root.py`（223，扣除 index `/` 路由） | `apps/docs/server/web_root.py` |
| `plugins/reports/diagram/`（整目录 40+ 文件）、`plugins/reports/diagram_tools/`（整目录） | `apps/docs/server/diagram/`、`apps/docs/server/diagram_tools/` |
| `backend-core/plantuml_service.py`（255） | `apps/docs/server/plantuml_service.py` |
| `backend-core/report_tree_service.py`（36） | `apps/docs/server/report_tree_service.py` |
| `backend-core/doc_service_app.py`（69） | `apps/docs/server/main.py`（+ `__main__.py`：`python -m topoone_app_docs`） |
| `packages/core/topoone/engine/service/render.py`、`report.py`（M03 解构产物） | `apps/docs/server/doc_service.py`（合并 render/report 注册函数） |
| `plugins/reports/common.py`（307，**拆散**） | 通用 DB 全局 → `packages/core/topoone/service_common.py`（新建，M11 创建）；`_ensure_chat_tables` → M12 chat 包；plantuml_cache → `apps/docs/server/plantuml_cache.py` |
| —（新建） | `apps/docs/server/{__init__.py,pyproject.toml}`（name=`topoone-app-docs`，deps: `topoone-core` + fastapi/uvicorn） |
| `apps/docs/manifest.toml` | 校正：`kind="service"`、`python_entry="topoone_app_docs:main"`、`static_dir="apps/docs/dist"`、`static_mount=["/viewer","/projects"]`、`api_prefixes=` §2 viewer+web_root 路径清单、`rpc_namespaces=["render","doc"]`、`port=3481`、`pub_port=5683` |

**doc 服务进程组装**（`apps/docs/server/main.py`，沿用 service_app 脚手架）：
`MethodServer` + `register_render_methods`+`register_report_methods`（自 doc_service.py）+ `create_service_app` + `include_router(viewer.router)` + `include_router(web_root.router)` + plantuml 缓存初始化 + `/health`。

## 4. 执行任务

### 任务 11.1 common.py 拆散
- 新建 `topoone/service_common.py`：`set_globals(multi_db, port, executor=None)` / `get_multi_db()` 等通用句柄（从 common.py 提取无业务部分）
- viewer.py/web_root.py 的 `import common` 改 `from topoone import service_common as common`（保持属性访问兼容）；chat.py 同步改（M12 前过渡）
- **验证**：G1；`python -c "import topoone.service_common"`

### 任务 11.2 后端迁移
- `git mv` §3.2 全部文件；建包结构 + pyproject；`pip install -e apps/docs/server`
- `engine/service/__init__.py` 移除 render/report 注册（docs 服务进程自行注册；**方法集不变**：`/api/rpc/render.*` 经网关路由到 docs 服务 :3481，现状已如此）
- `doc_service_app.py` → `main.py`：import 全部改新路径（`topoone.*` + 包内相对）
- **验证**：`python -m topoone_app_docs --data-dir <dir>` 独立启动 :3481，`GET /health` 200，`render.plantuml` RPC 冒烟（G2 方法集：核心进程基线中 render.*/report.* 不再由核心注册——**更新 G2 基线**：方法集对等改为"核心+各服务合并方法集"对等，脚本扩展为多进程采集，见 11.5）

### 任务 11.3 web_root 业务 API 移入 docs 服务
- `web_root.py` 扣除 index `/`（留 gateway 静态）迁入 docs 服务并 `include_router`
- gateway 摘除 `web_root_router` include（M06 的 TODO 收尾）；`/api/projects` `/api/tasks` `/api/docs` `/api/import*` `/api/export*` `/api/verify*` 加入 docs 的 `api_prefixes`（manifest）→ gateway 反代
- gateway 进程不再持有业务 DB 句柄（`web_server.py`/`server.py` 中 `common.set_globals` 业务用途移除，grep 断言）
- **验证**：`GET /projects`（静态）+ `GET /api/projects`（经网关反代）200；导入/导出/校验 API 各 1 次冒烟（G7）

### 任务 11.4 前端迁移
- `git mv` §3.1 前端项；`apps/docs/vite.config.ts` 双 entry 构建
- 共享 import 复核（`@topo/web-core`）；docs 域内部引用改 app 内相对/`@` 别名
- **验证**：G4（apps/docs `vue-tsc`）+ G5（双 entry 产物 `dist/viewer/`、`dist/web-root/`）

### 任务 11.5 注册/路由/回归
- supervisor `_SERVICE_DEFS` doc 条目 script → `-m topoone_app_docs`
- G2 基线升级：`scripts/rpc-baseline.py` 扩展为**合并方法集**（核心进程 + doc + chat + architect + agent + llm 各自 methods 并集），本步后重新生成基线并提交
- 全量：G2（新基线）+G3+G4+G5+G6+G7（/viewer 深度 smoke：社区文档·图·热力图·PlantUML 渲染；/projects：项目列表·导入 1 次）+G8
- **验证**：全绿后提交；README §7 更新 M11 状态

## 5. 验收标准

1. `apps/docs/` 自包含（拆仓库能力验证：拷出 + web-core + core 包可独立构建/启动）
2. gateway 进程零业务 router、零业务 DB 写（grep 断言 + 启动日志）
3. G2 新基线（合并方法集）对等；G3–G8 全过
4. `plugins/reports/` 仅剩 `chat.py`、`skills.py`、`web_tools.py`、`common.py`（已拆空壳待删）、`static/`（过渡）
5. `/viewer` `/projects` 全部 URL 现状不变，功能不变

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| common.py 拆散影响 chat.py（M12 未迁） | 任务 11.1 过渡方案：chat.py 改 import `topoone.service_common`，文件位置不动；M12 再整体迁 |
| G2 基线从"核心单进程"变"多进程合并" | `rpc-baseline.py` 在 M11 一次性升级并重新固化基线；升级本身作为独立 commit，便于回退 |
| viewer.py 内路径守卫（`/api/file` normpath+startswith） | 纯移动不改逻辑；冒烟含越权路径用例（`/api/file?path=/etc/passwd` → 403） |
| diagram 目录文件多（40+），import 相对路径深 | 整目录 `git mv`，内部相对 import 不变；包根变化后顶层 import（`from diagram.xxx`）统一改包内 |
| `/projects` 静态与 API 分属 gateway/docs 服务 | manifest `static_mount`（gateway 静态）+ `api_prefixes`（反代）分离声明，11.3 冒烟覆盖两条链路 |
