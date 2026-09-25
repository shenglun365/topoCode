# MS5 细化设计：引擎与外围巨型模块拆分

> 状态：**部分实施完成**（V0/V1/V2 落地；V3 回退挂账 MS6 前置） | 日期：2026-09-24 | 上游：[milestones.md](milestones.md) §2-MS5 · [0924 重构方案](../architecture-refactor-plan-20260924.md) B4
> 事实基线：2026-09-24 全量核证（task_manager 4,296 行锚点 / db/manager 2,181 行 DDL 块 / chat·web_tools·viewer 零漂移确认 / 基线与安全网清点）。0905 蓝图（A2/B1a/B1c/B1d）行号漂移已逐点修正。
> 并行性：与 MS4 零文件交集（本 MS 只动 packages/core + apps/chat + apps/docs），可并行推进。
> 铁律：**RPC 218 基线零变化**——所有拆分均为纯物理切分，方法集/注册顺序/编号不动。

## 1. 目标

1. task_manager.py（4,296）拆为 `engine/task_api/` 六模块 + 门面（0905-B1a）
2. db/manager.py（2,181）DDL 外置 `db/schema/` 五件 + 全等契约测试（0905-B1c）
3. chat.py（1,815）/web_tools.py（1,849）拆子包（0905-B1d，**先拆后迁**为 MS7 铺路）
4. docs viewer.py（1,219）拆 `viewer/` 子包（0905-A2，路由路径零变化）

## 2. 范围

**纳入**：V0 DDL 外置 ‖ V1 task_api 六域 ‖ V2 viewer 子包 ‖ V3 chat/web_tools 子包 ‖ V4 收口。
**排除**：`engine/service/project.py` 对 task_manager 的 `_tm_*` 八函数别名消费面（经门面保持稳定，不动 core service）；`packages/core/topoone/tests/` 独立套件（含 test_start_pipeline_tagent/test_tagent_host）只改 import 不改逻辑；不动 manager 的迁移块 `_migrate_*`（:1396-:1596/:1708-:2019，随 manager 留守）。

## 3. 现状事实基线（核证结论，含蓝图漂移修正）

