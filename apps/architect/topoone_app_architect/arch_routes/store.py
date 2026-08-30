"""Architect store layer — sqlite persistence via ctx architect.db.

Routers stay thin; all reads/writes go through these helpers. 契约见
docs/architect/conventions.md §7(architect.db)、docs/architect/*.md。

访问方式: `ctx.db()` (SQLiteContext，独立进程经 ctx.setup 注入)。
列名: DB 用 snake_case; 对外(前端契约)统一 camelCase, 读写自动互转。
JSON 列: 读写时自动 dumps/loads。
ID 生成: 按前缀单调递增序列(见 conventions.md §4)。
"""

import json
import re
from typing import Optional


def _db():
    """Architect sqlite context (lazy)。独立进程启动时经 `ctx.setup()` 注入；
    未注入时回退到进程内默认上下文(测试/嵌入式用，见 ctx.default_db)。"""
    from . import ctx
    it = ctx.db()
    if it is not None:
        return it
    it = ctx.default_db()
    if it is not None:
        return it
    raise RuntimeError("architect store 未初始化：请先调用 ctx.setup(data_dir) 或 ctx.default_db()")


# ── camelCase ↔ snake_case ────────────────────────────────────

_CAMEL_RE = re.compile(r"(?<!^)(?=[A-Z])")


def _to_snake(key: str) -> str:
    return _CAMEL_RE.sub("_", key).lower()


def _to_camel(key: str) -> str:
    parts = key.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


# JSON 列(列名按 DB snake_case)。row 解码时对这些列做 loads。
_JSON_COLUMNS = {
    "config", "acceptance", "analysis", "trace_to", "suggestion",
    "req_ids", "changes", "impact", "root", "history",
    "design",
    "session_ids", "test_ids", "amendments", "stats",
    "artifacts", "test_result", "levels", "last_result", "tool",
    "input", "output", "overrides", "explicit_rules", "derived_rules",
    "changelog", "default_channel", "scaffold",
    "related_to", "preferred_asset_ids", "meta",
    "detail", "ast_refs", "asset_refs", "anchor_hashes",
    "name_alias", "pending_rejudge",
    "symbols", "imports", "refs", "statements", "routes", "constants",
    "comp_ids", "progress", "messages",
    "payload",
    # M0 冻结 schema JSON 列（plan-C-M0.md §6）
    "affected_summary", "target_asset_ids", "anchor_basis",
    "applies_kinds", "scenarios", "alias", "origin", "target", "behavior",
    "z_axis", "item_ids", "asset_refs", "component_refs",
    "framework_snapshot", "evidence", "trigger_info", "summary",
}


def _dumps(value):
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _loads(raw, default=None):
    if raw is None or raw == "":
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def _row_to_api(row: dict) -> dict:
    """DB 行 → API 形状(camelCase + JSON 解码)。"""
    out = {}
    for k, v in row.items():
        key = _to_camel(k)
        if isinstance(v, str) and k in _JSON_COLUMNS:
            v = _loads(v)
        out[key] = v
    return out


def _data_to_db(data: dict) -> dict:
    """API 形状 → DB 列(camelCase → snake_case + JSON 编码)。"""
    out = {}
    for k, v in data.items():
        key = _to_snake(k)
        if k in {"analysis", "config", "root", "history", "stats",
                 "testIds", "reqIds", "sessionIds", "amendments",
                 "testResult", "lastResult", "acceptance", "traceTo",
                 "levels", "changes", "impact", "artifacts", "suggestion",
                 "explicitRules", "derivedRules", "overrides", "changelog",
                 "tool", "input", "output", "defaultChannel"}:
            out[key] = _dumps(v)
        else:
            out[key] = _dumps(v)
    return out


# ── ID 生成(单调递增序列) ──────────────────────────────────────

_SEQ_SQL = """
CREATE TABLE IF NOT EXISTS arch_id_seqs (
    prefix TEXT PRIMARY KEY,
    last_seq INTEGER DEFAULT 0
)
"""


def _next_seq(prefix: str) -> int:
    db = _db()
    db.execute(_SEQ_SQL)
    db.execute(
        "INSERT INTO arch_id_seqs (prefix, last_seq) VALUES (?, 1) "
        "ON CONFLICT(prefix) DO UPDATE SET last_seq = last_seq + 1",
        (prefix,),
    )
    row = db.fetchone("SELECT last_seq FROM arch_id_seqs WHERE prefix = ?", (prefix,))
    db.commit()
    return row["last_seq"] if row else 1


