"""Shared utilities for web_server modules"""

import hashlib
import json
import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

# ── Global state (injected at startup) ──
multi_db = None
zmq_server = None
plantuml_cache_db: Optional[sqlite3.Connection] = None
http_port = 3456
web_tool_executor = None


def set_globals(multi_db_instance, zmq_server_instance=None, port=3456, executor=None):
    global multi_db, zmq_server, http_port, web_tool_executor
    multi_db = multi_db_instance
    zmq_server = zmq_server_instance
    http_port = port
    web_tool_executor = executor


def get_db():
    return multi_db


def get_zmq():
    return zmq_server


# ── PlantUML Cache ──

def _init_cache_db(cache_path: str):
    global plantuml_cache_db
    plantuml_cache_db = sqlite3.connect(cache_path, check_same_thread=False)
    plantuml_cache_db.execute(
        "CREATE TABLE IF NOT EXISTS plantuml_cache ("
        "  code_hash TEXT PRIMARY KEY,"
        "  code TEXT NOT NULL,"
        "  svg TEXT NOT NULL,"
        "  created_at DATETIME DEFAULT CURRENT_TIMESTAMP"
        ")"
    )
    plantuml_cache_db.commit()


def _get_cached_plantuml(code_hash: str) -> Optional[str]:
    if not plantuml_cache_db:
        return None
    cursor = plantuml_cache_db.execute(
        "SELECT svg FROM plantuml_cache WHERE code_hash = ?", (code_hash,)
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _set_cached_plantuml(code_hash: str, code: str, svg: str):
    if not plantuml_cache_db:
        return
    plantuml_cache_db.execute(
        "INSERT OR REPLACE INTO plantuml_cache (code_hash, code, svg) VALUES (?, ?, ?)",
        (code_hash, code, svg),
    )
    plantuml_cache_db.commit()


def _clear_plantuml_cache():
    if plantuml_cache_db:
        plantuml_cache_db.execute("DELETE FROM plantuml_cache")
        plantuml_cache_db.commit()


# ── Project / Task / Doc Resolution ──

def _resolve_project_db(task_id: str):
    from fastapi import HTTPException
    task_row = multi_db.main_db.fetchone(
        "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
    )
    if not task_row:
        raise HTTPException(404, f"Task {task_id} not found")
    return task_row["project_id"], multi_db.get_project_db(task_row["project_id"])


def _resolve_project_by_doc_id(doc_id: str) -> Optional[str]:
    if not multi_db:
        return None
    task_id = _extract_task_id_from_doc_id(doc_id)
    if task_id:
        row = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if row:
            return row["project_id"]
    row = multi_db.main_db.fetchone(
        "SELECT project_id FROM doc_project_map WHERE doc_id = ?", (doc_id,)
    )
    if row:
        return row["project_id"]
    projects = multi_db.main_db.fetchall("SELECT id FROM projects")
    for proj in projects:
        pid = proj["id"]
        try:
            pdb = multi_db.get_project_db(pid)
            if pdb.fetchone("SELECT 1 FROM report_subdocs WHERE id=?", (doc_id,)):
                multi_db.main_db.execute(
                    "INSERT OR IGNORE INTO doc_project_map (doc_id, project_id, task_id) VALUES (?, ?, ?)",
                    (doc_id, pid, task_id or ""),
                )
                return pid
        except Exception:
            continue
    return None


def _extract_task_id_from_doc_id(doc_id: str) -> Optional[str]:
    if doc_id.startswith("overall-"):
        return doc_id[len("overall-"):]
    if doc_id.startswith("subdoc-"):
        rest = doc_id[len("subdoc-"):]
        idx = rest.find("-")
        return rest[:idx] if idx > 0 else rest
    return None


def _find_file_alternatives(project_id: str, path: str) -> list:
    basename = os.path.basename(path)
    if not basename:
        return []
    try:
        project_db = multi_db.get_project_db(project_id)
        seen = set()
        results = []

        def add(row):
            fp = row[0]
            if fp not in seen:
                seen.add(fp)
                results.append({"file_path": fp, "file_name": row[1], "language": row[2]})

        for row in project_db.execute(
            "SELECT file_path, file_name, language FROM source_files WHERE file_path LIKE ?",
            (f"%/{basename}",),
        ).fetchall():
            add(row)

        if not results:
            name_no_ext = os.path.splitext(basename)[0]
            if name_no_ext:
                for row in project_db.execute(
                    "SELECT file_path, file_name, language FROM source_files WHERE file_name = ?",
                    (name_no_ext,),
                ).fetchall():
                    add(row)

        if not results:
            short = basename[:8].replace(".", "_")
            for row in project_db.execute(
                "SELECT file_path, file_name, language FROM source_files WHERE file_name LIKE ?",
                (f"%{short}%",),
            ).fetchall():
                add(row)

        return results
    except Exception:
        return []


# ── Heatmap helper ──

def _drill_heatmap(pdb, task_id, et, comm_lv, comm_id, size, project_root):
    import community_data as cd
    children = cd.get_community_children(pdb, task_id, et, comm_id)
    if not children:
        return {"rows": [], "cols": [], "matrix": [], "maxCount": 0}

    child_ids = [c["commId"] for c in children]
    child_names = {c["commId"]: c.get("name") or c["commId"] for c in children}

    _rel = cd._make_rel(project_root)

    file_child = {}
    for child_cid in child_ids:
        doc_rows = pdb.fetchall(
            "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, child_cid)
        )
        for dr in doc_rows:
            try:
                nodes = json.loads(dr["node_list"]) if isinstance(dr["node_list"], str) else dr["node_list"] or []
            except Exception:
                nodes = []
            for n in (nodes if isinstance(nodes, list) else [nodes]):
                key = str(n) if isinstance(n, str) else str(n.get("id", ""))
                fp = _rel(key)
                if fp:
                    clean = fp.split(':')[0] if ':' in fp else fp
                    if clean and clean not in file_child:
                        file_child[clean] = child_cid

    if not file_child:
        return {"rows": [], "cols": [], "matrix": [], "maxCount": 0}

    kind = "imports" if et == "INCLUDE" else "calls"
    all_ge = pdb.fetchall(
        "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
        (task_id, kind)
    )
    hash_to_path = cd.resolve_call_symbols(pdb, task_id, all_ge, _rel) if et == "CALL" else {}

    edge_counts = {}
    for e in all_ge:
        src = _rel(e["source_id"] or "")
        tgt = _rel(e["target_id"] or "")
        if not src or not tgt:
            continue
        if ':' in src: src = src.split(':')[0]
        if ':' in tgt: tgt = tgt.split(':')[0]
        src = hash_to_path.get(src, src)
        tgt = hash_to_path.get(tgt, tgt)
        src_child = file_child.get(src)
        tgt_child = file_child.get(tgt)
        if not src_child or not tgt_child or src_child == tgt_child:
            continue
        pair = (src_child, tgt_child)
        edge_counts[pair] = edge_counts.get(pair, 0) + 1

    n = len(child_ids)
    comm_index = {cid: i for i, cid in enumerate(child_ids)}
    matrix = [[0] * n for _ in range(n)]
    for (src_c, tgt_c), cnt in edge_counts.items():
        si = comm_index.get(src_c)
        ti = comm_index.get(tgt_c)
        if si is not None and ti is not None:
            matrix[si][ti] = cnt

    max_count = max(max(row) for row in matrix) if n > 0 else 0
    return {
        "rows": [child_names[cid] for cid in child_ids],
        "cols": [child_names[cid] for cid in child_ids],
        "matrix": matrix, "maxCount": max_count,
        "commIds": child_ids
    }


# ── ZMQ publish ──

def _publish(channel: str, event: str, data: dict):
    global zmq_server
    if zmq_server:
        try:
            zmq_server.publish(channel, event, data)
        except Exception:
            pass


# ── Chat table setup ──

def _ensure_chat_tables():
    if not multi_db:
        return
    multi_db.main_db.execute("""
        CREATE TABLE IF NOT EXISTS chat_archives (
            id TEXT PRIMARY KEY,
            session_id TEXT,
            project_id TEXT,
            title TEXT,
            content TEXT NOT NULL,
            category TEXT DEFAULT 'note',
            tags TEXT DEFAULT '',
            source TEXT DEFAULT 'manual',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    # 迁移: chat_notes → chat_drafts (便签表改名, 保留数据)
    try:
        _old = multi_db.main_db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_notes'"
        )
        _new = multi_db.main_db.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chat_drafts'"
        )
        if _old and not _new:
            multi_db.main_db.execute("ALTER TABLE chat_notes RENAME TO chat_drafts")
            logger.info("[chat] migrated chat_notes → chat_drafts")
    except Exception as e:
        logger.warning(f"[chat] chat_notes→chat_drafts migration skipped: {e}")
    multi_db.main_db.execute("""
        CREATE TABLE IF NOT EXISTS chat_drafts (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT '',
            content TEXT DEFAULT '',
            refs TEXT DEFAULT '[]',
            status TEXT DEFAULT 'draft',
            session_id TEXT,
            message_id TEXT,
            project_id TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    """)
    multi_db.main_db.execute("""
        CREATE TABLE IF NOT EXISTS doc_categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            parent_id TEXT REFERENCES doc_categories(id),
            sort_order INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)


# ── i18n for index page ──

_INDEX_I18N = {
    'zh-CN': {
        'title': 'TopoCode 文档', 'search_placeholder': '搜索项目/任务...', 'search': '搜索',
        'per_page_50': '50条/页', 'per_page_100': '100条/页', 'per_page_200': '200条/页',
        'total': '共 {n} 条', 'ai': 'AI助手',
        'no_task': '资源项目 — 无需分析任务',
        'generated': '已生成', 'not_generated': '未生成', 'no_matches': '暂无匹配结果',
    },
    'en-US': {
        'title': 'TopoCode Documents', 'search_placeholder': 'Search projects/tasks...', 'search': 'Search',
        'per_page_50': '50/page', 'per_page_100': '100/page', 'per_page_200': '200/page',
        'total': 'Total {n}', 'ai': 'AI Assistant',
        'no_task': 'Resource — no analysis',
        'generated': 'Done', 'not_generated': 'Pending', 'no_matches': 'No matches',
    },
}
