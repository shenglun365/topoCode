"""I1 测试：TopoDataProvider / TopoPipelineProvider / 流水线回调（主项目 project_db → tAgent 协议）。"""

from __future__ import annotations

import json
import os

import pytest

from topoone.agent.tagent_host import (
    TopoDataProvider,
    TopoPipelineProvider,
    build_topo_pipeline_callbacks,
)
from helpers import seed_communities, seed_symbols

TASK = "t1"
PID = "p1"
ROOT = "/proj"


@pytest.fixture
def provider(project_db):
    seed_symbols(project_db, TASK, ROOT)
    return TopoDataProvider(None, project_db, project_root=ROOT, project_id=PID, task_id=TASK)


@pytest.fixture
def pipe_provider(project_db, multi_db):
    seed_symbols(project_db, TASK, ROOT)
    seed_communities(project_db, TASK, ROOT)
    multi_db.get_project_db = lambda pid: project_db if pid == PID else None
    multi_db.main_db.execute(
        "INSERT INTO projects (id, name, summary) VALUES (?, 'demo', 'A demo project.')", (PID,))
    return TopoPipelineProvider(multi_db, project_db, project_root=ROOT,
                                project_id=PID, task_id=TASK)


# ── TopoDataProvider ──

def test_symbol_detail(provider):
    d = provider.symbol_detail(f"sym-parse-{TASK}")
    assert d and d["name"] == "parse_user"
    assert d["file_path"] == "auth.py"  # 相对化


def test_symbol_search(provider):
    rows = provider.symbol_search("auth")
    names = {r["name"] for r in rows}
    assert "AuthService" in names
    kind_rows = provider.symbol_search("auth", kind="class")
    assert all(r["kind"] == "class" for r in kind_rows)
    assert provider.symbol_search("zzz-none") == []


def test_neighbors_and_edge_detail(provider):
    edges = provider.neighbors(f"sym-parse-{TASK}")
    assert len(edges) == 1
    assert edges[0]["target_id"] == f"sym-auth-{TASK}"
    assert edges[0]["relation"] == "call"
    d = provider.edge_detail(f"edge-1-{TASK}")
    assert d and d["source_id"] == f"sym-parse-{TASK}"
    assert d["type"] == "call"


def test_community_subgraph(provider):
    seed_communities(provider._db, TASK, ROOT)
    g = provider.community_subgraph(TASK, "comm-incl-L0-0001")
    assert g is not None
    assert g["edge_type"] == "INCLUDE"
    assert g["nodes"] and g["nodes"][0]["name"] == "parse_user"
    assert provider.community_subgraph(TASK, "comm-missing") is None


def test_file_content_sandbox(tmp_path):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "a.py").write_text("print('a')\n", encoding="utf-8")
    outside = tmp_path / "secret.py"  # root 的兄弟目录
    outside.write_text("secret", encoding="utf-8")
    p = TopoDataProvider(None, None, project_root=str(root))
    assert p.file_content("a.py") == "print('a')\n"
    # 越界路径被拒绝
    assert p.file_content(str(outside)) is None
    assert p.file_content("../secret.py") is None


def test_ast_node_and_resolve(provider):
    provider._db.execute(
        "INSERT INTO base_node (node_id, file_id, kind, code) VALUES ('n1', 'f1', 'fn', 'x=1')")
    n = provider.ast_node("n1", "f1")
    assert n and n["code"] == "x=1"
    provider._db.execute(
        "INSERT INTO graph_doc (task_id, edge_type, comm_lv, comm_id, node_list, node_count) "
        "VALUES (?, 'INCLUDE', 'L0', 'comm-x', '[]', 0)", (TASK,))
    assert provider.resolve_task_id("comm-x") == TASK


def test_graph_query_select_only(provider):
    rows = provider.graph_query("SELECT id FROM graph_node")
    assert len(rows) == 2
    assert provider.graph_query("DELETE FROM graph_node") == []


# ── TopoPipelineProvider ──

def test_list_level_components(pipe_provider):
    all_comps = pipe_provider.list_level_components(TASK, "L0", include_analyzed=True)
    assert {c["id"] for c in all_comps} == {"comm-incl-L0-0001", "comm-call-L0-0002"}
    by_id = {c["id"]: c for c in all_comps}
    assert by_id["comm-incl-L0-0001"]["edgeType"] == "INCLUDE"
    assert by_id["comm-incl-L0-0001"]["metadata"]["nodeCount"] == 10
    # 未分析过滤：comm-incl-L0-0001 已 completed → 只剩 CALL 的
    unanalyzed = pipe_provider.list_level_components(TASK, "L0", include_analyzed=False)
    assert [c["id"] for c in unanalyzed] == ["comm-call-L0-0002"]