def next_id(prefix: str) -> str:
    """生成 `prefix-<n>` id，保持 docs §2.4 前缀约定。"""
    return f"{prefix}-{_next_seq(prefix)}"


def bump_seq(prefix: str, min_seq: int) -> int:
    """把前缀序列抬升到至少 min_seq(用于与种子 id 对齐，避免碰撞)。"""
    db = _db()
    db.execute(_SEQ_SQL)
    db.execute(
        "INSERT INTO arch_id_seqs (prefix, last_seq) VALUES (?, ?) "
        "ON CONFLICT(prefix) DO UPDATE SET last_seq = MAX(last_seq, ?)",
        (prefix, min_seq, min_seq),
    )
    row = db.fetchone("SELECT last_seq FROM arch_id_seqs WHERE prefix = ?", (prefix,))
    db.commit()
    return row["last_seq"] if row else min_seq


# ── 项目库路由(统一布局: 主库默认桶 + 每项目 architect/<pid>/arch.db) ──

# 项目级表(落项目库; 其余为全局表, 恒在主库)
PROJECT_TABLES = frozenset({
    "arch_requirements", "arch_plans", "arch_task_trees",
    "arch_execution_tasks", "arch_agent_sessions", "arch_agent_messages",
    "arch_unit_tests", "arch_unit_test_sessions", "arch_unit_test_messages",
    "arch_conversations", "arch_conversation_messages",
    "arch_blueprints", "arch_tags", "arch_staging_scans",
    "arch_snapshot_records", "arch_kb_snapshots",
    "arch_semantic_assets", "arch_ast_cache", "arch_semantic_refs",
    "arch_extract_tasks",
    # M0 冻结 schema（plan-C-M0.md §6）
    "arch_framework_configs", "arch_name_tombstones", "arch_user_overlays",
    "arch_naming_conventions", "arch_glossary",
    "arch_contract_items", "arch_contract_packages",
    "arch_acceptance_reports", "arch_acceptance_facts", "arch_acceptance_opinions",
})


def _resolve_pid(project_id: Optional[str] = None, data: Optional[dict] = None) -> Optional[str]:
    """项目定位: 显式参数 > 请求上下文(contextvar) > 载荷 projectId > None(主库默认桶)。"""
    if project_id:
        return project_id
    from . import ctx
    pid = ctx.get_project()
    if pid:
        return pid
    if isinstance(data, dict):
        pid = data.get("projectId") or data.get("project_id")
        if pid:
            return pid
    return None


def _route_read(table: str, project_id: Optional[str] = None):
    """读路由。返回 (mode, db):

    - ("one", db)    单库查询(全局表恒主库; 项目表定位到项目库);
    - ("empty", None) 定位到项目但其库不存在 → 空结果(不跨项目泄漏);
    - ("scan", None)  无项目定位 → 调用方走全库扫描(主库+各项目库)。
    """
    if table not in PROJECT_TABLES:
        return "one", _db()
    from . import ctx
    pid = _resolve_pid(project_id)
    if not pid:
        return "scan", None
    db = ctx.project_db(pid, create=False)
    return ("one", db) if db is not None else ("empty", None)


def _target_db(table: str, project_id: Optional[str] = None,
               data: Optional[dict] = None):
    """写目标库: 项目表 → 项目库(按需创建)/主库默认桶; 全局表 → 主库。"""
    if table not in PROJECT_TABLES:
        return _db()
    from . import ctx
    pid = _resolve_pid(project_id, data)
    if not pid:
        return _db()
    return ctx.project_db(pid)


def _scan_dbs() -> list:
    """全库扫描列表: 主库(默认桶) + 磁盘上已存在的各项目库。"""
    from . import ctx
    dbs = [_db()]
    for pid in ctx.project_pids_on_disk():
        db = ctx.project_db(pid, create=False)
        if db is not None:
            dbs.append(db)
    return dbs


def _locate_db(table: str, row_id: str, project_id: Optional[str] = None):
    """定位行所在库(PK 探测)。返回 (db, found)。

    项目表: 有项目定位 → 该库(不存在则 found=False); 无 → 依次探测
    (主库+各项目库)，未命中时返回默认写目标(上下文项目库/主库)。全局表恒主库。
    """
    if table not in PROJECT_TABLES:
        db = _db()
        found = db.fetchone(f"SELECT id FROM {table} WHERE id = ?", (row_id,)) is not None
        return db, found
    mode, db = _route_read(table, project_id)
    if mode == "one":
        found = db.fetchone(f"SELECT id FROM {table} WHERE id = ?", (row_id,)) is not None
        return db, found
    if mode == "empty":
        return _target_db(table, project_id), False
    for d in _scan_dbs():
        if d.fetchone(f"SELECT id FROM {table} WHERE id = ?", (row_id,)):
            return d, True
    return _target_db(table, project_id), False


