# M06 gateway（P2⑤）

> 阶段：P2 第 5 步 | 预估：2 d | 前置：M02–M05 | 后续：M07
> 状态：✅ 完成（2026-08-20）
>
> 实施说明：
> - 迁移 5 文件（gateway/server/vue_routes/__main__/db_client）+ 新增 `static_sources.py`（静态源解析：manifest static_dir×static_mount + legacy 单向回退）。
> - `_SERVICE_URLS`/`_RPC_ROUTES`/`_PREFIX_TARGETS`/`_HEALTH_TARGETS`/事件桥端口全部由 `discover_apps()`+`validate_registry()` 生成；rpc_namespace/前缀/port 冲突即 `ManifestError` → 启动失败。env 覆盖（`KB_API_URL`/`DOC_API_URL` 等）优先于 manifest。
> - 反向代理改 **httpx 流式**（`StreamingResponse`+`aiter_bytes`）：chat SSE（`text/event-stream`）逐块透传不被缓冲；client 在流结束前保持打开。WS 代理（architect）用 `websockets`。
> - **viewer/chat 业务 router 摘出 gateway 进程**（规划原以为 P3 已切出，实际未切——本次移除）：其路由全被 docs/chat manifest `api_prefixes` 覆盖，经代理转发至 doc(3481)/chat(3483) 服务承接（两服务已挂载对应 router）。`web_root_router` 按 T6.3 暂留 gateway 进程（代码在 plugins/reports/web_root.py，M11 移入 docs 后摘除，已标 TODO）。
> - 删 dead `plugins/reports/{plugin.json,plugin_entry.py,__init__.py,.deps/}`（grep 确认引用清零；`import reports` 包式导入经命名空间包仍可用）。`main_cli` gateway spawn 与 `engine/app.py` 独立模式 spawn 改 `-m topoone.gateway`；`_cmd_doctor` 诊断路径同步更新。
> - pyproject 加 `httpx==0.28.1`/`websockets==16.0`（fastapi/uvicorn 已有）。
> - 新增 `tests/test_gateway_manifest.py`（7 测试：路由表合并/端口变更改代理目标/命名空间冲突/env 覆盖/kind=core 归 kb/前缀最长优先）。
> - 验收：G1 import 绿；G2 RPC 204 一致；G3 pytest 95/95（含 7 新测试，13 文件零收集错误）；G6 `topo serve` 9 进程全 ready + `/api/health` 聚合 ok；G7 现状 URL 布局全 200（/、/projects、/viewer、/home、/chat、/doc、/code、/architect 经 3456）；G8 `/ws/events` 心跳正常；黑名单 `/api/rpc/backend.*`→403；gateway 进程确为 `python -m topoone.gateway`。

## 1. 改造目标

把 gateway（统一端口 :3456）从"reports 插件"升级为 `packages/core/topoone/gateway/` 核心组件，并把**静态托管 / 反代 / RPC 路由 / 事件桥 / 鉴权**全部改为 **manifest 驱动**（读 `apps/*/manifest.toml`），消除硬编码服务表。收敛为纯基础设施：不再挂载任何业务 router（`web_root_router` 等随 M11 移入 docs 服务）。

## 2. 功能边界

**包含（In）**
- 反向代理：各 app `api_prefixes` → `127.0.0.1:<port>`（含 WS upgrade，`/api/architect`、`/ws/kb-analysis` 等）
- RPC 路由：`/api/rpc/{method}` 按命名空间前缀路由（核心默认表 + 各 app `rpc_namespaces` 声明合并）；method 黑名单（`backend.*`）服务端拦截
- 事件桥：`/ws/events` ← ZMQ-SUB（5681 kb + 5682 llm + 5683 doc + 5684 agent，env 可配）
- 静态托管：门户（web-core portal）+ 各 app `static_dir` 按 `static_mount` 挂载（SPA html + assets）
- 鉴权：token（`~/.topocode/token`）+ 默认 127.0.0.1 绑定（现状保留）
- 聚合健康：`GET /api/health`（探各服务 health 端点）
- SPA 页面路由（viewer.html/chat.html/web-root.html/home.html 按路径服务，现状 URL 布局**不变**）

**不包含（Out）**
- 任何业务数据路由（viewer 24 路由 → M11 docs；chat 26 路由 → M12；projects/tasks/import/export/verify 包装 → M11）
- 进程 spawn（由 M07 supervisor 统一）

**依赖方向**：gateway → 内核（messaging 事件桥、config）+ manifest 加载器（M01）；被 supervisor 以独立进程拉起。

## 3. 源码归属（文件映射）

