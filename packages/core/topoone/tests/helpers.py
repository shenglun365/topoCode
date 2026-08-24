"""I1 测试辅助：生产 schema 种子数据。"""

from __future__ import annotations

import json


def json_dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def seed_symbols(db, task_id: str = "t1", root: str = "/proj"):
    db.execute(
        "INSERT INTO graph_node (id, task_id, kind, name, file_path, start_line, end_line, "
        "signature, docstring) VALUES (?, ?, 'function', 'parse_user', ?, 10, 20, "
        "'(user: str) -> dict', 'Parse a user string')",
        (f"sym-parse-{task_id}", task_id, f"{root}/auth.py"))
    db.execute(
        "INSERT INTO graph_node (id, task_id, kind, name, file_path, start_line, end_line) "
        "VALUES (?, ?, 'class', 'AuthService', ?, 30, 80)",
        (f"sym-auth-{task_id}", task_id, f"{root}/auth.py"))
    db.execute(
        "INSERT INTO graph_edge (id, task_id, source_id, target_id, kind) VALUES "
        "(?, ?, ?, ?, 'call')",
        (f"edge-1-{task_id}", task_id, f"sym-parse-{task_id}", f"sym-auth-{task_id}"))


def seed_communities(db, task_id: str = "t1", root: str = "/proj"):
    db.execute(
        "INSERT INTO community_hierarchy (task_id, edge_type, comm_lv, comm_id, node_count, "
        "file_count, quality_score) VALUES (?, 'INCLUDE', 'L0', 'comm-incl-L0-0001', 10, 3, 0.8)",
        (task_id,))
    db.execute(
        "INSERT INTO community_hierarchy (task_id, edge_type, comm_lv, comm_id, node_count, "
        "file_count, quality_score) VALUES (?, 'CALL', 'L0', 'comm-call-L0-0002', 5, 2, 0.6)",
        (task_id,))
    node_list = json_dumps([{"id": f"sym-parse-{task_id}", "name": "parse_user"}])
    db.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count) "
        "VALUES (?, 'INCLUDE', 'L0', 'comm-incl-L0-0001', ?, 1)",
        (task_id, node_list))
    db.execute(
        "INSERT INTO community_llm_results (task_id, edge_type, comm_lv, comm_id, name, summary, "
        "status) VALUES (?, 'INCLUDE', 'L0', 'comm-incl-L0-0001', 'Auth Module', "
        "'Handles authentication', 'completed')",
        (task_id,))
