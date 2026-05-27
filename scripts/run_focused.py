"""
Quick runner that tests each project/edge_type combo separately with output capture.
"""
import sys, os, subprocess, json

tests = [
    ("proj-51a77082", "9597b9a9-d0d4-420b-8832-d1853d811813", "CALL"),
    ("proj-51a77082", "9597b9a9-d0d4-420b-8832-d1853d811813", "INCLUDE"),
    ("proj-3852f98e", "0faa19ad-9346-4a0e-ae89-900359c44317", "CALL"),
    ("proj-3852f98e", "0faa19ad-9346-4a0e-ae89-900359c44317", "INCLUDE"),
]

for proj, task_id, edge_type in tests:
    print(f"\n{'='*60}")
    print(f"  RUNNING: {proj} {edge_type}")
    print(f"{'='*60}")
    
    script = f"""
import sys, os, sqlite3, logging, time
from collections import defaultdict
logging.basicConfig(level=logging.INFO, format="%(message)s")
sys.path.insert(0, "{os.path.join(os.path.dirname(__file__), '..', 'backend')}")

import community_analysis as ca_mod
from community_analysis import _build_graph, _compute_modularity
from config import HUB_DEGREE_RATIO, HUB_MIN_DEGREE
import networkx as nx
from community import community_louvain

DB_DIR = os.path.expanduser("~/.config/topoone-ui/topoone.db")
db_path = f"{{DB_DIR}}/{proj}.db"
task_id = "{task_id}"

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

def communities_from_partition(partition):
    comm_map = defaultdict(set)
    for node, cid in partition.items():
        comm_map[cid].add(node)
    return sorted([s for s in comm_map.values() if len(s) >= 2], key=len, reverse=True)

def graph_to_networkx(graph):
    G = nx.Graph()
    for node, neighbors in graph.items():
        for nb in neighbors:
            G.add_edge(node, nb)
    return G

edges = load_edges(db_path, task_id, "{edge_type}")
print(f"Edges loaded: {{len(edges)}}")

t0 = time.time()
graph, directions, hubs, orphans = _build_graph(edges, "{edge_type}")
all_nodes = set(graph.keys())
for nb in graph.values():
    all_nodes.update(nb)
edge_set = set()
for n, nbs in graph.items():
    for nb in nbs:
        if (nb, n) not in edge_set:
            edge_set.add((n, nb))
print(f"Graph: {{len(all_nodes)}} nodes, {{len(edge_set)}} edges, hubs={{len(hubs)}}, orphans={{len(orphans)}}, time={{time.time()-t0:.1f}}s")

if len(all_nodes) >= 2:
    deg = {{n: len(graph.get(n, set())) for n in all_nodes}}
    m = sum(deg.values()) / 2

    # NX full
    G = graph_to_networkx(graph)
    t0 = time.time()
    nx_part = community_louvain.best_partition(G)
    nx_q = community_louvain.modularity(nx_part, G)
    nx_comms = communities_from_partition(nx_part)
    print(f"NX Louvain: {{len(nx_comms)}} comms, Q={{nx_q:.6f}}, time={{time.time()-t0:.1f}}s")
    
    # Custom Louvain - copy the function inline since we need to compare
    # Limit to 50 iters for large graphs
    max_iter = 50
    t0 = time.time()
    # Run custom _detect_communities
    from community_analysis import _detect_communities
    custom_comms = _detect_communities(graph, all_nodes)
    custom_q = _compute_modularity(custom_comms, graph, deg, m)
    print(f"Custom Louvain: {{len(custom_comms)}} comms, Q={{custom_q:.6f}}, time={{time.time()-t0:.1f}}s")
    
    if custom_comms and nx_comms:
        from scripts.test_compare_louvain import adjusted_rand_index
        ari = adjusted_rand_index(custom_comms, nx_comms)
        print(f"ARI: {{ari:.4f}}")
    else:
        print("ARI: N/A")
else:
    print("Too few nodes, skipping Louvain")
"""
    result = subprocess.run(
        ["python3", "-c", script],
        capture_output=True, text=True, timeout=600,
        cwd=os.path.dirname(__file__) + "/.."
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr[:500])
