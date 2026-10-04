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
        # 节点按 id 去重(keep-first): KB walker 对 TS/JS 变量声明存在双路径提取
        # (显式路径+通用遍历), 同 id 重复条目会撞 UNIQUE(project_id,rev,id)。
        # keep-first 实证安全: 361 重复组中 128 组 qualified_name 链不同, 全部
        # 第一条=显式路径产出的完整作用域链(顺序稳定)。
        seen_nodes: set = set()
        n_rows = []
        for n in nodes or []:
            if not (n or {}).get("id"):
                continue
            if n["id"] in seen_nodes:
                continue
            seen_nodes.add(n["id"])
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

    @classmethod
    def merge_partition(cls, project_id: str, rev: str, nodes: List[dict],
                        edges: List[dict], files: List[str]) -> dict:
        """分区增量落库(D3)：删该分区文件旧节点及其关联边，再合并插入。

        分区文件集不相交(拆分保证)，多分区串行落库同一 rev 互不覆盖；
        重跑同分区幂等(先删后插)。返回 {nodes, edges}。"""
        db = _target_db(cls.NODE_TABLE, project_id)
        file_list = [f for f in (files or []) if f]
        # 1) 删旧: 分区文件节点(file_path 命中 + file 虚拟节点), 收集被删 id
        deleted_ids: set = set()
        for i in range(0, len(file_list), 400):
            chunk = file_list[i:i + 400]
            ph = ",".join("?" * len(chunk))
            rows = db.fetchall(
                f"SELECT id FROM arch_graph_node WHERE project_id=? AND rev=?"
                f" AND (file_path IN ({ph}) OR id IN ({ph}))",
                (project_id, rev, *chunk, *(f"file:{c}" for c in chunk)))
            deleted_ids |= {r["id"] for r in (rows or [])}
            db.execute(f"DELETE FROM arch_graph_node WHERE project_id=? AND rev=?"
                       f" AND (file_path IN ({ph}) OR id IN ({ph}))",
                       (project_id, rev, *chunk, *(f"file:{c}" for c in chunk)))
        # 2) 端点在被删节点集的边一并删(分批 IN)
        dl = list(deleted_ids)
        for i in range(0, len(dl), 400):
            chunk = dl[i:i + 400]
            ph = ",".join("?" * len(chunk))
            db.execute(f"DELETE FROM arch_graph_edge WHERE project_id=? AND rev=?"
                       f" AND (source IN ({ph}) OR target IN ({ph}))",
                       (project_id, rev, *chunk, *chunk))
        # 3) 插入本批(节点去重 keep-first, 边端点须存在于 现存∪新批)
        kept_ids = {r["id"] for r in db.fetchall(
            "SELECT id FROM arch_graph_node WHERE project_id=? AND rev=?",
            (project_id, rev))}
        now = _now()
        seen_nodes: set = set()
        n_rows = []
        for n in nodes or []:
            if not (n or {}).get("id") or n["id"] in seen_nodes:
                continue
            seen_nodes.add(n["id"])
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
        valid = kept_ids | seen_nodes
        seen_edges = set()
        e_rows = []
        for e in edges or []:
            key = (e.get("source"), e.get("target"), e.get("kind"))
            if not all(key) or key in seen_edges:
                continue
            if key[0] not in valid or key[1] not in valid:
                continue
            seen_edges.add(key)
            e_rows.append((
                project_id, rev, key[0], key[1], key[2],
                int(e.get("line") or 0), int(e.get("col") or 0),
            ))
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
    def prune_old_revs(cls, project_id: str, keep: int = 2) -> int:
        """修剪旧图快照(数据主权批E): 按最近写入保留 keep 个 rev(当前+DIFF
        基准), 更旧的节点/边清理。与 ComponentStore.prune_old_revs 配套
        (collect_graph 采集尾部调用)。返回删除 rev 数。"""
        db = _target_db(cls.NODE_TABLE, project_id)
        rows = db.fetchall(
            "SELECT rev FROM arch_graph_node WHERE project_id=?"
            " GROUP BY rev ORDER BY MAX(updated_at) DESC LIMIT -1 OFFSET ?",
            (project_id, keep))
        n = 0
        for r in (rows or []):
            rev = r["rev"]
            db.execute("DELETE FROM arch_graph_edge WHERE project_id=? AND rev=?",
                       (project_id, rev))
            cur = db.execute("DELETE FROM arch_graph_node WHERE project_id=? AND rev=?",
                             (project_id, rev))
            n += 1 if (cur.rowcount or 0) > 0 else 0
        db.commit()
        return n

    @classmethod
    def rev_list(cls, project_id: str) -> List[dict]:
        """全部快照 rev 清单(D3/数据主权: 各 head 的基线数据管理面)。

        返回 [{rev, nodes, edges, files, updatedAt}] 按 updatedAt 新→旧。"""
        db = _target_db(cls.NODE_TABLE, project_id)
        rows = db.fetchall(
            "SELECT n.rev AS rev, COUNT(*) AS nodes, MAX(n.updated_at) AS updated_at,"
            " (SELECT COUNT(*) FROM arch_graph_edge e WHERE e.project_id=n.project_id"
            "   AND e.rev=n.rev) AS edges,"
            " (SELECT COUNT(DISTINCT n2.file_path) FROM arch_graph_node n2"
            "   WHERE n2.project_id=n.project_id AND n2.rev=n.rev AND n2.file_path!='') AS files"
            " FROM arch_graph_node n WHERE n.project_id=? GROUP BY n.rev"
            " ORDER BY updated_at DESC", (project_id,))
        return [{"rev": r["rev"], "nodes": int(r["nodes"] or 0),
                 "edges": int(r["edges"] or 0), "files": int(r["files"] or 0),
                 "updatedAt": int(r["updated_at"] or 0)} for r in (rows or [])]

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


# ComponentStore 自本文件拆分(store/component.py, 行数门禁); 此处重导出兼容
from .component import ComponentStore  # noqa: F401
