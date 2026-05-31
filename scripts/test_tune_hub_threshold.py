"""
P0-2: Tune HUB threshold parameters and measure effect on community quality.

Grid search over HUB_DEGREE_RATIO × HUB_MIN_DEGREE.
For each combo: report hub/orphan counts, run Louvain (custom + networkx), compare.

Target: reduce CALL L0 fragmentation from 1363 to a reasonable range (50-500 communities).
"""

import sys, os, sqlite3, logging, time
from collections import defaultdict
from typing import List, Set, Dict, Tuple
from dataclasses import dataclass
from itertools import product

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("test_hub")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import community_analysis as ca_mod
from community_analysis import _build_graph, _detect_communities, _compute_modularity
from config import HUB_DEGREE_RATIO as ORIG_RATIO, HUB_MIN_DEGREE as ORIG_MIN

import networkx as nx
from community import community_louvain


DB_DIR = os.path.expanduser("~/.config/topoone-ui/topoone.db")

PROJECTS = [
    {
        "label": "proj-51a77082",
        "path": f"{DB_DIR}/proj-51a77082.db",
        "task_id": "9597b9a9-d0d4-420b-8832-d1853d811813",
    },
    {
        "label": "proj-3852f98e",
        "path": f"{DB_DIR}/proj-3852f98e.db",
        "task_id": "0faa19ad-9346-4a0e-ae89-900359c44317",
    },
]

# Grid search
RATIOS = [0.30, 0.15, 0.10, 0.05]
MIN_DEGS = [50, 30, 20, 10]


def load_edges(db_path: str, task_id: str, edge_type: str) -> List[Dict]:
    sym_type = "call_relation" if edge_type == "CALL" else "dependence"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM graph_node WHERE task_id = ? AND symbol_node_type = ?",
        (task_id, sym_type),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def graph_to_networkx(graph: Dict[str, Set[str]]) -> nx.Graph:
    G = nx.Graph()
    for node, neighbors in graph.items():
        for nb in neighbors:
            G.add_edge(node, nb)
    return G


def communities_from_partition(partition: Dict) -> List[Set[str]]:
    comm_map = defaultdict(set)
    for node, cid in partition.items():
        comm_map[cid].add(node)
    return sorted([s for s in comm_map.values() if len(s) >= 2], key=len, reverse=True)


@dataclass
class GridResult:
    proj: str
    edge_type: str
    ratio: float
    min_deg: int
    raw_nodes: int
    raw_edges: int
    hubs: int
    orphans: int
    filtered_nodes: int
    filtered_edges: int
    custom_n_comms: int
    custom_mod: float
    nx_n_comms: int
    nx_mod: float


def run_grid_point(edges: List[Dict], edge_type: str, proj_label: str,
                   ratio: float, min_deg: int) -> GridResult:
    ca_mod.HUB_DEGREE_RATIO = ratio
    ca_mod.HUB_MIN_DEGREE = min_deg
    try:
        graph, directions, hubs, orphans = _build_graph(edges, edge_type)
        all_nodes = set(graph.keys())
        for nb in graph.values():
            all_nodes.update(nb)

        edge_set = set()
        for n, nbs in graph.items():
            for nb in nbs:
                if (nb, n) not in edge_set:
                    edge_set.add((n, nb))
        filtered_edges = len(edge_set)

        raw_node_set = set()
        for e in edges:
            if edge_type == "INCLUDE":
                raw_node_set.add(str(e.get("file_id", "")))
                raw_node_set.add(e.get("include_path", ""))
            else:
                raw_node_set.add(f"{e.get('caller_file_id', '')}:{e.get('caller_func_name', '')}")
                raw_node_set.add(f"{e.get('callee_file_id', '')}:{e.get('callee_name', '')}")
        raw_nodes = len(raw_node_set)
        raw_edges = len(edges)

        deg = {n: len(graph.get(n, set())) for n in all_nodes}
        m = sum(deg.values()) / 2

        if len(all_nodes) < 2:
            return GridResult(proj=proj_label, edge_type=edge_type, ratio=ratio, min_deg=min_deg,
                raw_nodes=raw_nodes, raw_edges=raw_edges, hubs=len(hubs), orphans=len(orphans),
                filtered_nodes=len(all_nodes), filtered_edges=filtered_edges,
                custom_n_comms=0, custom_mod=0.0, nx_n_comms=0, nx_mod=0.0)

        # Custom Louvain (via module, now NX-based)
        custom_comms = _detect_communities(graph, all_nodes)
        custom_mod = _compute_modularity(custom_comms, graph, deg, m) if m > 0 else 0.0

        # Networkx Louvain (always full)
        G = graph_to_networkx(graph)
        nx_partition = community_louvain.best_partition(G)
        nx_mod = community_louvain.modularity(nx_partition, G)
        nx_comms = communities_from_partition(nx_partition)

        return GridResult(proj=proj_label, edge_type=edge_type, ratio=ratio, min_deg=min_deg,
            raw_nodes=raw_nodes, raw_edges=raw_edges, hubs=len(hubs), orphans=len(orphans),
            filtered_nodes=len(all_nodes), filtered_edges=filtered_edges,
            custom_n_comms=len(custom_comms), custom_mod=round(custom_mod, 6),
            nx_n_comms=len(nx_comms), nx_mod=round(nx_mod, 6))
    finally:
        ca_mod.HUB_DEGREE_RATIO = ORIG_RATIO
        ca_mod.HUB_MIN_DEGREE = ORIG_MIN


