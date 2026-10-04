"""分区表存储(D3): arch_graph_partitions 按 project+head 版本化提案/状态。"""
import json
import time
from typing import List, Optional

from .base import _fetchall_routed, _to_camel


def _now() -> int:
    return int(time.time() * 1000)


def _db(project_id: str):
    """分区表为项目级(arch_graph_partitions ∈ PROJECT_TABLES) → 项目子库。"""
    from .. import ctx
    return ctx.project_db(project_id) if project_id else None


def _to_api(row: dict) -> dict:
    out = {}
    for k, v in row.items():
        if k in ("files", "langs") and isinstance(v, str):
            try:
                v = json.loads(v)
            except (TypeError, ValueError):
                pass
        out[_to_camel(k)] = v
    return out


class PartitionStore:

    @classmethod
    def replace_plan(cls, project_id: str, head: str, partitions: List[dict]) -> int:
        """整版重灌提案(state=proposed)。partitions: [{idx, files, langs, est_symbols, reason}]。"""
        db = _db(project_id)
        if db is None:
            return 0
        db.execute("DELETE FROM arch_graph_partitions WHERE project_id=? AND head=?",
                   (project_id, head))
        now = _now()
        for p in partitions:
            db.execute(
                "INSERT INTO arch_graph_partitions (project_id, head, idx, files, langs,"
                " est_symbols, reason, state, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,'proposed',?,?)",
                (project_id, head, p["idx"], json.dumps(p.get("files") or []),
                 json.dumps(p.get("langs") or []), int(p.get("est_symbols") or 0),
                 p.get("reason") or "", now, now))
        db.commit()
        return len(partitions)

    @classmethod
    def list_rev(cls, project_id: str, head: str) -> List[dict]:
        db = _db(project_id)
        if db is None:
            return []
        rows, _ = _fetchall_routed(
            "arch_graph_partitions",
            "SELECT * FROM arch_graph_partitions WHERE project_id=? AND head=? ORDER BY idx",
            (project_id, head), project_id or None)
        return [_to_api(r) for r in (rows or [])]

    @classmethod
    def get(cls, project_id: str, head: str, idx: int) -> Optional[dict]:
        db = _db(project_id)
        if db is None:
            return None
        rows, _ = _fetchall_routed(
            "arch_graph_partitions",
            "SELECT * FROM arch_graph_partitions WHERE project_id=? AND head=? AND idx=?",
            (project_id, head, idx), project_id or None)
        rows = rows or []
        return _to_api(rows[0]) if rows else None

    @classmethod
    def set_state(cls, project_id: str, head: str, idx: int, state: str) -> None:
        db = _db(project_id)
        if db is None:
            return
        db.execute("UPDATE arch_graph_partitions SET state=?, updated_at=?"
                   " WHERE project_id=? AND head=? AND idx=?",
                   (state, _now(), project_id, head, idx))
        db.commit()

    @classmethod
    def counts_by_state(cls, project_id: str, head: str) -> dict:
        out: dict = {}
        for r in cls.list_rev(project_id, head):
            out[r["state"]] = out.get(r["state"], 0) + 1
        return out
