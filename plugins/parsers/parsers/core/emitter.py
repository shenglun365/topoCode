"""GraphEmitter — 将 Walker/Resolver 的输出写入数据库

提供:
  write_nodes(table)         → graph_node
  write_edges(edges)         → graph_edge
  clear_task_data(task_id)   → 清理旧数据
  get_edges(task_id, kind)   → 按类型查询边

依赖 AnalysisStore 作为底层 SQL 执行器。
"""

from __future__ import annotations

import logging
from typing import Optional

from .node_types import NodeKind, EdgeKind, Provenance
from .symbol_model import Node, Edge, FileSymbolTable

logger = logging.getLogger(__name__)


class GraphEmitter:
    """将 Node/Edge 写入 SQLite graph_node / graph_edge 表"""

    def __init__(self, analysis_store, task_id: str):
        """
        Args:
            analysis_store: store.analysis_store.AnalysisStore 实例
            task_id: 任务 ID
        """
        self.store = analysis_store
        self.task_id = task_id

    # ── 写节点 ───────────────────────────────────────────

    def write_nodes(self, table: FileSymbolTable) -> int:
        """将 FileSymbolTable 中的 nodes 写入 graph_node

        Returns: 写入记录数
        """
        if not table.nodes:
            return 0

        # 确保 file 记录存在
        self.store._ensure_file_record(table.file_path, table.language, self.task_id)

        rows = []
        for n in table.nodes:
            rows.append({
                "id": n.id,
                "task_id": self.task_id,
                "kind": n.kind.value,
                "name": n.name,
                "qualified_name": n.qualified_name,
                "file_path": n.file_path,
                "language": n.language,
                "start_line": n.start_line,
                "start_col": n.start_col,
                "end_line": n.end_line,
                "end_col": n.end_col,
                "signature": n.signature or "",
                "visibility": n.visibility or "",
                "is_exported": 1 if n.is_exported else 0,
                "is_async": 1 if n.is_async else 0,
                "is_static": 1 if n.is_static else 0,
                "docstring": n.docstring or "",
                "decorators": _json_list(n.decorators) if n.decorators else "",
                "type_parameters": _json_list(n.type_parameters) if n.type_parameters else "",
            })

        self.store.bulk_insert_graph_nodes(rows)
        logger.debug(f"[GraphEmitter] Wrote {len(rows)} nodes for {table.file_path}")
        return len(rows)

    # ── 写边 ─────────────────────────────────────────────

    def write_edges(self, edges: list[Edge]) -> int:
        """将 edges 写入 graph_edge

        Returns: 写入记录数
        """
        if not edges:
            return 0

        rows = []
        for e in edges:
            rows.append({
                "id": _make_edge_id(e.source, e.target, e.kind),
                "task_id": self.task_id,
                "source_id": e.source,
                "target_id": e.target,
                "kind": e.kind.value,
                "provenance": e.provenance.value,
                "line": e.line,
                "col": e.col,
                "file_path": e.file_path,
                "metadata": _json_dict(e.metadata) if e.metadata else "",
            })

        self.store.bulk_insert_edges(rows)
        logger.debug(f"[GraphEmitter] Wrote {len(rows)} edges")
        return len(rows)

    def write_contains(self, table: FileSymbolTable) -> int:
        """从 FileSymbolTable 中提取 parser 阶段的 contains 边"""
        # contains 边在 walker 内部已生成
        # 这里是备用方法，如果需要从外部补充
        return 0

    # ── 清理 ─────────────────────────────────────────────

    def clear_task_data(self):
        """清理该任务的所有旧数据"""
        self.store.clear_task_data(self.task_id)

    # ── 查询 ─────────────────────────────────────────────

    def count_nodes(self) -> int:
        return self.store.count_graph_nodes(self.task_id)

    def get_edges(self, kind: Optional[EdgeKind] = None) -> list[dict]:
        return self.store.get_graph_edges(self.task_id, kind.value if kind else None)

    def get_nodes_by_kind(self, kind: Optional[NodeKind] = None) -> list[dict]:
        return self.store.get_graph_nodes(self.task_id, kind.value if kind else None)


# ── helper ───────────────────────────────────────────────

import hashlib
import json


def _make_edge_id(source: str, target: str, kind: EdgeKind) -> str:
    raw = f"{source}->{target}:{kind.value}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _json_list(items: list) -> str:
    return json.dumps(items, ensure_ascii=False)


def _json_dict(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)
