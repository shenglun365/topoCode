# M01 契约与骨架（P0）

> 阶段：P0（最高优先级） | 预估：1–2 d | 前置：无 | 后续：M02–M14 全部
> 状态：⬜ 未开始

## 1. 改造目标

在**不移动任何业务代码**的前提下，固化拆分的三大契约（App Manifest / RPC 方法集基线 / 前端 workspace 布局）并搭好目标目录骨架，使后续每个模块的移动都有确定落点与可验证出口。

## 2. 功能边界

**包含（In）**
- App Manifest schema 定义 + 加载器（Python）
- RPC 方法集基线固化（拆分前快照，供 G2 门禁 diff）
- 目标目录骨架：`packages/core`、`packages/web-core`、`apps/{workbench,docs,chat,architect}`
- 根 `package.json` workspaces + 新脚本骨架
- `packages/core/pyproject.toml`（空包可安装）
- 端口/路径规划表（dev 4 个 vite 端口 + 9 服务端口）

**不包含（Out）**
- 任何业务代码移动/改写（M02+ 才动代码）
- gateway/supervisor 的 manifest 驱动改造（M06/M07 实现，本模块只定 schema）

**依赖方向**：无（纯新增）。

## 3. 端口与路径规划表（固化契约）

| 服务 | 端口 | PUB | 源码归属（拆分后） |
|---|---|---|---|
| gateway | 3456 | — | topoone.gateway |
| kb（核心引擎进程） | 3459 | 5681 | topoone.engine（+workbench kind=core 薄层） |
| doc | 3481 | 5683（预留） | apps/docs/server |
| agent | 3482 | 5684 | topoone.agent |
| chat | 3483 | — | apps/chat/server |
| llm | 3484 | 5682 | topoone.llm |
| architect | 3470 | — | apps/architect/server |
| mcp | 3460 | — | topoone.plugins.mcp |
| runner | 3458 | — | topoone.plugins.runner |

| SPA | dev 端口 | 构建产物 | 3456 挂载 |
|---|---|---|---|
| workbench | 5173 | `apps/workbench/dist` | `/app` |
| docs（viewer） | 5174 | `apps/docs/dist/viewer` | `/viewer` |
| docs（web-root/projects） | 5174 | `apps/docs/dist/web-root` | `/projects` |
| chat | 5175 | `apps/chat/dist` | `/chat` |
| architect | 5176 | `apps/architect/server/static`（服务自托管） | `/architect` |
| 门户 home | （gateway 静态） | `packages/web-core/dist-portal` | `/` |

> 现状 5175 被 architect 占用 → M13 起 architect dev 迁 5176；M12 起 chat 迁 5175。

## 4. App Manifest Schema（`apps/<name>/manifest.toml`）

```toml
[app]
name = "docs"                    # workbench | docs | chat | architect
kind = "service"                 # "core"=方法注册进核心进程(workbench)；"service"=独立进程
python_entry = "topoone_app_docs.server:main"   # service 必填；core 填注册函数
static_dir = "apps/docs/dist"    # 相对仓库根
static_mount = ["/viewer", "/projects"]         # gateway 静态挂载点（可多个）
api_prefixes = ["/api/doc", "/doc", "/code"]    # gateway 反代前缀 → 本服务
rpc_namespaces = ["render", "doc"]              # /api/rpc 命名空间路由 → 本服务
port = 3481
pub_port = 5683
host = "127.0.0.1"
health = "/health"
[app.env]                        # 追加到子进程环境
TOPO_DATA_DIR = ""
```

workbench 示例（kind=core，无独立端口）：

```toml
[app]
name = "workbench"
kind = "core"
python_entry = "topoone_app_workbench.server:register_methods"
static_dir = "apps/workbench/dist"
static_mount = ["/app"]
rpc_namespaces = ["knowledge"]
```

**过渡期取值规则（重要）**：M01 阶段各 app 的 pip 包尚不存在（M10–M13 才建），manifest 初始值必须指向**现状入口/产物**，保证 M06（gateway 静态/反代 manifest 驱动）与 M07（supervisor 进程注册 manifest 驱动）落地时行为与硬编码完全等价：
- `python_entry` 支持两种格式：`module:func`（包已建后）或**仓库根相对脚本路径**（如 `backend-core/doc_service_app.py`，过渡期用）
- `static_dir` 过渡期指向现状产物（如 `plugins/reports/static/web/viewer`、根 `dist`）
- M10–M13 每个子项目迁移时**同步校正本 app manifest 为目标值**（各模块文档已列入任务）
- `validate_registry` 增加规则：`python_entry` 为 `module:func` 格式时模块必须可导入（M11 前用脚本路径格式，不触发该规则）