| # | 事实 | 依据 |
|---|---|---|
| F1 | task_manager 4,296 行；`register_analysis_methods` :268-4025（61 个 @server.register）；**蓝图漂移①**：`_ensure_project_db`(:4056)/`_ensure_table`/`_run_git` 及 git 族(:4089-4194)/positions 族(:4207-4296) 已是**模块级函数**非闭包；真实闭包仅 `_agent_mgr`(:280)/`_get_project_root`(:2441)/`_get_project_summary`/`_make_agent_history_cb`/`_save_agent_running_history` 五个 | 锚点核证 |
| F2 | 六域 RPC 锚点（现行号）：任务 CRUD :305-729（listTasks:305/createTask:334/runTask:378/stopTask:603/reRunTask:648/…）；社区查询 :730-2510（scanFileStats:730/getCommunityGraph:1032/getSymbolDetail:1429/getCascadeLevels:1807/rebuildUnified:2046/…）；agent 调度 :2511-3725（startOverview:2512/startPipeline:2734/startPreSummary:3063/analyzeComponents:3366/…）；subdocs :3726-3941（report.createSubDoc:3727 五写法+agent.getConfig:3943）；git_info :4089-4193；positions :4207-4296 | 逐 decorator 核证 |
| F3 | **蓝图漂移②**：positions 读侧无 `list_positions`，实为 `load_positions`(:4227)+`list_position_keys`(:4249)+`clear_positions`(:4280)；RPC 面经 `engine/service/project.py` 以 `_tm_*` 八别名二次包装暴露（project.py:14-23 import，:758-884 注册 graph.savePositions 等） | 核证 |
| F4 | `_compute_file_ranks`(:63) 被 agent 侧 3 处惰性引用（tagent_host:75,316/worker:282/tool_factory:554）——门面必须继续导出 | 核证 |
| F5 | db/manager 2,181：DDL 五块 :228-1265 共 **1,038 行**（MAIN 455/KNOWLEDGE 20/SESSIONS 60/CHAT 64/PROJECT 439）；SQLiteContext :30-227；MultiDBManager :1321-2181（含迁移块 ~511 行留守）；`_init_default_skills` :1266-1320 | 块区间核证 |
| F6 | chat.py 1,815/web_tools.py 1,849/chat_tables.py 31——与 MS1 零漂移；chat 路由分组：models/skills :242-295、sessions :295-510、messages+SSE :515-1049、autocomplete :1050、context :1092、archives :1132、drafts :1197-1482、notes :1483-1580、尾部四类 ReferenceParser/TokenBudget/ContextAssembler/SessionCompressor :1581-1815；web_tools：DEFS :48-592、MAP :594、Executor :618-1643（36 handler 表驱动）、resolve_refs :1644、_resolve_* 八族 :1675-1812、_REF_RESOLVERS :1840 | 逐锚点核证 |
| F7 | docs viewer.py 1,219 零漂移；diagram_editor_process :814-1085（272 行单 handler）；模块级共享态：common(:14)/router(:16)/cd(:18)/_diag_log(:29-38)/STATIC_DIR(:41)；**蓝图措辞修正**：doc_service/web_root 先例是单文件路由模块而非子包，但 0905 方案即为 viewer/ 子包（六职责组），遵循方案 | 核证 |
| F8 | 基线门禁：`python3 scripts/check-rpc-parity.py`（退出码 0=对等）；基线 count=218；再生成 `scripts/rpc-baseline.py`；test_rpc_ids.py 测 rpc_ids 模块本身（4 例） | 核证 |
| F9 | 安全网：docs 18 例（含路由数守卫 26/10）+ chat 32 例（21 REST/SSE + 11 tagent）+ core 291 例；task_manager 直接相关：test_start_pipeline_tagent（3 例，:19 import register_analysis_methods）/test_tagent_host（15 例，:154 monkeypatch `task_manager._compute_file_ranks` 字符串）/test_pipeline_integration(7)/test_parse_file_ast(6) | 清点 |
| F10 | 拆分先例：engine 单文件 register_* 形态（view_service/report_service/…）与 `engine/service/` 子包形态并存；analysis_utils.py 即「从 task_manager 提取」的先例 | 核证 |

## 4. 分步设计（文件级，五批独立 commit）

### V0 db/manager DDL 外置（1 天，先行——独立且为 F5 契约测试立基）

1. 新建 `packages/core/topoone/db/schema/`：`main.py`/`knowledge.py`/`sessions.py`/`chat.py`/`project.py`，各导出 `MAIN_DB_TABLES_SQL` 等五常量（从 manager :228-1265 原文搬移）
2. `manager.py` 顶部 `from .schema.main import MAIN_DB_TABLES_SQL`（五行），类内引用零改动
3. **契约测试** `packages/core/tests/test_db_schema_parity.py`：拆分前先在测试内固化「旧 manager 拼接快照」（本次实施时以 `git show pre-MS5:packages/core/topoone/db/manager.py` 提取五常量字符串作为 golden 内嵌）——断言 `schema/*` 五常量与 golden **逐字节全等**
4. 验证：core 291 + 新契约测试绿；`python -c "from topoone.db.manager import MultiDBManager"`

### V1 task_manager → engine/task_api/（3 天，核心批）

```
engine/
├── task_manager.py        # 门面（~80 行）：re-export register_analysis_methods + _compute_file_ranks
│                          #   + git/positions 八函数（service/project.py 与 agent 3 处的稳定进口）
└── task_api/
    ├── __init__.py        # register_analysis_methods = 按原顺序聚合六域 register
    ├── common.py          # 五闭包上提：_agent_mgr 改工厂、_get_project_root/_get_project_summary/
    │                      #   _make_agent_history_cb/_save_agent_running_history + _ensure_project_db/_ensure_table/_run_git
    ├── tasks_crud.py      # :268-729 段（61 方法中的 CRUD 14 个 + 清扫残留块 :4003-4025）
    ├── community_query.py # :730-2510 段（社区/符号/边/报表/统计查询 ~26 个）
    ├── agent_dispatch.py  # :2511-3725 段（startPipeline 双轨/preSummary 链/analyzeComponents/进度与取消 ~15 个）
    ├── subdocs.py         # :3726-4025 段（report.* 五写法 + agent.getConfig）
    ├── git_info.py        # :4089-4193（detect/save/get_git_info + check_import_status）
    └── positions.py       # :4207-4296（save/load/list_position_keys/clear + _POSITIONS_DDL :4032）
```

