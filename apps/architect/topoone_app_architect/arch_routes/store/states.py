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
REQ_OPEN_STATES = (REQ_DRAFT, REQ_READY)

# 任务
TASK_PENDING_CONFIRM = "pending_confirm"
TASK_RUNNING = "running"
TASK_WAITING_INPUT = "waiting_input"
TASK_DONE = "done"
TASK_FAILED = "failed"
TASK_CANCELLED = "cancelled"
ACTIVE_STATES = (TASK_PENDING_CONFIRM, TASK_RUNNING, TASK_WAITING_INPUT)

# 规约版本
SPEC_DRAFT = "draft"
SPEC_CONFIRMED = "confirmed"
SPEC_SUPERSEDED = "superseded"

# 会话
CONV_ACTIVE = "active"
CONV_ARCHIVED = "archived"

# 需求跟踪台账(tracking.state)
TRACK_RUNNING = "running"
TRACK_WAITING = "waiting"
TRACK_DONE = "done"
TRACK_FAILED = "failed"
TRACK_CANCELLED = "cancelled"
TRACK_TERMINAL = (TRACK_DONE, TRACK_FAILED, TRACK_CANCELLED)
# 台账角色词汇(creator/assignee/waiting_for 共用; 实例粒度走 *_id)
TRACK_ROLES = ("user", "architect", "coding")
