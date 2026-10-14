"""project.remove 级联清扫 + project.gc 孤儿回收 特征测试。

回归背景: 此前 remove 仅清 tasks/runs/项目库文件/镜像/签名, 主库其余
pid 键表(versions/version_files/update_requests/task_config_history/
view_*)全部残留为孤儿行; 项目库目录只删 project.db 文件留目录。
级联清单由 schema 动态派生(_project_keyed_tables), 加表免维护。
"""
from __future__ import annotations

import os

from topoone.db.manager import MultiDBManager
from topoone.engine.service.project import (
    _remove_project_impl, _gc_orphan_pids, _gc_purge_project)


def _seed(md: MultiDBManager, pid: str, with_project: bool = True):
    db = md.main_db
    if with_project:
        db.execute("INSERT INTO projects (id, name, root_path) VALUES (?, 'T', '/x')", (pid,))
    db.execute("INSERT INTO analysis_tasks (id, project_id, type, name, status) "
               "VALUES ('t1', ?, 'full', 'n', 'done')", (pid,))
    db.execute("INSERT INTO analysis_task_runs (id, task_id, run_number, status)"
               " VALUES ('r1', 't1', 1, 'done')")
    db.execute("INSERT INTO task_config_history (id, task_id, config_version)"
               " VALUES ('tc1', 't1', 1)")
    db.execute("INSERT INTO project_versions (id, project_id) VALUES ('v1', ?)", (pid,))
    db.execute("INSERT INTO project_version_files (id, version_id, project_id, "
               "change_type, file_path) VALUES ('vf1', 'v1', ?, 'A', 'a.py')", (pid,))
    db.execute("INSERT INTO project_update_requests (id, project_id, status)"
               " VALUES ('u1', ?, 'pending')", (pid,))
    db.execute("INSERT INTO view_change_log (project_id, version, action, task_id)"
               " VALUES (?, 1, 'mount', 't1')", (pid,))
    db.commit()


def _mirror(md: MultiDBManager, pid: str) -> str:
    d = md.source_cache_dir_for(pid)
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "f.txt"), "w") as f:
        f.write("x")
    return d


def test_remove_cascades_all_pid_keyed_rows(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    _seed(md, "p1")
    mirror = _mirror(md, "p1")
    md.init_project_db("p1", project_root="/x")
    db = md.main_db

    _remove_project_impl(server=None, main_db=db, multi_db=md,
                         pid="p1", root_path=str(tmp_path / "src"), request_id="")

    for t in ("projects", "analysis_tasks", "analysis_task_runs",
              "task_config_history", "project_versions",
              "project_version_files", "project_update_requests",
              "view_change_log"):
        n = db.fetchone(f"SELECT COUNT(*) AS n FROM {t}")["n"]
        assert n == 0, f"{t} 残留 {n} 行"
    assert not os.path.isdir(mirror), "源码镜像残留"
    assert not os.path.isdir(os.path.join(str(tmp_path), "projects", "p1")), \
        "项目库目录残留(此前只删 project.db 文件)"


def test_gc_scans_purges_and_skips_busy(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    _seed(md, "ghost", with_project=False)  # 孤儿: 仅残留行
    mirror = _mirror(md, "ghost")
    os.makedirs(os.path.join(str(tmp_path), "projects", "ghost"), exist_ok=True)
    os.makedirs(os.path.join(str(tmp_path), "projects", "alive"), exist_ok=True)
    md.main_db.execute(
        "INSERT INTO projects (id, name, root_path) VALUES ('alive', 'A', '/a')")
    md.main_db.commit()

    # 扫描: ghost 命中, alive(注册表在册)不误伤, busy 跳过
    assert "ghost" in _gc_orphan_pids(md.main_db, md)
    assert "alive" not in _gc_orphan_pids(md.main_db, md)
    assert "ghost" not in _gc_orphan_pids(md.main_db, md, busy={"ghost"})

    rep = _gc_purge_project(md.main_db, md, "ghost")
    assert rep["rows"].get("analysis_tasks") == 1
    assert rep["rows"].get("project_version_files") == 1
    assert not os.path.isdir(mirror)
    assert not os.path.isdir(os.path.join(str(tmp_path), "projects", "ghost"))
    assert os.path.isdir(os.path.join(str(tmp_path), "projects", "alive"))
    assert _gc_orphan_pids(md.main_db, md) == []


def test_gc_no_orphans_is_noop(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    _seed(md, "p1")  # 在册项目, 不是孤儿
    assert _gc_orphan_pids(md.main_db, md) == []
    # 注册表数据原样(扫描只读)
    assert md.main_db.fetchone("SELECT COUNT(*) AS n FROM projects")["n"] == 1
    assert md.main_db.fetchone("SELECT COUNT(*) AS n FROM analysis_tasks")["n"] == 1


def test_gc_purges_task_orphans(tmp_path):
    """task 间接键孤儿(任务行已先被旧删除清掉)全局清扫 —— pid 反查不可达,
    须按 NOT IN (SELECT id FROM analysis_tasks) 全局扫。"""
    from topoone.engine.service.project import _gc_purge_task_orphans
    md = MultiDBManager(data_dir=str(tmp_path))
    db = md.main_db
    db.execute("INSERT INTO analysis_tasks (id, project_id, type, name, status)"
               " VALUES ('t1', 'p1', 'full', 'n', 'done')")
    db.execute("INSERT INTO analysis_task_runs (id, task_id, run_number, status)"
               " VALUES ('r1', 't1', 1, 'done')")
    db.execute("INSERT INTO task_config_history (id, task_id, config_version)"
               " VALUES ('tc1', 't1', 1)")
    # 孤儿: 任务已不存在
    db.execute("INSERT INTO analysis_task_runs (id, task_id, run_number, status)"
               " VALUES ('r2', 'dead-task', 1, 'done')")
    db.execute("INSERT INTO task_config_history (id, task_id, config_version)"
               " VALUES ('tc2', 'dead-task', 1)")
    db.commit()
    cleaned = _gc_purge_task_orphans(db)
    assert cleaned == {"analysis_task_runs": 1, "task_config_history": 1}
    assert db.fetchone("SELECT COUNT(*) AS n FROM analysis_task_runs")["n"] == 1
    assert db.fetchone("SELECT COUNT(*) AS n FROM task_config_history")["n"] == 1
