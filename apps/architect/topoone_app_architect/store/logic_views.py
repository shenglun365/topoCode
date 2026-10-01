"""逻辑视图存储（arch_logic_views 表）。

逻辑资产 = 视图类型存在（非提取产出的资产行）：跨文件跨组件的业务逻辑链条。
- core_ids：核心(种子)实现资产——分析起点，非分析范围；
- member_ids：成员全集 = 核心 + agent 沿调用依赖边拓展；
- summary：LLM 文字概括（analyze 作业生成/刷新）；
- source：extract(提取时 LLM 归纳) | manual(手动新建)；
- fingerprint：name+sorted(members) 指纹——提取重跑时 upsert 判重。
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import List, Optional

from .base import _delete, _fetchall_routed, _get, _insert, _row_to_api, _update, next_id

TABLE = "arch_logic_views"


def _now() -> int:
    return int(time.time() * 1000)


def fingerprint_of(name: str, member_ids: List[str]) -> str:
    return hashlib.sha1(f"{name}|{','.join(sorted(member_ids))}".encode()).hexdigest()[:24]


class LogicViewsStore:
    """arch_logic_views CRUD。"""

    @classmethod
    def create(cls, project_id: str, name: str, core_ids: List[str],
               member_ids: Optional[List[str]] = None, *,
               summary: str = "", source: str = "manual") -> dict:
        now = _now()
        members = list(dict.fromkeys([*(core_ids or []), *(member_ids or [])]))
        row = {
            "id": next_id("lv"), "projectId": project_id,
            "name": name or "", "coreIds": json.dumps(core_ids or [], ensure_ascii=False),
            "memberIds": json.dumps(members, ensure_ascii=False),
            "summary": summary or "", "source": source or "manual",
            "fingerprint": fingerprint_of(name or "", members),
            "createdAt": now, "updatedAt": now,
        }
        _insert(TABLE, row)
        return cls.get(row["id"]) or row

    @classmethod
    def get(cls, view_id: str) -> Optional[dict]:
        row = _get(TABLE, view_id)
        return _row_to_api(row) if row else None

    @classmethod
    def update(cls, view_id: str, data: dict) -> Optional[dict]:
        payload = {k: v for k, v in data.items() if k in (
            "name", "coreIds", "memberIds", "summary", "fingerprint")}
        if not payload:
            return cls.get(view_id)
        payload["updatedAt"] = _now()
        _update(TABLE, view_id, payload)
        return cls.get(view_id)

    @classmethod
    def delete(cls, view_id: str) -> bool:
        return _delete(TABLE, view_id)

    @classmethod
    def list(cls, project_id: str, *, limit: int = 200) -> List[dict]:
        rows, _ = _fetchall_routed(
            TABLE,
            f"SELECT * FROM {TABLE} WHERE project_id = ? "
            f"ORDER BY updated_at DESC LIMIT ?",
            (project_id, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def by_fingerprint(cls, project_id: str, fingerprint: str) -> Optional[dict]:
        rows, _ = _fetchall_routed(
            TABLE,
            f"SELECT * FROM {TABLE} WHERE project_id = ? AND fingerprint = ? LIMIT 1",
            (project_id, fingerprint), project_id or None)
        return _row_to_api(rows[0]) if rows else None

    @classmethod
    def delete_many(cls, project_id: str, view_ids: List[str]) -> int:
        n = 0
        for vid in view_ids:
            if _delete(TABLE, vid):
                n += 1
        return n