**约束（写入 schema 校验）**：
- `rpc_namespaces` 全集必须与网关路由表（M06 的 `_RPC_ROUTES`）无冲突；新命名空间只允许声明、不允许两个 app 声明同一命名空间。
- `api_prefixes` 不得包含 `/api/rpc`、`/ws`、`/api/health` 等网关保留前缀。
- `kind=service` 的 app 必须有 `python_entry` 且进程启动后 `health` 返回 200。

## 5. 执行任务

### 任务 1.1 Manifest schema + 加载器
- 新增 `packages/core/topoone/__init__.py`（空）与 `packages/core/topoone/manifest.py`：
  - `AppManifest` dataclass（字段同 §4）
  - `load_manifest(path) -> AppManifest`（TOML 解析 + 校验规则 §4 约束）
  - `discover_apps(root) -> dict[str, AppManifest]`（扫描 `apps/*/manifest.toml`）
  - `validate_registry(apps) -> list[str]`（命名空间/前缀冲突检测，返回错误列表）
- 新增 `packages/core/topoone/tests_manifest.py` 的测试用例放 `packages/core/tests/test_manifest.py`（4 用例：合法解析 / 命名空间冲突 / 保留前缀 / kind=core 无端口）
- **验证**：`pip install -e packages/core && python -m pytest packages/core/tests/test_manifest.py -v` 全绿

### 任务 1.2 RPC 方法集基线固化
- 新增脚本 `scripts/rpc-baseline.py`：以 stdio 模式启动核心进程（`main.py --stdio` 注册全量方法后），dump `sorted(server.methods.keys())` 到 `packages/core/rpc-method-baseline.json`
- 新增 `scripts/check-rpc-parity.py`：启动后 dump 当前方法集，与基线 diff，非空即失败（G2 门禁工具）
- **验证**：`python scripts/rpc-baseline.py` 生成基线文件（提交入库）；`python scripts/check-rpc-parity.py` 当前代码下通过

### 任务 1.3 目录骨架
- 创建（空包 + 占位文件，不移动业务代码）：
  - `packages/core/pyproject.toml`（name=`topoone-core`，version 0.3.0，packages 含 `topoone*`；deps 暂沿用 `backend-core/requirements.txt` 全集，M14 收敛）
  - `packages/web-core/{package.json, tsconfig.json, src/.gitkeep}`（name=`@topo/web-core`，version 0.1.0）
  - `apps/workbench/{package.json, tsconfig.json, index.html, vite.config.ts, src/.gitkeep, server/.gitkeep, tests/.gitkeep, manifest.toml}`
  - `apps/docs/{...同上, manifest.toml}`
  - `apps/chat/{...同上, manifest.toml}`
  - `apps/architect/{...同上, manifest.toml}`
  - 各 `package.json`：name 见总纲 §1，`private: true`，`dependencies: {"@topo/web-core": "*"}`（workspaces 解析）
  - 各 `manifest.toml` 按 §4 写死规划值（此时指向**旧**构建产物路径亦可，M10–M13 校正）
- 根 `package.json` 增加 `"workspaces": ["packages/web-core", "apps/workbench", "apps/docs", "apps/chat", "apps/architect"]`
- **验证**：`npm install`（workspaces 链接成功，无新增依赖下载报错）；`node -e "console.log(require.resolve('@topo/web-core'))"` 成功

### 任务 1.4 文档与状态
- 更新本目录 README §7 状态列、`.gitignore`（追加 `apps/*/dist`、`packages/web-core/dist*`）
- **验证**：现有 `npm run build` 与 `bash scripts/serve.sh foreground` 行为不变（骨架不触碰旧路径）

## 6. 验收标准

1. `pip install -e packages/core` 成功，`python -c "from topoone.manifest import discover_apps"` 无报错（G1）
2. `rpc-method-baseline.json` 生成并提交；`check-rpc-parity.py` 通过（G2 基线就绪）
3. 4 个 `manifest.toml` 通过 `validate_registry` 校验
4. 现有构建/启动/测试零回归（`npm run build`、pytest 旧路径、5 SPA dev smoke）

## 7. 风险与注意

| 风险 | 缓解 |
|---|---|
| stdio 基线需拉起完整核心进程（依赖 .venv + tree-sitter 等） | 脚本内复用 `scripts/serve.sh` 的 Python 选择逻辑；基线生成失败时允许手动在 REPL 中 dump |
| workspaces 引入后旧构建脚本引用相对路径失效 | M01 只加 workspaces 字段不改旧脚本；`npm run build` 全量回归确认 |
| manifest 规划值与实际端口/路径偏差 | M10–M13 每模块校正本 app manifest，M14 终检 `validate_registry` |