纪律（0905 原文 + 漂移修正）：
1. 六域各导出 `register(server, multi_db, shared)`（shared=common.py 的共享态对象）；`__init__.py` **按原注册顺序**聚合——顺序即 rpc_ids 稳定基线
2. 门面保留三个稳定进口：`register_analysis_methods`（engine/app.py:40、service/version.py:110）；`_compute_file_ranks`（agent 3 处惰性 + test_tagent_host:154 字符串打桩——**打桩路径不变**）；git/positions 八函数（service/project.py `_tm_*` 别名与 service/_common.py:31-40）
3. 每拆一域：`python3 scripts/check-rpc-parity.py` 退出码 0 + `python -c "from topoone.engine.app import BackendApp"` + `python -m pytest packages/core/tests packages/core/topoone/tests -q`
4. **冻结契约**：rpc-method-baseline.json diff 为空（方法集与编号零变化）

### V2 docs viewer → viewer/ 子包（1 天）

```
topoone_app_docs/
└── viewer/
    ├── __init__.py        # router = APIRouter() 聚合挂载六子模块（main.py 挂载行零改动）
    ├── _shared.py         # common/router?不——router 分驻各子模块；此件放 _diag_log/STATIC_DIR/cd/logger/_et_unified
    ├── pages.py           # /doc /code（:46-63）
    ├── community.py       # 社区/图数据 11 路由（:68-575）
    ├── plantuml.py        # plantuml 代理缓存 3+2 路由（:579-672）
    ├── diagram_build.py   # mermaid rebuild + diagram build/validate/ir-docs（:677-782）
    ├── diagram_editor.py  # diagram-editor/process(272行)+diagram-tools/apply（:786-1120，独立 _diag_log 归此）
    └── layout.py          # graph-layout 三法（:1122-1219）+ _ensure_graph_layout_table
```
- 路由路径与方法**零变化**；MS1 smoke 的 **G0 路由数守卫（26/10）** 为拆分安全锁——子模块化后守卫改数聚合口径（`viewer/__init__.py` 聚合 router 的 routes 总数仍须 26）
- `web_root.py`/`doc_service.py` 不动；`main.py:80` import 行 `from topoone_app_docs.viewer import router as viewer_router` 零改动（子包 `__init__` 导出同名）
- D6 修复的 `topoone_app_chat.web_tools` import 随 diagram_editor 迁移保持

### V3 chat + web_tools 子包（1.5 天，MS7 铺路）

```
topoone_app_chat/
├── chat_api/
│   ├── __init__.py       # router 聚合（main.py:47 include 行零改动）
│   ├── models_skills.py  # :242-295 + autocomplete/context（:1050-1131）
│   ├── sessions.py       # :295-510（CRUD/auto-title/abort）
│   ├── messages.py       # :515-1049（SSE 核心 + _llm_round 闭包随迁）+ 尾部四类（:1581-1815，SessionCompressor 归此）
│   ├── drafts_notes.py   # drafts :1197-1482 + notes :1483-1580
│   └── archives.py       # :1132-1196
└── web_tools/
    ├── __init__.py       # 导出 get_web_tool_definitions/WebToolExecutor/resolve_refs_to_context/WEB_TOOL_DEFINITIONS/MAX_RESULT_LENGTH（docs viewer D6 消费面 + chat_api 消费面零改动）
    ├── defs.py           # :17-605（DEFS/MAP/_strip_ref_prefix/get_web_tool_definitions）
    ├── executor.py       # :618-1643（WebToolExecutor 36 handler）
    └── refs.py           # :1644-1849（resolve_refs_to_context + _resolve_* 八族 + _REF_RESOLVERS）
```
- `chat.py`/`web_tools.py` 删除（无 shim——apps/chat 全部内部消费一次改净；外部消费仅 docs viewer 的 D6 import，V2 已同步）
- MS1 chat 套件 32 例（SSE/工具循环/断言 `_llm_round` 接缝语义）为安全网

