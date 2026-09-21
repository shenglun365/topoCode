"""store 拆分模块（A1-T3：纯移动）。"""
from __future__ import annotations

from .base import (PROJECT_TABLES, _all, _db, _dumps, _fetchall_routed, _get,
                   _insert, _locate_db, _row_to_api, _row_to_api_v, _scan_dbs,
                   _target_db, _to_snake, _update, next_id)


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
        """创建会话；缺省补 id/时间字段。work_state(相位)生命周期用。

        roles 列已僵尸化(T4 清退): 会话身份由 executor_id 绑定 + running 推导
        替代——停写(列保留防迁移), API 读侧恒回 ["architect"]。"""
        import json as _json
        now = int(__import__("time").time() * 1000)
        roles = ["architect"]
        payload = {
            "id": data.get("id") or next_id("cv"),
            "kind": data.get("kind", "generic"),
            "project_id": data.get("projectId") or "",
            "req_id": data.get("reqId") or "",
            "title": data.get("title") or "",
            "status": data.get("status") or "active",
            "work_state": data.get("workState") or "architect",
            "review_state": data.get("reviewState") or "read",
            "analysis_mode": data.get("analysisMode") or "strict",
            "clarify_mode": data.get("clarifyMode") or "auto",
            "isolated": 1 if data.get("isolated") else 0,
            "parent_conv_id": data.get("parentConvId") or "",
            "executor_id": data.get("executorId") or "",
            "session_ref": data.get("sessionRef") or "",
            "executor_model": data.get("executorModel") or "",
            "roles": _json.dumps(roles, ensure_ascii=False),
            "tags": data.get("tags"),
            "summary": data.get("summary") or "",
            "meta": data.get("meta"),
            # 流程相位缓存(governance/flow.py derive-on-write; 缺省空=待惰性回填)
            "flow_state": data.get("flowState") or "",
            "flow_state_at": data.get("flowStateAt") or 0,
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
    def by_parent(cls, parent_conv_id: str, limit: int = 50) -> list[dict]:
        """主会话的 coding 子会话池(parent_conv_id 匹配, 更新时间倒序)。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT *, (SELECT COUNT(*) FROM {cls.MSG_TABLE} m "
            f" WHERE m.conversation_id = {cls.TABLE}.id) AS msg_count "
            f"FROM {cls.TABLE} WHERE parent_conv_id = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (parent_conv_id, int(limit)), None)
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
            return cls._summaries_scan(kind=kind, limit=limit,
                                       project_id=project_id)
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
    def _summaries_scan(cls, kind: str = None, limit: int = 100,
                        project_id: str = None) -> list[dict]:
        """全库扫描版 summaries(主库+各项目库), 按更新时间归并。

        project_id: 扫描后按 project_id 列过滤(会话中心项目隔离视图;
        历史行可能落在主库, 故扫全库再按列过滤, 不走单库路由)。"""
        from .base import _scan_dbs
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
        params = tuple(params)
        out: list[dict] = []
        for d in _scan_dbs():
            out.extend(_row_to_api(r) for r in d.fetchall(sql, params))
        out.sort(key=lambda r: (r.get("updatedAt") is None, r.get("updatedAt") or 0), reverse=True)
        return out[: int(limit)]

    @classmethod
    def append_message(cls, msg: dict) -> dict:
        _insert(cls.MSG_TABLE, msg)
        return msg

    # ── 生命周期重构: 角色集 + 工作相位 ──

    @classmethod
    def roles_of(cls, conv_id: str) -> list:
        row = cls.get(conv_id) or {}
        r = row.get("roles")
        if isinstance(r, list) and r:
            return r
        return ["architect"]

    @classmethod
    def work_state(cls, conv_id: str) -> str:
        row = cls.get(conv_id) or {}
        return (row.get("workState") or "architect") if row.get("workState") else "architect"

    @classmethod
    def set_work_state(cls, conv_id: str, state: str) -> None:
        """工作相位: architect(常态) | running(外调作业执行中)。
        running ⇔ 账本存在非终态作业——由 exec_bridge 聚合维护, 此处仅落库。"""
        if state in ("architect", "running"):
            cls.update(conv_id, {"workState": state})

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
    def update_message_by_meta(cls, conv_id: str, match: dict, data: dict) -> Optional[dict]:
        """单流卡片原位更新(cv-203 状态卡): 同库连接内 定位→改写→回读。

        match: meta 字段相等条件(如 {"kind": "task_status", "taskId": t})。
        必须用同一 db 句柄完成定位与改写——scan 与 update 分两次路由会落在
        不同库(项目库注册时序实证), 造成"找到卡却改不中"的静默漂移。
        返回更新后行(未命中→None, 调用方回落 land 新卡)。"""
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return None
        rows = db.fetchall(
            f"SELECT id, meta FROM {cls.MSG_TABLE} WHERE conversation_id = ? "
            "ORDER BY time DESC, rowid DESC LIMIT 400", (conv_id,))
        import json as _json
        for r in rows:
            try:
                meta = _json.loads(r.get("meta") or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(meta, dict):
                continue
            if all(meta.get(k) == v for k, v in match.items()):
                sets, params = [], []
                if "content" in data:
                    sets.append("content = ?")
                    params.append(str(data["content"] or ""))
                if "meta" in data:
                    new_meta = {**meta, **(data["meta"] if isinstance(
                        data["meta"], dict) else {})}
                    sets.append("meta = ?")
                    params.append(_dumps(new_meta))
                if "time" in data:
                    sets.append("time = ?")
                    params.append(int(data["time"] or 0))
                if not sets:
                    return None
                cur = db.execute(
                    f"UPDATE {cls.MSG_TABLE} SET {', '.join(sets)} "
                    f"WHERE conversation_id = ? AND id = ?",
                    (*params, conv_id, r["id"]))
                db.commit()
                if getattr(cur, "rowcount", 0) <= 0:
                    return None
                row = db.fetchone(
                    f"SELECT * FROM {cls.MSG_TABLE} WHERE id = ?", (r["id"],))
                return _row_to_api(row) if row else None
        return None

    @classmethod
    def update_message(cls, conv_id: str, message_id: str, data: dict) -> Optional[dict]:
        """原位更新单条消息(cv-203 状态卡): content/meta/time 可更新。

        专用状态/进度消息按 taskId 单卡存在, 事件驱动原位改写(非追加新消息),
        读侧经既有 SSE conv-message 通知刷新。返回更新后行(找不到→None)。"""
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return None
        sets, params = [], []
        if "content" in data:
            sets.append("content = ?")
            params.append(str(data["content"] or ""))
        if "meta" in data:
            sets.append("meta = ?")
            params.append(data["meta"] if isinstance(data["meta"], str)
                          else _dumps(data["meta"]))
        if "time" in data:
            sets.append("time = ?")
            params.append(int(data["time"] or 0))
        if not sets:
            return None
        params.append(message_id)
        # 写入经 WriteQueue 串行化(WriteResult.rowcount 不可靠)——以回读验证
        db.execute(
            f"UPDATE {cls.MSG_TABLE} SET {', '.join(sets)} "
            f"WHERE conversation_id = ? AND id = ?", (*params, conv_id))
        db.commit()
        row = db.fetchone(
            f"SELECT * FROM {cls.MSG_TABLE} WHERE conversation_id = ? AND id = ?",
            (conv_id, message_id))
        return _row_to_api(row) if row else None

    @classmethod
    def delete_messages_after(cls, conv_id: str, message_id: str) -> int:
        """回退到消息 N(环节十五): 删除其后全部消息(不含自身)。

        排序语义与 messages() 一致(time ASC, rowid ASC)。返回删除数;
        -1 = 锚点消息不存在。回退点之后语义作废(非任意删改)。"""
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return -1
        row = db.fetchone(
            f"SELECT time, rowid FROM {cls.MSG_TABLE} "
            "WHERE conversation_id = ? AND id = ?",
            (conv_id, message_id))
        if not row:
            return -1
        cur = db.execute(
            f"DELETE FROM {cls.MSG_TABLE} WHERE conversation_id = ? AND "
            "(time > ? OR (time = ? AND rowid > ?))",
            (conv_id, row["time"], row["time"], row["rowid"]))
        db.commit()
        return cur.rowcount

    @classmethod
    def delete(cls, conv_id: str) -> bool:
        db, found = _locate_db(cls.TABLE, conv_id)
        if not found:
            return False
        db.execute(f"DELETE FROM {cls.MSG_TABLE} WHERE conversation_id = ?", (conv_id,))
        cur = db.execute(f"DELETE FROM {cls.TABLE} WHERE id = ?", (conv_id,))
        db.commit()
        return cur.rowcount > 0




class StreamItemsStore:
    """A6.2 事件流 item 投影持久化(仅非落消息类型: 工具轨迹/文件变更/通知)。

    投影语义单源在 agent/execution/items.py(纯函数); 本 store 只管存取。
    落消息类卡片(approval/verify/turn_completed...)经 GET /messages 的
    item_from_card 读侧投影渲染, 不入本表(避免双源)。
    """

    TABLE = "arch_stream_items"

    @classmethod
    def create(cls, data: dict) -> dict:
        now = int(__import__("time").time() * 1000)
        payload = {
            "id": data.get("id") or next_id("si"),
            "conversationId": data.get("conversationId") or "",
            "projectId": data.get("projectId") or "",
            "taskId": data.get("taskId") or "",
            "jobId": data.get("jobId") or "",
            "type": data.get("type") or "event",
            "status": data.get("status") or "",
            "text": data.get("text") or "",
            "payload": data.get("payload") or {},
            "seq": data.get("seq"),
            "createdAt": data.get("createdAt") or now,
        }
        _insert(cls.TABLE, payload)
        return payload

    @classmethod
    def for_conv(cls, conversation_id: str, task_id: str = None,
                 before_ts: int = None, limit: int = 200) -> list[dict]:
        """会话流 item(新→旧); task_id/before_ts 过滤(分页回载挂点)。

        flow_transition(相位迁移审计, governance/flow.py)不属 UI 信息流,
        默认排除——审计读取走 transitions()。"""
        conds, params = ["conversation_id = ?",
                         "type != 'flow_transition'"], [conversation_id]
        if task_id:
            conds.append("task_id = ?")
            params.append(task_id)
        if before_ts:
            conds.append("created_at < ?")
            params.append(int(before_ts))
        sql = (f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
               f"ORDER BY created_at DESC, id DESC LIMIT ?")
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.TABLE, sql, tuple(params), None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def transitions(cls, conversation_id: str, limit: int = 100) -> list[dict]:
        """相位迁移审计流(flow_transition, 新→旧; 调试/复盘/自愈观测)。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE conversation_id = ? "
            f"AND type = 'flow_transition' "
            f"ORDER BY created_at DESC, id DESC LIMIT ?",
            (conversation_id, int(limit)), None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def delete_by_conversation(cls, conversation_id: str) -> None:
        for d in _scan_dbs():
            cur = d.execute(f"DELETE FROM {cls.TABLE} WHERE conversation_id = ?",
                            (conversation_id,))
            if cur.rowcount:
                d.commit()


class ContextUnitsStore:
    """上下文注册表(P2)：会话派生的可检索单元(拉取式供 architect/执行器提取)。"""

    TABLE = "arch_context_units"

    @classmethod
    def _api(cls, row: dict) -> dict:
        return _row_to_api_v("arch_context_units", row)


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
        return [cls._api(r) for r in rows]

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
        return [cls._api(r) for r in rows]

    @classmethod
    def all_across(cls, type_: str = None, q: str = None, limit: int = 200) -> list[dict]:
        """跨全库(主库+各项目库)扫描合并: 会话中心统一视图, 不受请求项目上下文限制。

        与 ConversationsStore._summaries_scan 同构: 各库独立 LIMIT 后归并重排再截断。"""
        from .base import _scan_dbs
        conds, params = [], []
        if q:
            conds.append("(title LIKE ? OR content LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if type_:
            conds.append("type = ?")
            params.append(type_)
        where = (" WHERE " + " AND ".join(conds)) if conds else ""
        sql = f"SELECT * FROM {cls.TABLE}{where} ORDER BY created_at DESC LIMIT ?"
        params = (*params, int(limit))
        out: list[dict] = []
        for d in _scan_dbs():
            out.extend(cls._api(r) for r in d.fetchall(sql, params))
        out.sort(key=lambda r: (r.get("createdAt") is None, r.get("createdAt") or 0), reverse=True)
        return out[: int(limit)]

    @classmethod
    def get(cls, unit_id: str):
        return _get(cls.TABLE, unit_id)

    @classmethod
    def update(cls, unit_id: str, data: dict) -> Optional[dict]:
        """单元内容修正/累积(如 error_pattern 同签名追加场景)。"""
        _update(cls.TABLE, unit_id, data)
        return cls.get(unit_id)

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
        return cls._api(payload)

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
    def _api(cls, row: dict) -> dict:
        return _row_to_api_v("arch_docs", row)


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
        return [cls._api(r) for r in rows]

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
        return cls._api(payload)

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
