#!/usr/bin/env python3
"""多语言解析对齐度量：codegraph 基准 vs native(core) 实测。

对给定项目 root：
  - codegraph 基准：<root>/.codegraph/codegraph.db（存在才有对比列）
  - native 实测：core 注册表 root_path 反查 → project.db 最新 done task 的 graph_node/graph_edge

输出各 kind 分布与 per-file 覆盖率对比，用于「native 提取对齐 codegraph」的验收。

用法：
  python3 scripts/parse_parity.py <project_root> [--json]
例：
  python3 scripts/parse_parity.py /home/cuser/soft/fastapi-0.104.1
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter

TOPONEDB = os.path.expanduser("~/.topocode/topoone.db")
DATADIR = os.environ.get("TOPOCODE_DB_DIR") or os.path.expanduser("~/.topocode")


def core_db_for(root: str) -> str | None:
    root = os.path.abspath(root)
    pid = None
    sig = os.path.join(root, ".topocode", "proj-id")
    if os.path.isfile(sig):
        pid = open(sig, encoding="utf-8").read().strip() or None
    if not pid and os.path.isfile(TOPONEDB):
        c = sqlite3.connect(f"file:{TOPONEDB}?mode=ro", uri=True)
        row = c.execute("SELECT id FROM projects WHERE root_path=?", (root,)).fetchone()
        pid = row[0] if row else None
        c.close()
    if not pid:
        return None
    db = os.path.join(DATADIR, "projects", pid, "project.db")
    return db if os.path.isfile(db) else None


def latest_task_db(db: str) -> sqlite3.Connection:
    """取最新 done 任务的图数据视图（native 工作图口径）。

    task 元数据在主库(topoone.db)，图数据在 project.db——跨库查 task_id。
    """
    tid = None
    if os.path.isfile(TOPONEDB):
        m = sqlite3.connect(f"file:{TOPONEDB}?mode=ro", uri=True)
        try:
            pid = os.path.basename(os.path.dirname(os.path.dirname(db)))
            row = m.execute(
                "SELECT id FROM analysis_tasks WHERE status='done' AND project_id=? "
                "ORDER BY created_at DESC LIMIT 1", (pid,)).fetchone()
            tid = row[0] if row else None
        finally:
            m.close()
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    if tid:
        c.execute(f"CREATE TEMP VIEW v_nodes AS SELECT * FROM graph_node WHERE task_id='{tid}'")
        c.execute(f"CREATE TEMP VIEW v_edges AS SELECT * FROM graph_edge WHERE task_id='{tid}'")
    else:
        c.execute("CREATE TEMP VIEW v_nodes AS SELECT * FROM graph_node")
        c.execute("CREATE TEMP VIEW v_edges AS SELECT * FROM graph_edge")
    return c


def kind_counts(conn: sqlite3.Connection, nodes: str, edges: str,
                n_kind: str = "kind", e_kind: str = "kind") -> tuple[Counter, Counter, int, int]:
    nk = Counter({r[0]: r[1] for r in conn.execute(f"SELECT {n_kind}, COUNT(*) FROM {nodes} GROUP BY {n_kind}")})
    ek = Counter({r[0]: r[1] for r in conn.execute(f"SELECT {e_kind}, COUNT(*) FROM {edges} GROUP BY {e_kind}")})
    return nk, ek, sum(nk.values()), sum(ek.values())


def files_with_symbols(conn: sqlite3.Connection, table: str, fp_col: str,
                       exclude: str) -> set[str]:
    q = (f"SELECT DISTINCT {fp_col} FROM {table} WHERE kind NOT IN ({exclude}) "
         "AND kind != 'import'")
    return {r[0] for r in conn.execute(q)}


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    as_json = "--json" in sys.argv
    root = os.path.abspath(root)
    cg_db = os.path.join(root, ".codegraph", "codegraph.db")
    core_db = core_db_for(root)
    if not core_db:
        print(f"[parity] native project.db not found for {root}")
        return 1

    cg = sqlite3.connect(f"file:{cg_db}?mode=ro", uri=True) if os.path.isfile(cg_db) else None
    co = latest_task_db(core_db)

    cg_nk, cg_ek, cg_nt, cg_et = kind_counts(cg, "nodes", "edges") if cg else (Counter(), Counter(), 0, 0)
    co_nk, co_ek, co_nt, co_et = kind_counts(co, "v_nodes", "v_edges")

    print(f"project: {root}")
    print(f"{'kind':<14}{'codegraph':>12}{'native':>12}{'coverage':>10}")
    all_kinds = sorted(set(cg_nk) | set(co_nk) - {"file"})
    for k in sorted(set(list(cg_nk) + list(co_nk))):
        if k == "file":
            continue
        cgn, con = cg_nk.get(k, 0), co_nk.get(k, 0)
        cov = f"{(con / cgn * 100):.0f}%" if cgn else "-"
        print(f"{k:<14}{cgn:>12}{con:>12}{cov:>10}")
    print(f"{'-- nodes total --':<14}{cg_nt:>12}{co_nt:>12}"
          f"{(co_nt / cg_nt * 100 if cg_nt else 0):>9.0f}%")
    print()
    print(f"{'edge kind':<14}{'codegraph':>12}{'native':>12}{'coverage':>10}")
    for k in sorted(set(list(cg_ek) + list(co_ek))):
        cge, coe = cg_ek.get(k, 0), co_ek.get(k, 0)
        cov = f"{(coe / cge * 100):.0f}%" if cge else "-"
        print(f"{k:<14}{cge:>12}{coe:>12}{cov:>10}")
    print(f"{'-- edges total --':<14}{cg_et:>12}{co_et:>12}"
          f"{(co_et / cg_et * 100 if cg_et else 0):>9.0f}%")

    # per-file 符号覆盖（排除 file/import）
    if cg:
        cg_files = files_with_symbols(cg, "nodes", "file_path", "'file'")
        co_rows = co.execute("SELECT file_path FROM v_nodes WHERE kind != 'import'").fetchall()
        co_files = {r[0] for r in co_rows}
        common = cg_files & co_files
        print(f"\nfiles with symbols: codegraph={len(cg_files)} native={len(co_files)} common={len(common)}")

    if as_json:
        print(json.dumps({
            "nodes": dict(cg_nk), "nodes_native": dict(co_nk),
            "edges": dict(cg_ek), "edges_native": dict(co_ek),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
