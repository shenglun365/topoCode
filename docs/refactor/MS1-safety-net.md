# MS1 细化设计：测试安全网与工程缺陷清零

> 状态：**已评审通过，实施完成**（2026-09-24，C1~C8 全部落地） | 日期：2026-09-24 | 上游：[milestones.md](milestones.md) §2-MS1 · [0924 重构方案](../architecture-refactor-plan-20260924.md) B0
> 事实基线：2026-09-24 三路代码探查（docs 路由与产物 / core 管线与 RPC / chat 路径与缺陷），全部结论带 文件:行号 落入本文。

## 1. 目标

1. 补齐四处测试盲区（docs / workbench / chat / core 管线），使 `npm run test:py` 覆盖全部 5 个 Python 测试域——这是 MS2~MS7 一切删除与拆分动作的回归保险
2. 清零已核证的工程缺陷（产物入库、依赖未声明、CI 保真、隐藏 500），并统一进程口径
3. **约束**：除 4.0 节一处行为保持的 app 构造器提取与 D6 一行 import 修复外，零生产代码改动

## 2. 范围

**纳入**（4 套测试 + 1 项提取 + 6 项缺陷处置）：
- `apps/docs/tests/`：全路由 smoke + 数据兜底（36 条业务路由，见 4.1）
- `apps/workbench/tests/`：knowledge.* 7 方法 RPC 直调测试（见 4.2）
- `apps/chat/tests/`：REST 核心路径测试（LLM 打桩，见 4.3）
- `packages/core/tests/`：6 步分析管线集成测试（见 4.4）
- `topoone_app_docs/main.py` 提取 `build_app()`（见 4.0）
- 缺陷 D1~D6（见 4.5）

**排除**（明确不做）：
- 不写 docs `/api/topo/*` 12 条渲染路由的独立测试——`packages/core/topoone/tests/diagram/` 已覆盖（test_render_api/test_report 等），MS1 不重复建
- 不测 web_tools 32 个工具的全量行为（仅 P2 抽 2 个只读工具冒烟）
- 不动 CI 之外的任何 pipeline/GitHub Actions 结构变更；不引入 pytest.ini/标记体系（维持各目录默认发现）
- 不修正 `packages/core/tests/` 现有 sys.path.insert 旧路径（test_service_app.py:16-20 等）——属 MS5 范围
- 不处理 `packages/core/topoone/engine/service/project.py:1264-1363` 重复注册死代码（MS2 删除项）

## 3. 现状事实基线（勘误与依据）