| 现有路径 | 目标路径 | 说明 |
|---|---|---|
| `plugins/reports/gateway.py`（433 行） | `packages/core/topoone/gateway/gateway.py` | 反代/RPC 路由/事件桥/鉴权；`_SERVICE_URLS`、`_RPC_ROUTES`、`_DOC_PATHS` 改 manifest 驱动 |
| `plugins/reports/web_server.py`（97 行） | `topoone/gateway/server.py` | FastAPI 骨架：中间件 + 静态挂载（manifest 驱动） |
| `plugins/reports/vue_routes.py`（90 行） | `topoone/gateway/vue_routes.py` | SPA html 路由；静态源改 manifest 驱动（URL 不变） |
| `plugins/reports/__main__.py`（84 行） | `topoone/gateway/__main__.py` | gateway 进程入口：`python -m topoone.gateway` |
| `plugins/reports/db_client.py`（40 行） | `topoone/gateway/db_client.py` | |
| `plugins/reports/{plugin_entry.py,plugin.json,__init__.py}` | **删除** | reports 不再是插件；plugin_entry 删除前 grep 确认无引用 |
| `plugins/reports/.deps/`（vendored fastapi/pydantic/uvicorn 等） | **删除** | 依赖并入 `packages/core/pyproject.toml`（fastapi/uvicorn/httpx/websockets）；开发态 venv 安装，分发态 Dockerfile pip install |
| `plugins/reports/static/`（构建产物 5.7M） | **保留至 M14** | 过渡期静态源（M10–M13 各 app dist 就绪后按 manifest 切换，M14 删除） |
| `plugins/reports/{common.py,viewer.py,chat.py,skills.py,web_tools.py,web_root.py,diagram/,diagram_tools/}` | 不动 | 属 M11（docs）/ M12（chat） |

**manifest 驱动的改造点（gateway.py 内）**
1. `_SERVICE_URLS` → 由 `discover_apps()` 生成：`{app.name: f"http://{host}:{port}"}`（核心默认：kb=3459）
2. `_RPC_ROUTES` → 核心默认表（project/analysis/group/version/module/system/dir/settings/report/model/graph → kb；llm/session/analysisSession/promptTemplate → llm；agent/skill/tool → agent）+ 各 app `rpc_namespaces`（render/doc → docs；chat → chat；knowledge → workbench[经 kb 进程]）合并，冲突即启动失败（`validate_registry`）
3. `_DOC_PATHS` 反代清单 → 各 app `api_prefixes` 合并
4. 静态挂载 → 门户（`packages/web-core/dist-portal`，M09 产出；未构建时回退 `plugins/reports/static/home.html`）+ 各 app `static_dir`×`static_mount`（未构建时回退 legacy static 对应子目录，日志 WARNING）
5. `/api/health` 聚合 → 探 manifest 内全部 `service` 类 app + kb + gateway 自身

## 4. 执行任务

### 任务 6.1 文件迁移
- `git mv` §3 前 5 个文件；建 `topoone/gateway/` 包；更新 import（`common` → 过渡期保留 `sys.path` 指向 `plugins/reports`（web_root 仍在那里）——**注意**：server.py 不再 include web_root_router（见 6.3）
- **验证**：G1

### 任务 6.2 manifest 驱动改造
- 按 §3 改造点 1–5 实现；保留 env 覆盖能力（`KB_API_URL` 等现有 env 仍生效，优先级高于 manifest）
- 新增 `packages/core/tests/test_gateway_manifest.py`：构造 2 个假 app manifest（不同命名空间/前缀）→ 断言路由表合并正确、冲突报错
- **验证**：pytest 新用例绿

### 任务 6.3 业务 router 摘除（web_root_router 摘出 gateway 进程）
- `web_root_router`（index /home /projects + projects/tasks API + import/export/verify）**本步暂留 gateway 进程挂载**（其代码在 plugins/reports/web_root.py，M11 才移入 docs 服务）；仅在其 include 处标注 TODO(M11)
- 其余业务 router（viewer/chat）确认已不在 gateway 进程（P3 已切出，grep 断言）
- **验证**：`topo serve` 后 `/`、`/projects`、`/api/projects` 等现状 URL 全部 200（G7 抽查）

### 任务 6.4 入口与部署切换
- `main_cli.py` `_SERVICE_DEFS` 的 gateway 条目 script 更新为 `-m topoone.gateway`
- `topo serve` 全流程回归：9 进程健康（G6）、`/api/health` 聚合（G6）、`/ws/events` 事件流（G8）、5 SPA 经 3456 可达（G7，静态走 legacy 回退）
- 删除 `plugins/reports/plugin.json`、`plugin_entry.py`、`.deps/`（grep 确认引用清零后）
- **验证**：G2+G3+G6+G7+G8 全过

## 5. 验收标准

1. `python -m topoone.gateway` 独立启动 :3456 成功（supervisor 与手动两路径）
2. 路由表/静态挂载完全 manifest 驱动：`apps/docs/manifest.toml` 改 port 后重启 gateway，反代目标随之改变（单测覆盖）
3. G2/G3/G6/G7/G8 全过；现状全部 URL 布局不变
4. `plugins/reports/` 仅剩 M11/M12 待迁文件（common/viewer/chat/skills/web_tools/web_root/diagram*）+ static（过渡）
5. 黑名单生效：`/api/rpc/backend.xxx` → 403（现状回归）

## 6. 风险与注意

| 风险 | 缓解 |
|---|---|
| 静态回退逻辑复杂化（legacy ↔ manifest 双源） | 回退只允许"manifest 路径不存在 → legacy 对应路径"单向；日志 WARNING 明示回退；M14 删除回退代码 |
| `_DOC_PATHS` 前缀匹配误伤（如 `/api/file` vs `/api/file-graph`） | 保持现状精确前缀清单语义（startswith 排序按最长匹配），迁移不改匹配算法 |
| web_root_router 摘除时机（M11）前 gateway 仍直接读共享 DB | 过渡期保留（现状行为）；M11 完成后 gateway 进程不再持有业务 DB 句柄（grep 断言） |
| `.deps` 删除影响离线分发 | 确认分发链路（Dockerfile/release 脚本）走 pip install 而非 .deps 挂载；`scripts/test-pack.sh` 跑 1 次 |
