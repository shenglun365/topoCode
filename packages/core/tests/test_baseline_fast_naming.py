"""基线就绪/快速命名/自适应增量 — A2/A3/A4 契约测试。

覆盖:
- derive_readiness 无状态推导(六状态) + ensure_ready 幂等编排 + auto 挂载语义
- swap_auto_mounts: manual 挂载永不触碰
- bulk_insert_llm_results UPSERT: name_manual 永不被通道覆盖
- inherit_names: 文件集 Jaccard 命名继承(name_manual 优先)
- run_fast_naming: 继承/人工命名跳过 + fast-agent 产物(agentic_chat 打桩)
- decide_rebuild: 阈值/显式 stages 优先/分支切换(纯函数)
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from topoone.db.manager import MultiDBManager
from topoone.engine.service import baseline_readiness as br
from topoone.engine import view_service as vs
from topoone.engine.store.analysis_store import AnalysisStore
from topoone.engine import version_sync_service as vss


# ── fixture ─────────────────────────────────────────────────

@pytest.fixture()
def mdb(tmp_path):
    """主库+项目库: 项目 proj-t, 源文件 a/b/c.py, 任务 done-1(done)。"""
    md = MultiDBManager(data_dir=str(tmp_path))
    db = md.main_db
    db.execute("INSERT INTO projects (id, name, root_path) VALUES "
               "('proj-t', 'T', ?)", (str(tmp_path / "src"),))
    db.execute("INSERT INTO analysis_tasks (id, project_id, type, name, status) "
               "VALUES ('done-1', 'proj-t', 'fast', 'ensure-fast', 'done')")
    db.commit()
    pdb = md.get_project_db("proj-t")
    for fp in ("a.py", "b.py", "c.py"):
        pdb.execute("INSERT INTO source_files (id, file_path, language) "
                    "VALUES (?, ?, 'python')", (fp, fp))
    for nid, fp in (("n1", "a.py"), ("n2", "b.py"), ("n3", "c.py")):
        pdb.execute("INSERT INTO graph_node (id, task_id, kind, name, file_path) "
                    "VALUES (?, 'done-1', 'file', ?, ?)", (nid, fp, fp))
    pdb.commit()
    return md


def _mk_l0_community(pdb, task_id, comm_id, files):
    pdb.execute(
        "INSERT INTO community_hierarchy (task_id, edge_type, comm_lv, comm_id, node_count, file_count) "
        "VALUES (?, 'UNIFIED', 'L0', ?, ?, ?)", (task_id, comm_id, len(files), len(files)))
    pdb.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count, file_count) "
        "VALUES (?, 'UNIFIED', 'L0', ?, ?, ?, ?)",
        (task_id, comm_id, json.dumps(files), len(files), len(files)))
    pdb.commit()


# ── A2: readiness 状态机 ────────────────────────────────────

def test_readiness_no_project(mdb):
    st = br.derive_readiness(mdb, root="/nonexistent-root-xyz")
    assert st["state"] == "no_project"


def test_readiness_states(mdb):
    db = mdb.main_db
    # 去基线化: done 即 ready(挂载不再是就绪前置)
    st = br.derive_readiness(mdb, project_id="proj-t")
    assert st["state"] == "ready" and st["taskId"] == "done-1"
    assert st["mountedTaskIds"] == ["done-1"]
    # 运行中任务 → analyzing(优先于挂载态)
    db.execute("INSERT INTO analysis_tasks (id, project_id, type, name, status) "
               "VALUES ('run-2', 'proj-t', 'fast', 'x', 'running')")
    db.commit()
    st = br.derive_readiness(mdb, project_id="proj-t")
    assert st["state"] == "analyzing" and st["taskId"] == "run-2"


def test_readiness_no_analysis(mdb):
    mdb.main_db.execute("DELETE FROM analysis_tasks")
    mdb.main_db.commit()
    st = br.derive_readiness(mdb, project_id="proj-t")
    assert st["state"] == "no_analysis"


def test_ensure_ready_done_is_stable(mdb):
    # 去基线化: done 即 ready, ensure 幂等且不再自动挂载
    st = br.ensure_ready(server=None, multi_db=mdb, project_id="proj-t")
    assert st["state"] == "ready"
    cnt = mdb.main_db.fetchone(
        "SELECT COUNT(*) c FROM view_mounts WHERE project_id='proj-t'")["c"]
    assert cnt == 0
    st2 = br.ensure_ready(server=None, multi_db=mdb, project_id="proj-t")
    assert st2["state"] == "ready"
    tcnt = mdb.main_db.fetchone(
        "SELECT COUNT(*) c FROM analysis_tasks WHERE project_id='proj-t'")["c"]
    assert tcnt == 1


def test_ensure_ready_creates_fast_task(mdb, monkeypatch):
    mdb.main_db.execute("DELETE FROM analysis_tasks")
    mdb.main_db.commit()
    created = {}

    async def fake_enqueue(server, multi_db, task_id, run_id, start_time):
        created["task_id"] = task_id

    monkeypatch.setattr("topoone.engine.analyst_runner.enqueue_analysis_task",
                        fake_enqueue)

    async def _run():
        out = br.ensure_ready(server=object(), multi_db=mdb,
                              project_id="proj-t", task_type="fast")
        await asyncio.sleep(0)  # 让 create_task 的入队协程执行
        return out

    st = asyncio.run(_run())
    assert st["state"] == "analyzing"
    task = mdb.main_db.fetchone(
        "SELECT id, type, name FROM analysis_tasks WHERE id = ?",
        (created.get("task_id"),))
    assert task and task["type"] == "fast"


def test_mount_origin_rejected_value(mdb):
    with pytest.raises(ValueError, match="origin"):
        vs.mount_task(mdb, "proj-t", "done-1", origin="weird")


def test_view_status_exposes_mount_origin(mdb):
    vs.mount_task(mdb, "proj-t", "done-1", origin="auto")
    st = vs.view_status(mdb, "proj-t")
    assert st["mounted"][0]["mountOrigin"] == "auto"


# ── A2: auto 挂载换代 ───────────────────────────────────────


def test_bulk_upsert_preserves_name_manual(mdb):
    pdb = mdb.get_project_db("proj-t")
    store = AnalysisStore(pdb)
    store.bulk_insert_llm_results([{
        "task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
        "comm_id": "c1", "name": "旧名", "summary": "s",
    }])
    pdb.execute(
        "UPDATE community_llm_results SET name_manual='用户命名' "
        "WHERE task_id='done-1' AND comm_id='c1'")
    pdb.commit()
    # 通道重跑: name 更新, name_manual 必须保留
    store.bulk_insert_llm_results([{
        "task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
        "comm_id": "c1", "name": "新名", "summary": "s2",
        "source": "fast-agent",
    }])
    row = store.get_llm_result("done-1", "UNIFIED", "L0", "c1")
    assert row["name"] == "新名"
    assert row["name_manual"] == "用户命名"
    assert row["source"] == "fast-agent"


def test_default_source_is_detail(mdb):
    pdb = mdb.get_project_db("proj-t")
    AnalysisStore(pdb).bulk_insert_llm_results([{
        "task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
        "comm_id": "c2", "name": "n", "summary": "s",
    }])
    row = AnalysisStore(pdb).get_llm_result("done-1", "UNIFIED", "L0", "c2")
    assert row["source"] == "detail"


# ── A3: 命名继承 ────────────────────────────────────────────

def test_inherit_names_jaccard_and_manual_priority(mdb):
    pdb = mdb.get_project_db("proj-t")
    _mk_l0_community(pdb, "done-1", "comm-old-uni-L0-0001", ["a.py", "b.py"])
    _mk_l0_community(pdb, "done-1", "comm-old-uni-L0-0002", ["c.py"])
    AnalysisStore(pdb).bulk_insert_llm_results([
        {"task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
         "comm_id": "comm-old-uni-L0-0001", "name": "旧自动名", "summary": "s1"},
        {"task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
         "comm_id": "comm-old-uni-L0-0002", "name": "旧名2", "summary": "s2"},
    ])
    pdb.execute("UPDATE community_llm_results SET name_manual='手工名' "
                "WHERE comm_id='comm-old-uni-L0-0002'")
    pdb.commit()
    # 新任务: 社区1 文件集高重合(继承); 社区2 完全不同文件(不继承)
    mdb.main_db.execute(
        "INSERT INTO analysis_tasks (id, project_id, type, name, status) "
        "VALUES ('done-2', 'proj-t', 'fast', 'rebuild', 'done')")
    mdb.main_db.commit()
    _mk_l0_community(pdb, "done-2", "comm-new-uni-L0-0001", ["a.py", "b.py"])
    _mk_l0_community(pdb, "done-2", "comm-new-uni-L0-0002", ["z9.py"])

    from topoone.engine.component_naming_fast import inherit_names
    res = inherit_names(mdb, "proj-t", "done-2")
    assert res["inherited"] == 1
    row = AnalysisStore(pdb).get_llm_result(
        "done-2", "UNIFIED", "L0", "comm-new-uni-L0-0001")
    assert row["name"] == "旧自动名" and row["source"] == "inherit"
    # 未达阈值的社区无继承行
    assert AnalysisStore(pdb).get_llm_result(
        "done-2", "UNIFIED", "L0", "comm-new-uni-L0-0002") is None


def test_inherit_names_prefers_manual(mdb):
    pdb = mdb.get_project_db("proj-t")
    _mk_l0_community(pdb, "done-1", "comm-old-uni-L0-0001", ["a.py"])
    AnalysisStore(pdb).bulk_insert_llm_results([
        {"task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
         "comm_id": "comm-old-uni-L0-0001", "name": "自动", "summary": ""}])
    pdb.execute("UPDATE community_llm_results SET name_manual='手工' "
                "WHERE comm_id='comm-old-uni-L0-0001'")
    pdb.commit()
    mdb.main_db.execute(
        "INSERT INTO analysis_tasks (id, project_id, type, name, status) "
        "VALUES ('done-2', 'proj-t', 'fast', 'r', 'done')")
    mdb.main_db.commit()
    _mk_l0_community(pdb, "done-2", "comm-new-uni-L0-0001", ["a.py"])
    from topoone.engine.component_naming_fast import inherit_names
    inherit_names(mdb, "proj-t", "done-2")
    row = AnalysisStore(pdb).get_llm_result(
        "done-2", "UNIFIED", "L0", "comm-new-uni-L0-0001")
    assert row["name"] == "手工" and row["source"] == "inherit"


def test_inherit_names_no_previous(mdb):
    from topoone.engine.component_naming_fast import inherit_names
    assert inherit_names(mdb, "proj-t", "done-1")["reason"] == "no_previous_task"


# ── A3: 命名 JSON 解析 ──────────────────────────────────────

def test_parse_naming_json_variants():
    from topoone.engine.component_naming_fast import _parse_naming_json
    ok = _parse_naming_json(
        '前置说明\n```json\n[{"commId":"c1","name":"网关路由","summary":"路由分发"}]\n```')
    assert ok == [{"commId": "c1", "name": "网关路由", "summary": "路由分发"}]
    assert _parse_naming_json('[{"commId":"c1"}]') == []          # 缺 name
    assert _parse_naming_json('{"commId":"c1","name":"x"}') == []  # 非数组
    assert _parse_naming_json('完全不是 JSON') == []
    long = _parse_naming_json(
        '[{"commId":"c1","name":"%s","summary":"%s"}]' % ("名" * 200, "摘" * 500))
    assert len(long[0]["name"]) == 80 and len(long[0]["summary"]) == 400


# ── A3: run_fast_naming 跳过规则(agentic_chat 打桩) ──────────

def test_run_fast_naming_skips_fixed_and_names_rest(mdb, monkeypatch):
    pdb = mdb.get_project_db("proj-t")
    _mk_l0_community(pdb, "done-1", "comm-a-uni-L0-0001", ["a.py"])
    _mk_l0_community(pdb, "done-1", "comm-b-uni-L0-0002", ["b.py"])
    AnalysisStore(pdb).bulk_insert_llm_results([
        {"task_id": "done-1", "edge_type": "UNIFIED", "comm_lv": "L0",
         "comm_id": "comm-a-uni-L0-0001", "name": "已有手工", "summary": "s"}])
    pdb.execute("UPDATE community_llm_results SET name_manual='手工' "
                "WHERE comm_id='comm-a-uni-L0-0001'")
    pdb.commit()

    async def fake_chat(messages, tools, multi_db, model_id="", **kw):
        return SimpleNamespace(
            content='[{"commId":"comm-a-uni-L0-0001","name":"不应生效"},'
                    '{"commId":"comm-b-uni-L0-0002","name":"新组件名","summary":"职责"}]',
            tool_calls=[], finish_reason="stop")

    monkeypatch.setattr(
        "topoone.agent.agent_workflow.tool_calling.agentic_chat", fake_chat)
    from topoone.engine.component_naming_fast import run_fast_naming
    out = asyncio.run(run_fast_naming(mdb, "proj-t", "done-1"))
    assert out["named"] == 1
    store = AnalysisStore(pdb)
    a = store.get_llm_result("done-1", "UNIFIED", "L0", "comm-a-uni-L0-0001")
    b = store.get_llm_result("done-1", "UNIFIED", "L0", "comm-b-uni-L0-0002")
    assert a["name_manual"] == "手工" and a["name"] == "已有手工"
    assert b["name"] == "新组件名" and b["source"] == "fast-agent"


def test_run_fast_naming_no_components(mdb):
    from topoone.engine.component_naming_fast import run_fast_naming
    out = asyncio.run(run_fast_naming(mdb, "proj-t", "done-1"))
    assert out == {"named": 0, "reason": "no_components"}


# ── A4: 自适应决策(纯函数) ──────────────────────────────────

def test_decide_rebuild_rules():
    # 阈值边界: 30/100 恰好等于阈值 → 不重建(严格大于)
    assert vss.decide_rebuild(31, 100, False, None) is True
    assert vss.decide_rebuild(30, 100, False, None) is False
    assert vss.decide_rebuild(4, 10, False, None) is True
    # 显式 stages 永远优先(不重建, 走调用方选择)
    assert vss.decide_rebuild(99, 100, True, {"ast": True}) is False
    # 分支切换 → 重建
    assert vss.decide_rebuild(1, 1000, True, None) is True
    # 无变更 → 不重建
    assert vss.decide_rebuild(0, 100, False, None) is False


def test_launch_rebuild_without_server(mdb):
    res = vss._launch_rebuild(None, mdb, "proj-t")
    assert res == {"launched": False, "reason": "no_server"}


# ── no_project 分支: import 经 server.methods 注册表调用(回归:
#    import_project 是 register_project_methods 闭包内函数, 延迟
#    from-import 必 ImportError → 冷启动 500) ──────────────────

def test_ensure_ready_no_project_triggers_import(mdb):
    mdb.main_db.execute("DELETE FROM projects")
    mdb.main_db.commit()
    calls = {}

    def fake_import(path, mode="git-local", init_git=False):
        calls["args"] = (path, mode, init_git)
        from topoone.engine.service.project import _IMPORT_JOBS
        _IMPORT_JOBS["imp-test"] = {"status": "running", "projectId": ""}

    class FakeServer:
        methods = {"project.import": fake_import}

    from topoone.engine.service.project import _IMPORT_JOBS
    try:
        st = br.ensure_ready(server=FakeServer(), multi_db=mdb,
                             root="/no/such/root", init_git=True)
    finally:
        _IMPORT_JOBS.pop("imp-test", None)
    assert calls["args"] == ("/no/such/root", "git-local", True)
    assert st["state"] == "importing"


def test_ensure_ready_no_project_without_handler_raises(mdb):
    mdb.main_db.execute("DELETE FROM projects")
    mdb.main_db.commit()

    class NoServer:
        methods = {}

    with pytest.raises(ValueError, match="project.import 未注册"):
        br.ensure_ready(server=NoServer(), multi_db=mdb, root="/x")


def test_ensure_ready_resolves_mirror_rooted_project(mdb):
    """git-local 导入后 root_path=镜像 worktree, 原始根只在 local_repo_path/
    remote_url —— ensureReady(原始根) 必须解析到既有项目, 不得重复建项。"""
    mdb.main_db.execute("DELETE FROM projects")
    mdb.main_db.commit()
    mdb.main_db.execute(
        "INSERT INTO projects (id, name, root_path, import_mode, local_repo_path, remote_url)"
        " VALUES ('proj-m', 'M', '/cache/proj-m/worktree', 'git-local', '/orig/root', '/orig/root')")
    mdb.main_db.commit()

    calls = []

    class FakeServer:
        methods = {"project.import": lambda path, mode="git-local": calls.append(path)}

    import asyncio

    async def _run():
        return br.ensure_ready(server=FakeServer(), multi_db=mdb, root="/orig/root")

    st = asyncio.run(_run())
    assert calls == []  # 未重复建项
    # no_analysis 一步内即建 fast 任务并置 running(ensure_ready 单步语义的
    # 建任务步), 终态 analyzing; 后续调用在任务 done 后走自动挂载。
    assert st["state"] == "analyzing"
    assert st["projectId"] == "proj-m"
    assert st["taskType"] == "fast"
    # report_types 必含 dependency/callChain —— _step5 社区三线之门,
    # 缺失则图谱有节点无社区、fast-naming 空转(回归: ensure 通道漏传)。
    task = mdb.main_db.fetchone(
        "SELECT report_types FROM analysis_tasks WHERE project_id = ?",
        ("proj-m",))
    import json as _json
    assert sorted(_json.loads(task["report_types"])) == ["callChain", "dependency"]


# ── B2+B3: 命名状态落 result_data.naming + rerunNaming 守卫 ──────────

def test_run_naming_recorded_writes_done_and_error(mdb, monkeypatch):
    import asyncio
    from topoone.engine import analyst_runner as ar
    from topoone.engine.store.task_store import TaskStore

    async def ok_naming(multi_db, pid, tid):
        return {"named": 7, "inherited": 2}

    monkeypatch.setattr("topoone.engine.component_naming_fast.run_fast_naming", ok_naming)
    res = asyncio.run(ar._run_naming_recorded(mdb, "proj-t", "done-1"))
    assert res["named"] == 7
    n = TaskStore(mdb.main_db).get_task("done-1")["result_data"]
    n = json.loads(n) if isinstance(n, str) else n
    assert n["naming"]["status"] == "done" and n["naming"]["named"] == 7

    async def boom(multi_db, pid, tid):
        raise RuntimeError("LLM 命名调用失败 (model=model-x, finish=error)")

    monkeypatch.setattr("topoone.engine.component_naming_fast.run_fast_naming", boom)
    with pytest.raises(RuntimeError):
        asyncio.run(ar._run_naming_recorded(mdb, "proj-t", "done-1"))
    n = TaskStore(mdb.main_db).get_task("done-1")["result_data"]
    n = json.loads(n) if isinstance(n, str) else n
    assert n["naming"]["status"] == "error" and "model-x" in n["naming"]["error"]


def test_merge_result_data_merges_not_replaces(mdb):
    from topoone.engine.store.task_store import TaskStore
    st = TaskStore(mdb.main_db)
    st.merge_result_data("done-1", {"a": 1})
    st.merge_result_data("done-1", {"b": 2})
    row = st.get_task("done-1")["result_data"]
    d = json.loads(row) if isinstance(row, str) else row
    assert d == {"a": 1, "b": 2}


def test_rerun_naming_guards(mdb, monkeypatch):
    import asyncio
    import topoone.engine.task_api.tasks_crud as tc

    class FakeServer:
        methods = {}

        def register(self, name):
            def _deco(fn):
                self.methods[name] = fn
                return fn
            return _deco

    tc.register(FakeServer(), mdb, type("S", (), {"_agent_proxy": None})())

    handler = FakeServer.methods["analysis.rerunNaming"]

    # 未 done 任务拒绝
    mdb.main_db.execute(
        "INSERT INTO analysis_tasks (id, project_id, type, name, status)"
        " VALUES ('t-run', 'proj-t', 'fast', 'r', 'running')")
    mdb.main_db.commit()
    with pytest.raises(ValueError, match="not done"):
        asyncio.run(handler(task_id="t-run"))

    # done 任务: 标记 running 后二启拒绝; 后台体 monkeypatch 防真跑
    async def fake_bg(multi_db, pid, tid):
        return None

    monkeypatch.setattr(tc, "_rerun_naming_bg", fake_bg)
    from topoone.engine.store.task_store import TaskStore
    out = asyncio.run(handler(task_id="done-1"))
    assert out["started"] is True
    out2 = asyncio.run(handler(task_id="done-1"))
    assert out2["started"] is False and out2["reason"] == "naming already running"
    n = TaskStore(mdb.main_db).get_task("done-1")["result_data"]
    n = json.loads(n) if isinstance(n, str) else n
    assert n["naming"]["status"] == "running"


# ── 全层级命名: L1 子组件 + 父名透传 + 总量护栏 ─────────────────────

def _seed_hierarchy(pdb, task_id, l0, l1):
    """community_hierarchy + graph_doc 两层插桩。"""
    for cid, parent, n in l0:
        pdb.execute(
            "INSERT INTO community_hierarchy (task_id, edge_type, comm_lv, comm_id,"
            " parent_comm_id, node_count) VALUES (?, 'UNIFIED', 'L0', ?, ?, ?)",
            (task_id, cid, parent, n))
        pdb.execute(
            "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count)"
            " VALUES (?, 'UNIFIED', 'L0', ?, ?, ?)", (task_id, cid, __import__('json').dumps([f"f{i}.py" for i in range(n)]), n))
    for cid, parent, n in l1:
        pdb.execute(
            "INSERT INTO community_hierarchy (task_id, edge_type, comm_lv, comm_id,"
            " parent_comm_id, node_count) VALUES (?, 'UNIFIED', 'L1', ?, ?, ?)",
            (task_id, cid, parent, n))
        pdb.execute(
            "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count)"
            " VALUES (?, 'UNIFIED', 'L1', ?, ?, ?)", (task_id, cid, __import__('json').dumps([f"g{i}.py" for i in range(n)]), n))
    pdb.commit()


def _mk_multi(mdb, monkeypatch, captured, l0_out, l1_out):
    """agentic_chat 桩: 按 brief 里组件数返回对应 JSON; 捕获每层 prompt。"""
    import json as _json
    from types import SimpleNamespace

    async def fake_chat(messages, tools, multi_db, model_id, **kw):
        brief = messages[1]["content"]
        captured.append(brief)
        n = 3 if "3 个组件" in brief else 2
        out = l0_out if "parent" not in brief else l1_out
        resp = SimpleNamespace(finish_reason="stop", content=_json.dumps(out),
                               tool_calls=[], tokens_used=1)
        return resp

    monkeypatch.setattr(
        "topoone.agent.agent_workflow.tool_calling.agentic_chat", fake_chat)
    monkeypatch.setattr(
        "topoone.agent.agent_workflow.tool_calling.strategy._resolve_model_id",
        lambda mdb: "model-x")


def test_fast_naming_covers_all_levels_with_parent_names(mdb, monkeypatch):
    import asyncio
    import json as _json
    from topoone.engine.component_naming_fast import run_fast_naming
    pdb = mdb.get_project_db("proj-t")
    _seed_hierarchy(pdb, "done-1",
                    [("c1", None, 3), ("c2", None, 3), ("c3", None, 3)],
                    [("s1", "c1", 2), ("s2", "c2", 2)])
    captured: list = []
    _mk_multi(mdb, monkeypatch, captured,
              [{"commId": f"c{i}", "name": f"顶层{i}", "summary": ""} for i in (1, 2, 3)],
              [{"commId": "s1", "name": "子组件一", "summary": ""},
               {"commId": "s2", "name": "子组件二", "summary": ""}])
    res = asyncio.run(run_fast_naming(mdb, "proj-t", "done-1"))
    assert res["named"] == 5
    assert res["perLevel"] == {"L0": 3, "L1": 2}
    assert res["truncated"] is False
    # L1 prompt 附父名(L0 已命名)
    l1_brief = [b for b in captured if "parent" in b][0]
    assert "顶层1" in l1_brief and "顶层2" in l1_brief
    rows = pdb.fetchall(
        "SELECT comm_lv, comm_id FROM community_llm_results"
        " WHERE task_id='done-1' ORDER BY comm_lv, comm_id")
    assert [(r["comm_lv"], r["comm_id"]) for r in rows] == [
        ("L0", "c1"), ("L0", "c2"), ("L0", "c3"), ("L1", "s1"), ("L1", "s2")]


def test_fast_naming_component_cap_truncates(mdb, monkeypatch):
    import asyncio
    import json as _json
    import topoone.engine.component_naming_fast as cnf
    from topoone.config import FAST_NAMING_MAX_COMPONENTS
    pdb = mdb.get_project_db("proj-t")
    many = [(f"c{i}", None, 2) for i in range(FAST_NAMING_MAX_COMPONENTS + 5)]
    _seed_hierarchy(pdb, "done-1", many, [])
    captured: list = []
    _mk_multi(mdb, monkeypatch, captured,
              [{"commId": "c1", "name": "n", "summary": ""}], [])
    res = asyncio.run(cnf.run_fast_naming(mdb, "proj-t", "done-1"))
    assert res["truncated"] is True
    total_sent = sum(b.count("commId") for b in captured)
    assert total_sent <= FAST_NAMING_MAX_COMPONENTS
