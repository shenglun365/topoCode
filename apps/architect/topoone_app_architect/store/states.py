"""实体状态词汇表(单源) — 规范化环节五。

只收**存储实体**的生命周期状态; runner 事件 wire 值(kind=done/failed/
progress 等)是执行器协议字符串, 不在此列(混用替换是事故源)。

## 需求(requirement.status) — 无草稿态(cv-175)
REQ_READY = "ready"    # 创建即 ready
REQ_DONE = "done"

## 任务(task.status)
TASK_PENDING_CONFIRM / TASK_RUNNING / TASK_WAITING_INPUT /
TASK_DONE / TASK_FAILED / TASK_CANCELLED
ACTIVE = (PENDING_CONFIRM, RUNNING, WAITING_INPUT)  # 占用互斥/可恢复

## 规约版本(specVersions[].state)
SPEC_DRAFT(遗留) / SPEC_CONFIRMED / SPEC_SUPERSEDED

## 会话(conversation.status / reviewState)
CONV_ACTIVE / CONV_ARCHIVED; reviewState: read/unread/awaiting_reply/error
"""
from __future__ import annotations

# 需求
REQ_DRAFT = "draft"
REQ_READY = "ready"
REQ_DONE = "done"
REQ_CANCELLED = "cancelled"
REQ_IGNORED = "ignored"     # 用户主动忽略(软删置灰)
REQ_OPEN_STATES = (REQ_DRAFT, REQ_READY)

# 任务
TASK_SAVED = "saved"        # 默认保存(2026-09-20 产品裁决): 建卡即登记, 手动触发执行
TASK_PENDING_CONFIRM = "pending_confirm"   # 存量确认门禁态(仅存量卡, 新卡不再产生)
TASK_RUNNING = "running"
TASK_WAITING_INPUT = "waiting_input"
TASK_DONE = "done"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"
TASK_IGNORED = "ignored"    # 用户主动忽略(软删终态: 流内置灰, 可追溯)
ACTIVE_STATES = (TASK_PENDING_CONFIRM, TASK_RUNNING, TASK_WAITING_INPUT)

# 规约版本
SPEC_DRAFT = "draft"
SPEC_CONFIRMED = "confirmed"
SPEC_SUPERSEDED = "superseded"

# 会话
CONV_ACTIVE = "active"
CONV_ARCHIVED = "archived"

# 会话流程相位(conversations.flow_state) — 派生物化缓存(derive-on-write)。
# 真相源 = 领域实体(需求版本链/arch_tasks); 相位只经领域事件 recompute 迁移,
# 无直改入口(防双源, meta.jobs 清退教训)。词表冻结 6 态——新增相位须裁决登记;
# 行为拓展走 agent/governance/flow.py 注册面(guard/hint/overlay), 不加状态。
FLOW_FREE = "free"                  # 空闲/自由对话(无占用事实)
FLOW_CLARIFYING = "clarifying"      # 澄清中(meta.specDraft 草稿卡未兑现)
FLOW_ARMED = "armed"                # 任务卡待执行(saved/pending_confirm, 无运行占用)
FLOW_EXECUTING = "executing"        # 执行中(running/waiting_input 任务存在)
FLOW_REVIEWING = "reviewing"        # 待验收(未消化 done 回执, 无运行/待执行卡)
FLOW_INTERRUPTED = "interrupted"    # 异常中断(stale 且自动恢复失败; 仅显式恢复退出)
FLOW_PHASES = (FLOW_FREE, FLOW_CLARIFYING, FLOW_ARMED, FLOW_EXECUTING,
               FLOW_REVIEWING, FLOW_INTERRUPTED)
# 派生优先级(interrupted 粘滞不参与 derive, 由自愈路径显式置位/解除)
FLOW_PRIORITY = (FLOW_EXECUTING, FLOW_ARMED, FLOW_REVIEWING, FLOW_CLARIFYING,
                 FLOW_FREE)

# 任务安全等级(arch_tasks.safety_class) — 三值小轴: 影响互斥/worktree/门禁。
# 工作类型(分析/文档/部署…)是开放标签(work_tags), 不设枚举——只有安全语义
# 需要小而稳的刻度。
SAFETY_READONLY = "readonly"        # 只读(豁免互斥; 强制就地; 轻量验收)
SAFETY_MUTATING = "mutating"        # 写入(默认; 互斥参与; worktree 跟随会话隔离开关)
SAFETY_HIGH_STAKES = "high-stakes"  # 高风险(互斥参与; worktree 强制; 合并 precheck 显式)
SAFETY_CLASSES = (SAFETY_READONLY, SAFETY_MUTATING, SAFETY_HIGH_STAKES)
DEFAULT_SAFETY_CLASS = SAFETY_MUTATING

# 需求跟踪台账(tracking.state)
TRACK_RUNNING = "running"
TRACK_WAITING = "waiting"
TRACK_DONE = "done"
TRACK_FAILED = "failed"
TRACK_CANCELLED = "cancelled"
TRACK_TERMINAL = (TRACK_DONE, TRACK_FAILED, TRACK_CANCELLED)
# 台账角色词汇(creator/assignee/waiting_for 共用; 实例粒度走 *_id)
TRACK_ROLES = ("user", "architect", "coding")
