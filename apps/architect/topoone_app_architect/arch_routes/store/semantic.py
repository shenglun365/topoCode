"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import _delete, _dumps, _fetchall_routed, _get, _insert, _locate_db, _route_read, _row_to_api, _scan_dbs, _target_db, _to_snake, _update

class SemanticAssetsStore:
    """语义数据资产(architect 自持，随最新代码结构增量更新)。

    表: arch_semantic_assets。scope_type×scope_key 唯一(同范围反复提取 → upsert)。
    """

    TABLE = "arch_semantic_assets"
    KINDS = ("entity", "contract", "state", "rule", "process", "decision")
    LEVELS = ("implementation", "logic", "business")

    @classmethod
    def all(cls, project_id: str = "", kind: str = "", limit: int = 200):
        conds, params = [], []
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        if kind in cls.KINDS:
            conds.append("kind = ?")
            params.append(kind)
        if conds:
            conds.append("status = 'active'")
            sql = f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)}"
        else:
            sql = f"SELECT * FROM {cls.TABLE} WHERE status = 'active'"
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows, mode = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id or None)
        out = [_row_to_api(r) for r in rows]
        if mode == "scan":
            out.sort(key=lambda r: (r.get("updatedAt") is None, r.get("updatedAt") or 0), reverse=True)
            out = out[: int(limit)]
        return out

    @classmethod
    def get(cls, asset_id: str):
        return _get(cls.TABLE, asset_id)

    @classmethod
    def find_by_scope(cls, project_id: str, scope_type: str, scope_key: str,
                      include_deleted: bool = False):
        status_sql = "status = 'active'" if not include_deleted else "1=1"
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM arch_semantic_assets "
            f"WHERE project_id = ? AND scope_type = ? AND scope_key = ? AND {status_sql} "
            f"ORDER BY created_at ASC",
            (project_id, scope_type, scope_key),
            project_id or None,
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, asset_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, asset_id, data)

    @classmethod
    def delete(cls, asset_id: str) -> bool:
        return _delete(cls.TABLE, asset_id)

    @classmethod
    def _scope_cond(cls, scopes: Optional[list]) -> tuple:
        """范围过滤 SQL 条件 + 参数。

        scopes: 组件 id 列表 + 可选哨兵 "__other__"。
        匹配语义与 `_component_asset_ids` 一致：资产属于某组件 =
        scope_key 命中 或 meta.scopes(跨 INCLUDE/CALL 归属)命中；
        "__other__" = 非组件资产(scope_type != 'comm')。
        """
        if not scopes:
            return "", []
        keys = [s for s in scopes if s != "__other__"]
        parts: list = []
        params: list = []
        for k in keys:
            parts.append(f"(scope_key = ? OR EXISTS (SELECT 1 FROM json_each({cls.TABLE}.meta, '$.scopes') je WHERE je.value = ?))")
            params += [k, k]
        if "__other__" in scopes:
            parts.append("scope_type != 'comm'")
        if not parts:
            return "", []
        return f"({' OR '.join(parts)})", params

    @classmethod
    def search(cls, project_id: str, text: str = "", kind: str = "",
               limit: int = 20, offset: int = 0,
               scopes: Optional[list] = None, level: str = "") -> list[dict]:
        """全文朴素检索：名称/描述命中，支持分页(limit/offset)与范围/粒度过滤。

        scopes: 组件 id 列表；含哨兵 "__other__" 表示非 comm 范围资产(scope_type != 'comm')。
        scope 命中含 meta.scopes 多组件归属(INCLUDE/CALL 两套口径共享代码只存一份)。
        """
        conds = ["project_id = ?", "status = 'active'"]
        params: list = [project_id]
        if kind in cls.KINDS:
            conds.append("kind = ?")
            params.append(kind)
        if level in cls.LEVELS:
            conds.append("level = ?")
            params.append(level)
        if text:
            conds.append("(name LIKE ? OR desc LIKE ? OR id LIKE ?)")
            like = f"%{text}%"
            params += [like, like, like]
        scope_sql, scope_params = cls._scope_cond(scopes)
        if scope_sql:
            conds.append(scope_sql)
            params += scope_params
        sql = (f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
               f"ORDER BY updated_at DESC LIMIT ? OFFSET ?")
        params += [int(limit), int(offset)]
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def count(cls, project_id: str, text: str = "", kind: str = "",
              scopes: Optional[list] = None, level: str = "") -> int:
        """满足检索条件的资产总数(与 search 同一条件)。"""
        conds = ["project_id = ?", "status = 'active'"]
        params: list = [project_id]
        if kind in cls.KINDS:
            conds.append("kind = ?")
            params.append(kind)
        if level in cls.LEVELS:
            conds.append("level = ?")
            params.append(level)
        if text:
            conds.append("(name LIKE ? OR desc LIKE ? OR id LIKE ?)")
            like = f"%{text}%"
            params += [like, like, like]
        scope_sql, scope_params = cls._scope_cond(scopes)
        if scope_sql:
            conds.append(scope_sql)
            params += scope_params
        mode, db = _route_read(cls.TABLE, project_id or None)
        if mode == "empty":
            return 0
        if mode == "one":
            rows = db.fetchall(
                f"SELECT COUNT(*) AS n FROM {cls.TABLE} WHERE {' AND '.join(conds)}",
                tuple(params),
            )
        else:
            rows = []
            for d in _scan_dbs():
                rows.extend(d.fetchall(
                    f"SELECT COUNT(*) AS n FROM {cls.TABLE} WHERE {' AND '.join(conds)}",
                    tuple(params),
                ))
        return sum(int((r or {}).get("n") or 0) for r in rows)

    @classmethod
    def mark_scope_stale(cls, project_id: str, scope_type: str, scope_key: str) -> None:
        db = _target_db(cls.TABLE, project_id)
        db.execute(
            "UPDATE arch_semantic_assets SET status = 'stale', updated_at = ? "
            "WHERE project_id = ? AND scope_type = ? AND scope_key = ? AND status = 'active'",
            (int(__import__("time").time() * 1000), project_id, scope_type, scope_key),
        )
        db.commit()

    @classmethod
    def set_needs_update(cls, asset_id: str, needs: bool = True, *, change: str = "",
                         reason: str = "") -> Optional[dict]:
        """文件变化 → 标记需更新后使用(status=stale + needs_update=1)。"""
        now = int(__import__("time").time() * 1000)
        payload: dict = {"status": "stale", "needsUpdate": 1 if needs else 0,
                         "updatedAt": now, "lastCheckedAt": now}
        if change:
            payload["change"] = change
        if reason:
            meta = _get(cls.TABLE, asset_id)
            m = dict((meta or {}).get("meta") or {})
            m["invalidateReason"] = reason
            payload["meta"] = m
        return cls.update(asset_id, payload)

    @classmethod
    def mark_deleted(cls, asset_id: str, *, change: str = "deleted") -> Optional[dict]:
        """软删：保留行与 id，引用可告警。"""
        now = int(__import__("time").time() * 1000)
        return cls.update(asset_id, {"status": "deleted", "change": change,
                                     "deletedAt": now, "updatedAt": now})

    @classmethod
    def list_stale(cls, project_id: str) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT * FROM arch_semantic_assets WHERE project_id = ? "
            "AND status = 'stale' ORDER BY updated_at DESC LIMIT 200",
            (project_id,),
            project_id or None,
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def all_status(cls, project_id: str, limit: int = 400) -> list[dict]:
        """全部状态(含 stale/deleted，供 reconcile/status 统计)。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT * FROM arch_semantic_assets WHERE project_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (project_id, int(limit)),
            project_id or None,
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def purge(cls, project_id: str, ids: list) -> int:
        """物理删除指定资产行(仅清理无引用遗留数据用，谨慎调用)。"""
        if not ids:
            return 0
        db = _target_db(cls.TABLE, project_id)
        ph = ",".join(["?"] * len(ids))
        cur = db.execute(
            f"DELETE FROM arch_semantic_assets WHERE project_id = ? AND id IN ({ph})",
            (project_id, *ids),
        )
        db.commit()
        return cur.rowcount or 0




class ExtractTaskStore:
    """语义资产提取任务(状态保持：浏览器刷新不中断，前端可恢复读取)。

    表: arch_extract_tasks。任务在服务端后台线程执行，进度/消息持久化，
    前端轮询同步到资产管理对话消息栏。
    """

    TABLE = "arch_extract_tasks"
    KINDS = ("semantic",)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, task_id: str) -> Optional[dict]:
        return _get(cls.TABLE, task_id)

    @classmethod
    def update(cls, task_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, task_id, data)

    @classmethod
    def delete(cls, task_id: str) -> bool:
        return _delete(cls.TABLE, task_id)

    @classmethod
    def list_recent(cls, project_id: str = "", limit: int = 20) -> list[dict]:
        conds, params = [], []
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        where = ("WHERE " + " AND ".join(conds)) if conds else ""
        rows, mode = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params + [int(limit)]),
            project_id or None,
        )
        out = [_row_to_api(r) for r in rows]
        if mode == "scan":
            out.sort(key=lambda r: (r.get("createdAt") is None, r.get("createdAt") or 0), reverse=True)
            out = out[: int(limit)]
        return out

    @classmethod
    def latest(cls, project_id: str = "", kind: str = "semantic") -> Optional[dict]:
        conds, params = ["kind = ?"], [kind or "semantic"]
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        sql = (f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
               "ORDER BY created_at DESC LIMIT 1")
        rows, mode = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id or None)
        if mode == "scan" and len(rows) > 1:
            rows.sort(key=lambda r: (r.get("created_at") or 0), reverse=True)
        return _row_to_api(rows[0]) if rows else None




class AstCacheStore:
    """architect AST 缓存层(要求③)：按文件存符号/边，content_hash 判新鲜。

    取数优先级: 缓存命中(content_hash 一致) → codegraph → KB parseFileAst → live 扫描。
    """

    TABLE = "arch_ast_cache"

    @classmethod
    def get(cls, project_id: str, file_path: str) -> Optional[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT * FROM arch_ast_cache WHERE project_id = ? AND file_path = ? LIMIT 1",
            (project_id, file_path),
            project_id or None,
        )
        return _row_to_api(rows[0]) if rows else None

    @classmethod
    def upsert(cls, project_id: str, file_path: str, data: dict) -> dict:
        now = int(__import__("time").time() * 1000)
        payload = {
            "projectId": project_id, "filePath": file_path,
            "contentHash": data.get("contentHash") or "",
            "language": data.get("language") or "",
            "symbols": data.get("symbols") or [],
            "imports": data.get("imports") or [],
            "refs": data.get("refs") or [],
            "statements": data.get("statements") or [],
            "routes": data.get("routes") or [],
            "constants": data.get("constants") or [],
            "source": data.get("source") or "codegraph",
            "parsedAt": now,
        }
        cols, params = [], []
        for k, v in payload.items():
            cols.append(_to_snake(k))
            params.append(_dumps(v))
        db = _target_db(cls.TABLE, project_id)
        db.execute(
            f"INSERT INTO {cls.TABLE} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(project_id, file_path) DO UPDATE SET "
            f"content_hash=excluded.content_hash, language=excluded.language, "
            f"symbols=excluded.symbols, imports=excluded.imports, refs=excluded.refs, "
            f"statements=excluded.statements, routes=excluded.routes, "
            f"constants=excluded.constants, "
            f"source=excluded.source, parsed_at=excluded.parsed_at",
            tuple(params),
        )
        db.commit()
        return cls.get(project_id, file_path) or payload

    @classmethod
    def invalidate(cls, project_id: str, files: Optional[list] = None) -> int:
        db = _target_db(cls.TABLE, project_id)
        if files:
            ph = ",".join("?" * len(files))
            cur = db.execute(
                f"DELETE FROM {cls.TABLE} WHERE project_id = ? AND file_path IN ({ph})",
                (project_id, *files),
            )
        else:
            cur = db.execute("DELETE FROM arch_ast_cache WHERE project_id = ?", (project_id,))
        db.commit()
        return cur.rowcount or 0

    @classmethod
    def for_project(cls, project_id: str, limit: int = 2000) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT * FROM arch_ast_cache WHERE project_id = ? LIMIT ?",
            (project_id, int(limit)),
            project_id or None,
        )
        return [_row_to_api(r) for r in rows]




class SemanticRefsStore:
    """语义资产引用登记(删除/失效时精确波及引用方)。"""

    TABLE = "arch_semantic_refs"

    @classmethod
    def _asset_db(cls, asset_id: str):
        """引用行随资产同库: 先定位资产所在项目库，未命中回退默认写目标。"""
        db, _ = _locate_db("arch_semantic_assets", asset_id)
        return db

    @classmethod
    def add(cls, asset_id: str, ref_type: str, ref_id: str, role: str = "related") -> None:
        now = int(__import__("time").time() * 1000)
        db = cls._asset_db(asset_id)
        db.execute(
            f"INSERT INTO {cls.TABLE} (asset_id, ref_type, ref_id, role, created_at) "
            f"VALUES (?, ?, ?, ?, ?) ON CONFLICT(asset_id, ref_type, ref_id) "
            f"DO UPDATE SET role = excluded.role",
            (asset_id, ref_type, ref_id, role, now),
        )
        db.commit()

    @classmethod
    def refs_of(cls, asset_id: str) -> list[dict]:
        db = cls._asset_db(asset_id)
        rows = db.fetchall(
            "SELECT * FROM arch_semantic_refs WHERE asset_id = ?", (asset_id,))
        return [_row_to_api(r) for r in rows]

    @classmethod
    def assets_referenced_in(cls, ref_type: str, ref_id: str) -> list[str]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT asset_id FROM arch_semantic_refs WHERE ref_type = ? AND ref_id = ?",
            (ref_type, ref_id),
        )
        return [r["asset_id"] for r in rows]

    @classmethod
    def delete_for_assets(cls, asset_ids: list) -> int:
        """物理删除这些资产的所有引用登记(随资产一并清除)。"""
        if not asset_ids:
            return 0
        db = cls._asset_db(asset_ids[0])
        ph = ",".join(["?"] * len(asset_ids))
        cur = db.execute(
            f"DELETE FROM {cls.TABLE} WHERE asset_id IN ({ph})", tuple(asset_ids))
        db.commit()
        return cur.rowcount or 0


# ── M0 冻结 schema stores（docs/architect-reconstruction/plan-C-M0.md §6） ──

