"""Comprehensive cross-community edge diagnostic for all projects and tasks."""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend-core'))

import sqlite3

def find_project_dbs():
    """Find all project DBs by scanning for .topocode/data/project.db"""
    project_dbs = {}
    base = os.path.expanduser("~")
    
    # Scan software projects
    soft_dir = os.path.join(base, "soft")
    if os.path.isdir(soft_dir):
        for name in os.listdir(soft_dir):
            db_path = os.path.join(soft_dir, name, ".topocode", "data", "project.db")
            if os.path.isfile(db_path):
                project_dbs[name] = db_path
    
    # Also check known projects
    more_dirs = [
        os.path.join(base, "topoCodeProj"),
    ]
    for d in more_dirs:
        if os.path.isdir(d):
            for name in os.listdir(d):
                db_path = os.path.join(d, name, ".topocode", "data", "project.db")
                if os.path.isfile(db_path) and name not in project_dbs:
                    project_dbs[name] = db_path

    return project_dbs


def diagnose_project(name: str, db_path: str):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    
    # Get all tasks
    tasks = conn.execute(
        "SELECT DISTINCT task_id FROM graph_doc ORDER BY task_id"
    ).fetchall()
    task_ids = [t['task_id'] for t in tasks]
    
    print(f"\n{'='*80}")
    print(f"Project: {name} ({len(task_ids)} tasks)")
    print(f"{'='*80}")
    
    for tid in task_ids:
        print(f"\n  Task: {tid}")
        
        for et in ('INCLUDE', 'CALL'):
            ek = 'calls' if et == 'CALL' else 'imports'
            
            # Check community levels
            levels = conn.execute(
                "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? AND edge_type=? ORDER BY comm_lv",
                (tid, et)
            ).fetchall()
            level_list = [r['comm_lv'] for r in levels]
            
            if not level_list:
                print(f"    {et}: NO COMMUNITIES")
                continue
            
            # Check for each level
            for lv in level_list:
                doc_rows = conn.execute(
                    "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
                    (tid, et, lv)
                ).fetchall()
                
                # Build node→comm map
                node_comm = {}
                for row in doc_rows:
                    try:
                        nodes = json.loads(row['node_list']) if row['node_list'] else []
                    except Exception:
                        nodes = []
                    for nid in nodes:
                        node_comm[nid] = row['comm_id']
                
                # Edges exist?
                edge_count = conn.execute(
                    "SELECT COUNT(*) FROM graph_edge WHERE task_id=? AND kind=?",
                    (tid, ek)
                ).fetchone()[0]
                
                if edge_count == 0:
                    print(f"    {et}/{lv}: {len(doc_rows)} comms, NO EDGES in graph_edge")
                    continue
                
                # Build symbol→file map for CALL
                symbol_file_map = {}
                if ek == 'calls':
                    all_e = conn.execute(
                        "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
                        (tid, ek)
                    ).fetchall()
                    sym_ids = set()
                    for e in all_e:
                        if e['source_id']: sym_ids.add(e['source_id'])
                        if e['target_id']: sym_ids.add(e['target_id'])
                    sym_list = list(sym_ids)
                    for i in range(0, len(sym_list), 900):
                        batch = sym_list[i:i + 900]
                        ph = ','.join(['?'] * len(batch))
                        rows = conn.execute(
                            f"SELECT id, file_path FROM graph_node WHERE task_id=? AND id IN ({ph})",
                            [tid] + batch
                        ).fetchall()
                        for r in rows:
                            symbol_file_map[r['id']] = r['file_path'] or ''
                
                # Resolve cross-edges
                def resolve(raw_id):
                    if not raw_id:
                        return None
                    if ek == 'imports':
                        key = raw_id.replace('file:', '', 1) if raw_id.startswith('file:') else raw_id
                        return node_comm.get(key)
                    else:
                        fpath = symbol_file_map.get(raw_id, '')
                        if fpath and fpath in node_comm:
                            return node_comm[fpath]
                        return node_comm.get(raw_id)
                
                edges_for_lv = conn.execute(
                    "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
                    (tid, ek)
                ).fetchall()
                
                cross = {}
                same = 0
                no_match = 0
                for e in edges_for_lv:
                    sc = resolve(e['source_id'])
                    tc = resolve(e['target_id'])
                    if sc and tc:
                        if sc != tc:
                            cross[(sc, tc)] = cross.get((sc, tc), 0) + 1
                        else:
                            same += 1
                    else:
                        no_match += 1
                
                status = "OK" if cross else "NO CROSS EDGES"
                print(f"    {et}/{lv}: {len(doc_rows)} comms, {edge_count} edges → cross-pairs={len(cross)}, cross-count={sum(cross.values())} [{status}]")
                if not cross:
                    # Investigate
                    some_nodes = list(node_comm.keys())[:3]
                    sample_edges = edges_for_lv[:3]
                    print(f"      node sample: {[n[:50] for n in some_nodes]}")
                    if ek == 'imports':
                        print(f"      edge src sample: {[e['source_id'][:50] for e in sample_edges]}")
                    else:
                        print(f"      edge src sample: {[e['source_id'][:20] for e in sample_edges]}")
                        for e in sample_edges[:1]:
                            fpath = symbol_file_map.get(e['source_id'], 'N/A')
                            print(f"      symbol→file example: {e['source_id'][:20]} → {fpath[:50] if fpath else 'N/A'}")

    conn.close()


if __name__ == '__main__':
    projects = find_project_dbs()
    print(f"Found {len(projects)} projects")
    
    for name, db_path in sorted(projects.items()):
        try:
            diagnose_project(name, db_path)
        except Exception as e:
            print(f"\n  ERROR: {name}: {e}")
    
    print("\n\nDone.")
