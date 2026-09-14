"""v2 统一会话: coding subagent 任务存储(arch_tasks)。

替代 conv.meta.jobs 账本——生命周期一等公民(轻门禁 pending_confirm →
running → waiting_input → 终态), 回执消息(agent=executor_type)落统一流。
"""
from __future__ import annotations

import json
import time

from .base import _all, _fetchall_routed, _get, _insert, _locate_db, _row_to_api, _update, next_id

TERMINAL_STATES = ("done", "failed", "cancelled")
ACTIVE_STATES = ("pending_confirm", "running", "waiting_input")


def _now() -> int:
    return int(time.time() * 1000)


def _loads(v):
    if isinstance(v, str):
        try:
            return json.loads(v)
        except Exception:  # noqa: BLE001
            return {}
    return v if isinstance(v, dict) else {}


class TasksStore:
    TABLE = "arch_tasks"

    @classmethod
    def create(cls, data: dict) -> dict:
        payload = {
            "id": data.get("id") or next_id("task"),
            "conversation_id": data["conversationId"],
            "project_id": data.get("projectId") or "",
            "req_id": data.get("reqId") or "",
            "title": data.get("title") or "",
            "instruction": data.get("instruction") or "",
            "status": data.get("status") or "pending_confirm",
            "executor_type": data.get("executorType") or "opencode",
            "executor_id": data.get("executorId") or "",
            "spec_ver": int(data.get("specVer") or 0),
            "runner_job_id": data.get("runnerJobId") or "",
            "session_ref": data.get("sessionRef") or "",
            "worktree": data.get("worktree") or "",
            "branch": data.get("branch") or "",
            "progress": json.dumps(data.get("progress") or {}, ensure_ascii=False),
            "result_md": data.get("resultMd") or "",
            "created_at": data.get("createdAt") or _now(),
            "updated_at": _now(),
            "finished_at": 0,
        }
        _insert(cls.TABLE, payload)
        return _row_to_api(payload)

    @classmethod
    def get(cls, task_id: str):
        row = _get(cls.TABLE, task_id)
        return _row_to_api(row) if row else None

    @classmethod
    def update(cls, task_id: str, data: dict) -> dict:
        data = dict(data)
        data["updated_at"] = _now()
        row = _update(cls.TABLE, task_id, data)
        return _row_to_api(row) if isinstance(row, dict) else (row or {})

    @classmethod
    def of_conv(cls, conv_id: str) -> list[dict]:
        """会话任务清单。库定位: 任务与会话同库——经会话行的项目路由
        (任务行 id ≠ conv_id, 不能用 _locate_db(conv_id) 直查)。"""
        from .base import _target_db
        from .conv import ConversationsStore
        conv = ConversationsStore.get(conv_id) or {}
        pid = conv.get("projectId") or ""
        try:
            db = _target_db(cls.TABLE, project_id=pid or None)
        except Exception:  # noqa: BLE001
            from .base import _db
            db = _db()
        rows = db.fetchall(
            f"SELECT * FROM {cls.TABLE} WHERE conversation_id = ? "
            "ORDER BY created_at ASC, rowid ASC",
            (conv_id,))
        return [_row_to_api(r) for r in rows]

    @classmethod
    def active_of_conv(cls, conv_id: str):
        """最新活跃任务(pending_confirm/running/waiting_input); 无则 None。"""
        for t in reversed(cls.of_conv(conv_id)):
            if (t.get("status") or "") in ACTIVE_STATES:
                return t
        return None

    @classmethod
    def delete_by_conv(cls, conv_id: str) -> None:
        """会话级联删除: 清该会话全部任务行(与会话同库)。"""
        from .base import _db, _target_db
        from .conv import ConversationsStore
        conv = ConversationsStore.get(conv_id) or {}
        pid = conv.get("projectId") or ""
        try:
            db = _target_db(cls.TABLE, project_id=pid or None)
        except Exception:  # noqa: BLE001
            db = _db()
        db.execute(f"DELETE FROM {cls.TABLE} WHERE conversation_id = ?", (conv_id,))
        db.commit()

    @classmethod
    def set_progress(cls, task_id: str, prog: dict) -> None:
        cls.update(task_id, {"progress": json.dumps(prog, ensure_ascii=False)})

    @classmethod
    def finish(cls, task_id: str, status: str, result_md: str = "") -> dict:
        return cls.update(task_id, {"status": status, "result_md": result_md,
                                    "finished_at": _now()})
