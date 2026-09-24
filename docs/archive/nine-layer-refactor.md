# architect Agent 九层重构实录（P0-P6）

> 2026-09 | 状态：**已完成** | 门禁：architect 456 tests + core 172 tests 全绿

## 一、决策记录

| 决策点 | 结论 |
|---|---|
| 重构性质 | 结构重组 + 能力增强 |
| 代码位置 | `apps/architect/topoone_app_architect/agent/`（chat 需要时再上提 core，符合 CONV-00 复用规则） |
| 旧 jobs 账本执行路径 | 本轮清退（meta.jobs 写路径全删；P6 起 runningRole 单读，存量行不再驱动任何 UI 状态） |
| 三方 coding agent 边界 | 方案 B：runner 事件 schema 化 + 宿主重组（走 core 门禁 G2 全量回归）；`/api/implement*` 契约只增不改 |
| 场景边界 | KB + 数据资产管理 = architect 自有认知；coding = 三方专业 agent（cline 内嵌/opencode/codex）经 TurnAdapter |

## 二、九层落位

```
topoone_app_architect/agent/
├── orchestrator.py        回合编排: gate→route→(cognition↔tools)*→fence→reflect→persist
├── perception/            ① gate(会话闸门/归档闸/自愈) router(attachTo/agent/缺省三向) intent
├── cognition/             ② llm(通道/偏好) roles(角色→模型) model_profile(t0-t4) strategy(策略矩阵) prompt(块化装配)
├── planning/              ③ req_spec(规约确定性链) task_plan(围栏/轻门禁/指令组装)
├── memory/                ④ units(上下文注册表) dossier(装配) working(历史窗口)
├── tools/                 ⑤ registry(44 工具+skills) protocol(TOOL_CALL 文本协议)
├── execution/             ⑥ pumps(单泵: WS订阅+轮询校准) runner_client(类型化)
├── reflection/            ⑦ guards(防编造/意图) repair(修复外循环+锚定) evaluator(WS4) mining(WS7) dataset(观测)
├── collab/                ⑧ sse(进程内事件总线)
└── governance/            ⑨ boundary(边界解析/互斥引擎/文件求交)
```

适配层：`arch_routes/*.py` 仅 REST/WS 适配 + 兼容 shim（9 个模块级 shim + req_agent 内 re-export），契约冻结（CONV-04）。

## 三、阶段实录

| 阶段 | 内容 | 关键产出 |
|---|---|---|
| **P0 契约固化** | 特征测试加固 | `test_runner_contract`(runner 黄金形状×6)、`test_kb_chat_routing`(WS 路由×9)、`test_feed_gate`(投喂门+runningRole×8)；**修 bug#1**：归档会话 WS `request_id` 未定义 → 前端挂死无反馈 |
| **P1 纵切抽取** | tools/cognition/dataset/sse 物理迁移 + re-export shim | req_agent 2959→2800；同对象校验（`_ARCH_TOOLS is registry._ARCH_TOOLS`） |
| **P2 编排器落地** | orchestrator 机械移植（git HEAD 切片+机械替换，逐字节保真校验） | websocket 1005→183；**修 bug#2**：sessions 克隆从 websocket 导入 `_prior_job_brief`（实际在 exec_bridge）→ 前情简报种子从未生效 |
| **P3 执行层统一** | core `runner/events.py`(EventKind/EventBus schema 单源) + architect `execution/`(单泵+类型化 client) | exec_bridge 1245→682，旧 jobs 写路径清退；stop-exec/feed/guide 转 v2 任务 |
| **P4 规划与记忆** | planning/(req_spec+task_plan) + memory/(units+dossier+working) | **循环导入根修**：agent 包内模块级 arch 导入全面惰性化（`_store()` 模式） |
| **P5 反思闭环** | reflection/(guards+repair+evaluator+mining+dataset) + 策略矩阵 guard 开关接线 | adaptation 退化为 shim；req_agent→1899 |
| **P6 清理收尾** | runningRole 单读、coding-sessions 存量状态清理、死导入扫尾、本文档 | `intent_followup` 分档接线评估后**暂缓**（默认路径行为锁定，需产品决策+生产验证） |

## 四、接缝纪律（重构全程的铁律）

