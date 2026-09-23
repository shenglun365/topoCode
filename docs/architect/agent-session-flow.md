# Agent 会话流转全景（v2 统一会话）

> 状态：2026-09-15 与代码对齐（cv-152~158 实证回归后）；**2026-09-22 增补**：流程相位机入图（①.5 相位硬闸 / flowState 派生缓存）——语义单源 `agent/governance/flow.py` + `agent-arch-gap-adoption-2609.md`，本图仅导航。
> **2026-09-22 补充（实时通道架构, cv-221）**：推送=信号, 拉取=真相——WS 回合流负责交互渲染(不过缓冲)；SSE 通知统一入 store 消息缓冲(单消费者, 消费期判卫/折叠/按任务 150ms progress 折叠)；补偿拉取 4 触发点=回合收尾/SSE 重连/页面可见/切换会话。语义单源 `conversation-store.ts`(EventBuffer)。
> 维护约定：流转变更（直通指令/执行器选定链/泵/守卫/相位闸/实时通路）须同步本图。

## 一、总览流程图

```mermaid
flowchart TD
    A[用户新建会话<br/>SessionsPage / ConversationDock] --> B[WS /ws/kb-analysis<br/>bind_session 会话闸门<br/>绑定/归档闸/需求回填]
    B --> C{泵恢复<br/>running/waiting_input 任务?}
    C -->|有| C1[recover_conv_tasks<br/>runner 实际态核对收尾/重挂泵]
    C -->|无| D
    C1 --> D[用户消息落库]

    D --> D2{①.5 相位硬闸<br/>flow.evaluate_guards<br/>仅 interrupted × 下发意图}
    D2 -->|命中| G0[⛔直通回执落库<br/>零 LLM + 恢复指引<br/>开关 flow_guards_enabled]
    D2 -->|放行| E
    D --> E{整条消息是指令?}
    E -->|/定稿| F1[finalize 门禁<br/>designMd 校验+幂等<br/>→ ready + specReady 卡]
    E -->|/执行| F2[ready 规约 → 建任务卡<br/>执行器选定链:显式@ > 会话绑定 > 注册表默认<br/>→ pending_confirm]
    E -->|确认语+恰有一张待确认卡| F3[confirm_task 直通<br/>同卡片按钮]
    E -->|普通消息| G

    F1 --> Z1[前端动作卡<br/>specReady→一键建卡]
    F2 --> Z2[任务卡落流<br/>用户点卡确认]
    Z1 --> F2
    F3 --> H
    Z2 --> H

    G[路由决策 router.decide] --> G1{语境}
    G1 -->|attachTo 转达| G2[task_input → 活跃任务<br/>可选语境摘要拼接<br/>回执 ➡️/📥]
    G1 -->|内联@执行器 assign| G3[指派契约注入<br/>architect 评估建卡]
    G1 -->|chat| GU

    DX{② 直通: 意图原语 match_imperative<br/>× 焦点栈 resolve_intent 就近消解<br/>(确认/推进→栈顶步骤卡; spec_ready→执行<br/>retry→recent.failed; 无指代→回落 GU)}
    G1 -->|chat| DX
    DX -->|"确认/推进类+焦点帧"| D1[confirm_task 零 LLM]
    DX -->|"execute+spec_ready"| D2[run_execute]
    DX -->|"无意图原语"| GU

    GU{③.5 目标理解 GU<br/>GoalProfile: L0 词表/策略库<br/>+L1 上下文(+L2 受限LLM 缺省关<br/>携带近期对话摘要+焦点事实面)<br/>→ policy.goal 决策表<br/>(8 动作含 present-options 候选菜单)} -->|回合指引注入| H

    H[architect 回合<br/>能力文档+posture 判据(静态人格)<br/>+挡位指引 strict/quick+skill 文档] --> I{LLM 通道}
    I -->|流式 llm.chat| I1[逐字 chunk]
    I -->|失败降级 llm.sync| I2[工具循环 run_tools_loop]
    I1 --> J
    I2 --> J

    J{模型产出} -->|req.propose| J1[规约落库 draft<br/>specCreated 卡→去定稿]
    J -->|task.propose 围栏/工具块| J2[任务卡代落<br/>按选定链执行器]
    J -->|普通回答| J3[流式回执+工具进度]
    J -->|谎报动作| J4[防编造守卫拦截卡<br/>建议修复/指令 chips]

    J1 --> K[/定稿<br/>用户或提案卡按钮/]
    K --> F1
    J2 --> H
```

## 二、活动图（泳道：用户 / architect 会话 / runner+执行器）

