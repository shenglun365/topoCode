"""符号源双后端：codegraph(外部 CLI，可选) vs native(project.db 原生 AST)。

质量持平设计：native 后端用 TEMP 视图把 project.db 的 graph_node/graph_edge
映射为 codegraph 同构 schema(nodes/edges，contains 由同文件行区间推导)，
上游 _query_nodes/_query_edges/_cg_* 全部零改动复用。
开关：env ARCH_CODEGRAPH(on|off|auto) > main_db KV > auto（见 codegraph.py）。
"""
from __future__ import annotations

import sqlite3
from typing import Optional, Tuple

from . import codegraph as _cg_mod
from .codegraph import effective_mode, logger


def open_symbol_conn(root: Optional[str], project: Optional[str]
                     ) -> Tuple[Optional[sqlite3.Connection], str]:
    """按有效模式返回 (只读符号库连接, source标签)。

    on   → 仅 codegraph（缺失 → (None, 'codegraph')，调用方按缺失降级）；
    off  → 仅 native（不触碰用户项目目录，零外部 CLI）；
    auto → codegraph 可用则用之，否则 native（质量持平，如实标注来源）。
    """
    mode = effective_mode()
    if mode in ('on', 'auto'):
        conn = _cg_mod._open_cg(root) if root else None
        if conn is not None:
            return conn, 'codegraph'
        if mode == 'on':
            return None, 'codegraph'
    native = _open_native(root, project)
    if native is not None:
        return native, 'native'
    return None, 'native'


def _open_native(root: Optional[str], project: Optional[str]) -> Optional[sqlite3.Connection]:
    """project.db 原生符号源：TEMP 视图同构映射为 codegraph schema。

    - nodes ← graph_node（列名对齐；return_type 从 signature 推导留空占位）
    - edges ← graph_edge（kind 直通 + type_of→references；
      metadata 缺省时按 provenance 注入 confidence/resolvedBy 证据）
    - contains ← 同文件行区间包含（class 区间包住 method/function 区间），物化 TEMP 表
    """
    try:
        from .. import ctx
        from ..store.base import _resolve_pid
        pid = _resolve_pid(project)
        pdb = ctx.project_db(pid, create=False) if pid else None
        if pdb is None:
            return None
        conn = pdb.conn
        cur = conn.cursor()
        cur.execute("CREATE TEMP VIEW IF NOT EXISTS nodes AS SELECT "
                    "id, kind, name, qualified_name, file_path, "
                    "start_line, end_line, start_col AS start_column, end_col AS end_column, "
                    "signature, docstring, '' AS return_type "
                    "FROM graph_node")
        cur.execute("CREATE TEMP TABLE IF NOT EXISTS edges_contains "
                    "(source TEXT, target TEXT, kind TEXT, line INTEGER, col INTEGER, metadata TEXT)")
        cur.execute("DELETE FROM edges_contains")
        cur.execute("INSERT INTO edges_contains "
                    "SELECT c.id, m.id, 'contains', m.start_line, m.start_col, '' "
                    "FROM graph_node c JOIN graph_node m ON c.file_path = m.file_path AND c.id != m.id "
                    "WHERE c.kind = 'class' AND m.kind IN ('method', 'function') "
                    "AND m.start_line >= c.start_line AND m.end_line <= c.end_line")
        cur.execute("CREATE TEMP VIEW IF NOT EXISTS edges AS SELECT "
                    "source_id AS source, target_id AS target, "
                    "CASE kind WHEN 'type_of' THEN 'references' ELSE kind END AS kind, "
                    "line, col, "
                    "CASE WHEN metadata IS NULL OR metadata = '' THEN "
                    "json_object('confidence', CASE provenance WHEN 'parser' THEN 'exact' ELSE 'heuristic' END, "
                    "'resolvedBy', 'native-ast') ELSE metadata END AS metadata "
                    "FROM graph_edge "
                    "UNION ALL SELECT source, target, kind, line, col, metadata FROM edges_contains")
        conn.commit()
        return conn
    except Exception as e:
        logger.warning("[semantic] native 符号源打开失败: %s", e)
        return None
