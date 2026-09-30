"""批 1 数据层测试：rev 锚点视角过滤 + arch_semantic_jobs 作业存储。"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

import topoone_app_architect.ctx as C
from topoone_app_architect.store import SemanticAssetsStore, SemanticJobsStore
from topoone_app_architect.store.jobs import _now
from topoone_app_architect.sem.incremental import _canonical_key

PID = ""


def _ctx_setup(tmp_path, monkeypatch):
    """与 test_semantic_assets._ctx 同款单例重置；不设 contextvar
    （set_project 泄漏会让 _resolve_pid 的 contextvar 优先级污染后续测试，
    实测 36 用例回归——store 调用全部显式传 pid，无需 contextvar）。"""
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "data"))
    C._db = None
    C._kb = None
    C._project_dbs.clear() if hasattr(C, "_project_dbs") else None
    C.setup(data_dir=str(tmp_path / "data"))
    global PID
    PID = "proj-b1revtest"


# ── rev 锚点视角 ─────────────────────────────────────────────

def test_canonical_key_rev_changes_identity(tmp_path, monkeypatch):
    _ctx_setup(tmp_path, monkeypatch)
    refs = [{"file": "a.ts", "symbol": "foo", "kind": "function"}]
    k_ws = _canonical_key("process", "implementation", refs, rev="workspace")
    k_base = _canonical_key("process", "implementation", refs, rev="baseline:v1")
    k_legacy = _canonical_key("process", "implementation", refs, rev="")
    assert k_ws != k_base != k_legacy
    # 同 rev 幂等
    assert k_ws == _canonical_key("process", "implementation", refs, rev="workspace")


def test_rev_search_scoping(tmp_path, monkeypatch):
    _ctx_setup(tmp_path, monkeypatch)
    for rid, name in (("workspace", "工作区资产"), ("baseline:v1", "基线资产"),
                      ("head:abc", "head资产"), ("", "legacy底座")):
        SemanticAssetsStore.create({
            "id": f"sa-{name}", "projectId": PID, "kind": "process",
            "level": "implementation", "name": name, "rev": rid,
            "status": "active", "scopeType": "files", "scopeKey": "",
            "createdAt": 1, "updatedAt": 1,
        })
    # workspace 视角 = 底座(legacy+baseline) ∪ workspace
    rows = SemanticAssetsStore.search(PID, rev="workspace", limit=50)
    names = {r["name"] for r in rows}
    assert {"工作区资产", "基线资产", "legacy底座"} <= names
    assert "head资产" not in names
    # head 视角 = 底座 ∪ head
    names_h = {r["name"] for r in SemanticAssetsStore.search(PID, rev="head:abc", limit=50)}
    assert {"head资产", "基线资产", "legacy底座"} <= names_h
    assert "工作区资产" not in names_h
    # 不过滤 = 全量
    assert len(SemanticAssetsStore.search(PID, limit=50)) == 4
    assert SemanticAssetsStore.count(PID, rev="workspace") == 3


# ── 作业存储 ─────────────────────────────────────────────────

def test_job_lifecycle(tmp_path, monkeypatch):
    _ctx_setup(tmp_path, monkeypatch)
    job = SemanticJobsStore.create(PID, "extract_delta", {"type": "project"}, llm=True)
    assert job["state"] == "queued" and job["llm"] == 1
    # claim（LLM 选择器）
    got = SemanticJobsStore.claim_next(PID, llm=True)
    assert got and got["id"] == job["id"] and got["state"] == "running"
    assert SemanticJobsStore.claim_next(PID, llm=True) is None   # 无其他排队
    # 非该类选择器取不到 running
    assert SemanticJobsStore.claim_next("proj-other", llm=True) is None
    # 进度更新
    SemanticJobsStore.update(job["id"], {"progress": {"total": 10, "done": 3}})
    assert SemanticJobsStore.get(job["id"])["progress"] == {"total": 10, "done": 3}
    # 取消请求 + 终态
    SemanticJobsStore.request_cancel(job["id"])
    assert SemanticJobsStore.get(job["id"])["cancelRequested"] == 1
    SemanticJobsStore.finish(job["id"], state="cancelled", result={"summary": "x"})
    row = SemanticJobsStore.get(job["id"])
    assert row["state"] == "cancelled" and row["finishedAt"] > 0
    # 列表过滤
    assert SemanticJobsStore.list(PID, state="cancelled")[0]["id"] == job["id"]
    assert SemanticJobsStore.active(PID) == []


def test_job_delete_and_clear_finished(tmp_path, monkeypatch):
    """终态作业可删（活跃拒绝）；清除只删终态行。"""
    _ctx_setup(tmp_path, monkeypatch)
    done = SemanticJobsStore.create(PID, "extract_impl", {"type": "files"})
    SemanticJobsStore.finish(done["id"], state="done", result={"summary": "ok"})
    cancel = SemanticJobsStore.create(PID, "extract_delta")
    SemanticJobsStore.finish(cancel["id"], state="cancelled")
    running = SemanticJobsStore.create(PID, "enhance_desc", llm=True)
    SemanticJobsStore.update(running["id"], {"state": "running", "startedAt": _now()})
    # 活跃作业删除拒绝
    with pytest.raises(ValueError):
        SemanticJobsStore.delete(running["id"])
    # 终态单删
    assert SemanticJobsStore.delete(cancel["id"]) is True
    assert SemanticJobsStore.get(cancel["id"]) is None
    # 清除：只删终态（done），running 保留
    assert SemanticJobsStore.clear_finished(PID) == 1
    assert SemanticJobsStore.get(done["id"]) is None
    assert SemanticJobsStore.get(running["id"]) is not None
    # 再清一次无终态可清
    assert SemanticJobsStore.clear_finished(PID) == 0


def test_job_recover_lost(tmp_path, monkeypatch):
    _ctx_setup(tmp_path, monkeypatch)
    job = SemanticJobsStore.create(PID, "enhance_desc", llm=True)
    SemanticJobsStore.update(job["id"], {"state": "running", "startedAt": 1})  # 远古启动
    from topoone_app_architect.sem import job_runner
    job_runner._recovered.discard(PID)
    job_runner.recover(PID)
    assert SemanticJobsStore.get(job["id"])["state"] == "lost"


# ── 结构化提取骨架(批2-3, 纯函数) ─────────────────────────────

def test_build_file_skeleton_mapping():
    from topoone_app_architect.sem.structural_extract import build_file_skeleton
    parsed = {
        "symbols": [
            {"name": "Order", "kind": "interface", "qualifiedName": "m::Order",
             "startLine": 1, "endLine": 10, "signature": "interface Order",
             "docstring": "订单实体"},
            {"name": "create", "kind": "function", "qualifiedName": "m::create",
             "startLine": 12, "endLine": 20, "signature": None},
        ],
        "implDetails": {
            "statements": [
                {"type": "loop", "condition": "for it in items", "startLine": 13,
                 "endLine": 15, "enclosing": "create"},
            ],
            "constants": [
                {"name": "id", "value": "string;", "line": 2},
                {"name": "n", "value": "number;", "line": 3},
            ],
        },
    }
    out = build_file_skeleton("m/a.ts", parsed)
    ent = [a for a in out if a["kind"] == "entity"]
    proc = [a for a in out if a["kind"] == "process"]
    assert len(ent) == 1 and len(proc) == 1
    assert ent[0]["detail"]["fields"] == [{"name": "id", "type": "string"}, {"name": "n", "type": "number"}]
    assert ent[0]["desc"] == "订单实体"
    assert proc[0]["detail"]["trigger"] == ""
    assert len(proc[0]["detail"]["steps"]) == 1
    assert "loop" in proc[0]["detail"]["steps"][0]["semantic"]
    # 锚点 kind 归一化(func)——过 _asset_anchor_kind_ok 白名单
    assert proc[0]["astRefs"][0]["kind"] == "func"
