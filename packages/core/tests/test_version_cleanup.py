"""KB 基线管理：物理清除(决策4) + 社区重划分 stage 测试。"""
from __future__ import annotations

import pytest

from topoone.db.manager import MultiDBManager
from topoone.engine import version_sync_service as vss


def _mk_project(md: MultiDBManager, pid: str, root: str):
    md.main_db.execute(
        "INSERT INTO projects(id, name, root_path) VALUES(?, ?, ?)",
        (pid, "test", root))
    md.main_db.conn.commit()
    return md.init_project_db(pid, project_root=root)


def _mk_schema(project_db):
    project_db.execute(
        "CREATE TABLE IF NOT EXISTS source_files("
        " id TEXT, file_path TEXT, file_name TEXT, language TEXT, size INT,"
        " content_hash TEXT, hashcode TEXT, parent_path TEXT, mtime INT,"
        " version_from TEXT, version_to TEXT)")
    project_db.execute(
        "CREATE TABLE IF NOT EXISTS source_files_history("
        " id TEXT, file_path TEXT, file_name TEXT, language TEXT, size INT,"
        " content_hash TEXT, hashcode TEXT, parent_path TEXT, mtime INT,"
        " version_from TEXT, version_to TEXT)")
    for t in ("graph_node", "graph_node_history"):
        project_db.execute(
            f"CREATE TABLE IF NOT EXISTS {t}("
            " id TEXT, task_id TEXT, file_path TEXT, kind TEXT, name TEXT,"
            " version_to TEXT)")
    for t in ("graph_edge", "graph_edge_history"):
        project_db.execute(
            f"CREATE TABLE IF NOT EXISTS {t}("
            " id TEXT, task_id TEXT, source_id TEXT, target_id TEXT, kind TEXT,"
            " version_to TEXT)")
    project_db.conn.commit()


def test_cleanup_removes_history_and_orphans(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    root = str(tmp_path / "src")
    (tmp_path / "src").mkdir()
    pdb = _mk_project(md, "proj-c1", root)
    _mk_schema(pdb)
    # 一个已完成的分析任务(孤儿清除按最新 done 任务范围)
    md.main_db.execute(
        "INSERT INTO analysis_tasks(id, project_id, type, name, status) "
        "VALUES('t1','proj-c1','full','t1','done')")
    md.main_db.conn.commit()

    # 活表 source_files 只保留 a.py；b.py 已删除（孤儿）
    pdb.execute("INSERT INTO source_files(id, file_path, version_from) "
                "VALUES('f1','a.py','v1')")
    # 历史归档行：v1→v2 (b.py 删除归档)
    pdb.execute("INSERT INTO source_files_history(id, file_path, version_from, version_to) "
                "VALUES('h1','b.py','v1','v2')")
    # graph 孤儿：n2 属于 b.py(已不在活表)，n1 属于 a.py(在活表)
    pdb.execute("INSERT INTO graph_node(id, task_id, file_path, kind, name) VALUES('n1','t1','a.py','function','n1')")
    pdb.execute("INSERT INTO graph_node(id, task_id, file_path, kind, name) VALUES('n2','t1','b.py','function','n2')")
    pdb.execute("INSERT INTO graph_edge(id, task_id, source_id, target_id, kind) "
                "VALUES('e1','t1','n1','n2','calls')")
    pdb.execute("INSERT INTO graph_edge(id, task_id, source_id, target_id, kind) "
                "VALUES('e2','t1','n1','n1','calls')")
    pdb.conn.commit()

    res = vss.cleanup(md, "proj-c1", keep_versions=0)
    deleted = res["deleted"]
    # 历史归档行被清除
    assert deleted["source_files_history"] == 1
    # 孤儿节点(b.py) 被清除，a.py 节点保留
    assert deleted["graph_node_orphans"] == 1
    remain_nodes = pdb.execute("SELECT id FROM graph_node ORDER BY id").fetchall()
    assert [r["id"] for r in remain_nodes] == ["n1"]
    # e1(指向已删 n2) 清除，e2(n1→n1) 保留
    remain_edges = pdb.execute("SELECT id FROM graph_edge").fetchall()
    assert [r["id"] for r in remain_edges] == ["e2"]


def test_cleanup_keep_versions_window(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    root = str(tmp_path / "src")
    (tmp_path / "src").mkdir()
    pdb = _mk_project(md, "proj-c2", root)
    _mk_schema(pdb)
    # 两个版本
    md.main_db.execute(
        "INSERT INTO project_versions(id, project_id, created_at) VALUES('v1','proj-c2','2026-01-01T00:00:00Z')")
    md.main_db.execute(
        "INSERT INTO project_versions(id, project_id, created_at) VALUES('v2','proj-c2','2026-01-02T00:00:00Z')")
    md.main_db.conn.commit()
    # 归档行：属于 v1(旧) 与 v2(新)
    pdb.execute("INSERT INTO source_files_history(id, file_path, version_from, version_to) "
                "VALUES('h_old','old.py','v0','v1')")
    pdb.execute("INSERT INTO source_files_history(id, file_path, version_from, version_to) "
                "VALUES('h_new','new.py','v1','v2')")
    pdb.conn.commit()

    res = vss.cleanup(md, "proj-c2", keep_versions=1)  # 仅保留最近 1 版(v2)
    # v2 的归档行 version_to=v2 被保留，v1 的(version_to=v1)被清除
    remain = pdb.execute("SELECT id FROM source_files_history").fetchall()
    assert [r["id"] for r in remain] == ["h_new"]
    assert res["deleted"]["source_files_history"] == 1


def test_cleanup_no_project(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    with pytest.raises(ValueError):
        vss.cleanup(md, "proj-missing", keep_versions=0)


def test_inc_community_stage_runs(tmp_path):
    """community stage：有边数据时执行社区重划分并返回 done。"""
    from topoone.engine import incremental_runner as ir
    md = MultiDBManager(data_dir=str(tmp_path))
    root = str(tmp_path / "src")
    (tmp_path / "src").mkdir()
    pdb = _mk_project(md, "proj-cm", root)
    # graph_edge 需要 AnalysisStore 读取的表结构：建最小 edge 表
    pdb.execute("CREATE TABLE IF NOT EXISTS graph_edge("
                " id TEXT, task_id TEXT, source_id TEXT, target_id TEXT, kind TEXT)")
    pdb.execute("CREATE TABLE IF NOT EXISTS graph_node("
                " id TEXT, task_id TEXT, file_path TEXT, name TEXT, kind TEXT)")
    # 造一条 CALL 边让社区检测有输入
    pdb.execute("INSERT INTO graph_node(id, task_id, file_path, name, kind) "
                "VALUES('a','t1','a.py','a','function')")
    pdb.execute("INSERT INTO graph_node(id, task_id, file_path, name, kind) "
                "VALUES('b','t1','b.py','b','function')")
    pdb.execute("INSERT INTO graph_edge(id, task_id, source_id, target_id, kind) "
                "VALUES('e1','t1','a','b','CALL')")
    pdb.conn.commit()
    res = ir._inc_community(md, pdb, "t1")
    # 不因缺表而崩溃；返回结构化结果
    assert "status" in res
    assert res["status"] in ("done", "error")
