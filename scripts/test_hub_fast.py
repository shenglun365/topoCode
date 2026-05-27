"""
Focused: test HUB threshold + NX Louvain (fast) for CALL on proj-51a77082.
Skip custom Louvain (too slow); use NX as reference.
"""
import sys, os, sqlite3, logging, time
from collections import defaultdict
from itertools import product
logging.basicConfig(level=logging.INFO, format="%(message)s")
sys.path.insert(0, "backend")
import community_analysis as ca_mod
from community_analysis import _build_graph
from config import HUB_DEGREE_RATIO as ORIG_R, HUB_MIN_DEGREE as ORIG_M
import networkx as nx
from community import community_louvain

DB_DIR = os.path.expanduser("~/.config/topoone-ui/topoone.db")
db_path = f"{DB_DIR}/proj-51a77082.db"
task_id = "9597b9a9-d0d4-420b-8832-d1853d811813"

def load_edges(etype):
    sym = "call_relation" if etype == "CALL" else "dependence"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM graph_node WHERE task_id = ? AND symbol_node_type = ?", (task_id, sym)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def graph_to_nx(g):
    G = nx.Graph()
    for n, nbs in g.items():
        for nb in nbs: G.add_edge(n, nb)
    return G

RATIOS = [0.30, 0.20, 0.15, 0.10, 0.05]
MIN_DEGS = [50, 30, 20, 10]

for etype in ("CALL", "INCLUDE"):
    print(f"\n{'='*60}")
    print(f"  {etype} HUB tuning (NX Louvain)")
    print(f"{'='*60}")
    edges = load_edges(etype)
    print(f"Edges: {len(edges)}")

    print(f"\n{'Ratio':<7} {'MinDeg':<8} {'Hubs':<7} {'Orphs':<8} {'Remain':<8} {'Rem%':<7} {'NX#':<8} {'NXQ':<10}")
    print("-"*65)
    for ratio, min_deg in product(RATIOS, MIN_DEGS):
        ca_mod.HUB_DEGREE_RATIO = ratio
        ca_mod.HUB_MIN_DEGREE = min_deg
        try:
            graph, _, hubs, orphans = _build_graph(edges, etype)
            all_nodes = set(graph.keys())
            for nb in graph.values(): all_nodes.update(nb)
            remaining = len(all_nodes)

            if remaining >= 2:
                G = graph_to_nx(graph)
                t0=time.time()
                part = community_louvain.best_partition(G)
                nq = community_louvain.modularity(part, G)
                nx_t = time.time()-t0
                comm_map = defaultdict(set)
                for n,c in part.items(): comm_map[c].add(n)
                nx_n = len([s for s in comm_map.values() if len(s)>=2])
            else:
                nx_n, nq, nx_t = 0, 0, 0

            total_nodes_raw = len(set().union(*[
                {f"{e.get('caller_file_id','')}:{e.get('caller_func_name','')}",
                 f"{e.get('callee_file_id','')}:{e.get('callee_name','')}"}
                if etype=="CALL" else
                {str(e.get('file_id','')), e.get('include_path','')}
                for e in edges
            ]))
            remain_pct = remaining/total_nodes_raw*100 if total_nodes_raw else 0
            print(f"{ratio:<7.2f} {min_deg:<8d} {len(hubs):<7d} {len(orphans):<8d} {remaining:<8d} {remain_pct:<7.1f} {nx_n:<8d} {nq:<10.4f}")
        finally:
            ca_mod.HUB_DEGREE_RATIO = ORIG_R
            ca_mod.HUB_MIN_DEGREE = ORIG_M