| # | 事实 | 依据 |
|---|---|---|
| F1 | docs 路由实数：viewer.py **26** 条 + web_root.py **10** 条 + 脚手架 3 条（`/zmq/{method}`、`/health`、`/zmq/status`）+ topo 渲染 12 条 = 51 条；"27"为 0905 文档笔误（自 2026-08-23 起恒为 26） | viewer.py:16-1195、web_root.py:16-197、`packages/core/topoone/rpc/service_app.py:127-161`、`packages/core/topoone/diagram/diagrams/router.py` |
| F2 | docs 无 `build_app()`——app 全部内联在 `main()`（main.py:42-93）；可复用构造器 `create_service_app` 在 core（service_app.py:127-161） | main.py:42-93 |
| F3 | docs 路由依赖全局态：`common.set_globals(multi_db, port)`（main.py:48），几乎全部 handler 先查 `common.multi_db`，None 即 503 | `packages/core/topoone/service_common.py:13-25` |
| F4 | **隐藏缺陷**：`POST /api/diagram-editor/process` 内 `from web_tools import ...`（viewer.py:852）——顶层模块不存在（真身 `apps/chat/topoone_app_chat/web_tools.py`），实测 ModuleNotFoundError → 该端点必 500（被外层 except 转 HTTPException，viewer.py:1081-1083） | 实测复现 |
| F5 | knowledge.* 11 方法 = workbench 侧 7 个（`apps/workbench/topoone_app_workbench/server/knowledge_service.py:8` 起，操作 `multi_db.knowledge_db.knowledge_docs`，表 schema `packages/core/topoone/db/manager.py:683-701`）+ core 侧 4 个版本同步方法（`packages/core/topoone/engine/service/version.py:58-76`） | 基线 218 中 knowledge 命名空间 11 |
| F6 | 6 步管线 = `analyst_runner.py`（自述"6 步分析流程执行器":1-8）：`_do_parse`（:1064-1104）顺序调 `_step1_parse_ast`:590 / `_step2_resolve_references`:733 / `_step3_extract_imports`:827 / `_step4_synthesize_frameworks`:867 / `_step5_detect_communities`:912 / `_step6_generate_summary`:1014；**步骤 1~6 全为静态分析，不依赖 LLM**（LLM 仅出现在另一条 `analysis.startPipeline` 4 单元流水线与 `version.sync` 5 stage，均不在本测试范围） | analyst_runner.py |
| F7 | 可复用测试范本：architect conftest（`isolate_arch` 临时目录+单例重置，conftest.py:15-40）；core 的 FakeServer 模式（`test_db_layout.py:17-29`）、真实 `MultiDBManager(tmp_path)` 自建全套库表（manager.py:1331-1377）、注册后直调 `srv.methods["x"](...)`（test_db_layout.py:128-145） | 各文件行号 |
| F8 | render-worker-bundled.js **两处均已 untracked 且被 ignore**（根 .gitignore:37,38,61）——原缺陷的 untrack 动作已天然完成，MS1 仅保留验证 | `git ls-files` 零命中实测 |
| F9 | **进程口径**：代码注册表实测 = **9 进程**（`supervisor/cli.py:258-265` `_FIXED_SERVICES`=kb/gateway/llm/agent/mcp/runner 6 项 + manifest 3 个 kind=service：docs/chat/architect；workbench kind=core 无进程）。README:115 与 CONV-00:8 的「9 进程」**准确**；0924 方案 :13「supervisor 统管 10 进程」与 B0 条目 5「9→10」是笔误（源于已退役的 agent-bus broker，README:115 已注明退役） | cli.py 逐行核证 |
| F10 | 根 test:py（package.json:33）当前指向**无误**——5 个目录均存在，pytest 对空目录（docs 仅 .gitkeep、workbench 仅 .ts）不做失败收集；新增测试后自然生效，**无需改 script** | package.json:33 |
| F11 | CI backend job 只 `pip install -e packages/core`（ci.yml:34-47），但 test:py 含 4 个 app 包测试（且现有 test_service_app.py:131 已 import topoone_app_docs）——CI 与本地环境（scripts/setup.sh:28-32 装全部 5 包）不一致 | ci.yml vs setup.sh |
| F12 | `static/architect.html` 仍被 git 跟踪（`1c657d8` 入库早于 ignore 规则；.gitignore:60 已覆盖该目录，untrack 后即闭环）；CONV-04:146"已在 .gitignore"的陈述在 untrack 后成立 | git ls-files 实测 |
| F14 | **（套件新发现缺陷 D7）**`GET /api/chat/archives` 带 project/category/tag 任一筛选必 500——chat.py:1174 `fetchall` 漏传 `tuple(params)`，SQL 占位符与绑定数不匹配；无筛选时正常，故存量未暴露 | 测试首跑复现 |
| F13 | architect 源码 9 处真实 import `@topo/web-core`（ConversationDock.vue:23、AppTopbar.vue:6-7、useDiagramRenderer.ts:9-10、i18n/en+zh:1、conversation-store.ts:18、settings-store.ts:4-10），package.json 无声明，靠 hoisting 生效 | grep 实测 |

## 4. 分步设计（文件级）

### 4.0 前置提取：`topoone_app_docs.build_app()`（唯一结构性生产改动）

**动机**：docs app 组装内联在 `main()`（F2），TestClient 无法构造；范本 = architect `build_app(data_dir)`（server.py:78-170）。

**改动**（`apps/docs/topoone_app_docs/main.py`，行为保持）：
```
def build_app(data_dir: str, port: int = 3481) -> FastAPI:
    # 原 main.py:42-93 的组装体原样搬入：
    # MultiDBManager(data_dir) → common.set_globals(multi_db, port)（注意：不传 executor）
    # plantuml 缓存库初始化(:51-53) → MethodServer(pub_port=None)(:59)
    # create_service_app(server, multi_db, title="docs-service", lifespan=...)(:84)
    # include_router(viewer/web_root/topo 三路由组)(:85-87)
def main():
    args = parse(...)            # 原 :26-40
    app = build_app(args.data_dir, args.port)
    uvicorn.run(app, ...)        # 原 :93
```
- 纯搬移，不改任何装配顺序与参数；`main()` 行为等价
- **不含** `uvicorn.run`（测试不监听端口）；`register_methods`（main.py:22-29）保持模块级不动
- 验证：`python -m topoone_app_docs --help` 正常；`python -c "from topoone_app_docs.main import build_app"` 可导入

