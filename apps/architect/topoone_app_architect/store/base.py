"""Architect store layer — sqlite persistence via ctx architect.db.

Routers stay thin; all reads/writes go through these helpers. 契约见
docs/architect/conventions.md §7(architect.db)、docs/architect/*.md。

访问方式: `ctx.db()` (SQLiteContext，独立进程经 ctx.setup 注入)。
列名: DB 用 snake_case; 对外(前端契约)统一 camelCase, 读写自动互转。
JSON 列: 读写时自动 dumps/loads。
ID 生成: 按前缀单调递增序列(见 conventions.md §4)。
"""

import json
import sqlite3
import time
import re
from typing import Optional

# A1-T3：原 store.py 头部原样保留（helpers 纯移动）


def _db():
    """Architect sqlite context (lazy)。独立进程启动时经 `ctx.setup()` 注入；
    未注入时回退到进程内默认上下文(测试/嵌入式用，见 ctx.default_db)。"""
    from .. import ctx
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
    "spec_versions", "roles", "task_plan",
    "req_ids", "changes", "impact", "root", "history",
    "design",
    "session_ids", "test_ids", "amendments", "stats",
    "artifacts", "test_result", "levels", "last_result", "tool",
    "input", "output", "overrides", "explicit_rules", "derived_rules",
    "changelog", "default_channel", "scaffold",
    "related_to", "preferred_asset_ids", "meta", "tags",
    "detail", "ast_refs", "asset_refs", "anchor_hashes",
    "name_alias", "pending_rejudge",
    "symbols", "imports", "refs", "statements", "routes", "constants",
    "comp_ids", "progress", "messages",
    "payload", "verify_config",
    "work_tags",
    # M0 冻结 schema JSON 列（plan-C-M0.md §6）
    "affected_summary", "target_asset_ids", "anchor_basis",
    "applies_kinds", "scenarios", "alias", "origin", "target", "behavior",
    "z_axis", "item_ids", "asset_refs", "component_refs",
    "framework_snapshot", "evidence", "trigger_info", "summary",
    'skills', 'tools', 'permissions',
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


def _row_to_api_v(table: str, row: dict) -> dict:
    """版本化行读取(K1): _row_to_api + 表级迁移链惰性应用(读时补齐, 不刷库)。"""
    out = _row_to_api(row)
    from .migrations import apply_migrations
    return apply_migrations(table, out)


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
    "arch_requirements",
    "arch_unit_tests", "arch_unit_test_sessions", "arch_unit_test_messages",
    "arch_conversations", "arch_conversation_messages", "arch_docs",
    "arch_context_units",
    # v2 统一会话: coding subagent 任务
    "arch_tasks",
    "arch_blueprints", "arch_tags", "arch_staging_scans",
    "arch_snapshot_records", "arch_kb_snapshots",
    "arch_semantic_assets", "arch_ast_cache", "arch_semantic_refs",
    # M0 冻结 schema（plan-C-M0.md §6）
    "arch_framework_configs",
    "arch_naming_conventions", "arch_glossary",
    # 核心资产守护(2610 重构: 规约库+挂载; 旧 arch_asset_marks 已 DROP)
    "arch_rule_defs", "arch_target_rules",
    "arch_capability_proposals",
    "arch_contract_items", "arch_contract_packages",
    "arch_acceptance_reports", "arch_acceptance_facts", "arch_acceptance_opinions",
    # 需求跟踪台账(会话中心左栏, 跨库统一视图)
    "arch_tracking_items",
    # 语义作业(批1-3)：统一异步任务(项目库, 多实例按项目隔离)
    "arch_semantic_jobs",
    # 组件级聚合视图缓存(批3)：虚拟节点内容(可清除重生成)
    "arch_component_views",
    "arch_req_drafts",
    # architect 自有图谱基线(数据主权批A)：符号/关系按 project+rev 持久化
    "arch_graph_node", "arch_graph_edge",
    "arch_components", "arch_component_hierarchy", "arch_component_naming",
    "arch_graph_partitions",
})

# WS8 认知层→主库提升: 主库全局桶哨兵 project_id(设计稿 global-promotion-design.md)
GLOBAL_PID = "__global__"


