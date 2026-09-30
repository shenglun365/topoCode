"""语义作业存储（批1-3：统一异步任务表 arch_semantic_jobs）。

收编原三套 daemon（sync-extract/unowned-extract/enhance-desc）的进程内
_jobs dict 状态——持久化 + 恢复对账 + 协作式取消。表在项目库（多实例按
项目隔离，实例内统一队列）。

状态机：queued → running → done | failed | cancelled
                      └→ lost（进程重启对账：running 且非本进程 → lost）
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .base import _dumps, _fetchall_routed, _get, _insert, _row_to_api, _target_db, _to_snake, _update, next_id

TABLE = "arch_semantic_jobs"

STATES = ("queued", "running", "done", "failed", "cancelled", "lost")
_ACTIVE_STATES = ("queued", "running")

_JSON_COLS = ("scope", "progress", "stages", "result")


def _now() -> int:
    return int(time.time() * 1000)


def _norm(row: dict) -> dict:
    out = _row_to_api(row)
    for k in _JSON_COLS:
        v = out.get(k)
        if isinstance(v, str):
            try:
                out[k] = json.loads(v or ("{}" if k != "stages" else "[]"))
            except Exception:
                out[k] = {} if k != "stages" else []
    return out


class SemanticJobsStore:
    """arch_semantic_jobs CRUD + 队列查询。"""

    @classmethod
    def create(cls, project_id: str, kind: str, scope: Optional[dict] = None,
               *, llm: bool = False, stages: Optional[list] = None,
               created_by: str = "") -> dict:
        now = _now()
        row = {
            "id": next_id("sj"), "projectId": project_id, "kind": kind,
            "scope": scope or {}, "state": "queued",
            "progress": {}, "stages": stages or [], "stageIndex": 0,
            "result": {}, "llm": 1 if llm else 0, "cancelRequested": 0,
            "createdBy": created_by,
            "createdAt": now, "startedAt": 0, "finishedAt": 0, "updatedAt": now,
        }
        payload = {k: (_dumps(v) if k in _JSON_COLS else v) for k, v in row.items()}
        _insert(TABLE, payload)
        return cls.get(row["id"]) or row

    @classmethod
    def get(cls, job_id: str) -> Optional[dict]:
        row = _get(TABLE, job_id)
        return _norm(row) if row else None

    @classmethod
    def update(cls, job_id: str, data: dict) -> Optional[dict]:
        payload = {k: (_dumps(v) if k in _JSON_COLS else v) for k, v in data.items()}
        payload["updatedAt"] = _now()
        _update(TABLE, job_id, payload)
        return cls.get(job_id)

    @classmethod
    def list(cls, project_id: str, *, state: str = "", limit: int = 50) -> List[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if state in STATES:
            conds.append("state = ?")
            params.append(state)
        rows, _ = _fetchall_routed(
            TABLE,
            f"SELECT * FROM {TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY created_at DESC LIMIT ?",
            (*params, int(limit)), project_id or None)
        return [_norm(r) for r in rows]

    @classmethod
    def active(cls, project_id: str, kind: str = "") -> List[dict]:
        """项目内活跃作业（queued/running；kind 空则全部）。"""
        conds = ["project_id = ?", "state IN ('queued','running')"]
        params: list = [project_id]
        if kind:
            conds.append("kind = ?")
            params.append(kind)
        rows, _ = _fetchall_routed(
            TABLE, f"SELECT * FROM {TABLE} WHERE {' AND '.join(conds)} "
                   f"ORDER BY created_at ASC LIMIT 100",
            tuple(params), project_id or None)
        return [_norm(r) for r in rows]

    @classmethod
    def claim_next(cls, project_id: str, *, llm: bool) -> Optional[dict]:
        """取队头一个 queued 作业并置 running（FIFO；llm 选择器过滤 LLM/非 LLM 类）。

        简单 claim（单实例假设）：UPDATE where state='queued' 幂等兜底——并发 claim
        同一行时后写者覆盖 started_at，不破坏状态机（runner 单线程分派下不发生）。
        """
        conds = ["project_id = ?", "state = 'queued'", "llm = ?"]
        params: list = [project_id, 1 if llm else 0]
        rows, _ = _fetchall_routed(
            TABLE, f"SELECT * FROM {TABLE} WHERE {' AND '.join(conds)} "
                   f"ORDER BY created_at ASC LIMIT 1",
            tuple(params), project_id or None)
        if not rows:
            return None
        job = _norm(rows[0])
        cls.update(job["id"], {"state": "running", "startedAt": _now()})
        return cls.get(job["id"])

    @classmethod
    def finish(cls, job_id: str, *, state: str, result: Optional[dict] = None,
               progress: Optional[dict] = None) -> Optional[dict]:
        payload: Dict[str, Any] = {"state": state, "finishedAt": _now()}
        if result is not None:
            payload["result"] = result
        if progress is not None:
            payload["progress"] = progress
        return cls.update(job_id, payload)

    @classmethod
    def request_cancel(cls, job_id: str) -> Optional[dict]:
        return cls.update(job_id, {"cancelRequested": 1})

    @classmethod
    def recover_lost(cls, project_id: str) -> int:
        """进程启动对账：running → lost（重启后作业无痕蒸发的如实标记）。

        只对账本进程启动时刻之前的 running（无 pid 记录，按启动时间戳分界：
        started_at < boot_at 的 running 一律 lost）。
        """
        db = _target_db(TABLE, project_id)
        cur = db.execute(
            f"UPDATE {TABLE} SET state='lost', finished_at=?, updated_at=? "
            f"WHERE project_id=? AND state='running'",
            (_now(), _now(), project_id))
        db.commit()
        return cur.rowcount or 0
