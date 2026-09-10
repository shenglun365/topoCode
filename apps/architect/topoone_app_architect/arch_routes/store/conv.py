"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import PROJECT_TABLES, _all, _db, _dumps, _fetchall_routed, _get, _insert, _locate_db, _row_to_api, _target_db, _to_snake, _update, next_id

class AgentSessionsStore:
    TABLE = "arch_agent_sessions"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def get(cls, session_id: str):
        return _get(cls.TABLE, session_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, session_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, session_id, data)

    @classmethod
    def messages(cls, session_id: str) -> list[dict]:
        db, found = _locate_db(cls.TABLE, session_id)
        if not found:
            return []
        rows = db.fetchall(
            "SELECT * FROM arch_agent_messages WHERE session_id = ? "
            "ORDER BY time ASC, rowid ASC",
            (session_id,),
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def append_message(cls, msg: dict) -> None:
        sid = msg.get("sessionId") or msg.get("session_id") or ""
        db, _ = _locate_db(cls.TABLE, sid) if sid else (None, False)
        if db is None:
            db = _target_db("arch_agent_messages")
        cols = [_to_snake(k) for k in msg]
        vals = [_dumps(v) for k, v in msg.items()]
        db.execute(
            f"INSERT INTO arch_agent_messages ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            tuple(vals),
        )
        db.commit()

    @classmethod
    def delete(cls, session_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, session_id)
        if not found:
            return False
        db.execute("DELETE FROM arch_agent_messages WHERE session_id = ?", (session_id,))
        cur = db.execute("DELETE FROM arch_agent_sessions WHERE id = ?", (session_id,))
        db.commit()
        return cur.rowcount > 0




class UnitTestsStore:
    TABLE = "arch_unit_tests"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def get(cls, test_id: str):
        return _get(cls.TABLE, test_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, test_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, test_id, data)




class UnitTestSessionsStore:
    TABLE = "arch_unit_test_sessions"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def get(cls, session_id: str):
        return _get(cls.TABLE, session_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, session_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, session_id, data)

    @classmethod
    def messages(cls, session_id: str) -> list[dict]:
        db, found = _locate_db(cls.TABLE, session_id)
        if not found:
            return []
        rows = db.fetchall(
            "SELECT * FROM arch_unit_test_messages WHERE session_id = ? "
            "ORDER BY time ASC, rowid ASC",
            (session_id,),
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def append_message(cls, msg: dict) -> None:
        _insert("arch_unit_test_messages", msg)




class SessionRolesStore:
    """会话执行角色(主库全局表; architect 系统种子 builtin=1 不可删)。"""

    TABLE = "arch_session_roles"

    @classmethod
    def all(cls):
        rows = _db().fetchall(f"SELECT * FROM {cls.TABLE} ORDER BY created_at ASC")
        return [_row_to_api(r) for r in rows]

    @classmethod
    def get(cls, role_id: str):
        row = _db().fetchone(f"SELECT * FROM {cls.TABLE} WHERE id = ?", (role_id,))
        return _row_to_api(row) if row else None

    @classmethod
    def upsert(cls, data: dict) -> dict:
        now = int(__import__("time").time() * 1000)
        payload = {
            "id": data.get("id") or data.get("name", "").strip().lower().replace(" ", "-"),
            "name": data.get("name") or "",
            "kind": data.get("kind") or "executor",
            "executorId": data.get("executorId") or "",
            "modelId": data.get("modelId") or "",
            "skills": data.get("skills"),
            "tools": data.get("tools"),
            "permissions": data.get("permissions"),
            "builtin": 1 if data.get("builtin") else 0,
            "updatedAt": now,
        }
        existing = cls.get(payload["id"])
        if existing:
            # 内置角色只允许改能力配置(skills/tools/permissions), 不许改绑定
            if existing.get("builtin"):
                payload["kind"] = existing["kind"]
                payload["executorId"] = existing.get("executorId") or ""
            cols = list(payload)
            db = _db()
            db.execute(
                f"UPDATE {cls.TABLE} SET {', '.join(f'{_to_snake(c)} = ?' for c in cols)} WHERE id = ?",
                (*[_dumps(payload[c]) for c in cols], payload["id"]))
            db.commit()
            return cls.get(payload["id"])
        payload["createdAt"] = now
        cols = list(payload)
        db = _db()
        db.execute(
            f"INSERT INTO {cls.TABLE} ({', '.join(_to_snake(c) for c in cols)}) "
            f"VALUES ({', '.join('?' * len(cols))})",
            tuple(_dumps(payload[c]) for c in cols))
        db.commit()
        return payload

    @classmethod
    def delete(cls, role_id: str) -> bool:
        row = cls.get(role_id)
        if not row or row.get("builtin"):
            return False
        db = _db()
        cur = db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (role_id,))
        db.commit()
        return cur.rowcount > 0


class AssetLocksStore:
    """并行执行资产锁(项目库; PR5 acquire/release 使用, PR1 先落表)。"""

    TABLE = "arch_asset_locks"

    @classmethod
    def all(cls, project_id: str = ""):
        return _all(cls.TABLE, project_id=project_id)

    @classmethod
    def conflicts(cls, project_id: str, resources: list, exclude_holder: str = "") -> list:
        """资源清单与现有锁的冲突(排除自己持有的)。"""
        if not resources:
            return []
        out = []
        for lk in cls.all(project_id):
            if lk.get("holder") == exclude_holder:
                continue
            if lk.get("resource") in resources:
                out.append(lk)
        return out


class ConversationsStore:
    """统一会话(阶段D 主干)：requirement/design/execution/unit-test 共用一张表+消息表。"""

    TABLE = "arch_conversations"
    MSG_TABLE = "arch_conversation_messages"

    @classmethod
    def all(cls, kind: str = None, project_id: str = None, limit: int = 100,
            kinds: list = None):
        """会话列表。kind=单类过滤；kinds=多类过滤(会话中心全量口径含 asset)。"""
        sql = f"SELECT * FROM {cls.TABLE}"
        conds, params = [], []
        if kind:
            conds.append("kind = ?")
            params.append(kind)
        elif kinds:
            conds.append("kind IN (%s)" % ",".join("?" * len(kinds)))
            params.extend(kinds)
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows, mode = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id)
        out = [_row_to_api(r) for r in rows]
        if mode == "scan":
            out.sort(key=lambda r: (r.get("updatedAt") is None, r.get("updatedAt") or 0), reverse=True)
            out = out[: int(limit)]
        return out

    @classmethod
    def get(cls, conv_id: str):
        return _get(cls.TABLE, conv_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        """创建会话；缺省补 id/时间字段。tags(JSON {modules,groups})/summary 会话中心用。"""
        now = int(__import__("time").time() * 1000)
        payload = {
            "id": data.get("id") or next_id("cv"),
            "kind": data.get("kind", "requirement"),
            "project_id": data.get("projectId") or "",
            "req_id": data.get("reqId") or "",
            "title": data.get("title") or "",
            "status": data.get("status") or "active",
            "review_state": data.get("reviewState") or "read",
            "role_id": data.get("roleId") or "architect",
            "role_locked": 1 if data.get("roleLocked") else 0,
            "tags": data.get("tags"),
            "summary": data.get("summary") or "",
            "meta": data.get("meta"),
            "created_at": data.get("createdAt") or now,
            "updated_at": data.get("updatedAt") or now,
        }
        _insert(cls.TABLE, payload)
        return payload

    @classmethod
    def upsert(cls, conv_id: str, data: dict) -> dict:
        existing = _get(cls.TABLE, conv_id)
        if existing:
            _update(cls.TABLE, conv_id, {**data, "updatedAt": int(__import__("time").time() * 1000)})
            return _get(cls.TABLE, conv_id) or existing
        return cls.create({"id": conv_id, **data})

    @classmethod
    def update(cls, conv_id: str, data: dict) -> Optional[dict]:
        data["updatedAt"] = int(__import__("time").time() * 1000)
        return _update(cls.TABLE, conv_id, data)

    @classmethod
    def messages(cls, conv_id: str, limit: int = 200) -> list[dict]:
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return []
        rows = db.fetchall(
            f"SELECT * FROM {cls.MSG_TABLE} WHERE conversation_id = ? "
            "ORDER BY time ASC, rowid ASC LIMIT ?",
            (conv_id, int(limit)),
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def by_req(cls, req_id: str, project_id: str = "", limit: int = 20) -> list[dict]:
        """按关联需求/提案 id 找会话(req_id 匹配; 同需求多会话按更新时间倒序)。"""
        conds, params = ["req_id = ?"], [req_id]
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            "ORDER BY updated_at DESC LIMIT ?",
            tuple(params + [int(limit)]),
            project_id or None,
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def summaries(cls, kind: str = None, project_id: str = None, limit: int = 100,
                  all_scopes: bool = False) -> list[dict]:
        """会话摘要(用于历史导入列表): 会话头 + 消息数 + 首条用户消息预览。

        all_scopes=True: 跨全库(主库+各项目库)扫描合并, 不受请求项目上下文限制
        (会话中心统一视图)。"""
        if all_scopes:
            return cls._summaries_scan(kind=kind, limit=limit)
        sql = (f"SELECT c.*, "
               "(SELECT COUNT(*) FROM {msg} m WHERE m.conversation_id = c.id) AS msg_count, "
               "(SELECT MIN(m2.time) FROM {msg} m2 WHERE m2.conversation_id = c.id "
               " AND m2.role = 'user') AS first_user_time, "
               "(SELECT m3.content FROM {msg} m3 WHERE m3.conversation_id = c.id "
               " AND m3.role = 'user' ORDER BY m3.time ASC, m3.rowid ASC LIMIT 1) AS preview "
               f"FROM {cls.TABLE} c").format(msg=cls.MSG_TABLE)
        conds, params = [], []
        if kind:
            conds.append("c.kind = ?")
            params.append(kind)
        if project_id:
            conds.append("c.project_id = ?")
            params.append(project_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY c.updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def _summaries_scan(cls, kind: str = None, limit: int = 100) -> list[dict]:
        """全库扫描版 summaries(主库+各项目库), 按更新时间归并。"""
        from .base import _scan_dbs
        sql = (f"SELECT c.*, "
               "(SELECT COUNT(*) FROM {msg} m WHERE m.conversation_id = c.id) AS msg_count, "
               "(SELECT MIN(m2.time) FROM {msg} m2 WHERE m2.conversation_id = c.id "
               " AND m2.role = 'user') AS first_user_time, "
               "(SELECT m3.content FROM {msg} m3 WHERE m3.conversation_id = c.id "
               " AND m3.role = 'user' ORDER BY m3.time ASC, m3.rowid ASC LIMIT 1) AS preview "
               f"FROM {cls.TABLE} c").format(msg=cls.MSG_TABLE)
        params: tuple = ()
        if kind:
            sql += " WHERE c.kind = ?"
            params = (kind,)
        out: list[dict] = []
        for d in _scan_dbs():
            out.extend(_row_to_api(r) for r in d.fetchall(sql, params))
        out.sort(key=lambda r: (r.get("updatedAt") is None, r.get("updatedAt") or 0), reverse=True)
        return out[: int(limit)]

    @classmethod
    def append_message(cls, msg: dict) -> dict:
        _insert(cls.MSG_TABLE, msg)
        return msg

    @classmethod
    def delete_message(cls, conv_id: str, message_id: str) -> bool:
        """删除会话内的单条消息(对话流单条删除)。"""
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return False
        cur = db.execute(
            f"DELETE FROM {cls.MSG_TABLE} WHERE conversation_id = ? AND id = ?",
            (conv_id, message_id),
        )
        db.commit()
        return cur.rowcount > 0

    @classmethod
    def delete(cls, conv_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return False
        db.execute(f"DELETE FROM {cls.MSG_TABLE} WHERE conversation_id = ?", (conv_id,))
        cur = db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (conv_id,))
        db.commit()
        return cur.rowcount > 0




class ContextUnitsStore:
    """上下文注册表(P2)：会话派生的可检索单元(拉取式供 architect/执行器提取)。"""

    TABLE = "arch_context_units"

    @classmethod
    def all(cls, conversation_id: str = None, type_: str = None,
            project_id: str = None, limit: int = 200) -> list[dict]:
        sql = f"SELECT * FROM {cls.TABLE}"
        conds, params = [], []
        if conversation_id:
            conds.append("conversation_id = ?")
            params.append(conversation_id)
        if type_:
            conds.append("type = ?")
            params.append(type_)
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def search(cls, q: str, type_: str = None, conversation_id: str = None,
               project_id: str = None, limit: int = 30) -> list[dict]:
        """标题/正文 LIKE 检索(降序)。"""
        sql = f"SELECT * FROM {cls.TABLE} WHERE (title LIKE ? OR content LIKE ?)"
        like = f"%{q}%"
        params = [like, like]
        if type_:
            sql += " AND type = ?"
            params.append(type_)
        if conversation_id:
            sql += " AND conversation_id = ?"
            params.append(conversation_id)
        if project_id:
            sql += " AND project_id = ?"
            params.append(project_id)
        sql += " ORDER BY importance DESC, created_at DESC LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def get(cls, unit_id: str):
        return _get(cls.TABLE, unit_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        now = int(__import__("time").time() * 1000)
        payload = {
            "id": data.get("id") or next_id("cu"),
            "conversation_id": data.get("conversationId") or "",
            "project_id": data.get("projectId") or "",
            "type": data.get("type") or "note",
            "title": data.get("title") or "",
            "content": data.get("content") or "",
            "refs": data.get("refs") or {},
            "importance": int(data.get("importance") or 0),
            "created_at": data.get("createdAt") or now,
        }
        _insert(cls.TABLE, payload)
        return _row_to_api(payload)

    @classmethod
    def delete(cls, unit_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, unit_id)
        if not found:
            return False
        cur = db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (unit_id,))
        db.commit()
        return cur.rowcount > 0

    @classmethod
    def delete_by_conversation(cls, conversation_id: str) -> None:
        db, found = _locate_db(cls.TABLE, conversation_id)
        if not found:
            return
        db.execute(f"DELETE FROM {cls.TABLE} WHERE conversation_id = ?", (conversation_id,))
        db.commit()


class DocsStore:
    """备案文档(会话派生总结)：需求快照/开发简报/笔记，随时生成随时增删。"""

    TABLE = "arch_docs"

    @classmethod
    def all(cls, project_id: str = None, conversation_id: str = None,
            type_: str = None, limit: int = 200) -> list[dict]:
        sql = f"SELECT * FROM {cls.TABLE}"
        conds, params = [], []
        if project_id:
            conds.append("project_id = ?")
            params.append(project_id)
        if conversation_id:
            conds.append("conversation_id = ?")
            params.append(conversation_id)
        if type_:
            conds.append("type = ?")
            params.append(type_)
        if conds:
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params), project_id)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def get(cls, doc_id: str):
        return _get(cls.TABLE, doc_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        now = int(__import__("time").time() * 1000)
        payload = {
            "id": data.get("id") or next_id("doc"),
            "project_id": data.get("projectId") or "",
            "conversation_id": data.get("conversationId") or "",
            "type": data.get("type") or "requirement_summary",
            "title": data.get("title") or "",
            "content_md": data.get("contentMd") or "",
            "refs": data.get("refs"),
            "created_at": data.get("createdAt") or now,
            "updated_at": data.get("updatedAt") or now,
        }
        _insert(cls.TABLE, payload)
        return _row_to_api(payload)

    @classmethod
    def update(cls, doc_id: str, data: dict) -> Optional[dict]:
        data["updatedAt"] = int(__import__("time").time() * 1000)
        return _update(cls.TABLE, doc_id, data)

    @classmethod
    def delete(cls, doc_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, doc_id)
        if not found:
            return False
        cur = db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (doc_id,))
        db.commit()
        return cur.rowcount > 0


class McpCallsStore:
    TABLE = "arch_mcp_calls"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="time DESC")

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data