def print_header(text: str):
    print(f"\n{'=' * 70}")
    print(f"  {text}")
    print(f"{'=' * 70}")


def main():
    all_results: List[GridResult] = []

    for proj in PROJECTS:
        label = proj["label"]
        task_id = proj["task_id"]
        db_path = proj["path"]
        if not os.path.exists(db_path):
            log.warning(f"  DB not found: {db_path}")
            continue

        for edge_type in ("CALL", "INCLUDE"):
            print_header(f"{label} | {edge_type}")
            edges = load_edges(db_path, task_id, edge_type)
            log.info(f"  Loaded {len(edges)} edges")
            if not edges:
                continue

            for ratio, min_deg in product(RATIOS, MIN_DEGS):
                t0 = time.time()
                r = run_grid_point(edges, edge_type, label, ratio, min_deg)
                elapsed = time.time() - t0
                all_results.append(r)
                log.info(f"  ratio={ratio:.2f} min_deg={min_deg:2d} → "
                         f"hubs={r.hubs:4d} orphs={r.orphans:4d} "
                         f"nodes={r.filtered_nodes:5d} edges={r.filtered_edges:5d} "
                         f"custom={r.custom_n_comms:4d}(mod={r.custom_mod:.4f}) "
                         f"nx={r.nx_n_comms:4d}(mod={r.nx_mod:.4f}) "
                         f"[{elapsed:.1f}s]")

    # Summary table
    print_header("GRID SEARCH RESULTS")
    hdr = (f"{'Proj':<16} {'Type':<6} {'Ratio':<6} {'MinD':<5} "
           f"{'Hubs':<5} {'Orph':<5} {'Nodes':<7} {'Edges':<7} "
           f"{'Cust#':<6} {'CustQ':<8} {'NX#':<6} {'NXQ':<8}")
    print(hdr)
    print("-" * 85)
    for r in all_results:
        p = r.proj.split()[0]
        print(f"{p:<16} {r.edge_type:<6} {r.ratio:<6.2f} {r.min_deg:<5d} "
              f"{r.hubs:<5d} {r.orphans:<5d} {r.filtered_nodes:<7d} {r.filtered_edges:<7d} "
              f"{r.custom_n_comms:<6d} {r.custom_mod:<8.4f} "
              f"{r.nx_n_comms:<6d} {r.nx_mod:<8.4f}")

    # Recommendations
    print_header("RECOMMENDATIONS")
    keys = set((r.proj.split()[0], r.edge_type) for r in all_results)
    for proj_short, edge_type in sorted(keys):
        subset = [r for r in all_results if r.proj.startswith(proj_short) and r.edge_type == edge_type]
        if not subset:
            continue

        current = next((r for r in subset if r.ratio == 0.30 and r.min_deg == 50), None)

        # Pick best: moderate community count + high modularity
        target = (50, 300) if edge_type == "CALL" else (10, 80)
        reasonable = [r for r in subset
                      if target[0] <= r.custom_n_comms <= target[1] and r.custom_mod > 0.001
                      and r.custom_n_comms > 0]
        best = max(reasonable, key=lambda r: r.custom_mod) if reasonable else None

        # Also find best by nx
        nx_reasonable = [r for r in subset
                         if target[0] <= r.nx_n_comms <= target[1] and r.nx_mod > 0.001
                         and r.nx_n_comms > 0]
        nx_best = max(nx_reasonable, key=lambda r: r.nx_mod) if nx_reasonable else None

        print(f"\n  [{proj_short}] {edge_type}:")
        if current:
            print(f"    Current (r={current.ratio}, d={current.min_deg}): "
                  f"{current.custom_n_comms} comms (Q={current.custom_mod:.4f}), "
                  f"hubs={current.hubs} orphans={current.orphans}")
            print(f"    NX with current: {current.nx_n_comms} comms (Q={current.nx_mod:.4f})")
        if best:
            print(f"    ★ Best custom: r={best.ratio}, d={best.min_deg} → "
                  f"{best.custom_n_comms} comms (Q={best.custom_mod:.4f}), "
                  f"hubs={best.hubs} orphans={best.orphans}")
        if nx_best:
            print(f"    ★ Best NX:     r={nx_best.ratio}, d={nx_best.min_deg} → "
                  f"{nx_best.nx_n_comms} comms (Q={nx_best.nx_mod:.4f}), "
                  f"hubs={nx_best.hubs} orphans={nx_best.orphans}")

        # Propose final recommendation
        if best and nx_best:
            avg_ratio = round((best.ratio + nx_best.ratio) / 2, 2)
            avg_deg = (best.min_deg + nx_best.min_deg) // 2
            print(f"\n    ⮕ SUGGESTED: HUB_DEGREE_RATIO={avg_ratio}, HUB_MIN_DEGREE={avg_deg}")


if __name__ == "__main__":
    main()
