# Agent 会话流转全景（v2 统一会话）

> 状态：2026-09-15 与代码对齐（cv-152~158 实证回归后）。
> 维护约定：流转变更（直通指令/执行器选定链/泵/守卫）须同步本图。

## 一、总览流程图

```mermaid
flowchart TD
    A[用户新建会话<br/>SessionsPage / ConversationDock] --> B[WS /ws/kb-analysis<br/>bind_session 会话闸门<br/>绑定/归档闸/需求回填]
    B --> C{泵恢复<br/>running/waiting_input 任务?}
    C -->|有| C1[recover_conv_tasks<br/>runner 实际态核对收尾/重挂泵]
    C -->|无| D
    C1 --> D[用户消息落库]

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
    G1 -->|chat| H

    H[architect 回合<br/>能力文档+挡位指引 strict/quick<br/>+skill 文档] --> I{LLM 通道}
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
