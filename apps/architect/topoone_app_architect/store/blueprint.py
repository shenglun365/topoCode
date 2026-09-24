"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import _all, _db, _get, _insert, _update

class BlueprintsStore:
    TABLE = "arch_blueprints"

    @classmethod
    def get(cls, bp_id: str):
        return _get(cls.TABLE, bp_id)

    @classmethod
    def upsert(cls, bp_id: str, data: dict) -> None:
        existing = _get(cls.TABLE, bp_id)
        if existing:
            _update(cls.TABLE, bp_id, data)
        else:
            _insert(cls.TABLE, data)




class TagsStore:
    TABLE = "arch_tags"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def get(cls, tag_id: str):
        return _get(cls.TABLE, tag_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, tag_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, tag_id, data)




class CollabConfigStore:
    TABLE = "arch_collab_config"

    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        row = _db().fetchone(f"SELECT value FROM {cls.TABLE} WHERE key = ?", (key,))
        return row["value"] if row else default

    @classmethod
    def set(cls, key: str, value: str) -> None:
        _db().execute(
            f"INSERT INTO {cls.TABLE} (key, value) VALUES (?, ?) "
            f"ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        _db().commit()




class StagingScansStore:
    TABLE = "arch_staging_scans"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data




class SnapshotsStore:
    TABLE = "arch_kb_snapshots"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data



