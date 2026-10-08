# B1-W5 实施文档：单测建议层（缺口建议面板 + 轻事实层 + approval 扩展位）

> 组：W5(3~4d) · 依赖：**W2**（graph_neighborhood）+ **W4**（K2 tests 段）· 决策依据：D-3（追溯矩阵延后）/ D-4（approval 扩展位）/ D-8（覆盖率不采）/ 基调修正 1（建议视角非强制）
> 定位：UnitTestPage 原位升级为"建议 + 执行"双区；一切产出为**建议视角**，无强制步骤

---

## 1. 模块操作总表

| 模块 | 操作 | 摘要 |
|---|---|---|
| `sem/test_reach.py` | **新增** | 图加权测试可达性计算（~150 行）：扇入×域标记×无测试可达 → Top-N 缺口 |
| `arch_routes/unit_test.py` | **变更** | 新增 2 建议端点（advice/facts）；approval 字段入提案配置 |
| `sem/` baseline_refresh 编排 | **变更** | 尾步挂测试文件模式扫描（轻事实层） |
| `store/tracking.py` + `arch_routes/tracking_api.py` | **复用 + 变更** | 对账差异事件经 emit/sync_task 挂账 |
| `src/services/unit-test-service.ts` | **变更** | advice/facts API 适配 |
| `src/pages/UnitTestPage.vue` | **变更（原位升级）** | IA 双区：上半屏建议面板 / 下半屏执行会话（现状保留） |
| `src/components/unit-test/AdvicePanel.vue` | **新增** | 缺口建议卡列表（含最小证据视图 + approval 位展示） |
| 缺口建议卡 → 任务卡委派 | **复用** | 确认后走既有 propose→confirm 单源（载荷 = context_pack + W2 邻域 + KB 测试风格样本） |
| approval 扩展位 | **新增** | 提案/任务配置 schema 加 `approval` 对象，**缺省 `none` 无行为** |
| 移除 | 无 | 既有单测列表/会话/生成对话框（UnitTestGenerateDialog 等）全部保留 |

## 2. 逐模块明细

### 2.1 `sem/test_reach.py`（新增：缺口计算）

**内容**：
- `test_reach_gaps(top_n, focus?) -> [TestGap]`：输入 = `arch_graph_node/edge`（图）+ 事实层测试集（2.3）+ 组件目录（`arch_components` 域标记）；计算 = 测试文件可达符号闭包（反向）→ 图上无测试可达符号集合 → 加权（扇入 × 组件域标记）排序取 Top-N
- 排序键默认图中心度（D-7 学习路径变体的零成本落地）
- 每缺口携带**最小证据视图**（D-5 多角度呈现的最小落地）：变更统计（cached_compare 口径）+ 关联符号签名 + 一跳邻域摘要（复用 `graph_neighborhood(depth=1)`）

**上游**：W2 `graph_neighborhood`；事实层测试集；`sem/comp_graph.py` 的 cached_compare（**只读复用，勿另起变更态通道**）；`arch_components`。
**下游**：unit_test.py advice 端点；（远期）D2 多视图审核面板的证据卡形态参考。

### 2.2 `arch_routes/unit_test.py`（2 新端点 + approval 位）

**改动**：
- `GET /unit-tests/advice?top_n=&focus=` → `[{symbol, module, weight, evidence}]`（建议视图，纯读）
- `GET /unit-tests/facts` → 事实层对账状态：`{scanned_tests, claimed_tests(K2), diff_events}`（供建议面板状态条）
- approval 扩展位：提案配置 schema 加 `approval: {mode: "none"|"human"|"agent", policy?: object}`——**缺省 `none`，本批无任何行为分支**（D-4 预留；未来对接人工审批/主控 agent 审批）

**上游**：test_reach；tracking 事件。
**下游**：AdvicePanel；（远期）CI/CD 整合的 approval/coverage 消费方。

