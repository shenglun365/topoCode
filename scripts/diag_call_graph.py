#!/usr/bin/env python3
"""诊断 CALL 边 callee_file_id 为 None 的根因"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from sqlite_ctx import MultiDBManager
from config import DB_DIR

def find_db_dir():
    candidates = [
        os.environ.get('TOPOCODE_DB_DIR', ''),
        os.path.join(os.path.expanduser("~"), ".config", "topoone-ui", "topoone.db"),
        os.path.join(os.path.expanduser("~"), ".topoone"),
        DB_DIR,
    ]
    for d in candidates:
        if d and os.path.isdir(d) and os.path.exists(os.path.join(d, 'topoone.db')):
            return d
    sys.exit("Cannot find DB dir")

def main():
    if len(sys.argv) < 2:
        print("Usage: python diag_call_graph.py <task_id>")
        sys.exit(1)

    task_id = sys.argv[1]
    db_dir = find_db_dir()
    multi_db = MultiDBManager(db_dir)

    # 获取项目 ID
    task = multi_db.main_db.execute(
        "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if not task:
        sys.exit(f"Task {task_id} not found")
    project_id = task[0]
    project_db = multi_db.get_project_db(project_id)

    # 1. 查看 CALL 边中 callee_file_id 的分布
    print("=" * 60)
    print("1. CALL 边 callee_file_id 分布")
    rows = project_db.execute("""
        SELECT
            COUNT(*) as total,
            SUM(CASE WHEN callee_file_id IS NULL OR callee_file_id = '' THEN 1 ELSE 0 END) as null_count,
            SUM(CASE WHEN callee_file_id IS NOT NULL AND callee_file_id != '' THEN 1 ELSE 0 END) as valid_count
        FROM graph_node WHERE task_id = ? AND symbol_node_type = 'call_relation'
    """, (task_id,)).fetchone()
    print(f"   总计: {rows[0]}, 有效 callee_file_id: {rows[2]}, 为 None: {rows[1]}")

    # 2. 抽样 CALL 边查看 callee_name
    print("\n2. CALL 边 callee_name 抽样 (前20)")
    rows = project_db.execute("""
        SELECT caller_func_name, callee_name, callee_file_id, callee_node_id
        FROM graph_node WHERE task_id = ? AND symbol_node_type = 'call_relation'
        LIMIT 20
    """, (task_id,)).fetchall()
    for r in rows:
        print(f"   caller={r[0]:30s} callee={r[1]:30s} file_id={r[2]} node_id={r[3]}")

    # 3. 查看 method_name 符号 （方法定义）
    print("\n3. method_name 符号抽样 (前20)")
    rows = project_db.execute("""
        SELECT file_id, method_name
        FROM graph_node WHERE task_id = ? AND symbol_node_type = 'method_name'
        LIMIT 20
    """, (task_id,)).fetchall()
    for r in rows:
        print(f"   file_id={r[0]:6s} method={r[1]:40s}")

    # 4. 统计 method_name 总数
    total = project_db.execute("""
        SELECT COUNT(*) FROM graph_node
        WHERE task_id = ? AND symbol_node_type = 'method_name'
    """, (task_id,)).fetchone()[0]
    print(f"\n   method_name 总数: {total}")

    # 5. 抽样 base_node 中 Java 调用表达式（查看 refs 结构）
    print("\n4. base_node 抽样 (type=method_invocation, 前10)")
    rows = project_db.execute("""
        SELECT node_id, type, name, op, refs, scope_node_id
        FROM base_node WHERE type = 'method_invocation'
        LIMIT 10
    """).fetchall()
    for r in rows:
        refs = r[4]
        if refs:
            try:
                refs = json.loads(refs)
            except:
                refs = [refs]
        print(f"   node_id={r[0]} name={r[2]} op={r[3]} refs={refs} scope={r[5]}")

    # 6. 抽样 base_node 中 Java 方法定义
    print("\n5. base_node 抽样 (type=method_declaration, 前10)")
    rows = project_db.execute("""
        SELECT node_id, type, name, op, def_node_id
        FROM base_node WHERE type = 'method_declaration'
        LIMIT 10
    """).fetchall()
    for r in rows:
        print(f"   node_id={r[0]} name={r[2]} op={r[3]} def={r[4]}")

    # 7. 交叉比对：CALL 边中的 callee_name 在 method_name 中的命中情况
    print("\n6. callee_name 在 method_name 中的命中情况")
    # 取去重后的 callee_name
    sample_callees = project_db.execute("""
        SELECT DISTINCT callee_name FROM graph_node
        WHERE task_id = ? AND symbol_node_type = 'call_relation' AND callee_name IS NOT NULL
        LIMIT 50
    """, (task_id,)).fetchall()

    hit = 0
    miss = 0
    for (cn,) in sample_callees:
        match = project_db.execute(
            "SELECT COUNT(*) FROM graph_node WHERE task_id = ? AND symbol_node_type = 'method_name' AND method_name = ?",
            (task_id, cn)
        ).fetchone()[0]
        if match > 0:
            hit += 1
        else:
            miss += 1
            if miss <= 5:
                print(f"   MISS: callee='{cn}' 在 method_name 中找不到")

    print(f"   命中: {hit}/{len(sample_callees)}, 缺失: {miss}/{len(sample_callees)}")

    multi_db.close_all()

if __name__ == '__main__':
    main()
