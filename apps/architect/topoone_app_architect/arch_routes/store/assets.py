"""K2 知识资产存储(arch_assets)——任务回执/里程碑/人工与 LLM 资产沉淀。

五类词汇(v2-todo P1): requirement(需求表格)/todo(待办)/plan(执行快照·任务回执)/
data_asset/analysis(里程碑报告等分析产物)。source 标写入方:
manual|llm|task_receipt|milestone|verify。
"""
from __future__ import annotations

import time

from .base import (_all, _delete, _get, _insert, _row_to_api, _update,
                   next_id)

ASSET_KINDS = ("requirement", "todo", "plan", "data_asset", "analysis")
ASSET_SOURCES = ("manual", "llm", "task_receipt", "milestone", "verify")


def _now() -> int:
    return int(time.time() * 1000)


class AssetsStore:
    TABLE = "arch_assets"

    @classmethod
    def create(cls, data: dict) -> dict:
        kind = data.get("kind") or "analysis"
        if kind not in ASSET_KINDS:
            raise ValueError(f"未知资产类别: {kind!r} (合法: {ASSET_KINDS})")
        payload = {
            "id": data.get("id") or next_id("asset"),
            "conversation_id": data.get("conversationId") or "",
            "project_id": data.get("projectId") or "",
            "req_id": data.get("reqId") or "",
            "task_id": data.get("taskId") or "",
            "kind": kind,
            "title": data.get("title") or "",
            "content": data.get("content") or "",
            "source": data.get("source") or "manual",
            "status": data.get("status") or "active",
            "created_at": data.get("createdAt") or _now(),
            "updated_at": _now(),
        }
        import json as _json
        payload["meta"] = _json.dumps(data.get("meta") or {}, ensure_ascii=False)
        _insert(cls.TABLE, payload)
        return _row_to_api(payload)

    @classmethod
    def get(cls, asset_id: str):
        row = _get(cls.TABLE, asset_id)
        return _row_to_api(row) if row else None

    @classmethod
    def update(cls, asset_id: str, data: dict) -> Optional[dict]:
        data = dict(data)
        data["updatedAt"] = _now()
        if "kind" in data and data["kind"] not in ASSET_KINDS:
            raise ValueError(f"未知资产类别: {data['kind']!r}")
        _update(cls.TABLE, asset_id, data)
        return cls.get(asset_id)

    @classmethod
    def delete(cls, asset_id: str) -> bool:
        return _delete(cls.TABLE, asset_id)

    @classmethod
    def of_conv(cls, conv_id: str, kind: str = "", q: str = "",
                limit: int = 100) -> list:
        """会话内资产清单（新→旧），kind 过滤 + 标题/正文子串检索。"""
        rows = _all(cls.TABLE, order_by="created_at DESC, id DESC")
        out = []
        ql = (q or "").lower()
        for row in rows:
            api = _row_to_api(row)
            if conv_id and (api.get("conversationId") or "") != conv_id:
                continue
            if kind and api.get("kind") != kind:
                continue
            if ql and ql not in (api.get("title") or "").lower() \
                    and ql not in (api.get("content") or "").lower():
                continue
            out.append(api)
            if len(out) >= max(1, int(limit)):
                break
        return out