def _resolve_pid(project_id: Optional[str] = None, data: Optional[dict] = None) -> Optional[str]:
    """项目定位: 显式参数 > 请求上下文(contextvar) > 载荷 projectId > None(主库默认桶)。"""
    if project_id:
        return project_id
    from .. import ctx
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
    from .. import ctx
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
    from .. import ctx
    pid = _resolve_pid(project_id, data)
    if not pid:
        return _db()
    return ctx.project_db(pid)


def _scan_dbs() -> list:
    """全库扫描列表: 主库(默认桶) + 磁盘上已存在的各项目库。"""
    from .. import ctx
    dbs = [_db()]
    for pid in ctx.project_pids_on_disk():
        db = ctx.project_db(pid, create=False)
        if db is not None:
            dbs.append(db)
    return dbs


_HAS_PID_CACHE: dict = {}


def _table_has_project_id(db, table: str) -> bool:
    """表是否带 project_id 列(legacy 表/需求表等无此列, 全局桶探测跳过)。"""
    key = (getattr(db, "db_path", ""), table)
    if key not in _HAS_PID_CACHE:
        try:
            cols = [r[1] for r in db.conn.execute(f"PRAGMA table_info({table})")]
        except Exception:  # noqa: BLE001
            cols = []
        _HAS_PID_CACHE[key] = "project_id" in cols
    return _HAS_PID_CACHE[key]


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
        if not found and _table_has_project_id(db, table):
            # 提升的全局桶行落在主库(project_id=__global__)——项目上下文下也要可寻址
            # (仅对带 project_id 列的表; requirements 等靠"住在项目库"定位, 无该列)
            if _db().fetchone(f"SELECT id FROM {table} WHERE id = ? AND project_id = ?",
                              (row_id, GLOBAL_PID)):
                return _db(), True
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

_TBL_COLS_CACHE: dict = {}


def _table_cols(db, table: str) -> set:
    """表列集合(带缓存)——插入前过滤载荷里的纯路由键(如 projectId)。"""
    key = (getattr(db, "db_path", "") or id(db), table)
    cols = _TBL_COLS_CACHE.get(key)
    if cols is None:
        try:
            rows = db.execute(f"PRAGMA table_info({table})").fetchall()
            cols = {r[1] if not isinstance(r, sqlite3.Row) else r["name"]
                    for r in rows}
        except Exception:  # noqa: BLE001
            cols = set()
        _TBL_COLS_CACHE[key] = cols
    return cols


def _insert_into(db, table: str, data: dict) -> None:
    cols = []
    params = []
    vals = []
    known = _table_cols(db, table)
    for k, v in data.items():
        snake = _to_snake(k)
        if known and snake not in known:
            continue  # 路由提示键(projectId 等)不落库, 防列缺失崩溃
        cols.append(snake)
        params.append("?")
        vals.append(_dumps(v))
    if not cols:
        raise RuntimeError(f"插入载荷为空(全部键不匹配表列): {table}")
    db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(params)})",
        tuple(vals),
    )
    db.commit()


def _insert(table: str, data: dict) -> None:
    _insert_into(_target_db(table, data=data), table, data)


def _insert_global(table: str, data: dict) -> dict:
    """写入主库全局桶(WS8 提升通道专用): project_id 强制 __global__。"""
    data = dict(data)
    data["projectId"] = GLOBAL_PID
    _insert_into(_db(), table, data)
    return data


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
    if not row:
        return None
    from .migrations import apply_migrations  # K1: 读时惰性迁移(未登记表恒等)
    return apply_migrations(table, _row_to_api(row))


def _fetchall_plus_global(table: str, project_id: str, where: str = "1=1",
                          params: tuple = (), order: str = "id",
                          limit: int = 200) -> list[dict]:
    """项目库行 + 主库全局桶行合并(项目行在前, WS8 消费侧只读合并)。

    where 由调用方给出(不含 project 过滤); 全局桶行 project_id=__global__。
    """
    if table not in PROJECT_TABLES or not project_id:
        return []
    base = (f"SELECT * FROM {table} WHERE ({where}) AND project_id = ? "
            f"ORDER BY {order} LIMIT {int(limit)}")
    out: list[dict] = []
    from .. import ctx
    db = ctx.project_db(project_id, create=False)
    if db is not None:
        out.extend(_row_to_api(r) for r in db.fetchall(base, (*params, project_id)))
    out.extend(_row_to_api(r) for r in _db().fetchall(base, (*params, GLOBAL_PID)))
    return out


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


def _now_ms() -> int:
    return int(time.time() * 1000)
