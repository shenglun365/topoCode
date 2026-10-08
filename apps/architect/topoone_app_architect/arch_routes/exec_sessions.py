"""执行器会话档案 REST(2610 执行器会话拓展 B2)——会话浏览器数据面。

数据源: arch_exec_events 留痕(B1, architect 自持) + arch_tasks 关联补全
(标题/执行器/需求/会话)。live 跟进 = FE ?since= 增量轮询(MVP)。
"""
from __future__ import annotations

from fastapi import APIRouter

from ..common import err, ok

router = APIRouter()


def _enrich(rows: list) -> list:
    """会话行 + 任务关联(内存匹配, 本地量级)。"""
    by_job = {}
    try:
        from ..store.base import _db, _scan_dbs
        for db in [_db(), *_scan_dbs()]:
            tr = db.fetchall(
                "SELECT id, title, executor_type, conversation_id, req_id,"
                " session_ref, status, runner_job_id FROM arch_tasks"
                " WHERE runner_job_id IS NOT NULL AND runner_job_id != ''") or []
            for t in tr:
                by_job.setdefault(t["runner_job_id"], t)
    except Exception:  # noqa: BLE001
        pass
    out = []
    for r in rows:
        t = by_job.get(r["jobId"]) or {}
        out.append({**r,
                    "taskId": t.get("id") or "",
                    "title": t.get("title") or "",
                    "executorType": t.get("executor_type") or "",
                    "conversationId": t.get("conversation_id") or "",
                    "reqId": t.get("req_id") or "",
                    "sessionRef": t.get("session_ref") or "",
                    "taskStatus": t.get("status") or ""})
    return out


@router.get("/arch/exec-sessions")
async def list_sessions(limit: int = 100):
    """会话档案列表(按首事件时间倒序)。"""
    from ..store import exec_events
    return ok(_enrich(exec_events.sessions(limit)))


@router.get("/arch/exec-sessions/{job_id}/events")
async def list_events(job_id: str, since: int = 0, limit: int = 2000):
    """单会话事件流(?since= 增量; seq 升序)。"""
    from ..store import exec_events
    evs = exec_events.events_of(job_id, since_seq=since, limit=limit)
    if not evs and since == 0:
        # 无留痕(存量会话/未过泵) — 明确空态而非 404(浏览器区分显示)
        return ok({"events": [], "empty": True})
    return ok({"events": evs, "empty": False})
