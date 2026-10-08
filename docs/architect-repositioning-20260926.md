# architect 主 agent 定位裁决 — 2026-09-26

> 背景：cv-256/257 系列实测暴露主 agent 越位（问询自动起草需求卡→默认派编码
> 执行器→执行器往用户仓库写码）。经评估裁决：**精准化缩小化主 agent，未命中
> 核心能力的一律指向执行器**；长远自研可控主 agent 的目标不变。

## 一、定位三原则（治理词汇单源）

1. **问什么答什么**——信息问询回合只做只读应答，零落库副作用，禁起草需求卡。
2. **不扩大化**——无明确行动意图（要建/要改/要修）不得 propose/预填/自动续步。
3. **不强硬保底**——缺数据报缺数据，缺指定显式要指定；禁止静默默认引发意外行为。

## 二、主 agent 职责白名单（只做五件事）

| 职能 | 既有落点 |
|---|---|
| 1. 资产域内操作（KB 构建/重建/检索/地图——域内管道，永不派编码执行器） | semantic assets / staging scans / asset.semantic.* |
| 2. 问询应答（状态/进度/资产检索——只读工具面） | project.ctx(聚合画像) / ctx.* / map.* |
| 3. 需求规约生成（含中小模型细粒度微规约） | req.propose / spec_versions / designMd |
| 4. 执行编排（计划分解→执行器路由→上下文包装配） | task_plan / dispatch.py / router.py |
| 5. 资产比对验收 + 迁移跟踪（规约资产↔交付资产 diff；单测归执行器侧） | arch_acceptance_facts / arch_tracking_items |

**负面清单（明确不做）**：通用编码问答、直接写代码/脚本、无行动意图的需求卡
起草、单测判定、仓库直写（域内管道除外，且仅落 arch 库）。

## 三、配套机制

- **模型能力探测**：probe_suite 新增 inquiry(问询纪律)/routing(路由决策) 两维
  （WEIGHTS 重平衡 tool 0.30/inquiry 0.15）；TIERS 文案对齐新定位。用户按自身
  条件自选模型（可大可小，非强制），过小模型经 admission 明示风险。
- **上下文包契约**（P2 建设项）：执行器输入从 instruction 自由文本升级为
  结构化 brief（specMd + 资产引用 + 约束 + 验收判据）。
- **执行门禁**（dispatch 前置）：主工作区有未提交变更（其它进程在编码）→
  显式失败/强制隔离，不静默开工。
- **域内管道形态**：KB 域操作=进程内技能（asset.semantic.extract 等），
  不做"域内执行器类型"——执行器位只留给外部 agent。

## 四、阶段判据与进度（全部落地, 2026-09-26）

- P0 ✅（56a50971）：三原则+白名单入档；探测套件 inquiry/routing 两维+TIERS 对齐；req.propose 边界
- P1 ✅（2e5a7df7）：三挡 architect_note 问询纪律行 + 哨兵测试
- P3 前置 ✅（41f80c9d）：执行门禁（就地+脏工作区 → 显式失败/引导隔离）
- P2 ✅（cef6f13f）：上下文包契约 context_pack.py——载荷结构化 contextPack + 指令尾契约段；缺规约透明降级
- P3 ✅（cef6f13f）：验收材料并入 execution_report 沉淀单元（持久化）；越界缺口提示（迭代规约需用户确认）

**人工验证清单**（重启 dev 后）：
1. ✅ **已验证（cv-258, 2026-09-26）**：问"检查完成情况" → 只答事实（当时执行统计确为 0——旧会话由用户在 UI 删除），零需求卡零任务；越界建议仅口头提示不行动
2. ⬜ ConfigPage 模型探测 → 档案含 问询/路由 两维新分数
3. ⬜ 带规约任务执行 → 完成消息含验收简报；执行器载荷含上下文契约段（日志可查）
4. ⬜ 其它进程有未提交变更时就地执行 → 显式拒绝并引导（不再互踩）

**随验证确认的行为注记**：cv-257 的 task-56 污染物（topo-animation:
`ast-scanner.mjs` + `.topo/asset-map.json`）已由用户处置（2026-09-26）；
KB 重建功能**待重新规划**（用户裁决 2026-09-26，稍后再议——届时按域内管道
形态设计，不走编码执行器）。


---

## 执行器协作演进（2026-09-27 批次，用户实证驱动）