def test_get_project_summary(pipe_provider):
    assert pipe_provider.get_project_summary(PID) == "A demo project."
    assert pipe_provider.get_project_summary("p-missing") is None


def test_has_overview_and_rows(pipe_provider):
    assert pipe_provider.has_overview(TASK) is False
    pipe_provider._db.execute(
        "INSERT INTO report_subdocs (id, task_id, edge_type, comm_id, title, content) "
        "VALUES ('ov1', ?, 'INCLUDE', 'overall', 'Architecture Overview', '# Overview')", (TASK,))
    assert pipe_provider.has_overview(TASK) is True
    rows = pipe_provider.list_overview_rows(TASK)
    assert len(rows["INCLUDE"]) == 1
    assert rows["INCLUDE"][0]["name"] == "Auth Module"
    assert rows["INCLUDE"][0]["comm_lv"] == "L0"
    assert rows["CALL"] == []


def test_list_key_file_summaries(pipe_provider):
    pipe_provider._db.execute(
        "INSERT INTO file_summaries (id, project_id, task_id, file_path, summary, summary_len) "
        "VALUES ('fs1', ?, ?, 'a.py', 'alpha summary', 13)", (PID, TASK))
    out = pipe_provider.list_key_file_summaries(TASK, PID)
    assert out == [("a.py", "alpha summary")]


def test_list_batch_files(pipe_provider, monkeypatch):
    calls = {}

    def fake_ranks(task_id, project_db, components, project_root=""):
        calls["components"] = len(components)
        return {"files": [
            {"file_path": "a.py", "batch": "P0", "score": 90},
            {"file_path": "b.py", "batch": "P1", "score": 50},
        ], "counts": {"P0": 1, "P1": 1, "P2": 0}}

    monkeypatch.setattr("topoone.engine.task_manager._compute_file_ranks", fake_ranks)
    all_p0 = pipe_provider.list_batch_files(TASK, PID, "P0", include_cached=True)
    assert all_p0 == ["a.py"]
    assert calls["components"] == 2  # L0 社区（INCLUDE+CALL）
    # 缓存过滤：a.py 已有摘要
    pipe_provider._db.execute(
        "INSERT INTO file_summaries (id, project_id, file_path, summary) VALUES ('fs1', ?, 'a.py', 'x')",
        (PID,))
    uncached = pipe_provider.list_batch_files(TASK, PID, "P0", include_cached=False)
    assert uncached == []


# ── 流水线回调 ──

def test_save_component_result_ingest(pipe_provider, multi_db, tmp_path):
    cbs = build_topo_pipeline_callbacks(multi_db, PID, TASK, model_id="m1")
    cbs.save_component_result({
        "task_id": TASK, "component_id": "comm-call-L0-0002",
        "component_type": "community", "analyzed_name": "Call Module",
        "functional_summary": "Handles calls.", "status": "completed",
        "edge_type": "CALL", "comm_lv": "L0",
    })
    # ingest 写到 data_dir 下（.json 文件）
    ingest_dir = os.path.join(multi_db.data_dir, "ingest")
    found = []
    for root, _dirs, files in os.walk(multi_db.data_dir):
        for f in files:
            if f.endswith(".json"):
                with open(os.path.join(root, f), encoding="utf-8") as fh:
                    found.append(json.load(fh))
    assert any(d.get("comm_id") == "comm-call-L0-0002" and d.get("_type") == "community_result"
               for d in found), f"ingest not found: {found}"


def test_save_overview_doc(pipe_provider, multi_db, monkeypatch):
    saved = {}

    def fake_save(mdb, task_id, title, content):
        saved.update(task_id=task_id, title=title, content=content)
        return {"id": "ov-new"}

    monkeypatch.setattr("topoone.engine.report_tree_service.save_overall_doc", fake_save)
    cbs = build_topo_pipeline_callbacks(multi_db, PID, TASK)
    cbs.save_overview({"task_id": TASK, "title": "Architecture Overview", "content": "# OV"})
    assert saved == {"task_id": TASK, "title": "Architecture Overview", "content": "# OV"}


def test_callbacks_types(pipe_provider, multi_db):
    from topocode_agent.workflows.pipeline import PipelineCallbacks
    cbs = build_topo_pipeline_callbacks(multi_db, PID, TASK)
    assert isinstance(cbs, PipelineCallbacks)
    assert cbs.generate_project_summary is not None
    assert cbs.file_summarizer is not None
