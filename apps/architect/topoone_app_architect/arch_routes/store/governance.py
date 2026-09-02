"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import _delete, _dumps, _fetchall_routed, _get, _insert, _locate_db, _now_ms, _row_to_api, _target_db, _update

class FrameworkConfigStore:
    """认知框架配置（版本行即变更审计；每 project 至多一行 active=1）。

    无 active 行 = 未定制 → 调用方回退默认预设 mid（不落库，首次变更时才落版本行）。
    """

    TABLE = "arch_framework_configs"

    @classmethod
    def get_active_raw(cls, project_id: str) -> Optional[dict]:
        """返回 raw 行（config 仍为 JSON 串）；无则 None。"""
        if not project_id:
            return None
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? AND active = 1 "
            f"ORDER BY version DESC LIMIT 1",
            (project_id,), project_id or None)
        return rows[0] if rows else None

    @classmethod
    def versions(cls, project_id: str, limit: int = 50) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? ORDER BY version DESC LIMIT ?",
            (project_id, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def next_version(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(version) AS v FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        v = rows[0].get("v") if rows else None
        return int(v or 0) + 1

    @classmethod
    def activate(cls, project_id: str, config: dict, change_kind: str,
                 affected: Optional[dict] = None, executed_by: str = "",
                 note: str = "") -> dict:
        """事务：旧 active 行清零 + 插入新版本行(active=1)。"""
        now = _now_ms()
        version = cls.next_version(project_id)
        row_id = f"fwc-{project_id[:8]}-{version}"
        db = _target_db(cls.TABLE, project_id=project_id)
        db.execute(
            f"UPDATE {cls.TABLE} SET active = 0 WHERE project_id = ?", (project_id,))
        db.execute(
            f"INSERT INTO {cls.TABLE} (id, project_id, version, config, change_kind, "
            f"affected_summary, executed_by, note, active, created_at) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
            (row_id, project_id, version, _dumps(config), change_kind,
             _dumps(affected or {}), executed_by, note, now))
        db.commit()
        return {"id": row_id, "projectId": project_id, "version": version,
                "config": config, "changeKind": change_kind,
                "affectedSummary": affected or {}, "executedBy": executed_by,
                "note": note, "active": 1, "createdAt": now}




class NameTombstoneStore:
    """命名墓碑（参考池）——仅服务"标准不变的代码变更"生命周期（框架作废不写墓碑 R1）。"""

    TABLE = "arch_name_tombstones"

    @classmethod
    def add(cls, project_id: str, name: str, file_path: str = "", symbol: str = "",
            source: str = "llm", reason: str = "anchor_gone",
            asset_id: str = "", note: str = "") -> dict:
        if not project_id or not name:
            return {}
        data = {"id": f"tomb-{_now_ms()}-{abs(hash((file_path, symbol, name))) % 10 ** 8}",
                "projectId": project_id, "filePath": file_path, "symbol": symbol,
                "name": name, "source": source, "reason": reason,
                "assetId": asset_id, "note": note, "createdAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def lookup(cls, project_id: str, file_path: str, symbol: str,
               limit: int = 5) -> list[dict]:
        """新提取命名前查参考池：同名符号的历史命名（新→旧）。"""
        if not project_id:
            return []
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? AND file_path = ? "
            f"AND symbol = ? ORDER BY created_at DESC LIMIT ?",
            (project_id, file_path, symbol, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def search(cls, project_id: str, q: str = "", limit: int = 100) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if q.strip():
            conds.append("(name LIKE ? OR symbol LIKE ? OR file_path LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like, like]
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY created_at DESC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]




class UserOverlayStore:
    """用户编辑层（改名/合并/拆分/描述修订；seq 有序重放，锚点失配 → orphaned）。"""

    TABLE = "arch_user_overlays"

    @classmethod
    def next_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(seq) AS s FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def add(cls, project_id: str, op: str, target_asset_ids: list,
            payload: dict, anchor_basis: list, author: str = "",
            reason: str = "") -> dict:
        data = {"id": f"ovl-{_now_ms()}-{abs(hash((op, tuple(target_asset_ids)))) % 10 ** 8}",
                "projectId": project_id, "seq": cls.next_seq(project_id),
                "author": author, "op": op, "targetAssetIds": target_asset_ids,
                "payload": payload, "anchorBasis": anchor_basis,
                "reason": reason, "status": "active", "createdAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def list_active(cls, project_id: str) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? AND status = 'active' "
            f"ORDER BY seq ASC",
            (project_id,), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def mark_status(cls, overlay_id: str, status: str) -> Optional[dict]:
        return _update(cls.TABLE, overlay_id, {"status": status})




class NamingConventionStore:
    """资产命名规约（场景标签 NOT NULL——agent 按场景加载，禁全量注入 R7）。"""

    TABLE = "arch_naming_conventions"

    @classmethod
    def create(cls, project_id: str, rule_text: str, scenarios: list,
               scope: str = "project", component_id: str = "",
               applies_kinds: Optional[list] = None, source: str = "manual",
               author: str = "", framework_version: int = 0,
               status: str = "active") -> dict:
        data = {"id": f"conv-{_now_ms()}-{abs(hash(rule_text)) % 10 ** 6}",
                "projectId": project_id, "scope": scope,
                "componentId": component_id,
                "appliesKinds": applies_kinds or [],
                "ruleText": rule_text, "source": source,
                "scenarios": scenarios or ["general"], "status": status,
                "author": author, "frameworkVersion": framework_version,
                "createdAt": _now_ms(), "updatedAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def list(cls, project_id: str, scenario: str = "",
             status: str = "active", limit: int = 200) -> list[dict]:
        conds = ["project_id = ?", "status = ?"]
        params: list = [project_id, status]
        if scenario.strip():
            # 场景过滤：scenarios JSON 含该标签（LIKE 足够，标签是封闭枚举）
            conds.append("scenarios LIKE ?")
            params.append(f'%"{scenario.strip()}"%')
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY updated_at DESC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        patch = dict(patch)
        patch["updatedAt"] = _now_ms()
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def delete(cls, row_id: str) -> bool:
        return _delete(cls.TABLE, row_id)

    @classmethod
    def mark_pending_review(cls, project_id: str, framework_version: int) -> int:
        """框架标准变更 → 关联旧值域的规约标记待复核（plan-C §5.3）。"""
        db = _target_db(cls.TABLE, project_id=project_id)
        cur = db.execute(
            f"UPDATE {cls.TABLE} SET status = 'pending_review', updated_at = ? "
            f"WHERE project_id = ? AND status = 'active'",
            (_now_ms(), project_id))
        db.commit()
        return cur.rowcount or 0




class GlossaryStore:
    """术语表（词典，纯参考非约束）。"""

    TABLE = "arch_glossary"

    @classmethod
    def create(cls, project_id: str, term: str, alias: Optional[list] = None,
               definition: str = "", source: str = "manual",
               source_ref: str = "", author: str = "") -> dict:
        data = {"id": f"gls-{_now_ms()}-{abs(hash(term)) % 10 ** 6}",
                "projectId": project_id, "term": term, "alias": alias or [],
                "definition": definition, "source": source,
                "sourceRef": source_ref, "author": author,
                "createdAt": _now_ms(), "updatedAt": _now_ms()}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def list(cls, project_id: str, q: str = "", limit: int = 500) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if q.strip():
            conds.append("(term LIKE ? OR definition LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like]
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY term ASC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        patch = dict(patch)
        patch["updatedAt"] = _now_ms()
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def delete(cls, row_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, row_id)
        if not found:
            return False
        db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (row_id,))
        db.commit()
        return True


# ── M2 契约/验收（plan-C §6；事实/意见物理分表 R6） ─────────────────