| cv | 内容 | 状态 |
|---|---|---|
| cv-259~264 | 直通模式系列收口: R1 依赖注入/泵快照+异常清理/空白态挡位预置/首回合形状归一/流式单卡生长/僵尸泵根治 | ✅ 已提交 |
| cv-265 | 挡位回落修复（activeMeta 就绪才同步） | ✅ |
| cv-266 | 直通历史上下文: 历史脉络默认注入(确定性拼接, 容量可调)+digest 接线+MCP 默认接线(ctx.*)+工具告知 | ✅ |
| cv-267 | sessionRole 对话回合制: chat 角色无协作协议/无验收门/turn_done 保活; system prompt 分型; system_prompt 白名单接通 | ✅ |
| cv-268 | 执行器过程感知统一通道: process_stream 单源+ExecutorProcessStrip 共享组件+任务泵等价重构+直通过程条(消息区尾部) | ✅ |
| cv-269 | 脏区自干扰死锁(工具告知落盘自污染)+门禁软化(chat 警告+继续, 任务链硬闸不变)+**就地→融合模式改名** | ✅ |
| cv-270 | 信息流污染(警告并入回执)+折叠计数失真(tool 自计数+turn_done 折叠快照) | ✅ |
| cv-271 | 长输出头部截断(撤 buf 6000 上限, 失控保护归 loopguard) | ✅ |
| **cv-272** | **规约文档投影**: `.topo/docs/{reqId}/` 四件(SPEC/DESIGN/ACCEPTANCE/BOUNDARY)经 workspaceFiles 载荷投影+`.git/info/exclude` 幂等注入(.topo/ 整目录)+指令瘦身(要点~800字+强指引"执行前先读")/written 回报缺失降级+淘汰机制(任务轮次作用域: 终态即删融合目录/隔离随 worktree/waiting 保留/孤儿清扫)+并行规避(跨会话边界集求交→软警告+可继续; 同会话硬互斥保留) | 🔄 实施中 |

**模式命名**: 就地模式→**融合模式**(用户裁决 cv-269; API token `inplace` 不变)。
**测试超时纪律**: 单文件≤120s/全量≤300s(超时即定位, 不加大超时)。
| cv-273 | 直通执行器控制与会话延续: 复活链(sessionRef 持久化+start 回传)/停止通道(REST proxy-stop+泵终态收尾)/steer 消费(cline 直达, 他器回落排队)/会话控制条(turnCount+停止钮) | ✅ cfd8f705 |
| cv-274 | 控制条数据链修复(text 双路进过程流——lastText 预览死面)+FE 诊断布点(到达/落 map/渲染三断点)+渲染探针 | ✅ e5b9bdde/bbb6c8f1，**cv-269 实测通过**(2026-09-27: 渲染 LIVE/工具自计数 0→20/折叠'本轮共 8 次'全对) |
| cv-275 | 持久会话状态条(REST proxy-state 真相源)+停止分型(running→abort/空闲→finish) | ✅ c55d1cf7 |
| cv-276/277/278 | 长消息折叠阅读(420px 滚动+⤢放大弹窗+最小化/展开切换 SVG 钮)+toolbar-extra 恢复+ChatFeedPanel attrs | ✅ e2d975bd/dafcb76c/5066a154 |
| **cv-279~281** | **需求卡细化(用户实证 cv-271)**: 需求卡编辑(EditSpecModal+PUT content, 版本链 append 旧版快照行永不改动——防已执行需求与任务 specVer 对应错乱)/「执行」→「任务生成」改名/「立即执行」单任务直发(execute_requirement_now 单源复用 propose→confirm) | ✅ e616e420/b59d7215/bf3cefd5 |
| **cv-282** | **脏区门禁问询化**(用户裁决: 硬闸命中给问询提示等反馈后处理): P3 门禁不再一次失败——waiting_input+choices 问询卡(稳定 key 单源/fingerprint 原位更新)+gate_ask.py 拆分(resolve_dirty_gate: 隔离重试/干净后重试/取消, 全程 confirm_task 单源门禁不削弱) | ✅ caed4624 |
| **cv-283** | **任务卡归一**(用户裁决: proxy 卡升级同构): 直通作业 JobCard(TaskCard 同族)——meta 作业快照键+终态/停止状态回写原位更新+items.py 统一投影 type=job | ✅ 5b6bd4db |
| **cv-284** | **需求浮层大窗**: ReqDetailWindow 双入口共享组件(消息流放大钮+会话列表跟踪条点击)——全文/版本切换器(specVersions 只读浏览)/编辑入口/任务生成/立即执行/关联任务清单(specVer 标注) | ✅ 6fe487af |
| **cv-285** | **执行详情窗(方案甲 双源统一)**: exec_control.py 统一视图模型(taskId\|jobId)+单一控制面(pause/resume/stop/input)+ExecutionDetailWindow(入口: TaskCard/JobCard 组件内放大钮自持)+信息补充/问询回答转达 | ✅ 7defd2ff |

**cv-279~285 批次纪律执行**: 单源复用零并行通道(spec_append/propose→confirm/task_input/confirm_task 全链既有); 门禁不削弱(无 bypass); 稳定 key 非 UI 文本匹配; 行数基线登记(dispatch 966/gate_ask 90/proxy 479/sessions_tasks 282/exec_control 146)。门禁: BE 1211+FE 64+TSC 0。

---

## 定位诠释细化（2026-10-10）

「人在环上」（产品基调锚点 2）的环位细化（用户裁决，**不改三原则**）：环的重心在**头尾**——
**执行前规划确认 + 执行后审核**（多角度证据呈现 + 人工终审），中间过程放活，**不做逐步
审批流**。预留通用 `approval` 扩展位（缺省 `none`=无行为）供未来人工审批或主控 agent
审批按需接入。详见 `docs/architect/adoption-batch1-plan-2610.md` §1.4 与
`tech-debt-ledger-2609.md` 对标增强轨道 G2 条。