### 4.1 docs smoke 套件（`apps/docs/tests/`）

**conftest.py**（新建，范本=architect conftest + F3 全局态纪律）：
```python
@pytest.fixture
def docs_env(tmp_path):                      # 临时数据目录 + 全局态设置/复位
    data_dir = tmp_path / "docsdata"
    multi_db = MultiDBManager(str(data_dir))
    common.set_globals(multi_db, port=3481)
    yield multi_db
    common.multi_db = None                   # 防 set_globals 跨测试泄漏（F3）

@pytest.fixture
def client(docs_env):
    from topoone_app_docs.main import build_app
    with TestClient(build_app(str(docs_env.data_dir))) as c:   # lifespan 启动
        yield c

@pytest.fixture
def seeded_db(docs_env):                     # 最小项目库：主库 projects/analysis_tasks 各 1 行
    ...  # 按 db/manager.py 主库 schema 原始 SQL 插入 + 附带空项目库；
         # 若 MultiDBManager 存在项目注册公共 API 则用 API（实现时定，见风险 R2）
```

**test_route_smoke.py**（新建）——三层断言 + 路由数守卫：

| 层 | 断言 | 覆盖 |
|---|---|---|
| G0 路由数守卫 | `len(viewer_routes)==26 and len(web_root_routes)==10` | 防 MS5 拆分 viewer/ 子包时路由意外丢失（本套件的长期价值锚点） |
| G1 可达性 | 36 条业务路由逐条请求：`status != 404/405`；`/health`==200 | 全部 GET 直接打；POST 用最小合法 body |
| G2 参数与兜底 | GET 空参**不得 422**（query 参数须有默认）；POST 最小 body 的失败必须是业务 4xx 或 503，**不得 500**；空库数据路由返回 200 空结构或业务 4xx | 三级断言沿用 0905-A1 方案 |

路由逐条用例表（36 条，方法+路径+最小 body+预期桶）：

- **页面 2**：`GET /doc`、`GET /code`——仅当 `apps/docs/dist/viewer.html` 存在时断 200，否则 skip（构建产物非 pytest 职责；dist 当前无 code.html，skip 分支天然兼容）
- **社区/文件数据 8**：community-doc/files/children/graph、file-graph/file-summary/file、cascade-levels、heatmap——空库断 200 空结构或 4xx；带 `project_id=<seeded>` 断非 500
- **external 2**：external-graph/external-stats——同上
- **plantuml 5**：GET/POST `/api/plantuml`（无 jar → 容忍 {200,503,4xx}）、clear-cache(200)、rebuild mermaid/plantuml（{200,4xx}）
- **diagram 5**：build/validate/ir-docs/editor-process/tools-apply——最小 body 断非 500（**editor-process 修复 D6 后从必 500 变为可测**，作为 D6 的回归锚点）
- **graph-layout 3**：save→load→delete 闭环（同一 key 三连，验证真读写而非只 200）
- **web_root 10**：projects/tasks/docs/{id} 只读 + export/import/verify 三异步对（start→status 轮询断 {200,4xx}；download 在无产物时 4xx）

**test_viewer_data.py**（新建，seeded_db 上加深）：community-graph 节点/边结构形状、file-summary 对不存在文件的业务错误、graph-layout 闭环数据一致性。

### 4.2 workbench knowledge RPC 套件（`apps/workbench/tests/`）

**test_knowledge_service.py**（新建；范本=进程内注册直调，test_db_layout.py:128-145）：
```python
server = MethodServer()
multi_db = MultiDBManager(str(tmp_path))          # 真实库表自动建（F7）
register_knowledge_methods(server, multi_db)      # topoone_app_workbench.server.knowledge_service:8
# 直调 server.methods["knowledge.xxx"]({...})，不起 ZMQ/HTTP
```
7 方法用例表（每个方法 ≥2 例，共 ~14 例）：