class InteractionsStore:
    TABLE = "arch_interactions"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="time DESC")

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, interaction_id: str):
        return _get(cls.TABLE, interaction_id)

    @classmethod
    def update(cls, interaction_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, interaction_id, data)




class AgentBusStore:
    """agent_bus 持久化消息队列(全局主库表；broker 进程轮询分发)。

    不在 PROJECT_TABLES → 恒主库(broker 单表轮询，无需项目路由)。
    """
    TABLE = "arch_bus_messages"

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, msg_id: str):
        return _get(cls.TABLE, msg_id)

    @classmethod
    def pending(cls, limit: int = 20) -> list:
        rows = _db().fetchall(
            f"SELECT * FROM {cls.TABLE} WHERE status = 'pending' "
            "ORDER BY created_at ASC LIMIT ?", (limit,))
        return [_row_to_api(r) for r in rows]

    @classmethod
    def mark(cls, msg_id: str, status: str, error: str = "") -> Optional[dict]:
        import time
        return _update(cls.TABLE, msg_id, {"status": status, "error": error,
                                           "updatedAt": int(time.time() * 1000)})

    @classmethod
    def list(cls, dst: str = None, topic: str = None, status: str = None,
              limit: int = 100) -> list:
        sql = f"SELECT * FROM {cls.TABLE}"
        where, params = [], []
        if dst:
            where.append("dst = ?"); params.append(dst)
        if topic:
            where.append("topic = ?"); params.append(topic)
        if status:
            where.append("status = ?"); params.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = _db().fetchall(sql, tuple(params))
        return [_row_to_api(r) for r in rows]

    @classmethod
    def count_pending(cls) -> int:
        row = _db().fetchone(
            f"SELECT COUNT(*) AS c FROM {cls.TABLE} WHERE status = 'pending'")
        return row["c"] if row else 0



