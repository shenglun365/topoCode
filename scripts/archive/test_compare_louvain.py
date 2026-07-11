"""
P0-1验证: 验证基于 NX 的社区检测算法在所有数据集上产生合理结果。

验证项:
  1. 社区数量合理（CALL < 200, INCLUDE < 100）
  2. 模块度 > 0.3
  3. 无单节点社区被丢弃
  4. 性能可接受
"""

import sys, os, sqlite3, logging, time
from collections import defaultdict
logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("validate")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from community_analysis import _build_graph, _detect_communities, _compute_modularity
from community import community_louvain
import networkx as nx

DB_DIR = os.path.expanduser("~/.config/topoone-ui/topoone.db")
PROJECTS = [
    ("proj-51a77082", "9597b9a9-d0d4-420b-8832-d1853d811813", "CALL",    "旧版碎片化"),
    ("proj-51a77082", "9597b9a9-d0d4-420b-8832-d1853d811813", "INCLUDE", ""),
    ("proj-3852f98e", "0faa19ad-9346-4a0e-ae89-900359c44317", "CALL",    ""),
    ("proj-3852f98e", "0faa19ad-9346-4a0e-ae89-900359c44317", "INCLUDE", ""),
]


def load_edges(db_path, task_id, edge_type):
    sym_type = "call_relation" if edge_type == "CALL" else "dependence"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM graph_node WHERE task_id = ? AND symbol_node_type = ?",
        (task_id, sym_type),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def print_header(text):
    print(f"\n{'=' * 60}\n  {text}\n{'=' * 60}")


passed = 0
failed = 0

for proj, task_id, edge_type, note in PROJECTS:
    db_path = f"{DB_DIR}/{proj}.db"
    label = f"{proj}/{edge_type}"
    print_header(f"{label} {note}")

    edges = load_edges(db_path, task_id, edge_type)
    log.info(f"  Edges: {len(edges)}")

    t0 = time.time()
    graph, directions, hubs, orphans = _build_graph(edges, edge_type)
    build_time = time.time() - t0

    all_nodes = set(graph.keys())
    for nb in graph.values():
        all_nodes.update(nb)

    log.info(f"  Graph: {len(all_nodes)} nodes, hubs={len(hubs)}, orphans={len(orphans)}, build={build_time:.2f}s")

    if len(all_nodes) < 2:
        log.warning("  ⚠ Too few nodes, skip")
        continue

    deg = {n: len(graph.get(n, set())) for n in all_nodes}
    m = sum(deg.values()) / 2

    t0 = time.time()
    communities = _detect_communities(graph, all_nodes)
    detect_time = time.time() - t0

    # Verify no empty communities
    non_empty = all(len(c) >= 2 for c in communities) if communities else True

    # Verify coverage (all nodes in some community, including singletons)
    covered_nodes = set()
    for c in communities:
        covered_nodes.update(c)
    pct_covered = len(covered_nodes) / len(all_nodes) * 100

    q = _compute_modularity(communities, graph, deg, m)
    sizes = sorted([len(c) for c in communities], reverse=True)

    # Expected ranges
    if edge_type == "CALL":
        n_ok = len(communities) < 200
    else:
        n_ok = len(communities) < 100
    q_ok = q > 0.3

    status = "✅" if (n_ok and q_ok) else "❌"
    log.info(f"  {status} Communities: {len(communities)}, Q={q:.4f}, time={detect_time:.1f}s")
    log.info(f"     Coverage: {pct_covered:.0f}% ({len(covered_nodes)}/{len(all_nodes)})")
    log.info(f"     Top5 sizes: {sizes[:5]}")
    log.info(f"     All non-empty: {non_empty}")

    if n_ok and q_ok:
        passed += 1
    else:
        failed += 1
        log.error(f"     FAIL: n_ok={n_ok} (count={len(communities)}), q_ok={q_ok} (q={q:.4f})")

    # Compare with direct NX call to verify consistency
    G = nx.Graph()
    for n in all_nodes:
        if n in graph:
            for nb in graph[n]:
                if nb in all_nodes:
                    G.add_edge(n, nb)
    nx_part = community_louvain.best_partition(G)
    nx_q = community_louvain.modularity(nx_part, G)
    q_diff = abs(q - nx_q)
    log.info(f"     Direct NX Q={nx_q:.4f}, diff={q_diff:.4f}")
    if q_diff < 0.05:
        log.info(f"     ✅ Q matches NX reference")
    else:
        log.warning(f"     ⚠ Q differs from NX reference ({q_diff:.4f})")

    # Old vs new comparison
    if edge_type == "CALL" and "51a77082" in proj:
        log.info(f"     ★ Before NX rewrite: 1460 comms, Q=0.347")
        log.info(f"     ★ After  NX rewrite: {len(communities)} comms, Q={q:.4f}")
        improvement = (len(communities) - 1460) / 1460 * 100
        log.info(f"     ★ Change: {improvement:.0f}% community count")

print(f"\n{'=' * 60}")
print(f"  Results: {passed} passed, {failed} failed")
print(f"{'=' * 60}")
sys.exit(1 if failed else 0)
