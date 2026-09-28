"""基线视图(Baseline View)单元测试：挂载/重合检测/覆盖率/catalog 多任务合并。"""
import json

import pytest

from topoone.db.manager import MultiDBManager
from topoone.engine import view_service as vs
from topoone.engine.architecture_model_service import build_component_catalog


@pytest.fixture()
def mdb(tmp_path):
    """主库 + 项目库：3 个任务(aaa/bbb done，ccc running)、3 个源文件。"""
    md = MultiDBManager(data_dir=str(tmp_path))
    db = md.main_db
    db.execute("INSERT INTO projects (id, name, root_path) VALUES ('proj-t', 'T', '/tmp/src')")
    for tid, status in (("task-aaaaaaaa", "done"), ("task-bbbbbbbb", "done"),
                        ("task-cccccccc", "running")):
        db.execute(
            "INSERT INTO analysis_tasks (id, project_id, type, name, status) "
            "VALUES (?, 'proj-t', 'full', ?, ?)", (tid, tid, status))
    db.commit()
    pdb = md.get_project_db("proj-t")
    for fp in ("a.py", "b.py", "c.py"):
        pdb.execute("INSERT INTO source_files (id, file_path, language) VALUES (?, ?, 'python')",
                    (fp, fp))
    # 任务覆盖：aaa → {a.py, b.py}；bbb → {b.py, c.py}(与 aaa 交叉 b.py)
    for nid, tid, fp in (("n1", "task-aaaaaaaa", "a.py"), ("n2", "task-aaaaaaaa", "b.py"),
                         ("n3", "task-bbbbbbbb", "b.py"), ("n4", "task-bbbbbbbb", "c.py")):
        pdb.execute(
            "INSERT INTO graph_node (id, task_id, kind, name, file_path) "
            "VALUES (?, ?, 'file', ?, ?)", (nid, tid, fp, fp))
    pdb.commit()
    return md


def test_mount_rejects_non_done(mdb):
    with pytest.raises(ValueError, match="running"):
        vs.mount_task(mdb, "proj-t", "task-cccccccc")


def test_mount_status_and_coverage(mdb):
    st = vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    assert [m["taskId"] for m in st["mounted"]] == ["task-aaaaaaaa"]
    # 任务口径: 无 scope → 选择集=全部源文件; 已分析∩已选择 = {a,b}
    assert st["coverage"]["totalFiles"] == 3
    assert st["coverage"]["coveredFiles"] == 2
    assert st["coverage"]["coveragePct"] == 66.7
    assert st["coverage"]["perTask"] == [{
        "taskId": "task-aaaaaaaa", "selectedFiles": 3,
        "coveredFiles": 2, "coveragePct": 66.7}]
    assert vs.resolve_view_task_ids(mdb, "proj-t") == ["task-aaaaaaaa"]


def test_coverage_scoped_tasks_union(mdb):
    """任务口径汇总: 选择集过滤生效, 跨任务并集聚合。"""
    md = mdb
    db = md.main_db
    db.execute("UPDATE analysis_tasks SET scopes = '[\"a.py\"]' WHERE id = 'task-aaaaaaaa'")
    db.commit()
    st = vs.mount_task(md, "proj-t", "task-aaaaaaaa")
    # aaa 选择 {a.py}, 已分析 {a,b} ∩ 选择 = {a}
    assert st["coverage"]["totalFiles"] == 1
    assert st["coverage"]["coveredFiles"] == 1
    assert st["coverage"]["coveragePct"] == 100.0


def test_view_change_log_and_history(mdb):
    """变更记录: mount/unmount 留痕(版本/动作/任务名快照/任务现状)。"""
    vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    vs.unmount_task(mdb, "proj-t", "task-aaaaaaaa")
    vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    h = vs.view_history(mdb, "proj-t")
    e = h["entries"]
    assert len(e) == 3
    assert [x["action"] for x in e] == ["mount", "unmount", "mount"]   # 倒序
    assert [x["version"] for x in e] == [3, 2, 1]   # 初始 v0(未发布) + 三次代际更替
    assert e[0]["taskId"] == "task-aaaaaaaa"
    assert e[0]["taskName"] == "task-aaaaaaaa"
    assert e[0]["taskExists"] is True
    # 任务删除后 → 现状=已删除
    db = mdb.main_db
    db.execute("DELETE FROM analysis_tasks WHERE id = 'task-aaaaaaaa'")
    db.commit()
    h2 = vs.view_history(mdb, "proj-t")
    assert all(x["taskExists"] is False for x in h2["entries"])


def test_strict_overlap_rejected_then_force(mdb):
    vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    with pytest.raises(ValueError, match="交叉.*1 个文件"):
        vs.mount_task(mdb, "proj-t", "task-bbbbbbbb")
    st = vs.mount_task(mdb, "proj-t", "task-bbbbbbbb", force=True)
    assert st["overlapWarned"] is True
    assert vs.resolve_view_task_ids(mdb, "proj-t") == ["task-aaaaaaaa", "task-bbbbbbbb"]
    assert st["coverage"]["coveredFiles"] == 3


def test_unmount_and_stale(mdb):
    vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    st = vs.unmount_task(mdb, "proj-t", "task-aaaaaaaa")
    assert st["mounted"] == []
    assert st["stale"] is True and st["unmountedLatest"]["taskId"] == "task-aaaaaaaa"


def test_empty_view_resolves_nothing(mdb):
    assert vs.resolve_view_task_ids(mdb, "proj-t") == []
    out = build_component_catalog(mdb, "proj-t")
    assert out["components"] == [] and out["taskIds"] == []


def test_catalog_merges_mounted_tasks(mdb):
    pdb = mdb.get_project_db("proj-t")
    # UNIFIED 社区：aaa 一个组件(owns a.py)，bbb 一个组件(owns c.py)——分区不重叠
    pdb.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count, file_count) "
        "VALUES ('task-aaaaaaaa', 'UNIFIED', 'L0', 'comm-task-aaa-uni-L0-0000', ?, 1, 1)",
        (json.dumps(["a.py"]),))
    pdb.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count, file_count) "
        "VALUES ('task-bbbbbbbb', 'UNIFIED', 'L0', 'comm-task-bbb-uni-L0-0000', ?, 1, 1)",
        (json.dumps(["c.py"]),))
    pdb.commit()
    vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    vs.mount_task(mdb, "proj-t", "task-bbbbbbbb", force=True)

    out = build_component_catalog(mdb, "proj-t")
    ids = {c["id"] for c in out["components"]}
    assert ids == {"comm-task-aaa-uni-L0-0000", "comm-task-bbb-uni-L0-0000"}
    assert sorted(out["taskIds"]) == ["task-aaaaaaaa", "task-bbbbbbbb"]
    assert out["view"]["mountedTaskIds"] == ["task-aaaaaaaa", "task-bbbbbbbb"]
    # 显式 task_id 仍可覆盖（内部消费方）
    only = build_component_catalog(mdb, "proj-t", task_id="task-aaaaaaaa")
    assert [c["id"] for c in only["components"]] == ["comm-task-aaa-uni-L0-0000"]


def test_remove_project_view_cleanup(mdb, tmp_path):
    vs.mount_task(mdb, "proj-t", "task-aaaaaaaa")
    vs.remove_project_view(mdb.main_db, "proj-t")
    assert mdb.main_db.fetchone(
        "SELECT * FROM project_views WHERE project_id = 'proj-t'") is None
    assert vs.resolve_view_task_ids(mdb, "proj-t") == []
