"""执行器会话档案 REST(2610 执行器会话拓展 B2)——会话浏览器数据面。

数据源: arch_exec_events 留痕(B1, architect 自持) + arch_tasks 关联补全
(标题/执行器/需求/会话)。live 跟进 = FE ?since= 增量轮询(MVP)。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..common import err, ok

router = APIRouter()


def _enrich(rows: list) -> list:
    """会话行 + 任务关联 + 主会话定位 + 关联会话标题/首消息摘要(内存匹配, 本地量级)。

    主会话定位与 tracking 同口径(store/tracking.py _resolve_main):
    沿 conversation_id → parent_conv_id 上溯一层到主会话(coding 子会话
    恒一层)。会话中心列表/需求跟踪按 mainConvId 分组与筛选;
    convTitle/convPreview = 关联会话自身标题, 缺标题回退首条用户消息摘要。
    """
    by_job: dict = {}
    conv_by_id: dict = {}
    preview_by_conv: dict = {}
    try:
        from ..store.base import _db, _scan_dbs
        for db in [_db(), *_scan_dbs()]:
            tr = db.fetchall(
                "SELECT id, title, executor_type, conversation_id, req_id,"
                " session_ref, status, runner_job_id FROM arch_tasks"
                " WHERE runner_job_id IS NOT NULL AND runner_job_id != ''") or []
            for t in tr:
                by_job.setdefault(t["runner_job_id"], t)
            cv = db.fetchall(
                "SELECT id, title, parent_conv_id FROM arch_conversations") or []
            for c in cv:
                conv_by_id.setdefault(c["id"], c)
            # 首条用户消息摘要(独立收集: 消息与会话行可能落不同库位)
            pv = db.fetchall(
                "SELECT m.conversation_id, m.content FROM arch_conversation_messages m"
                " WHERE m.role = 'user' AND m.rowid = ("
                "  SELECT m2.rowid FROM arch_conversation_messages m2"
                "  WHERE m2.conversation_id = m.conversation_id AND m2.role = 'user'"
                "  ORDER BY m2.time ASC, m2.rowid ASC LIMIT 1)") or []
            for p in pv:
                preview_by_conv.setdefault(p["conversation_id"], str(p["content"] or ""))
    except Exception:  # noqa: BLE001
        pass
    out = []
    for r in rows:
        t = by_job.get(r["jobId"]) or {}
        cid = t.get("conversation_id") or ""
        conv = conv_by_id.get(cid) or {}
        # 会话行缺失(已删/历史孤儿) → 空定位(前端归入「未关联主会话」组)
        main_id = (str(conv.get("parent_conv_id") or "") or cid) if conv else ""
        main_conv = conv_by_id.get(main_id) or {}
        out.append({**r,
                    "taskId": t.get("id") or "",
                    "title": t.get("title") or "",
                    "executorType": t.get("executor_type") or "",
                    "conversationId": cid,
                    "reqId": t.get("req_id") or "",
                    "sessionRef": t.get("session_ref") or "",
                    "taskStatus": t.get("status") or "",
                    "mainConvId": main_id,
                    "mainConvTitle": main_conv.get("title") or "",
                    "convTitle": str(conv.get("title") or "")[:80],
                    "convPreview": preview_by_conv.get(cid, "").strip()[:80]})
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


@router.post("/arch/exec-sessions/{job_id}/input")
async def send_input(job_id: str, request: Request):
    """serve 直通作业输入转发(深链会话页输入框)——runner user_input/steer。

    delivery: steered(running 中即时插入) | queued(回合排队) | started。
    """
    from ..agent.execution import exec_bridge as eb
    data = await request.json() if request else {}
    text = str(data.get("text") or "").strip()
    if not text:
        return err(400, "text 为空")
    r = eb._client().input(job_id, text, steer=bool(data.get("steer")))
    if not r.ok:
        return err(400, r.error or "输入失败(作业已结束或 runner 不可达)")
    return ok({"delivery": r.delivery, "queued": r.queued, "reason": r.reason})


@router.post("/arch/exec-sessions/{job_id}/stop")
async def stop_job(job_id: str):
    """serve 直通作业中止转发(深链会话页「停止」)。"""
    from ..agent.execution import exec_bridge as eb
    r = eb._client().abort(job_id)
    if not r.get("ok"):
        return err(400, str(r.get("error") or "停止失败(作业已结束或 runner 不可达)"))
    return ok({"stopped": True})
