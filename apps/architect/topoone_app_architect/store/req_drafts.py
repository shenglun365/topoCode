"""需求草稿存储（批B：arch_req_drafts 表）。

非会话模式的 AI 辅助需求文本编辑载体（需求草稿概念设计 2.3/2.5）：
- 多草稿独立管理，仅资产管理页可见；
- status: editing(可编辑) | archived(已发布只读)；
- 续写 = 复制归档草稿为新 editing 副本（parent_id 溯源）；
- last_proposed_md：最近一轮 AI 产物——未采纳也保留（UI 参考给人工修正
  文本/指令做参考，不进下一轮 AI 上下文）；采纳时拷入 content_md 并清空。
"""
from __future__ import annotations

import time
from typing import List, Optional

from .base import _delete, _fetchall_routed, _get, _insert, _row_to_api, _update, next_id

TABLE = "arch_req_drafts"


def _now() -> int:
    return int(time.time() * 1000)


class ReqDraftsStore:
    """arch_req_drafts CRUD。"""

    @classmethod
    def create(cls, project_id: str, title: str = "", content_md: str = "") -> dict:
        now = _now()
        row = {
            "id": next_id("rd"), "projectId": project_id,
            "title": title or "", "contentMd": content_md or "",
            "lastProposedMd": "", "lastProposedAt": 0,
            "status": "editing", "parentId": "",
            "publishedConvId": "", "publishedReqId": "",
            "createdAt": now, "updatedAt": now,
        }
        _insert(TABLE, row)
        return cls.get(row["id"]) or row

    @classmethod
    def get(cls, draft_id: str) -> Optional[dict]:
        row = _get(TABLE, draft_id)
        return _row_to_api(row) if row else None

    @classmethod
    def update(cls, draft_id: str, data: dict) -> Optional[dict]:
        payload = {k: v for k, v in data.items() if k in (
            "title", "contentMd", "lastProposedMd", "lastProposedAt",
            "status", "publishedConvId", "publishedReqId")}
        if not payload:
            return cls.get(draft_id)
        payload["updatedAt"] = _now()
        _update(TABLE, draft_id, payload)
        return cls.get(draft_id)

    @classmethod
    def delete(cls, draft_id: str) -> bool:
        return _delete(TABLE, draft_id)

    @classmethod
    def list(cls, project_id: str, *, limit: int = 200) -> List[dict]:
        rows, _ = _fetchall_routed(
            TABLE,
            f"SELECT * FROM {TABLE} WHERE project_id = ? "
            f"ORDER BY updated_at DESC LIMIT ?",
            (project_id, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def copy(cls, draft_id: str, *, title_suffix: str = "") -> Optional[dict]:
        """续写：归档草稿 → 新 editing 副本（parent_id 溯源；不带未采纳参考产物）。"""
        src = cls.get(draft_id)
        if not src:
            return None
        now = _now()
        row = {
            "id": next_id("rd"), "projectId": src.get("projectId") or "",
            "title": (src.get("title") or "") + title_suffix,
            "contentMd": src.get("contentMd") or "",
            "lastProposedMd": "", "lastProposedAt": 0,
            "status": "editing", "parentId": draft_id,
            "publishedConvId": "", "publishedReqId": "",
            "createdAt": now, "updatedAt": now,
        }
        _insert(TABLE, row)
        return cls.get(row["id"]) or row
