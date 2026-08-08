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
    "session_ids", "test_ids", "amendments", "stats",
    "artifacts", "test_result", "levels", "last_result", "tool",
    "input", "output", "overrides", "explicit_rules", "derived_rules",
    "changelog", "default_channel", "scaffold",
    "related_to", "preferred_asset_ids",
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


# ── 通用 CRUD ──────────────────────────────────────────────────

def _insert(table: str, data: dict) -> None:
    cols = []
    params = []
    vals = []
    for k, v in data.items():
        cols.append(_to_snake(k))
        params.append("?")
        vals.append(_dumps(v))
    db = _db()
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
    if not sets:
        return get_by_id(table, row_id)
    vals.append(row_id)
    db = _db()
    db.execute(f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?", tuple(vals))
    db.commit()
    return get_by_id(table, row_id)


def _delete(table: str, row_id: str) -> bool:
    db = _db()
    cur = db.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    db.commit()
    return cur.rowcount > 0


def _all(table: str, order_by: str = None) -> list[dict]:
    db = _db()
    sql = f"SELECT * FROM {table}"
    if order_by:
        sql += f" ORDER BY {order_by}"
    return [_row_to_api(r) for r in db.fetchall(sql)]


def _get(table: str, row_id: str) -> Optional[dict]:
    row = _db().fetchone(f"SELECT * FROM {table} WHERE id = ?", (row_id,))
    return _row_to_api(row) if row else None


def get_by_id(table: str, row_id: str) -> Optional[dict]:
    return _get(table, row_id)


def run_atomic(items: list[tuple]):
    """在单事务内执行多条写入(经 WriteQueue.execute_batch), 任一失败整体回滚。

    items = [(sql, params), ...]。仅用于 commitBatch 等需要原子的写流程。
    """
    db = _db()
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
        row = _db().fetchone(
            f"SELECT * FROM {cls.TABLE} WHERE plan_id = ? ORDER BY revision DESC",
            (plan_id,),
        )
        return _row_to_api(row) if row else None

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
        rows = _db().fetchall(
            "SELECT * FROM arch_agent_messages WHERE session_id = ? "
            "ORDER BY time ASC, rowid ASC",
            (session_id,),
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def append_message(cls, msg: dict) -> None:
        _insert("arch_agent_messages", msg)

    @classmethod
    def delete(cls, session_id: str) -> bool:
        db = _db()
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
        rows = _db().fetchall(
            "SELECT * FROM arch_unit_test_messages WHERE session_id = ? "
            "ORDER BY time ASC, rowid ASC",
            (session_id,),
        )
        return [_row_to_api(r) for r in rows]

    @classmethod
    def append_message(cls, msg: dict) -> None:
        _insert("arch_unit_test_messages", msg)


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


class AgentConfigsStore:
    TABLE = "arch_agent_configs"

    @classmethod
    def all(cls):
        return _all(cls.TABLE)

    @classmethod
    def get(cls, cfg_id: str):
        return _get(cls.TABLE, cfg_id)

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, cfg_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, cfg_id, data)

    @classmethod
    def delete(cls, cfg_id: str) -> bool:
        return _delete(cls.TABLE, cfg_id)


class StagingScansStore:
    TABLE = "arch_staging_scans"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data


class AgentInstancesStore:
    TABLE = "arch_agent_instances"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="updated_at DESC")

    @classmethod
    def get(cls, instance_id: str):
        return _get(cls.TABLE, instance_id)

    @classmethod
    def get_by_key(cls, project_id: str, adapter: str, host: str):
        rows = _all(cls.TABLE)
        for r in rows:
            if r.get("projectId") == project_id and r.get("adapter") == adapter and r.get("host") == host:
                return r
        return None

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data

    @classmethod
    def update(cls, instance_id: str, data: dict) -> Optional[dict]:
        return _update(cls.TABLE, instance_id, data)

    @classmethod
    def delete(cls, instance_id: str) -> bool:
        return _delete(cls.TABLE, instance_id)


class SnapshotsStore:
    TABLE = "arch_kb_snapshots"

    @classmethod
    def all(cls):
        return _all(cls.TABLE, order_by="created_at DESC")

    @classmethod
    def create(cls, data: dict) -> dict:
        _insert(cls.TABLE, data)
        return data