```mermaid
activityDiagram
    participant U as 用户
    participant A as architect 会话(WS)
    participant R as runner + cline-sdk

    U->>A: 新建会话·发消息
    A->>A: bind_session + 泵恢复 + 指令/确认拦截
    A->>A: architect 回合(KB工具/规约/任务卡)
    A-->>U: 回执卡(specCreated/方案/守卫)
    U->>A: /定稿 (直通·零LLM)
    A-->>U: ✅ ready + [一键建卡执行]
    U->>A: /执行 或 运行按钮 (直通·零LLM)
    A->>A: propose_task<br/>执行器选定链→pending_confirm
    A-->>U: 📋 任务卡(cline-sdk·完整配置)
    U->>A: 点卡确认 / 文字「确认」
    A->>A: confirm_task: 单源解析→互斥→边界检查
    A->>R: POST /api/implement<br/>(worktree+分支task/N+model配置)
    R-->>A: jobId + session_ready
    A-->>U: 🚀 启动回执 (work_state=running)

    loop 任务泵(主循环调度)
        R-->>A: 事件流(progress/text/input_required/done/failed)
        A-->>U: 消息落流(agent=cline-sdk 徽标归因)
    end

    alt subagent 需要输入
        R-->>A: [[NEED_INPUT]]
        A-->>U: ⏸ 等待输入 (waiting_input)
        U->>A: 直接回复(可附语境摘要)
        A->>R: 转达 → 续跑
    else 执行完成
        R-->>A: [[IMPLEMENT_DONE]]
        A-->>U: ✅ 完成回执+变更文件+验收简报 (done)
    else 失败
        R-->>A: error
        A-->>U: ❌ 失败原文 (failed, 分支保留)
    end

    opt 异常兜底
        A-->>U: ❌ turnError 落库+全文回传<br/>(WS顶层捕获, 刷新不失)
    end
```

## 三、状态机

### 会话 `work_state`

```
architect ──confirm──▶ running ──泵终态聚合──▶ architect
```

### 任务（arch_tasks）

```
pending_confirm ──confirm──▶ running ◀──转达/续跑──┐
      │                        │                    │
      │                        ▼                    │
   cancel(取消)          waiting_input ────────────┘
                               │
              done / failed(分支保留) / cancelled
```

### 规约（requirements）

```
draft ──/定稿(designMd 门禁, 幂等)──▶ ready ──/执行──▶ 任务卡 ──确认──▶ 执行
  ▲                                    (已存入待执行; 提案卡显示[运行])
  └── /调整 / req.amend (严格挡)
```

### 消息归因（读侧徽标）

| agent 前缀 | 归因 | 来源 |
|---|---|---|
| `''` | architect（灰标） | 外循环/系统回执(log_conv_event/直通/守卫) |
| `cline-sdk` / `opencode` / `codex-server` | 执行器（teal 标） | 任务泵 `_handle_task_event` 落流 |

## 四、执行器选定链（单一事实源，无静默降级）

```
显式 @指定(消息前缀/组合指令)  >  会话绑定(executor_id, 工具栏选择钮)  >  注册表默认(default&&enabled)
```

- 类型别名单点归一：`cline→cline-sdk`、`codex→codex-server`（architect 与 runner 两侧一致）
- **id/配置同源**：类型取自注册表默认时，id 与 executorConfig(models/provider/key) 取同一注册项
- 解析不到 → 建卡/确认**显式失败原文回执**；runner `build_adapter` 未知类型 raise（支持清单），绝不回退 opencode
- 绑定语义（v3）：未绑定=选择即绑定；已绑定切换=克隆新会话

## 五、关键守护点

| 守护 | 位置 | 说明 |
|---|---|---|
| 指令直通零 LLM（/定稿 /执行 /文字确认） | `agent/perception/commands.py` + `handle_chat` 拦截 | 仅 chat 路由生效；转达语境的 /文本是给 subagent 的内容不拦 |
| 轻门禁 | 任务卡确认才拉 subagent；严格挡先定稿再建卡 | `/执行`=建卡待确认；quick 挡 task.propose 直出 |
| 泵恢复 + 主循环调度 | `exec_bridge.set_main_loop/_start_task_pump/recover_conv_tasks` | REST to_thread 无循环必炸的根治；会话交互前惰性核对收尾 |
| 错误完整可见 | `websocket.py` 顶层捕获 + 空返回分支 | turnError 落库(meta) + 全文回传，刷新不失 |
| 防编造守卫 | `agent/reflection/guards.py` + `_guard_repair_core` | 谎报「已启动」→ 拦截卡；repair 确定性提取建卡（拒状态话术载荷） |
| 语境摘要 | `POST /sessions/{id}/msg-digest` → WS digest → transfer 拼接 | 仅转达语境；digest_sent 折叠卡审计 |
| 幽灵卡防线 | 守卫修复 markdown 兜底守门 | 状态话术(已启动/处理中/完成后将)不充当任务载荷 |
| 回执动作卡 | specCreated→[去定稿] / specReady→[一键建卡] / 提案卡[运行] | 零手敲指令；后端状态核验防重复存入 |

## 六、实证回归索引