### 2.3 baseline_refresh 编排尾步（轻事实层）

**改动**：一键基线刷新编排（采集→分组→命名）尾部追加一步：测试文件模式扫描（`*.test.ts` / `test_*.py` / `*_test.go` / `*.spec.ts` / `*.spec.js` / `*_test.py` 变体）——纯文件名 glob，成本极低；结果 = 当前测试集清单 + 与上轮差异（复用 change_detector 判"新引入测试"）；落库供 test_reach / 对账消费。**不采覆盖率**（D-8：未来 CI/CD 整合供数）。

**上游**：baseline_refresh 既有作业链；仓库工作区。
**下游**：test_reach 输入；K2 对账的"事实"侧。

### 2.4 对账（主张层）

**改动**：`K2 tests.files`（W4，主张）∩ 事实层扫描集（事实）——差异（声称有/扫描无；扫描有/未声称）经 `store/tracking.py` emit 挂账（tracking_api 既有 GET/POST/PATCH 直接可查可处置）。**对账结果是状态展示，不产生任何阻断**（基调修正）。

### 2.5 前端（原位升级）

**改动**：
- `UnitTestPage.vue`：上半屏新增建议面板区块（可折叠/可隐藏），下半屏执行会话**现状不动**（B2 纪律：下线优先于拆分，本批零下线）
- `AdvicePanel.vue`（新增）：缺口卡列表——每卡：符号/模块/权重、最小证据视图（变更统计+关联符号+邻域摘要）、操作按钮【生成任务】（→ 既有任务生成入口，载荷自动附带邻域与 KB 测试风格样本）、approval 状态位（本批恒显示 none）
- 文案 i18n zh/en 明示"建议/参考"语义（防走样为"必须清零的工单"——风险表预防项）
- `unit-test-service.ts`：+2 API 适配

**上游**：advice/facts 端点。
**下游**：用户确认缺口 → 委派链（复用 propose→confirm，不新建委派通道）。

## 3. 数据与契约变更

| 面 | 变更 | 兼容性 |
|---|---|---|
| REST | +2 只读 GET 端点 | 纯增量 |
| 提案/任务配置 schema | + 可选 `approval` 对象（缺省 none） | CONV-04 登记；老数据无此字段 |
| 事实层测试集 | 新增轻量存储（复用 jobs/KV 或既有表，实现时按 store 现状择小者） | 无破坏 |
| 表结构 | **尽量零新增表**（tracking 复用；追溯矩阵已延后不建表） | — |

## 4. 测试计划

- `tests/test_test_reach.py`：fixture 项目——① 已测符号不进缺口 ② 加权排序正确 ③ Top-N/预算
- `tests/test_unit_test_advice.py`：端点形状；approval 缺省；facts 对账差异事件挂账
- `tests/test_baseline_scan.py`：模式扫描（多语言后缀）；diff 判定
- FE：`tests/unit-advice.smoke.test.ts`（AdvicePanel 渲染/折叠/i18n 文案"建议"语义）
- 手测 DoD 5：一张建议卡走完 确认→委派→回执→对账 全链；建议面板独立可用（无前置步骤）

## 5. 回退

| 片 | 回退 |
|---|---|
| 建议面板 | `unit_test_advice.*` 开关（BE 端点 404 降级 + FE 面板隐藏） |
| 事实层扫描 | baseline_refresh 尾步摘除（作业链其余不变） |
| approval 位 | 无行为字段，revert schema 即可 |

## 6. 组内验收清单

- [ ] 建议面板可见缺口 Top-N（带最小证据视图）与对账状态条
- [ ] 一张缺口建议卡走完 确认→委派→回执→对账 全链
- [ ] `approval.mode` 缺省 `none` 且无行为分支
- [ ] **无强制步骤**：建议面板在无 K2 回执/无扫描数据时仍可独立使用（降级展示）
- [ ] UnitTestPage 既有功能（列表/会话/生成对话框）零回归
