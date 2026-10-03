"""architect 自有图谱基线存储（数据主权批A）。

KB 转纯算力服务后，符号/关系的持久事实源落 architect 库（arch_graph_node /
arch_graph_edge），按 (project_id, rev) 版本化——rev 与 arch_semantic_assets.rev
同族（baseline:<commit> | head:<sha> | workspace）。

写入原语 replace_rev：事务内整 rev 重灌（DELETE + executmany 批量 INSERT），
采集作业幂等（同 rev 重跑结果收敛）；组件三表（arch_components/hierarchy/naming）
的读写方法随批B 社区接线补齐。
"""
from __future__ import annotations

import json
import time
from typing import Dict, List, Optional

from .base import _fetchall_routed, _target_db

_NODE_COLS = ("id", "kind", "name", "qualified_name", "file_path", "language",
              "start_line", "end_line", "start_column", "end_column",
              "signature", "docstring", "return_type", "is_exported")
_EDGE_COLS = ("source", "target", "kind", "line", "col")


def _now() -> int:
    return int(time.time() * 1000)


class GraphStore:
    """arch_graph_node / arch_graph_edge 按 (project, rev) 的持久化与查询。"""

    NODE_TABLE = "arch_graph_node"
    EDGE_TABLE = "arch_graph_edge"

    # ── 写入 ──────────────────────────────────────────────────────

    @classmethod
    def replace_rev(cls, project_id: str, rev: str, nodes: List[dict],
                    edges: List[dict]) -> dict:
        """整 rev 重灌（事务）：先清该 rev 旧快照再批量写入。返回 {nodes, edges}。"""
        db = _target_db(cls.NODE_TABLE, project_id)
        now = _now()
        n_rows = []
        for n in nodes or []:
            if not (n or {}).get("id"):
                continue
            n_rows.append((
                project_id, rev, n["id"], n.get("kind") or "",
                n.get("name") or "", n.get("qualified_name") or "",
                n.get("file_path") or "", n.get("language") or "",
                int(n.get("start_line") or 0), int(n.get("end_line") or 0),
                int(n.get("start_column") or 0), int(n.get("end_column") or 0),
                n.get("signature") or "", n.get("docstring") or "",
                n.get("return_type") or "",
                1 if n.get("is_exported") else 0, now,
            ))
        e_rows = []
        seen_edges = set()
        for e in edges or []:
            key = (e.get("source"), e.get("target"), e.get("kind"))
            if not all(key) or key in seen_edges:
                continue
            seen_edges.add(key)
            e_rows.append((
                project_id, rev, key[0], key[1], key[2],
                int(e.get("line") or 0), int(e.get("col") or 0),
            ))
        db.execute("DELETE FROM arch_graph_node WHERE project_id=? AND rev=?",
                   (project_id, rev))
        db.execute("DELETE FROM arch_graph_edge WHERE project_id=? AND rev=?",
                   (project_id, rev))
        if n_rows:
            db.executemany(
                "INSERT INTO arch_graph_node (project_id, rev, id, kind, name, "
                "qualified_name, file_path, language, start_line, end_line, "
                "start_column, end_column, signature, docstring, return_type, "
                "is_exported, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                n_rows)
        if e_rows:
            db.executemany(
                "INSERT INTO arch_graph_edge (project_id, rev, source, target, "
                "kind, line, col) VALUES (?,?,?,?,?,?,?)",
                e_rows)
        db.commit()
        return {"nodes": len(n_rows), "edges": len(e_rows)}

    @classmethod
    def drop_rev(cls, project_id: str, rev: str) -> None:
        """清除整 rev 快照（rev 重建/清理用）。"""
        db = _target_db(cls.NODE_TABLE, project_id)
        db.execute("DELETE FROM arch_graph_node WHERE project_id=? AND rev=?",
                   (project_id, rev))
        db.execute("DELETE FROM arch_graph_edge WHERE project_id=? AND rev=?",
                   (project_id, rev))
        db.commit()

    # ── 查询 ──────────────────────────────────────────────────────

    @classmethod
    def counts(cls, project_id: str, rev: str) -> dict:
        rows, _ = _fetchall_routed(
            cls.NODE_TABLE,
            "SELECT (SELECT COUNT(*) FROM arch_graph_node WHERE project_id=? AND rev=?) AS n, "
            "(SELECT COUNT(*) FROM arch_graph_edge WHERE project_id=? AND rev=?) AS e",
            (project_id, rev, project_id, rev), project_id or None)
        r = rows[0] if rows else {}
        return {"nodes": int(r.get("n") or 0), "edges": int(r.get("e") or 0)}

    @classmethod
    def files(cls, project_id: str, rev: str) -> List[str]:
        """快照覆盖的文件清单（相对路径，正斜杠）。"""
        rows, _ = _fetchall_routed(
            cls.NODE_TABLE,
            "SELECT DISTINCT file_path FROM arch_graph_node "
            "WHERE project_id=? AND rev=? AND file_path != '' ORDER BY file_path",
            (project_id, rev), project_id or None)
        return [r["file_path"] for r in rows]

    @classmethod
    def nodes(cls, project_id: str, rev: str, *,
              file_path: Optional[str] = None,
              kind: Optional[str] = None,
              limit: int = 5000) -> List[dict]:
        """符号查询（file/kind 可选过滤），统一符号模型（snake_case）。"""
        sql = "SELECT * FROM arch_graph_node WHERE project_id=? AND rev=?"
        params: list = [project_id, rev]
        if file_path:
            sql += " AND file_path = ?"
            params.append(file_path)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY file_path, start_line LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.NODE_TABLE, sql, tuple(params),
                                   project_id or None)
        return [cls._node_api(r) for r in rows]

    @classmethod
    def edges(cls, project_id: str, rev: str, *,
              kind: Optional[str] = None,
              limit: int = 20000) -> List[dict]:
        sql = "SELECT * FROM arch_graph_edge WHERE project_id=? AND rev=?"
        params: list = [project_id, rev]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " LIMIT ?"
        params.append(int(limit))
        rows, _ = _fetchall_routed(cls.EDGE_TABLE, sql, tuple(params),
                                   project_id or None)
        return [{"source": r["source"], "target": r["target"], "kind": r["kind"],
                 "line": int(r.get("line") or 0), "col": int(r.get("col") or 0)}
                for r in rows]

    @classmethod
    def _node_api(cls, r: dict) -> dict:
        return {
            "id": r["id"], "kind": r.get("kind") or "", "name": r.get("name") or "",
            "qualified_name": r.get("qualified_name") or "",
            "file_path": r.get("file_path") or "", "language": r.get("language") or "",
            "start_line": int(r.get("start_line") or 0),
            "end_line": int(r.get("end_line") or 0),
            "start_column": int(r.get("start_column") or 0),
            "end_column": int(r.get("end_column") or 0),
            "signature": r.get("signature") or "",
            "docstring": r.get("docstring") or "",
            "return_type": r.get("return_type") or "",
            "is_exported": bool(r.get("is_exported")),
        }


