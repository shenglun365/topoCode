"""Diagnose cross-community edge generation."""
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend-core'))

from sqlite_ctx import MultiDBManager


def diagnose(task_id: str, project_id: str):
    multi_db = MultiDBManager()
    project_db = multi_db.get_project_db(project_id)

    for et in ('INCLUDE', 'CALL'):
        ek = 'calls' if et == 'CALL' else 'imports'
        doc_rows = project_db.execute(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (task_id, et, 'L0')
        ).fetchall()
        if not doc_rows:
            print(f"{et}/L0: NO COMMUNITIES")
            continue

        node_comm = {}
        for row in doc_rows:
            try:
                nodes = json.loads(row[1]) if row[1] else []
            except Exception:
                nodes = []
            for nid in nodes:
                node_comm[nid] = row[0]

        symbol_file_map = {}
        if ek == 'calls':
            all_e = project_db.execute(
                "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
                (task_id, ek)
            ).fetchall()
            sym_ids = set()
            for e in all_e:
                if e[0]: sym_ids.add(e[0])
                if e[1]: sym_ids.add(e[1])
            sym_list = list(sym_ids)
            for i in range(0, len(sym_list), 900):
                batch = sym_list[i:i + 900]
                ph = ','.join(['?'] * len(batch))
                rows = project_db.execute(
                    f"SELECT id, file_path FROM graph_node WHERE task_id=? AND id IN ({ph})",
                    [task_id] + batch
                ).fetchall()
                for r in rows:
                    symbol_file_map[r[0]] = r[1] or ''

        def resolve(raw_id: str):
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

        edges = project_db.execute(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
            (task_id, ek)
        ).fetchall()

        cross = {}
        same = 0
        no_match = 0
        for e in edges:
            sc = resolve(e[0])
            tc = resolve(e[1])
            if sc and tc:
                if sc != tc:
                    cross[(sc, tc)] = cross.get((sc, tc), 0) + 1
                else:
                    same += 1
            else:
                no_match += 1

        print(f"{et}/L0: {len(doc_rows)} communities, {len(node_comm)} nodes, {len(edges)} edges")
        print(f"  unmatched={no_match}, same-community={same}, cross-pairs={len(cross)}, cross-edges={sum(cross.values())}")
        if cross:
            for (s, t), c in sorted(cross.items(), key=lambda x: -x[1])[:8]:
                print(f"  {s} → {t}: {c} edges")
        print()

    multi_db.close_all()


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--task-id', required=True)
    p.add_argument('--project-id', required=True)
    args = p.parse_args()
    diagnose(args.task_id, args.project_id)