1. **机械移植优先**：P2 曾因手抄 `_LiveForward` 逻辑漂移被保真校验当场抓获 → 之后所有函数体迁移一律 git 原文切片+机械替换（仅导入路径/签名归一），归一化 diff 验证。
2. **monkeypatch 接缝 = 模块属性 + 调用时解析**：40+ 处测试 patch（`req_agent.llm_sync`/`ra.repair_spec_payload_format`/`eb._runner`…）全部保持生效——迁移体经源模块属性调用时解析（`_ra().llm_sync`）。
3. **agent 包循环导入防线**：任何 `from ...arch_routes import X` 不得出现在模块级（P4 实证会引爆半初始化），统一 `_store()/_ra()` 惰性访问器。
4. **契约只增不改**：WS/SSE 事件形状、`/api/implement*` 响应、REST 前缀全程冻结；行为变更（feed 目标/stop-exec 范围/runningRole 单读）同步更新对应特征测试并留档。

## 五、本轮修复的存量缺陷（非重构引入）

| # | 缺陷 | 影响 | 修复 |
|---|---|---|---|
| 1 | `websocket.py` 归档分支引用未定义 `request_id` | 对归档会话发消息 → UnboundLocalError 被外层吞 → **前端连接挂死零反馈** | `data.get("requestId")`（现 gate.py） |
| 2 | `sessions.py` 克隆从 websocket 导入 `_prior_job_brief`（实际定义在 exec_bridge） | 克隆会话"前情简报"种子 **一直静默失败** | 改从 exec_bridge 导入 |
| 3 | `test_context_registry` 摘要测试依赖"LLM 不可达" | 本机 3459 活栈可达时随机失败 | 显式 stub llm_sync 固化降级路径 |

## 六、P6 收尾审计补充（遗漏排查与修复）

收尾时对照原方案逐项审计，发现并修复 **2 个 shim 引入的回退风险**：

| # | 缺陷 | 根因 | 修复 |
|---|---|---|---|
| 4 | `capability_mining` shim 漏导出 `start_periodic_mine` → server lifespan 定时批量提炼循环被 try/except **静默禁用** | shim 导出名清单手工维护 | shim 补导出；新增程序化 shim 完整性审计（全仓 from-import 需求 vs shim 导出差集） |
| 5 | 会话栏发送方向选择器(@architect/@cline)硬编码两项, @codex 选不到 | AnalysisChat AGENT_PICKS/宿主 AGENT_CHOICES 写死 | 改由执行器注册表派生(type→后端白名单别名映射+去重), 兜底保留缺省两项 |
| 6 | ctx.*/评估/提炼工具注册时机回退：原为服务启动即注册（websocket import 期），P4 改延迟到首个 chat 回合 → MCP 面（:3460）在无人进过对话前调 `ctx.search` 报"未知工具" | 工具注册块从模块级迁入 orchestrator | server lifespan 显式调 `_register_session_tools()`（幂等），恢复启动语义 |

同步补齐方案承诺项：
- **MemoryStore 门面**（`agent/memory/store.py`）：消息/单元/文档/检索/上下文包/dossier/摘要统一只读入口（P4 原方案的统一记忆接口）
- **intent.py 注释校正**：LLM 分级兜底为后续项，不冒称已落地

## 七、遗留与后续

- **shim 撤除**：9 个模块级 shim + req_agent re-export 待外圈调用方（其他 app/MCP 面）迁移后统一收口（当前同时服务测试接缝，撤除收益低）
- **intent_followup 分档**：策略矩阵 t2+ 开/大模型关——默认路径（无模型=t0）现无条件跑意图追问守卫；接线需产品确认（守卫来自 cv-88~102 生产痛点）
- **流式 token 透传**：`events.EventKind.TEXT` 已预留，TurnAdapter 逐段 emit → 泵原生承载（架构零改动）
- **旧 meta.jobs 读残留**：`exec_bridge.stop`（存量行终态化兜底）/`_prior_job_brief`（克隆种子）保留一个版本后随账本删除
- **runner JobStore**：`_JOBS` dict 保持进程内注册表原样（EventBus 已拆出；四类拆分收益低未做）

## 八、验证基线

```bash
python -m pytest apps/architect/tests -q        # 456 passed
python -m pytest packages/core/tests -q         # 172 passed（G2）
npm run type-check && npm run lint              # 0 新增（存量 130 lint errors 为基线负债）
npm run test:fe                                 # 21 passed
# 特征锚点: test_kb_chat_routing / test_runner_contract / test_feed_gate /
#           test_execution_pumps / test_exec_implement / test_fabrication_guard
```
