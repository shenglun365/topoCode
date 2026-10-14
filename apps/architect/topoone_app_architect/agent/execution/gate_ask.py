"""脏区门禁问询(cv-282): P3 硬闸命中 → 问询卡等用户裁决, 确定性消费。

用户裁决(2026-09-27): 硬闸不再一次失败——task 置 waiting_input + choices
问询卡(选项稳定 key 单源 DIRTY_GATE_CHOICES), 用户答复经 gate-answer 端点
进 resolve_dirty_gate: 隔离重试/干净后重试/取消, 全程走 confirm_task 单源
(门禁重判, 无 bypass 通道——门禁本身不削弱)。
"""
from __future__ import annotations

from typing import Any, Dict

from ... import store
from ...store import states as ST

DIRTY_GATE_ASK = "dirty_worktree"
DIRTY_GATE_CHOICES = {
    "isolate_retry": "转会话隔离(worktree)重试——分支隔离执行，不触碰主工作区",
    "clean_retry": "我已处理完变更，重新检查并执行",
    "cancel": "取消执行",
}


def land_dirty_gate_ask(conv_id: str, task_id: str) -> None:
    """脏区问询卡落流(choices 卡, fingerprint=taskId 原位更新——重拦不刷屏)。
    meta 携 taskId+gateAsk 路由键: FE 答复经 gate-answer 端点确定性消费。"""
    from ..collab import cards as _cards
    payload = {
        "title": "任务被脏区门禁拦下——请选择处理方式",
        "groups": [{
            "label": "处理方式",
            "question": "主工作区有未提交变更（可能来自你或其它开发进程），"
                        "融合执行会互踩。如何处理？",
            "required": True,
            "options": [{"id": k, "label": v}
                        for k, v in DIRTY_GATE_CHOICES.items()],
        }],
        "note": "门禁不削弱：无跳过检查的通道；选「已处理完变更」将重新检查主工作区。",
    }
    _cards.land_choices(
        conv_id, payload,
        fingerprint=f"{DIRTY_GATE_ASK}:{task_id}",
        meta_extra={"taskId": task_id, "gateAsk": DIRTY_GATE_ASK})


def resolve_dirty_gate(task_id: str, choice_text: str) -> Dict[str, Any]:
    """脏区问询确定性消费: 用户在问询卡的答复 → 既有语义动作。

    isolate_retry → 开启会话隔离开关(conv.isolated=1)后重新 confirm;
    clean_retry → 直接重新 confirm(门禁重判, 仍脏则再问——原位更新);
    cancel → 任务取消。全程走 confirm_task 单源, 无并行 dispatch 通道。"""
    from . import dispatch as _dispatch
    task = store.TasksStore.get(task_id) or {}
    if (task.get("status") or "") != ST.TASK_WAITING_INPUT:
        return {"ok": False, "error": "task-not-waiting"}
    conv_id = str(task.get("conversationId") or "")
    text = str(choice_text or "")
    key = next((k for k, v in DIRTY_GATE_CHOICES.items() if v in text), "")
    if not key:
        return {"ok": False, "error": "unknown-choice"}
    if key == "cancel":
        store.TasksStore.finish(task_id, ST.TASK_CANCELLED,
                                "用户在脏区问询中选择取消执行。")
        _dispatch._publish_task(conv_id, store.TasksStore.get(task_id) or {})
        _dispatch._eb()._append(
            conv_id, "assistant",
            "🚫 已取消执行（脏区问询）——任务卡保留，可随时重新开始。",
            msg_meta={"kind": "task_status", "taskId": task_id,
                      "status": "cancelled"},
            project_id=(store.ConversationsStore.get(conv_id) or {})
            .get("projectId") or "")
        return {"ok": True, "action": "cancel"}
    if key == "isolate_retry":
        store.ConversationsStore.update(conv_id, {"isolated": 1})
    # confirm 对 waiting_input 幂等命中(duplicate)——用户已裁决, 翻回 saved
    # 重走 confirm 全链(门禁重判: 隔离已开/变更已处理)。
    store.TasksStore.update(task_id, {"status": ST.TASK_SAVED})
    res = _dispatch.confirm_task(task_id)
    receipt = ("🔒 已开启会话隔离开关(worktree)——重新执行。" if key == "isolate_retry"
               else "🔁 已重新检查主工作区并执行。")
    if not res.get("ok"):
        gate_hit = res.get("gateAsk") == DIRTY_GATE_ASK
        receipt += ("门禁再次拦下（主工作区仍有未提交变更）——请处理变更后重试。"
                    if gate_hit else f"仍未能启动：{str(res.get('error') or '')[:140]}")
    _dispatch._eb()._append(
        conv_id, "assistant", receipt,
        msg_meta={"kind": "task_status", "taskId": task_id},
        project_id=(store.ConversationsStore.get(conv_id) or {})
        .get("projectId") or "")
    return {"ok": bool(res.get("ok")), "action": key,
            "task": res.get("task") or {}}