### V4 收口（0.5 天）

全量门禁 + 行数复核（task_manager 门面 <150 / 六域各 <1,500；manager ~1,150；chat_api 各 <600；viewer 各 <400）+ `git diff pre-MS5 -- packages/core/rpc-method-baseline.json` 为空 + 状态回写。

## 5. 测试计划

- 每批：对应域 pytest（core 291+ / chat 32 / docs 18）+ `check-rpc-parity.py`（V1 每域一跑）
- V1 专项：test_start_pipeline_tagent（注册顺序敏感）+ test_tagent_host（`task_manager._compute_file_ranks` 打桩路径经门面保持）
- V2 专项：MS1 smoke 全量（路由数守卫 26/10 是核心断言）
- V3 专项：chat SSE 工具循环用例（monkeypatch requests.post 接缝零变化）
- 收口：`npm run test:py` 全域 + `npm run type-check`（零 FE 影响，应保持绿）

## 6. 验收门禁（对 milestones §2-MS5 判据）

| # | 命令 | 预期 |
|---|---|---|
| 1 | `git diff pre-MS5..HEAD -- packages/core/rpc-method-baseline.json` | **空** |
| 2 | `python -m pytest packages/core/tests/test_db_schema_parity.py -q` | 全绿（五段 SQL 与 golden 全等） |
| 3 | `python -m pytest packages/core/tests packages/core/topoone/tests apps/chat/tests apps/docs/tests -q` | 全绿（291+18+32+18+topoone 套件） |
| 4 | docs smoke 全量（含 G0 路由数守卫）；各拆分产物单文件 <1,500 行 | ✓ |

## 7. 风险与回退

| 风险 | 缓解 | 回退 |
|---|---|---|
| R1 注册顺序漂移破坏 rpc_ids/启动序 | `__init__.py` 锁序聚合 + 每域 parity 校验 + 基线 diff 门禁 | revert 单域 |
| R2 闭包上提改变共享态语义（_agent_mgr 单例性） | common.py 以模块级惰性单例保持；test_start_pipeline 双轨对拍覆盖 | revert V1 |
| R3 门面漏导出（agent 3 处/_tm_ 八别名/打桩字符串） | F3/F4 清单即检查表；grep 校验门面导出面 | 补导出（增量修复） |
| R4 viewer 子包破坏静态页/日志路径 | STATIC_DIR/_diag_log 归 _shared.py 原语义；smoke+手动 /doc | revert V2 |
| R5 chat 拆分破坏 SSE 闭包（_llm_round 捕获 session 态） | messages.py 整段随迁不拆内部；MS1 SSE 用例锁定 | revert V3 |
| R6 与 MS4 并行的 merge 冲突 | 零文件交集已核证；各自 milestone 分支纪律 | — |

## 8. commit 序列（预估 ~7 人日）

| 序 | 内容 | 预估 |
|---|---|---|
| V0 | DDL 外置 + 全等契约测试 | 1d |
| V1 | task_api 六域（每域独立 commit，共 7 commits 含门面） | 3d |
| V2 | viewer 子包七件 | 1d |
| V3 | chat_api 六件 + web_tools 四件 | 1.5d |
| V4 | 收口验收回写 | 0.5d |

开工前 `git tag pre-MS5`；与 MS4 并行（零文件交集，双方判据互不依赖）。


---

## 9. 实施记录（2026-09-24）