def _fetchall_routed(table: str, sql: str, params: tuple,
                     project_id: Optional[str] = None) -> tuple:
    """按路由执行查询。返回 (rows, mode) — mode 供调用方判断是否需合并重排。"""
    mode, db = _route_read(table, project_id)
    if mode == "one":
        return db.fetchall(sql, params), mode
    if mode == "empty":
        return [], mode
    out = []
    for d in _scan_dbs():
        out.extend(d.fetchall(sql, params))
    return out, "scan"


# ── 通用 CRUD(项目表自动路由) ──────────────────────────────────

def _insert(table: str, data: dict) -> None:
    cols = []
    params = []
    vals = []
    for k, v in data.items():
        cols.append(_to_snake(k))
        params.append("?")
        vals.append(_dumps(v))
    db = _target_db(table, data=data)
    db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(params)})",
        tuple(vals),
    )
    db.commit()


def _update(table: str, row_id: str, data: dict) -> Optional[dict]:
    sets = []
    vals = []
    for k, v in data.items():
        sets.append(f"{_to_snake(k)} = ?")
        vals.append(_dumps(v))
    db, found = _locate_db(table, row_id)
    if not sets:
        row = db.fetchone(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
        return _row_to_api(row) if row else None
    if not found:
        return None
    vals.append(row_id)
    db.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", tuple(vals))
    db.commit()
    row = db.fetchone(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    return _row_to_api(row) if row else None


def _delete(table: str, row_id: str) -> bool:
    db, found = _locate_db(table, row_id)
    if not found:
        return False
    cur = db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    db.commit()
    return cur.rowcount > 0


def _all(table: str, order_by: str = None, project_id: Optional[str] = None) -> list[dict]:
    sql = f"SELECT * FROM {table}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    rows, mode = _fetchall_routed(table, sql, (), project_id)
    out = [_row_to_api(r) for r in rows]
    if order_by and mode == "scan":
        # 多库合并后重排(保持与原单库 ORDER BY 一致的语义)
        col = order_by.split()[0]
        reverse = "DESC" in order_by.upper()
        key = _to_camel(col)
        out.sort(key=lambda r: (r.get(key) is None, r.get(key) or 0), reverse=reverse)
    return out


def _get(table: str, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
    db, found = _locate_db(table, row_id, project_id)
    if not found:
        return None
    row = db.fetchone(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    return _row_to_api(row) if row else None


def get_by_id(table: str, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
    return _get(table, row_id, project_id)


def run_atomic(items: list[tuple], project_id: Optional[str] = None,
               table: str = "arch_requirements"):
    """在单事务内执行多条写入(经 WriteQueue.execute_batch), 任一失败整体回滚。

    items = [(sql, params), ...]。仅用于 commitBatch 等需要原子的写流程。
    目标库按项目路由(上下文/显式)，缺省主库默认桶。
    """
    db = _target_db(table, project_id)
    wq = getattr(db, "_wq", None)
    if wq is not None:
        return wq.execute_batch(db._label, [(sql, params, True) for sql, params in items])
    # 无写队列(测试/内存) → 直接事务
    conn = db.conn
    conn.execute("BEGIN")
    try:
        for sql, params in items:
            conn.execute(sql, params)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ── 分域访问器 ─────────────────────────────────────────────────

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
    TABLE = "arch_requirements"

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


class PlansStore:
    TABLE = "arch_plans"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="updated_at DESC")

    @classmethod
    def get(cls, plan_id: str):
        return _get(cls.TABLE, plan_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, plan_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, plan_id, data)


class TaskTreesStore:
    TABLE = "arch_task_trees"

    @classmethod
    def get(cls, tree_id: str):
        return _get(cls.TABLE, tree_id)

    @classmethod
    def get_by_plan(cls, plan_id: str) -> Optional[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE plan_id = ? ORDER BY revision DESC",
            (plan_id,),
        )
        return _row_to_api(rows[0]) if rows else None

    @classmethod
    def upsert(cls, tree_id: str, data: dict) -> None:
        existing = _get(cls.TABLE, tree_id)
        if existing:
            _update(cls.TABLE, tree_id, data)
        else:
            _insert(cls.TABLE, data)


class ExecutionTasksStore:
    TABLE = "arch_execution_tasks"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def get(cls, task_id: str):
        return _get(cls.TABLE, task_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, task_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, task_id, data)


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


class ConversationsStore:
    """统一会话(阶段D 主干)：requirement/design/execution/unit-test 共用一张表+消息表。"""

    TABLE = "arch_conversations"
    MSG_TABLE = "arch_conversation_messages"

    @classmethod
    def all(cls, kind: str = None, project_id: str = None, limit: int = 100):
        sql = f"SELECT * FROM {cls.TABLE}"
        conds, params = [], []
        if kind:
            conds.append("kind = ?")
            params.append(kind)
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
        """创建会话；缺省补 id/时间字段。"""
        now = int(__import__("time").time() * 1000)
        payload = {
            "id": data.get("id") or next_id("cv"),
            "kind": data.get("kind", "requirement"),
            "project_id": data.get("projectId") or "",
            "req_id": data.get("reqId") or "",
            "title": data.get("title") or "",
            "status": data.get("status") or "active",
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
    def summaries(cls, kind: str = None, project_id: str = None, limit: int = 100) -> list[dict]:
        """会话摘要(用于历史导入列表): 会话头 + 消息数 + 首条用户消息预览。"""
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

def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


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

class ContractItemStore:
    """契约条目（ci-{seq} 项目内自增；状态机 draft→confirmed→injected→verifying→accepted|rejected）。"""

    TABLE = "arch_contract_items"

    @classmethod
    def next_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(seq) AS s FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def create(cls, project_id: str, item: dict, author: str = "") -> dict:
        """item: {reqId?, convId?, origin?, kind, level?, target?, intentOnly?,
        behavior?, zAxis?, acceptance?} → draft 条目。"""
        now = _now_ms()
        seq = cls.next_seq(project_id)
        data = {"id": f"ci-{seq}", "projectId": project_id, "seq": seq,
                "reqId": item.get("reqId") or "", "convId": item.get("convId") or "",
                "origin": item.get("origin") or {},
                "kind": item["kind"], "level": item.get("level") or "implementation",
                "target": item.get("target") or {},
                "intentOnly": 1 if item.get("intentOnly") else 0,
                "behavior": item.get("behavior") or {},
                "zAxis": item.get("zAxis") or [],
                "acceptance": item.get("acceptance") or {},
                "status": "draft", "staleByFramework": 0, "version": 1,
                "createdBy": author, "createdAt": now,
                "confirmedAt": 0, "injectedAt": 0, "verifiedAt": 0}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def list(cls, project_id: str, status: str = "", req_id: str = "",
             limit: int = 500) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if status:
            conds.append("status = ?")
            params.append(status)
        if req_id:
            conds.append("req_id = ?")
            params.append(req_id)
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE {' AND '.join(conds)} "
            f"ORDER BY seq ASC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def set_status(cls, row_id: str, status: str, ts_field: str = "") -> Optional[dict]:
        """状态迁移 + 时间戳列（confirmed_at/injected_at/verified_at）。"""
        patch: dict = {"status": status}
        if ts_field in ("confirmed_at", "injected_at", "verified_at"):
            patch[ts_field] = _now_ms()
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def delete(cls, row_id: str) -> bool:
        return _delete(cls.TABLE, row_id)


class ContractPackageStore:
    """契约包（cp-{seq}；注入 runner 的单元，框架快照随行冻结）。"""

    TABLE = "arch_contract_packages"

    @classmethod
    def next_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT MAX(seq) AS s FROM {cls.TABLE} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def create(cls, project_id: str, framework_snapshot: dict, item_ids: list,
               asset_refs: Optional[list] = None,
               component_refs: Optional[list] = None,
               agents_md: str = "") -> dict:
        seq = cls.next_seq(project_id)
        data = {"id": f"cp-{seq}", "projectId": project_id, "seq": seq,
                "frameworkSnapshot": framework_snapshot,
                "itemIds": item_ids, "assetRefs": asset_refs or [],
                "componentRefs": component_refs or [],
                "agentsMd": agents_md, "status": "created",
                "injectedTo": "", "createdAt": _now_ms(), "injectedAt": 0}
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def get(cls, row_id: str, project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.TABLE, row_id, project_id)

    @classmethod
    def list(cls, project_id: str, limit: int = 100) -> list[dict]:
        rows, _ = _fetchall_routed(
            cls.TABLE,
            f"SELECT * FROM {cls.TABLE} WHERE project_id = ? "
            f"ORDER BY seq DESC LIMIT ?",
            (project_id, int(limit)), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update(cls, row_id: str, patch: dict) -> Optional[dict]:
        return _update(cls.TABLE, row_id, patch)

    @classmethod
    def mark_injected(cls, row_id: str, injected_to: str = "") -> Optional[dict]:
        return _update(cls.TABLE, row_id,
                       {"status": "injected", "injectedTo": injected_to,
                        "injectedAt": _now_ms()})


class AcceptanceStore:
    """验收报告 + facts + opinions（报告 ar-{seq}；facts/opinions 无 seq，时间戳 id）。"""

    REPORTS = "arch_acceptance_reports"
    FACTS = "arch_acceptance_facts"
    OPINIONS = "arch_acceptance_opinions"

    @classmethod
    def next_report_seq(cls, project_id: str) -> int:
        rows, _ = _fetchall_routed(
            cls.REPORTS,
            f"SELECT MAX(seq) AS s FROM {cls.REPORTS} WHERE project_id = ?",
            (project_id,), project_id or None)
        s = rows[0].get("s") if rows else None
        return int(s or 0) + 1

    @classmethod
    def create_report(cls, project_id: str, package_id: str,
                      trigger_info: dict, profile: str = "strict") -> dict:
        seq = cls.next_report_seq(project_id)
        data = {"id": f"ar-{seq}", "projectId": project_id, "seq": seq,
                "packageId": package_id,
                "triggerInfo": trigger_info, "extractionProfile": profile,
                "summary": {}, "createdAt": _now_ms()}
        _insert(cls.REPORTS, data)
        return data

    @classmethod
    def get_report(cls, report_id: str,
                   project_id: Optional[str] = None) -> Optional[dict]:
        return _get(cls.REPORTS, report_id, project_id)

    @classmethod
    def list_reports(cls, project_id: str, package_id: str = "",
                     limit: int = 100) -> list[dict]:
        conds = ["project_id = ?"]
        params: list = [project_id]
        if package_id:
            conds.append("package_id = ?")
            params.append(package_id)
        rows, _ = _fetchall_routed(
            cls.REPORTS,
            f"SELECT * FROM {cls.REPORTS} WHERE {' AND '.join(conds)} "
            f"ORDER BY seq DESC LIMIT ?",
            tuple(params + [int(limit)]), project_id or None)
        return [_row_to_api(r) for r in rows]

    @classmethod
    def update_summary(cls, report_id: str, summary: dict) -> Optional[dict]:
        return _update(cls.REPORTS, report_id, {"summary": summary})

    @classmethod
    def add_fact(cls, project_id: str, report_id: str, item_id: str,
                 check_layer: str, verdict: str, evidence: dict) -> dict:
        data = {"id": f"af-{_now_ms()}-{abs(hash((report_id, item_id, check_layer))) % 10 ** 6}",
                "projectId": project_id, "reportId": report_id, "itemId": item_id,
                "checkLayer": check_layer, "verdict": verdict,
                "evidence": evidence or {}, "createdAt": _now_ms()}
        _insert(cls.FACTS, data)
        return data

    @classmethod
    def add_opinion(cls, project_id: str, report_id: str, item_id: str,
                    text: str, confidence: float, model: str,
                    evidence: dict, trigger_by: str = "") -> dict:
        data = {"id": f"ao-{_now_ms()}-{abs(hash((report_id, item_id, text[:64]))) % 10 ** 6}",
                "projectId": project_id, "reportId": report_id, "itemId": item_id,
                "text": text, "confidence": confidence, "model": model,
                "evidence": evidence or {}, "triggerBy": trigger_by,
                "createdAt": _now_ms()}
        _insert(cls.OPINIONS, data)
        return data

    @classmethod
    def report_detail(cls, report_id: str,
                      project_id: Optional[str] = None) -> Optional[dict]:
        report = _get(cls.REPORTS, report_id, project_id)
        if report is None:
            return None
        pid = report.get("projectId") or project_id
        facts, _ = _fetchall_routed(
            cls.FACTS,
            f"SELECT * FROM {cls.FACTS} WHERE project_id = ? AND report_id = ? "
            f"ORDER BY created_at ASC", (pid, report_id), pid or None)
        opinions, _ = _fetchall_routed(
            cls.OPINIONS,
            f"SELECT * FROM {cls.OPINIONS} WHERE project_id = ? AND report_id = ? "
            f"ORDER BY created_at ASC", (pid, report_id), pid or None)
        return {"report": _row_to_api(report),
                "facts": [_row_to_api(r) for r in facts],
                "opinions": [_row_to_api(r) for r in opinions]}