| 方法 | 关键用例 |
|---|---|
| listDocs | 空库 → `[]`；search 命中；pinned/favorite 排序优先 |
| createDoc | 返回 id 形如 `doc-{8hex}`、status=draft、字段回读一致 |
| getDoc | 存在 → tags JSON 反序列化为 list；不存在 → 业务错（非 500） |
| updateDoc | 白名单外字段被忽略；tags **merge 语义**（增删并存）；返回更新后全文 |
| deleteDoc | 删后 getDoc 业务错；不存在 id 幂等/业务错 |
| getGraph | 文档+tags → 二部图 nodes 含 doc/tag 两类、edges 端点闭合 |
| getDimensions | lifecycle/techStack/abstraction/purpose 四维去重排序；空库全空 |

core 侧 4 个版本方法（pullRequest/pendingUpdates/updateConfirm/updateCancel，version.py:58-76）：在 `packages/core/tests/test_knowledge_version_methods.py` 补一组生命周期测试（pull→pending 可见→cancel 清空；confirm 分支 monkeypatch `version_sync_service` 预览函数，断委托调用与参数透传）。

### 4.3 chat 核心路径套件（`apps/chat/tests/test_chat_routes.py`，新建）

**app 构造**（复刻 main.py:42-51 组装，不提生产构造器——chat 将在 MS7 迁移，不投资）：
```python
multi_db = MultiDBManager(str(tmp_path))
common.set_globals(multi_db, port=3483, executor=WebToolExecutor(multi_db))
ensure_chat_tables(multi_db)
app = FastAPI(); app.include_router(chat_router)
client = TestClient(app)          # teardown: common.multi_db = None
```
**LLM 打桩策略**（实施期修正）：`_llm_round` 是 `send_chat_message` 闭包内的同步函数（chat.py:707），**不可 monkeypatch**——真实接缝是模块内 `import requests` 后的 `_req.post`（chat.py:749，流式 `iter_lines` + 非流式 auto-title 双形态）。`/compress` 分支 monkeypatch `SessionCompressor.execute`。零真实 HTTP（同 test_tagent_chat.py 纪律）。另：`stream=False` 通道（chat.py:642）无 LLM 即可全链路持久化，作为零打桩用例。

用例表（P0 必做/P1 应做/P2 冒烟）：

| 级 | 用例 | 断言要点 |
|---|---|---|
| P0 | health / 会话 CRUD 全周期（POST/GET list/GET one/PUT/DELETE，chat.py:295-470） | 创建注入默认模型/skills/refs；list 过滤；删后 404 |
| P0 | **发消息 SSE**（POST messages，chat.py:543-972） | `text/event-stream`；事件序 chunk→done；assistant 消息落 `llm_messages`；session 更新时间/计数 |
| P0 | abort（chat.py:503-510） | 中断后流终止、状态一致 |
| P0 | 消息上限（chat.py:571-575） | 超 `SESSION_MAX_MESSAGES` → 业务 4xx 非 500 |
| P0 | messages GET/DELETE/batch/PUT（chat.py:515-1045） | 分页/清空/批量 |
| P1 | /compress 命令分支（chat.py:556-562） | mock 压缩器，断 SSE 事件与落库 |
| P1 | models GET/PUT（chat.py:253-284）、skills（:286）、autocomplete（:1050）、template-locale（:242） | 空库结构形状 |
| P1 | drafts 全周期 + send（chat.py:1197-1412） | CRUD + 发送后草稿态迁移 |
| P1 | notes 全周期（chat.py:1483-1569） | 写 `knowledge_db.knowledge_docs`（与 4.2 表共享语义） |
| P2 | 工具循环 1 例：LLM 脚本产出 tool_call → executor 执行 `web_list_projects`（空库）→ tool_result 事件（chat.py:914-925） | 事件序 tool_call→tool_result→done |
| P2 | archives 三端点（chat.py:1132-1185） | 空库/往返 1 例 |

### 4.4 core 管线集成套件（`packages/core/tests/test_pipeline_integration.py`，新建）

**fixture 项目**：`tmp_path` 下 10 个源文件、2 语言（python 6 + typescript 4；语言集按 `topoone/parsers` EXTRACTORS 支持面取交集，含跨文件 import/call/继承关系各 ≥2 处，保证 step2/step3 有非空产物）。
**驱动方式**：不走 `analysis.runTask` 的 asyncio 队列，直接构造 ctx 后同步调 `_do_parse`（范本=test_start_pipeline_tagent 的 FakeServer+种子记录）：
```python
multi_db = MultiDBManager(str(tmp_path)); server = FakeServer()   # publish 记录器（F7）
# 种子：主库 projects/analysis_tasks 各 1 行（helpers 沿用 test_start_pipeline_tagent.py:96-166 风格）
ctx = _load_task_context(...)            # analyst_runner.py:559
result = _do_parse(ctx)                  # :1064，同步执行 6 步
```
**断言域**（对应 F6 六步）：