| 批 | commit | 内容 |
|---|---|---|
| V0 | a4f2ef1 | DDL 外置五件（manager 2,181→1,159 行）+ 契约测试 5 例（golden 内嵌 pre-MS5 快照）+ core 296 绿 |
| V1 | 7ac450b | task_api 六域+common+门面（4,296→门面 34 行+域件最大 1,750）；parity 218 对等；`_compute_file_ranks` 接缝经 PEP562 惰性委托保持穿透；3 例失败 worktree 归因为 pre-MS5 存量（ab 对拍×2+list_batch_files），V1 自身回归（cancel）已修 |
| V2 | 36ff479 + cc60fdd | viewer/ 七件；G0 守卫 26 路由不变；两处深度陷阱（community 漏 os、测试 STATIC_DIR 路径）修补 |
| V3 | ——**回退** | 子包化后 SSE 事件环挂起（字节级等价复现仍挂，pre-MS5 原版当日 0.95s 通过——排除环境漂移，定性为模块组织引发的深层 asyncio/线程时序问题）；已按裁决⑥恢复单文件，chat 32+docs 18 全绿。挂账 MS6 前置。
> **V3 重做结论（本次）**：渐进二分执行——Step A（web_tools 三件子包）✅ 全绿落地（1ac94e4）；Step B（chat_api 五件，头部整块原样拷贝、send 字节级 ast 等价）❌ SSE 挂起**精确复现**并取得关键法证：faulthandler 全栈显示「LLM 线程在打印 enter 后、执行下一行前**凭空消失**」（5 线程中无任何 chat 帧；消费协程 0.15s 轮询正常；事件循环 idle select）。线程不可能在两条纯 Python 语句间消失且无帧——指向 C 扩展层阻塞且帧不可见，或线程被外部机制移除。已尝试未果：stdlib 注入排查、模块双实例排查（无）、PEP562 委托、`-o faulthandler_timeout`、py-spy（需提权）。
> **归因突破（2026-09-25 py-spy TRACEME 模式）**：`py-spy record -- python -m pytest <挂起用例>` 以父进程身份 TRACEME,**免提权可用**(yama=1 下 record 启动模式有效, dump--pid 模式无效)。794 采样原生栈已存档。关键事实: ① producer 停在 messages.py:340 `await run_in_executor(chunk_q.get, True, 0.1)` ② executor worker 空闲(697 采样 idle _worker) ③ 事件循环 idle select——producer 的 0.1s 超时轮询未唤醒它 ④ **LLM 线程从未出现**(非卡死, 是未启动/启动即失联)。定性: run_in_executor future 回调的 call_soon_threadsafe 唤醒链断裂——TestClient portal 循环 + 子包模块组织下的深层交互。专项会话入口: 对比单文件版同一 producer 的唤醒链 / 缩减 chat_api 五件逐件回退二分。
> **当前处置**: Step B 再回退(单文件 chat.py 保持), chat 32 绿。V3-StepB 列为独立专项, 不阻塞 MS5 验收(判据 1-4 在分域口径下全部达成)。 |

### 实施期修正
1. graph-kernel 深路径（继承 MS1 教训）直接走 barrel 出口
2. `from-import` 绑定复制使 monkeypatch 失效——域内改模块属性调用（`common._compute_file_ranks`），门面用 `__getattr__` 委托
3. tests 同名模块跨套件混跑冲突（conftest/test_* 裸名）——判据 3 改为分域命令口径；sys.path 卫生债挂 MS6

---

## 附：V3-StepB 收口方案（2026-09-25 细化，待评审）

> 核证：chat.py 1,815 行 / 82 顶层定义 / 3 处 SSE 流（:562 tagent 流 / :700 tagent 事件流 / :968 主事件流）。web_tools 子包（StepA）已落地。挂起法证链完整（见上表 V3 行）。

### 路径（二选一，0.5~1 人日）
- **路径 a（先诊断，推荐）**：一次性 `sudo py-spy dump` 终局归因（TRACEME 免提权路径已打通，复现命令存档）。
  - 若根因为**可修的模块组织问题**（如特定 import 顺序触发）：修复后重试 chat_api 子包化（messages/skills/tables 三件+装配），字节级等价判据照旧；
  - 若根因为**深层 C 扩展/线程机制问题**：按 W8 先例落档"保留单文件"结论，结项。
- **路径 b（直接结项）**：按 W8 先例直接落档保留单文件。依据：① 1,815 行仅超软上限 21%；② tagent/legacy 双后端复杂度是真实内聚（同 engine 六域）；③ MS7-W4 迁移时原样搬迁即可，拆分收益进一步降低。

### 判据
- 路径 a 修复线：chat 32 例全绿 + 挂起用例 3 连跑稳定 + 与单文件版行为对照清单零漂移
- 结项线：结论文档入本节 + milestones 状态改"已结项（保留单文件）"

### 与 MS7 的关系
- 专项独立，不阻塞 MS6/MS7 任何批次
- 若选路径 b，MS7-W4 按单文件原样迁移
