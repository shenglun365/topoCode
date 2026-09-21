"""消息卡片契约(单源) — 会话流内确定性回执卡的唯一落流出口。

## 卡类型词汇表(闭集; 新增 kind 必须先在此注册并补前端渲染分支)

| kind               | 卡       | 载荷字段                              | 前端渲染              |
|--------------------|----------|----------------------------------------|-----------------------|
| specReady          | 需求卡   | requirementId, ver, updated?, noDesign? | [一键建卡执行]        |
| task_card          | 执行卡   | taskId                                  | TaskCard(确认/停止)   |
| task_approval      | 决策卡   | taskId, approvalJobId, approvalRequestId | 批准/拒绝 + /approve  |
| task_start         | 执行回执 | taskId                                  | 文本                  |
| task_input         | 执行回执 | taskId                                  | 文本                  |
| task_done          | 执行回执 | taskId, branch                          | 文本                  |
| task_failed        | 执行回执 | taskId                                  | 文本                  |
| task_approval_done | 执行回执 | taskId                                  | 文本                  |
| task_progress      | 执行回执 | taskId                                  | 文本                  |
| turnError          | 错误卡   | —                                       | ❌ 文本(review=error) |
| digest_sent        | 转达存证 | chars                                   | 折叠卡                |
| taskPlan           | 计划卡   | requirementId, total                    | 文本(步骤清单)        |
| taskPlanDone       | 汇总回执 | requirementId, total                    | 文本(合并提醒)        |

历史遗留(仅存在于旧数据, 渲染层兼容降级, 不再产生): specCreated、guard、
specDraft、task_* 旧语义变体。

## 规范(cv-175/177 裁决)
- 卡片落流唯一入口 land(): 库路由 / reviewState / meta 序列化 / SSE 通知
  全部单点实现; 禁止再手写 append_message+meta 组合(四实现漂移是
  cv-163~177 多起事故根因)。
- kind 不在白名单 → raise ValueError(明确报错, 禁止静默降级)。
- wire 名(如 specReady)保持不变——前端与历史消息依赖, 语义重命名不做。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger("arch.collab.cards")

# ── 词汇表(wire 名 = 前端/历史契约, 不重命名) ──────────────────────────
KIND_REQUIREMENT = "specReady"
KIND_TASK_CARD = "task_card"
KIND_TASK_APPROVAL = "task_approval"
KIND_TURN_ERROR = "turnError"
KIND_DIGEST = "digest_sent"
KIND_TASK_PLAN = "taskPlan"          # 环节十四: 任务计划卡(有序步骤清单)
KIND_TASK_INPUT_ECHO = "task_input_echo"  # R4: 用户回复转达持久回执(requestId 对账)
KIND_TASK_PLAN_DONE = "taskPlanDone"  # 环节十四: 计划全部完成汇总回执
# 消息级标记(非卡片 kind): meta 布尔字段, 落流单点登记(cv-197 审计 D3)
MSG_FLAG_SYNTHETIC = "synthetic"      # 按钮触发的合成用户消息(/执行 等)——前端不回显

KIND_TASK_IGNORED = "task_ignored"    # 2026-09-20: 用户主动忽略任务卡(置灰回执)
KIND_REQ_IGNORED = "req_ignored"      # 2026-09-20: 用户主动忽略需求卡(置灰回执)
KIND_TASK_STATUS = "task_status"      # cv-203: 任务执行状态卡(同 taskId 单卡原位更新)
KIND_TASK_RECEIPTS = (
    "task_start", "task_input", "task_done", "task_failed",
    "task_approval_done", "task_progress",
)

_KNOWN_KINDS = frozenset(
    (KIND_REQUIREMENT, KIND_TASK_CARD, KIND_TASK_APPROVAL, KIND_TURN_ERROR,
     KIND_DIGEST, KIND_TASK_PLAN, KIND_TASK_PLAN_DONE, KIND_TASK_INPUT_ECHO,
     KIND_TASK_IGNORED, KIND_REQ_IGNORED, KIND_TASK_STATUS,
     *KIND_TASK_RECEIPTS))

_ERROR_REVIEW_STATE = "error"


def land(conv_id: str, text: str, kind: Optional[str] = None, *,
         role: str = "assistant", project_id: str = "", agent: str = "",
         review_state: str = "unread", **payload) -> Optional[dict]:
    """卡片/回执落流唯一入口: 落库 + reviewState + SSE 通知单点实现。

    kind: 卡类型(白名单外 raise); None = 纯文本回执(无卡)。
    **payload: 卡载荷字段(requirementId/taskId/ver/branch/chars...)
    返回落库消息行(含 id; 供调用方回指 done 事件), 失败返回 None(不阻断主流程)。
    """
    if kind is not None and kind not in _KNOWN_KINDS:
        raise ValueError(
            f"未知卡片类型 {kind!r}——必须在 collab.cards 词汇表注册后再使用")
    try:
        from ...arch_routes import store as _store
        from ...arch_routes.common import _ts
        if not project_id:
            try:
                project_id = ((_store.ConversationsStore.get(conv_id) or {})
                              .get("projectId") or "")
            except Exception:  # noqa: BLE001
                pass
        row = {
            "id": _store.next_id("m"), "conversationId": conv_id, "role": role,
            "time": _ts(), "content": text, "projectId": project_id,
            "agent": agent or "",
        }
        if kind is not None or payload:
            meta = {"kind": kind} if kind else {}
            meta.update(payload)
            row["meta"] = json.dumps(meta, ensure_ascii=False)
        _store.ConversationsStore.append_message(row)
        if review_state:
            try:
                _store.ConversationsStore.update(
                    conv_id, {"reviewState": review_state})
            except Exception:  # noqa: BLE001
                pass
        try:
            logger.info("[cards] land conv=%s kind=%s id=%s → emit conv-message",
                        conv_id, kind or "", row["id"])
            emit(conv_id, row["id"], agent=agent or "", kind=kind or "")
        except Exception:  # noqa: BLE001
            logger.exception("[cards] conv-message emit 失败 conv=%s", conv_id)
        return row
    except ValueError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[cards] 落流失败 conv=%s kind=%s: %s", conv_id, kind, e)
        return None


def land_status(conv_id: str, text: str, task_id: str, *, status: str = "",
                project_id: str = "", agent: str = "", **payload) -> Optional[dict]:
    """任务状态卡(cv-203 裁决): 状态/进度独立为专用消息, 同 taskId 单卡。

    首次落新卡(kind=task_status); 之后原位 UPDATE 同一行(不追加新消息,
    进度不刷屏)——定位与改写同库连接(update_message_by_meta, 防跨库路由
    漂移); 读侧经 SSE conv-message 通知刷新。失败返回 None(不阻断)。"""
    try:
        from ...arch_routes import store as _store
        upd = _store.ConversationsStore.update_message_by_meta(
            conv_id, {"kind": KIND_TASK_STATUS, "taskId": task_id},
            {"content": text, "meta": {"status": status, **payload},
             "time": int(__import__("time").time() * 1000)})
        if upd:
            try:
                emit(conv_id, upd["id"],
                     agent=agent or "", kind=KIND_TASK_STATUS)
            except Exception:  # noqa: BLE001
                pass
            return upd
        return land(conv_id, text, kind=KIND_TASK_STATUS, role="assistant",
                    project_id=project_id, agent=agent, taskId=task_id,
                    status=status, **payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("[cards] 状态卡落流失败 conv=%s task=%s: %s",
                       conv_id, task_id, e)
        return None


def emit(conv_id: str, msg_id: str, agent: str = "", kind: str = "") -> None:
    """SSE conv-message 通知(前端按会话刷新 → 卡片即时渲染)。测试可 patch。"""
    from .sse import emit as _emit
    _emit("conv-message", conv_id, msgId=msg_id, agent=agent, kind=kind)