| 断言 | 依据步骤 |
|---|---|
| task 终态 done、进度单调 5→99、FakeServer 收到 task/progress + task/complete 事件序 | 编排器 :1064-1196 |
| `graph_node` 含 file/function 节点、contains 边落库 | step1 :590-730 |
| resolved_edges 非空：calls/imports 边存在且端点在节点集内 | step2 :733-824 |
| 文件级 IMPORTS 边（python↔ts 各自的 import 声明） | step3 :827-864 |
| `community_hierarchy`/`graph_doc` 非空（10 文件小图 Louvain 可分区；若不可分断言表存在且无异常） | step5 :912-1011 |
| report upsert：计数汇总（文件数/节点数/边数>0） | step6 :1014-1059 |
| 全程零 LLM 调用（F6 静态性）；PUB 仅经 FakeServer，零真实端口 | — |

### 4.5 工程缺陷处置 D1~D6

| # | 缺陷 | 处置 | 验证 |
|---|---|---|---|
| D1 | `static/architect.html` 构建产物被跟踪（F12/F13 无关此条；根因 :60 规则晚于入库 `1c657d8`） | `git rm --cached apps/architect/topoone_app_architect/static/architect.html`（工作区文件保留，本地 dev 仍可用；.gitignore:60 已覆盖） | `git ls-files \| grep static/architect.html` 零命中；clone 后 `npm run build` 可再生成 |
| D2 | architect 9 处 import `@topo/web-core` 未声明（F13） | `apps/architect/package.json` dependencies 增 `"@topo/web-core": "*"`（临时声明，MS3 独立化完成后随 import 一并移除） | `npm install && npm run build -w @topo/app-architect` 成功 |
| D3 | 进程口径不一致：方案文档 :13「10 进程」、B0 条目 5「9→10」为笔误，代码实测 9 进程（F9） | 修方案文档两处为 9；README/CONV-00/CONV-01/CONV-04 的「9 进程」**保持不动**（准确）；在 CONV-00 §3 加一行口径注：「agent-bus 退役后恒为 9，变更须过 G6」 | `topo serve && topo status` 实测 9 OK（记录进验收）；`grep -rn "10 进程" docs/ README.md` 零命中 |
| D4 | render-worker-bundled.js untrack——**已天然完成**（F8） | 无动作，转为验证项 | `git ls-files \| grep render-worker-bundled` 零命中 |
| D5 | CI backend job 未装 4 个 app 包（F11） | `.github/workflows/ci.yml` backend job 改为 `pip install -e packages/core -e apps/workbench -e apps/docs -e apps/chat -e apps/architect`（与 scripts/setup.sh:28-32 对齐） | CI backend job 绿（本地等效：setup 后 `npm run test:py`） |
| D7 | `GET /api/chat/archives` 带筛选必 500（F14，套件发现） | chat.py:1174 `fetchall(...)` 补传 `tuple(params)`（一行） | 带筛选 list 断言 200 且 total 正确 |
| D6 | `POST /api/diagram-editor/process` 必 500（F4） | viewer.py:852 `from web_tools import ...` → `from topoone_app_chat.web_tools import ...`；`apps/docs/pyproject.toml` 增临时依赖 `topoone-app-chat`（MS5 拆分时随 chat.py/web_tools.py 归位重估） | smoke 套件该端点断非 500；`python -c "import topoone_app_docs.viewer"` 无警告 |

### 4.6 全局态纪律（三套新 conftest 共同遵守）

`service_common.set_globals` 是进程级单例：每个用例 teardown 必须复位 `common.multi_db = None`（及 executor），防止跨套件/跨用例泄漏（F3；architect conftest isolate_arch 同款纪律）。

## 5. 测试计划

- 实测：docs 18 例 /6s（session 级 app+sidecar，用例级唯一种子 id 隔离）· chat 21 例新增 /3s · workbench+core 版本 12 例 /0.8s · 管线 7 例 /0.9s
- 实施期修正两处预期：① 管线进度事件在 step1 批次并发（as_completed）下可能交错，单调断言放宽为「界内 + 收口 ≥99」；② docs G2 的空 body 规则改为「空 JSON 对象不得 500」——裸 `request.json()` 对无 body 抛 JSONDecodeError → 500 属系统性缺口，记档为 MS5 加固候选（test_route_smoke.py 模块注释）
- CI：D5 落地后 backend job 首次真实覆盖 5 域
- 不新增 pytest 标记/ini；全部用例默认收集

