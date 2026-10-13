"""执行器会话事件留痕(2610 执行器会话拓展 B1)——architect 自持。

pumps.run_event_pump 统一双写: JobEvent 原始流按 job_id+seq 落库
(INSERT OR IGNORE 幂等, 订阅/校准双路重放安全); 会话浏览器(B2/B3)与
审计回溯的唯一数据源。text 截断 2000 防大行; usage/progress 等高频轻事件
全存(本地部署量级可接受, 预留 delete_before 清理钩子)。
"""
from __future__ import annotations

import json
from typing import List, Optional

from .base import _db

_TEXT_KEEP = 2000
_SKIP_KEYS = ("seq", "kind", "text", "ts")


def record_event(job_id: str, ev: dict) -> None:
    """单事件留痕(幂等; 任何失败静默——留痕不得影响泵主链)。"""
    try:
        db = _db()
        seq = int(ev.get("seq") or 0)
        if not job_id or seq <= 0:
            return
        text = str(ev.get("text") or "")[:_TEXT_KEEP]
        extra = {k: v for k, v in ev.items() if k not in _SKIP_KEYS}
        db.execute(
            "INSERT OR IGNORE INTO arch_exec_events"
            " (job_id, seq, kind, text, extra, ts) VALUES (?,?,?,?,?,?)",
            (job_id, seq, str(ev.get("kind") or ""), text,
             json.dumps(extra, ensure_ascii=False)[:8000] if extra else None,
             int(ev.get("ts") or 0) or _now()))
        db.commit()
    except Exception:  # noqa: BLE001 — 留痕失败不阻塞泵
        pass


def _now() -> int:
    import time
    return int(time.time() * 1000)


def events_of(job_id: str, since_seq: int = 0,
              limit: int = 2000) -> List[dict]:
    db = _db()
    rows = db.fetchall(
        "SELECT seq, kind, text, extra, ts FROM arch_exec_events"
        " WHERE job_id=? AND seq>? ORDER BY seq LIMIT ?",
        (job_id, int(since_seq), int(limit)))
    out = []
    for r in rows or []:
        ev = {"seq": r["seq"], "kind": r["kind"], "text": r["text"],
              "ts": r["ts"]}
        if r["extra"]:
            try:
                ev.update(json.loads(r["extra"]))
            except Exception:  # noqa: BLE001
                pass
        out.append(ev)
    return out


def sessions(limit: int = 100) -> List[dict]:
    """会话档案聚合(job 维度: 事件数/起止/终态)。

    2610 F3: last_status 纳入 input_required/stopped——chat 回合制作业
    停在 input_required 保活, 只认 done/failed/finished 时行几乎恒空态。
    2610 B1: conv_hint = 泵留痕 extra.conversationId(单源锚点, 2610 起
    新事件自带; 历史行 NULL → _enrich 走回退链)。"""
    db = _db()
    rows = db.fetchall(
        "SELECT job_id, COUNT(*) n, MIN(ts) first_ts, MAX(ts) last_ts,"
        " (SELECT kind FROM arch_exec_events e2 WHERE e2.job_id=e1.job_id"
        "   AND e2.kind IN ('done','failed','finished','input_required','stopped')"
        "   ORDER BY seq DESC LIMIT 1) last_status,"
        " (SELECT json_extract(extra,'$.conversationId') FROM arch_exec_events e3"
        "   WHERE e3.job_id=e1.job_id AND extra LIKE '%conversationId%'"
        "   ORDER BY seq DESC LIMIT 1) conv_hint"
        " FROM arch_exec_events e1 GROUP BY job_id"
        " ORDER BY first_ts DESC LIMIT ?", (int(limit),))
    out = []
    for r in rows or []:
        hint = ""
        try:
            hint = str(r["conv_hint"] or "")
        except Exception:  # noqa: BLE001 — json1 不可用/脏行 → 无 hint
            hint = ""
        out.append({"jobId": r["job_id"], "eventCount": r["n"],
                    "firstTs": r["first_ts"], "lastTs": r["last_ts"],
                    "lastStatus": r["last_status"] or "",
                    "convHint": hint})
    return out


def delete_before(ts: int) -> int:
    """清理钩子: 删除 ts 之前的事件(保留策略由调用方定)。"""
    db = _db()
    cur = db.execute("DELETE FROM arch_exec_events WHERE ts < ?", (int(ts),))
    db.commit()
    return cur.rowcount or 0


def delete_by_jobs(job_ids: list) -> int:
    """按作业清单删除留痕(会话级联删除时清执行器会话档案, 防孤儿行)。"""
    ids = [str(j).strip() for j in (job_ids or []) if str(j).strip()]
    if not ids:
        return 0
    db = _db()
    ph = ",".join("?" * len(ids))
    cur = db.execute(f"DELETE FROM arch_exec_events WHERE job_id IN ({ph})", ids)
    db.commit()
    return cur.rowcount or 0
