"""A3/A4 端点测试：rejudge(stale 重判) + confirm(PUT+rejudge+run) + verify(验证报告)。

临时 DB + TestClient + ScriptedGateway(脚本化 LLM) + StubRunner(记录调用)，零真实 HTTP/LLM。
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient
from topoone_app_architect.arch_routes import store
from topoone_app_architect.arch_routes import kb_gateway, runner_gateway
from topoone_app_architect.server import build_app


class ScriptedGateway:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def call(self, method, timeout=None, **params):
        self.calls.append((method, params))
        if method != "llm.sync":
            return None
        if not self.script:
            return {"content": "", "mode": "chat"}
        return self.script.pop(0)


class StubRunner:
    def __init__(self, tree):
        self._tree = tree
        self.updates = []
        self.rejudges = []
        self.runs = []

    def get_tree(self, tree_id):
        return {"tree": self._tree, "progress": {"tree_id": tree_id, "total": 3}}

    def update_tree(self, tree_id, tree_dict):
        self.updates.append((tree_id, tree_dict))
        return True

    def rejudge(self, tree_id, task_ids):
        self.rejudges.append((tree_id, list(task_ids)))
        return True

    def run(self, tree_id):
        self.runs.append(tree_id)
        return {"progress": {"tree_id": tree_id}}


# runner 当前树：t-2 stale
RUNNER_TREE = {"roots": [
    {"id": "tp-1", "title": "方案", "kind": "epic", "status": "done", "depends_on": [],
     "context": [], "files": [], "est_min": 120, "source_hash": "", "children": [
        {"id": "t-1", "title": "梳理", "kind": "task", "status": "done", "depends_on": [],
         "context": [], "files": ["a.go"], "est_min": 30, "source_hash": "h1", "children": []},
        {"id": "t-2", "title": "实现", "kind": "task", "status": "stale", "depends_on": ["t-1"],
         "context": [], "files": ["b.go"], "est_min": 90, "source_hash": "h2", "children": []},
    ]},
]}

REJUDGE_TREE_JSON = (
    '{"roots": [{"id": "tp-1", "title": "方案", "kind": "epic", "est_min": 120, "children": ['
    '{"id": "t-1", "title": "梳理", "kind": "task", "est_min": 30, "files": ["a.go"]},'
    '{"id": "t-2", "title": "实现(重判)", "kind": "task", "est_min": 90, "depends_on": ["t-1"], "files": ["b.go", "c.go"]}]}]}'
)
VERIFY_JSON = '{"passed": true, "issues": [], "unmet_requirements": [], "report": "变更满足需求"}'


@pytest.fixture
def client(tmp_path, monkeypatch):
    # ctx._db 为进程级单例 → 重置以强制指向本测试的临时库
    from topoone_app_architect.arch_routes import ctx
    monkeypatch.setattr(ctx, "_db", None, raising=False)
    monkeypatch.setattr(ctx, "_data_dir", None, raising=False)
    app = build_app(data_dir=str(tmp_path / "arch"))
    c = TestClient(app)
    # 种子：需求 + 方案 + 树 + 执行任务(带 runnerTreeId)
    now = store._ts() if hasattr(store, "_ts") else 0
    from topoone_app_architect.arch_routes.common import _ts
    now = _ts()
    store.RequirementsStore.create({
        "id": "req-1", "title": "订单退款", "desc": "支持退款", "kind": "user-story",
        "status": "planned", "analysis": {"assessmentSummary": "可行"}, "updatedAt": now,
    })
    store.PlansStore.create({
        "id": "plan-1", "reqIds": ["req-1"], "title": "批次", "approach": "x",
        "changes": [], "impact": {"affected": [], "grade": "S"}, "status": "confirmed",
        "taskPlanId": "tp-1", "baseCommit": "abc123", "updatedAt": now,
    })
    store.TaskTreesStore.upsert("tree-1", {
        "id": "tree-1", "planId": "plan-1",
        "root": {"id": "tp-1", "title": "方案", "kind": "epic", "status": "pending",
                 "estMin": 120, "context": [], "files": [], "dependsOn": [],
                 "children": [{"id": "t-2", "title": "实现", "kind": "task", "status": "pending",
                               "estMin": 90, "context": [], "files": ["b.go"], "dependsOn": []}]},
        "revision": 1, "history": [], "updatedAt": now,
    })
    stub = StubRunner(RUNNER_TREE)
    monkeypatch.setattr(runner_gateway, "get_runner", lambda: stub)
    store.ExecutionTasksStore.create({
        "id": "ex-1", "planId": "plan-1", "adapter": "opencode", "model": "m",
        "reqIds": ["req-1"], "connectivity": "ok", "status": "blocked",
        "sessionIds": [], "baseCommit": "abc123", "runCount": 1, "treeRevision": 0,
        "testIds": [], "amendments": [],
        "stats": {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0},
        "instanceId": "", "taskBranch": "arch/ex-1", "branchMode": "auto",
        "runnerTreeId": "tree-stub-1", "createdAt": now, "updatedAt": now,
    })
    c._stub = stub  # 测试断言用
    return c


def test_rejudge_and_confirm(client, monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": REJUDGE_TREE_JSON, "mode": "chat"}]))
    res = client.post("/api/architect/exec/ex-1/rejudge")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["treeId"] == "tree-stub-1"
    assert body["staleIds"] == ["t-2"]
    assert body["newTree"]["children"][1]["title"] == "实现(重判)"
    # pending 已落库
    task = store.ExecutionTasksStore.get("ex-1")
    assert task["status"] == "blocked"
    assert task["pendingRejudge"]["staleIds"] == ["t-2"]
    assert task["pendingRejudge"]["tree"]["roots"][0]["children"][1]["files"] == ["b.go", "c.go"]

    # confirm → PUT + rejudge + run
    res2 = client.post("/api/architect/exec/ex-1/rejudge/confirm")
    assert res2.status_code == 200, res2.text
    stub = client._stub
    assert len(stub.updates) == 1
    assert stub.updates[0][0] == "tree-stub-1"
    assert stub.updates[0][1]["roots"][0]["children"][1]["files"] == ["b.go", "c.go"]
    assert stub.rejudges == [("tree-stub-1", ["t-2"])]
    assert stub.runs == ["tree-stub-1"]
    task = store.ExecutionTasksStore.get("ex-1")
    assert task["pendingRejudge"] in (None, "")
    assert task["status"] == "running"


def test_rejudge_no_stale_409(client, monkeypatch):
    # 无 stale 节点 → 409（重新 monkeypatch get_runner 返回无 stale 的树）
    monkeypatch.setattr(runner_gateway, "get_runner", lambda: StubRunner({"roots": [
        {"id": "tp-1", "title": "x", "kind": "epic", "status": "done", "depends_on": [],
         "context": [], "files": [], "est_min": 1, "source_hash": "", "children": []}]}))
    res = client.post("/api/architect/exec/ex-1/rejudge")
    assert res.status_code == 400  # err() 恒 400，业务码 409 在 body
    assert res.json()["code"] == 409


def test_verify(client, monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": VERIFY_JSON, "mode": "chat"}]))
    res = client.post("/api/architect/exec/ex-1/verify")
    assert res.status_code == 200, res.text
    body = res.json()["data"]
    assert body["treeId"] == "tree-stub-1"
    assert body["passed"] is True
    assert body["report"] == "变更满足需求"
    assert body["issues"] == []


def test_rejudge_missing_tree_409(client, monkeypatch):
    # 无 runnerTreeId → 409
    store.ExecutionTasksStore.update("ex-1", {"runnerTreeId": ""})
    res = client.post("/api/architect/exec/ex-1/rejudge")
    assert res.status_code == 400
    assert res.json()["code"] == 409