## 6. 验收门禁（对 milestones §2-MS1 判据的执行口径）

| # | 命令 | 预期 |
|---|---|---|
| 1 | `python -m pytest apps/docs/tests apps/chat/tests apps/workbench/tests packages/core/tests -q` | **✅ 349 passed / 39.7s**（docs 18 + chat 32 含存量 tagent 11 + workbench 12 + core 291） |
| 2 | `npm run type-check` / `npm run test:fe` / `npm run lint` | **✅ type-check exit=0；✅ test:fe 21 passed；⚠️ lint exit=1 为存量红灯**——130 错误全部位于 MS1 未触碰文件（web-core/src、scripts/、前会话在途 architect 组件），MS1 commit 集内零 lint 目标文件 |
| 3 | `git ls-files \| grep -E "render-worker-bundled\|static/architect.html"` | 仅余 `apps/architect/src/architect.html`（源模板，合法） |
| 4 | 进程口径：`_all_service_names()` 代码级核证 = **9**（kb/gateway/llm/agent/docs/chat/architect/mcp/runner）；`grep -rn "10 进程" docs/` 命中仅限归档件与勘误记录本身 | **✅ 一致**（`topo serve` 全量起停留待用户环境执行） |
| 5 | `git status` 确认 D1 untrack、D2/D6 声明与修复落地 | 见 4.5 各验证列 |

## 7. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| R1 4.0 build_app 提取改变装配行为 | 纯搬移+`--help`/导入烟测；smoke 套件本身即回归网 | 单 commit 还原（提取独立成 commit，先于测试提交） |
| R2 seeded_db 造项目库无公共 API，须裸 SQL | schema 直引 db/manager.py 建表语句；断言仅用业务读路由，不猜内部结构 | 降级：数据路由用例并进 smoke 层（空库断言），seeded 深测延后 |
| R3 管线 fixture 语言解析器缺失（tree-sitter 19 语言运行时依赖） | 语言集取 EXTRACTORS 实测支持交集（py+ts 最稳）；缺则该语言用例 skip 并标注 | 缩到 python 单语言 10 文件，覆盖面不减步骤 |
| R4 chat monkeypatch `_llm_round` 触碰私有符号，MS5 拆分时签名变更 | P0 用例集中在事件序与落库，不依赖内部实现细节；MS5 拆分设计须回改本套件（已在其范围注记） | — |
| R5 CI 时长上升（+4 editable 安装） | 均为本地路径 pip，秒级 | — |
| R6 D6 引入 docs→chat 依赖方向 | 显式临时声明+注记 MS5 重估；仅此一处 import | revert 该 commit，端点用例改 xfail(raises=500) 并挂 MS5 |

## 8. 工作量与 commit 序列（每项独立可 revert）

### 实施记录（2026-09-24，全部落地）

| 序 | commit | 内容 |
|---|---|---|
| — | `pre-MS1` tag + b8cf54f + b3a18a0 | 文档归档与 MS1 设计定稿先行入库 |
| C1 | f4c68d9 + f8accef | CONV-00 口径注记 + harness-evaluation 残留关闭 |
| C2 | 63c658f + eec1f5d | D2 依赖声明 + D5 CI 对齐 ‖ D1 untrack（pathspec 提交会从工作区回捞文件，需「暂离→提交→移回」三步） |
| C3 | c2cd8b9 | build_app 提取（multi_db 经 app.state 传回收尾） |
| C8' | 73608ad | D6 悬空 import 修复（先于 C4 落地使锚点用例可绿） |
| C4 | 5b832c0 | docs smoke 套件 18 例（首跑即实证 D6：500+ModuleNotFoundError） |
| C5 | 944e64e | knowledge 套件 12 例 |
| C6 | af76b4f | chat 套件 21 例 + **D7 修复**（套件首跑发现 list_archives 筛选 500） |
| C7 | a835b5d | 管线集成 7 例（core 全量 291 passed 零回归） |

验收证据见 §6。安全网建成的直接收益已在实施中兑现：**D6/D7 两个存量生产缺陷由新套件首次运行即捕获**。
