"""遗留#3 资产级增量重析: merge_files 写入语义 + collect_graph 增量分支 +
assets_of_files 反查 + E3 受影响资产清单 + E4 增量排队。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _env(tmp_path, monkeypatch):
    import topoone_app_architect.ctx as C
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "data"))
    C._db = None
    C._kb = None
    C.setup(data_dir=str(tmp_path / "data"))
    from topoone_app_architect import store
    store.ProjectsStore.upsert("p-inc", {"name": "t", "rootPath": str(tmp_path)})
    return store


def test_merge_files_incremental_semantics(tmp_path, monkeypatch):
    """merge_files: 变更文件旧节点删+牵连边删, 未变文件保留。"""
    store = _env(tmp_path, monkeypatch)
    from topoone_app_architect.store.graph import GraphStore
    rev = "baseline:abc"
    # 全量: a.ts(2节点) + b.ts(1节点), a→b 边
    GraphStore.replace_rev("p-inc", rev, [
        {"id": "n1", "kind": "function", "name": "fa", "file_path": "src/a.ts"},
        {"id": "n2", "kind": "function", "name": "ga", "file_path": "src/a.ts"},
        {"id": "n3", "kind": "function", "name": "fb", "file_path": "src/b.ts"},
    ], [{"source": "n1", "target": "n3", "kind": "calls"}])
    assert GraphStore.counts("p-inc", rev) == {"nodes": 3, "edges": 1}
    # 增量: a.ts 重析(只 1 节点, 无边)——n1/n2 删, 牵连边删, n3 保留
    out = GraphStore.merge_files("p-inc", rev, ["src/a.ts"],
                                 [{"id": "n1", "kind": "function", "name": "fa2",
                                   "file_path": "src/a.ts"}], [])
    assert out["removedNodes"] == 2 and out["removedEdges"] == 1
    assert GraphStore.counts("p-inc", rev) == {"nodes": 2, "edges": 0}
    # b.ts 节点仍在(n3)
    rows = GraphStore.nodes_of_rev("p-inc", rev) if hasattr(GraphStore, "nodes_of_rev") else None
    import sqlite3
    from topoone_app_architect.store.base import _fetchall_routed
    rr, _ = _fetchall_routed("arch_graph_node",
                             "SELECT id FROM arch_graph_node WHERE project_id=? AND rev=?",
                             ("p-inc", rev), "p-inc")
    ids = {r["id"] for r in rr}
    assert ids == {"n1", "n3"}


def test_assets_of_files_reverse_lookup(tmp_path, monkeypatch):
    store = _env(tmp_path, monkeypatch)
    from topoone_app_architect.store.semantic import SemanticAssetsStore
    SemanticAssetsStore.create({
        "projectId": "p-inc", "kind": "service", "level": "L1", "name": "对账服务",
        "desc": "d", "astRefs": [{"file": "src/bill/recon.ts", "line": 10}],
        "scopeType": "file", "scopeKey": "src/bill/recon.ts"})
    SemanticAssetsStore.create({
        "projectId": "p-inc", "kind": "config", "level": "L2", "name": "无关配置",
        "desc": "d", "astRefs": [{"file": "src/other.ts"}],
        "scopeType": "file", "scopeKey": "src/other.ts"})
    hits = SemanticAssetsStore.assets_of_files("p-inc", ["src/bill/recon.ts"])
    assert [h["name"] for h in hits] == ["对账服务"]
    assert SemanticAssetsStore.assets_of_files("p-inc", []) == []


def test_acceptance_brief_lists_affected_assets(tmp_path, monkeypatch):
    """E3 清单段: changed→assets 命中展示/无命中如实标注。"""
    store = _env(tmp_path, monkeypatch)
    from topoone_app_architect.agent.execution.exec_bridge import _acceptance_brief
    from topoone_app_architect.store.core import RequirementsStore
    SemanticAssetsStore = store.SemanticAssetsStore
    SemanticAssetsStore.create({
        "projectId": "p-inc", "kind": "service", "level": "L1", "name": "对账服务",
        "desc": "d", "astRefs": [{"file": "src/bill/recon.ts"}],
        "scopeType": "file", "scopeKey": "src/bill/recon.ts"})
    conv = store.ConversationsStore.create({"projectId": "p-inc", "title": "c"})
    orig = RequirementsStore.spec_active
    RequirementsStore.spec_active = classmethod(lambda cls, rid: {"snapshot": {}})
    try:
        brief = _acceptance_brief(conv["id"], "", ["src/bill/recon.ts"], "")
        assert "受影响语义资产" in brief and "[service] 对账服务" in brief
        brief2 = _acceptance_brief(conv["id"], "", ["src/none.ts"], "")
        assert "无命中" in brief2
    finally:
        RequirementsStore.spec_active = orig


def test_merge_queues_incremental_when_changed_known(monkeypatch, tmp_path):
    """E4 增量优先: progress.changedFiles 已知 → collect_graph+incremental。"""
    from topoone_app_architect.agent.execution import merge as mg
    from topoone_app_architect import store
    started = []

    import topoone_app_architect.sem.job_runner as _jr
    monkeypatch.setattr(_jr, "start_job",
                        lambda pid, kind, scope=None, **kw:
                        started.append((pid, kind, scope)) or {"started": True})
    conv = store.ConversationsStore.create({
        "projectId": "p-e4i", "title": "m", "meta": {"root": str(tmp_path)}})
    t = store.TasksStore.create({
        "conversationId": conv["id"], "projectId": "p-e4i", "title": "合并",
        "instruction": "x", "status": "done", "branch": "task/x",
        "runnerJobId": "j1"})
    store.TasksStore.set_progress(t["id"], {"changedFiles": ["src/a.ts", "src/b.ts"]})
    monkeypatch.setattr(mg, "merge_precheck",
                        lambda tid: {"ok": True, "checkable": False,
                                     "advice": "融合模式(直接写入项目目录)"})
    mg.merge_branch(t["id"])
    assert started and started[-1][1] == "collect_graph"
    assert started[-1][2]["incremental"] is True
    assert started[-1][2]["files"] == ["src/a.ts", "src/b.ts"]
