"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import _all, _db, _delete, _fetchall_routed, _get, _insert, _row_to_api, _update

class ProjectsStore:
    TABLE = "arch_projects"

    @classmethod
    def all(cls):
        return _all(cls.TABLE)

    @classmethod
    def get(cls, project_id: str):
        return _get(cls.TABLE, project_id)

    @classmethod
    def get_active(cls) -> Optional[dict]:
        row = _db().fetchone(
            f"SELECT * FROM {cls.TABLE} WHERE active = 1 ORDER BY updated_at DESC LIMIT 1"
        )
        return _row_to_api(row) if row else None

    @classmethod
    def get_by_root(cls, root: str) -> Optional[dict]:
        """按工作目录(root_path)查项目(URL ?root= 解析)。"""
        row = _db().fetchone(
            f"SELECT * FROM {cls.TABLE} WHERE root_path = ? ORDER BY updated_at DESC LIMIT 1",
            (root,),
        )
        return _row_to_api(row) if row else None

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def upsert(cls, project_id: str, data: dict) -> dict:
        """按 id 存在则更新、否则插入(URL 绑定登记用，避免重复绑定 UNIQUE 冲突)。"""
        existing = _get(cls.TABLE, project_id)
        if existing:
            _update(cls.TABLE, project_id, data)
            return {**existing, **data}
        _insert(cls.TABLE, {**data, "id": project_id})
        return {**data, "id": project_id}

    @classmethod
    def update(cls, project_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, project_id, data)

    @classmethod
    def delete(cls, project_id: str) -> bool:
        return _delete(cls.TABLE, project_id)




class RequirementsStore:
    """需求登记簿 + 规约版本链真相源。

    生命周期(生命周期重构 v2):
    - status: draft(演进中) | ready(已确认可执行) | done(用户判定完结) | cancelled
    - spec_versions: append-only 版本链 [{ver, state: draft|confirmed|superseded,
      snapshot, source, reason, createdAt}], 留最近 8 版
    - done_mark/done_at: 用户完成判定(裁决: completed 由用户判定, 无系统触发器)
    - owner_conv: 演进所有权会话(其他会话只读引导)
    """

    TABLE = "arch_requirements"
    MAX_VERSIONS = 8

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="updated_at DESC")

    @classmethod
    def get(cls, req_id: str):
        return _get(cls.TABLE, req_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, req_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, req_id, data)

    @classmethod
    def delete(cls, req_id: str) -> bool:
        """删除需求(级联删除会话时清理孤儿提案用; 版本链随行内 JSON 一并销毁)。"""
        return _delete(cls.TABLE, req_id)

    # ── 规约版本链 ──

    @classmethod
    def spec_versions(cls, req_id: str) -> list:
        row = cls.get(req_id) or {}
        v = row.get("specVersions")
        return v if isinstance(v, list) else []

    @classmethod
    def spec_active(cls, req_id: str) -> Optional[dict]:
        """当前生效版本(active_ver 指针)。"""
        av = int((cls.get(req_id) or {}).get("activeVer") or 0)
        for v in cls.spec_versions(req_id):
            if v.get("ver") == av:
                return v
        return None

    @classmethod
    def spec_append(cls, req_id: str, snapshot: dict, *, actor: str = "user",
                    conv_id: str = "", reason: str = "") -> dict:
        """追加新 draft 版本(append-only)。旧 active 未 superseded 的 confirmed/draft
        版本保持原状态——superseded 只在新版本被 confirm 时统一收口(隐式废弃)。
        """
        import json as _json
        import time as _t
        versions = cls.spec_versions(req_id)
        ver = max([int(v.get("ver") or 0) for v in versions] or [0]) + 1
        entry = {"ver": ver, "state": "draft", "snapshot": snapshot,
                 "source": {"convId": conv_id, "actor": actor},
                 "reason": reason or "", "createdAt": int(_t.time() * 1000)}
        versions.append(entry)
        cls.update(req_id, {
            "specVersions": versions[-cls.MAX_VERSIONS:],
            "activeVer": ver,
            "status": "draft" if (cls.get(req_id) or {}).get("doneMark") != 1 else "done",
            "updatedAt": int(_t.time() * 1000)})
        return entry

    @classmethod
    def spec_confirm(cls, req_id: str) -> dict:
        """active draft → confirmed(交托门禁)。隐式废弃: 其他 confirmed 未完结版本
        → superseded。登记簿状态 → ready。
        """
        import time as _t
        row = cls.get(req_id)
        if not row:
            return {"ok": False, "error": "需求不存在"}
        versions = cls.spec_versions(req_id)
        av = int(row.get("activeVer") or 0)
        hit = False
        for v in versions:
            if v.get("ver") == av:
                if v.get("state") != "draft":
                    return {"ok": False, "error": f"当前版本 v{av} 非 draft(={v.get('state')})"}
                v["state"] = "confirmed"
                hit = True
            elif v.get("state") == "confirmed":
                v["state"] = "superseded"      # 隐式废弃(裁决: append-only 不回退)
        if not hit:
            return {"ok": False, "error": "无生效版本"}
        cls.update(req_id, {"specVersions": versions, "status": "ready",
                            "updatedAt": int(_t.time() * 1000)})
        return {"ok": True, "ver": av}

    @classmethod
    def mark_done(cls, req_id: str, done: bool = True) -> Optional[dict]:
        """用户完成判定(RQ 已完成=阶段性完结; 完成后继续=新 RQ)。"""
        import time as _t
        row = cls.update(req_id, {
            "doneMark": 1 if done else 0,
            "doneAt": int(_t.time() * 1000) if done else 0,
            "status": "done" if done else "ready",
            "updatedAt": int(_t.time() * 1000)})
        return row

    @classmethod
    def set_owner(cls, req_id: str, conv_id: str) -> None:
        if req_id and conv_id:
            try:
                cls.update(req_id, {"ownerConv": conv_id})
            except Exception:  # noqa: BLE001
                pass