class ComponentStore:
    """arch_components / arch_component_hierarchy（批B 社区结果承载，A1 先建）。"""

    TABLE = "arch_components"

    @classmethod
    def replace_rev(cls, project_id: str, rev: str,
                    components: List[dict], hierarchy: List[dict]) -> dict:
        db = _target_db(cls.TABLE, project_id)
        now = _now()
        c_rows = []
        for c in components or []:
            if not (c or {}).get("id"):
                continue
            c_rows.append((
                project_id, rev, c["id"], c.get("name") or "",
                c.get("summary") or "",
                json.dumps(c.get("owns") or [], ensure_ascii=False),
                c.get("source") or "community", now, now,
            ))
        h_rows = []
        for h in hierarchy or []:
            cid = (h or {}).get("childId") or (h or {}).get("child_id") or ""
            if not cid:
                continue
            h_rows.append((project_id, rev, cid,
                           h.get("parentId") or h.get("parent_id") or "",
                           int(h.get("level") or 0)))
        db.execute("DELETE FROM arch_components WHERE project_id=? AND rev=?",
                   (project_id, rev))
        db.execute("DELETE FROM arch_component_hierarchy WHERE project_id=? AND rev=?",
                   (project_id, rev))
        if c_rows:
            db.executemany(
                "INSERT INTO arch_components (project_id, rev, id, name, summary, "
                "owns, source, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                c_rows)
        if h_rows:
            db.executemany(
                "INSERT INTO arch_component_hierarchy (project_id, rev, child_id, "
                "parent_id, level) VALUES (?,?,?,?,?)",
                h_rows)
        db.commit()
        return {"components": len(c_rows), "hierarchy": len(h_rows)}

    @classmethod
    def list_rev(cls, project_id: str, rev: str) -> List[dict]:
        """目录形状（catalog 最小消费形状 {id,name,owns,parentId} 直配接缝）。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT c.*, h.parent_id AS parent_id FROM arch_components c "
            "LEFT JOIN arch_component_hierarchy h ON h.project_id = c.project_id "
            "AND h.rev = c.rev AND h.child_id = c.id "
            "WHERE c.project_id=? AND c.rev=? ORDER BY c.id",
            (project_id, rev), project_id or None)
        out = []
        for r in rows:
            try:
                owns = json.loads(r.get("owns") or "[]")
            except Exception:  # noqa: BLE001
                owns = []
            out.append({
                "id": r["id"], "name": r.get("name") or "",
                "summary": r.get("summary") or "", "owns": owns,
                "parentId": r.get("parent_id") or "",
                "source": r.get("source") or "community",
            })
        return out

    @classmethod
    def latest_rev(cls, project_id: str) -> str:
        """最近一次写入组件结果的 rev（无则 ''）。"""
        rows, _ = _fetchall_routed(
            cls.TABLE,
            "SELECT rev, MAX(updated_at) AS ts FROM arch_components "
            "WHERE project_id=? GROUP BY rev ORDER BY ts DESC LIMIT 1",
            (project_id,), project_id or None)
        return (rows[0] or {}).get("rev") or "" if rows else ""