| 会话 | 暴露问题 | 修复 |
|---|---|---|
| cv-152 | 指令落 LLM 引用 v1 死契约死胡同；无卡片动作 | 指令直通 + 契约单源 + 回执卡 |
| cv-153 | ready→任务卡断链；幽灵任务；泵卡死；cline 指定失效 | /执行 直通桥；guard-repair 守门；泵主循环调度+恢复；执行器单源 |
| cv-154/156 | 错误零反馈；流式通道停用两天(`_req_chat_stream` 函数体丢失) | turnError 落库全文回传；流式入口恢复+回归锁 |
| cv-157 | `_ws_send` 幻影引用 NameError | 幻影清扫（5 处）+ AST 扫描回归 |
| cv-158 | cline-sdk 启动即失败(空 model) | 默认执行器 id/配置同源 + hint 透传补 models 等 |

### 结构化问询卡(cv-247, 2026-09-23)

- **choices 卡=可交互选项一等实体**(卡片词汇表成员, collab/cards 单源):
  三源汇入同一卡型——①模型 ```choices 显式围栏(不进 json 候选扫描);
  ②GU present-options 候选(确定性落卡, fingerprint=candidates); ③
  clarify-first 策略问题集(开放题组, fingerprint=strategy:<key>, 同源
  原位更新单锚位)。
- **通用性约束**: 问题自由度不设模板(最小可渲染校验 fail-soft, 坏载荷
  不落卡正文保留); 开放题与选择题同卡混排(无 options=纯输入组)。
- **交互模型**: 每题三态(点选/自定义恒驻/跳过显式表达「弃权也是答案」);
  全局补充恒在; 模板可整体弃用——对话输入区自由回复(发送后卡片置已答)。
- **回复=普通文本消息**(组装「1: X， 2: 跳过（由你决定）—— 补充」)走既有
  发送通道, 与手打等价——GU/执法点/澄清续答面(clarify_pending)全部照旧,
  零新协议。
- choices 交互卡**非实体写卡**(不落 Requirements/Tasks)——不经 GU 写权
  验权(执法点管「写实体权力」), 每回合最多 1 张。

## 澄清答复与围栏代落(cv-246, 2026-09-23)

- **澄清答复消解**: 澄清在飞=焦点栈 clarify_pending 帧(回合产物 meta.guAction
  派生, 零写点)→ 答复轮无行动信号时消解到续答面(continuation, req.propose
  可达)——「全部确认」等任意自然语言答复均可立卡; L0 确定性命中优先。
- **围栏代落=执法点统一**: 正文 JSON 载荷与工具轮 tool_calls 同一验权关卡
  (GU allowed_tools); 纯读面不代落(载荷原文保留+rejected 遥测); 归属由内容
  schema 判别(规约字段→req.propose, 任务形态→task.propose); 代落成功剥载荷
  零通知(卡即回执)。详见 goal-understanding-2609「回合权力模型」。

## 信息流组织(批戊同批: 计划进度锚 + 消息降噪)

- **进度锚(L3)**: 计划总览卡(kind=taskPlan)按 requirementId **单卡原位更新**
  ——每步完成/预填刷新为 ✅/➡️/❌/⬚ 进度视图, N 步计划信息流只占 1 个锚位;
  独立「➡️ 已预填」receipt 退役(状态并入锚, L1①)
- **卡尾分叉(L1④)**: 计划步骤卡尾精简为「待确认执行」(流转说明归进度锚),
  独立任务卡保留完整指引
- **中文标题(L1③)**: 拆步 prompt 约束 title 简体中文(≤16 字动宾短语)
- **诊断三分态(L1⑥)**: /执行 遇已存计划 → 待确认/失败/依赖未满分类提示
  (步骤态读绑定任务行)
- **L2 核查结论**: task_status 状态卡原位更新(cv-203/land_status upsert)已
  健康工作——「双 ✅」中状态卡是原位变形非新增行; done 态统计卡保留
  (耗时/变更数), task_done 长报告为内容回执(设计如此, 不混流)

### 焦点栈(工作记忆/情景记忆显式化, 批戊 2026-09-22)

直通判别从"词表直判动作"升级为三层模型：**词表定意图**(`match_imperative`
五原语: execute/confirm/continue/retry/extract) → **焦点定指代**
(`governance/focus.build_focus` 派生栈帧投影: task_input_wait > task_running >
plan_step_ready > task_confirm > spec_ready > reviewing, 同级时间就近) →
**实体定状态**(任务/需求/计划行, 焦点栈零新存储零写点, 每回合重算)。
消费点: 直通分派(resolve_intent 单一矩阵, cv-241「继续执行」病灶根治)、
GU 事实面(focus.phase/focusTop)、flow_hints 帧计数、相位派生单源
(flow.derive_flow_state 迁入 focus.derive_phase, flow.py 降级纯配置消费者)。
命令式 push/pop 退场: 帧生灭=谓词真伪, 实体状态迁移即进出栈(崩溃自愈,
无幽灵帧/泄漏面)。事件栈=实体时间戳近窗投影(60min/10 条), retry 指代用。
