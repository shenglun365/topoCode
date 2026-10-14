"""W6 资产存储（2610-B1）——arch_assets 表存取（D-1 裁决：表为真相源）。

kind 维度承载 v2-todo P1 五类预留；本批消费 skill 型（payload:
{route_hint, child_registry[], instructions_md}）。同名(项目+kind)upsert
覆盖；skills 目录解析（表覆盖内置 _ARCH_SKILLS 同名项）在 sem/skill_catalog。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from .base import _now_ms, _fetchall_routed, next_id


def _now() -> int:
    return _now_ms()


class ArchAssetsStore:
    TABLE = "arch_assets"

    @classmethod
    def _row_api(cls, r: dict) -> dict:
        try:
            payload = json.loads(r.get("payload") or "{}")
        except Exception:  # noqa: BLE001
            payload = {}
        return {"id": r.get("id"), "projectId": r.get("project_id") or "",
                "kind": r.get("kind") or "", "name": r.get("name") or "",
                "description": r.get("description") or "", "payload": payload,
                "enabled": bool(r.get("enabled")),
                "createdAt": r.get("created_at") or 0,
                "updatedAt": r.get("updated_at") or 0}

    @classmethod
    def upsert(cls, data: dict) -> dict:
        from .. import ctx as _ctx
        pid = str(data.get("projectId") or data.get("project_id")
                  or _ctx.get_project() or "")
        kind = str(data.get("kind") or "skill")
        name = str(data.get("name") or "").strip()
        if not name:
            raise ValueError("name required")
        payload = data.get("payload") or {}
        if not isinstance(payload, dict):
            raise ValueError("payload must be object")
        db = _ctx.db()
        row = db.execute(
            "SELECT id FROM arch_assets WHERE project_id=? AND kind=? AND name=?",
            (pid, kind, name)).fetchone()
        now = _now()
        if row:
            db.execute(
                "UPDATE arch_assets SET description=?, payload=?, enabled=?, "
                "updated_at=? WHERE id=?",
                (str(data.get("description") or ""),
                 json.dumps(payload, ensure_ascii=False),
                 1 if data.get("enabled", True) else 0, now, row[0]))
            aid = row[0]
        else:
            aid = data.get("id") or next_id("as")
            db.execute(
                "INSERT INTO arch_assets (id, project_id, kind, name, description,"
                " payload, enabled, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (aid, pid, kind, name, str(data.get("description") or ""),
                 json.dumps(payload, ensure_ascii=False),
                 1 if data.get("enabled", True) else 0, now, now))
        return cls.get(aid) or {}

    @classmethod
    def get(cls, asset_id: str) -> Optional[dict]:
        from .. import ctx as _ctx
        row = _ctx.db().execute(
            f"SELECT * FROM {cls.TABLE} WHERE id=?", (asset_id,)).fetchone()
        return cls._row_api(dict(row)) if row else None

    @classmethod
    def all(cls, kind: str = "", project_id: str = "",
            limit: int = 200) -> List[dict]:
        sql = f"SELECT * FROM {cls.TABLE}"
        conds, params = [], []
        if kind:
            conds.append("kind = ?")
            params.append(kind)
        if project_id:
            conds.append("(project_id = ? OR project_id = '')")
            params.append(project_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY kind, name LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params),
                                   project_id or None)
        return [cls._row_api(r) for r in rows]

    @classmethod
    def delete(cls, asset_id: str) -> bool:
        from .. import ctx as _ctx
        cur = _ctx.db().execute(
            f"DELETE FROM {cls.TABLE} WHERE id=?", (asset_id,))
        return bool(cur.rowcount)
