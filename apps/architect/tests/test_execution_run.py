"""A1 端点测试：POST /exec/{task_id}/run — 确认树 → CodingTaskTree → runner 提交。

临时 DB + stub runner(记录调用)，零真实 HTTP/LLM。验证：
- 从 DB 还原树并校验、构建 context、se.execute(on_submit=runner) 取 tree_id
- tree_id 落库(runnerTreeId)、状态→running、runCount+1、触发 runner.run
- runner 不可达 → 502；任务不存在 → 404
"""
import asyncio
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.responses import JSONResponse
from topoone_app_architect.arch_routes import ctx, store
from topoone_app_architect.arch_routes import runner_gateway
from topoone_app_architect.arch_routes import execution
from topoone_app_architect.arch_routes.common import _ts


def _err_code(res) -> int:
    """err() 恒 status 400，业务码在 body.code。"""
    assert isinstance(res, JSONResponse)
    return json.loads(res.body)["code"]


FE_TREE = {
    "id": "tp-1", "title": "方案", "kind": "epic", "status": "pending",
    "estMin": 120, "context": [], "files": [], "dependsOn": [],
    "children": [
        {"id": "t-1", "title": "梳理现状", "kind": "task", "status": "pending",
         "estMin": 30, "context": ["c1"], "files": ["a.go"], "dependsOn": []},
        {"id": "t-2", "title": "实现核心", "kind": "task", "status": "pending",
         "estMin": 90, "context": [], "files": ["a.go"], "dependsOn": ["t-1"]},
    ],
}


class StubRunner:
    def __init__(self, tree_id="tree-stub01"):
        self.tree_id = tree_id
        self.submitted = []
        self.run_calls = []

    def submit_tree(self, tree_dict, context=None):
        self.submitted.append((tree_dict, context or {}))
        return self.tree_id

    def run(self, tree_id):
        self.run_calls.append(tree_id)
        return {"progress": {"tree_id": tree_id, "total": 3, "done": 0}}


@pytest.fixture
def temp_ctx(tmp_path, monkeypatch):
    # ctx._db 为进程级单例 → 重置以强制指向本测试的临时库
    monkeypatch.setattr(ctx, "_db", None, raising=False)
    monkeypatch.setattr(ctx, "_data_dir", None, raising=False)
    ctx.setup(str(tmp_path / "data"))
    stub = StubRunner()
    monkeypatch.setattr(runner_gateway, "get_runner", lambda: stub)
    yield stub


def _seed():
    now = _ts()
    store.RequirementsStore.create({
        "id": "req-1", "kind": "user-story", "tier": "analyzed", "location": "pool",
        "status": "planned", "title": "订单重构", "priority": "P1", "desc": "重构订单",
        "analysis": {"assessmentSummary": "可行"}, "updatedAt": now,
    })
    store.PlansStore.create({
        "id": "plan-1", "reqIds": ["req-1"], "title": "批次", "approach": "x",
        "changes": [], "impact": {"affected": [], "grade": "S"},
        "status": "confirmed", "taskPlanId": "tp-1", "baseCommit": "abc123",
        "updatedAt": now,
    })
    store.TaskTreesStore.upsert("tree-1", {
        "id": "tree-1", "planId": "plan-1", "root": FE_TREE,
        "revision": 1, "history": [], "updatedAt": now,
    })
    store.ExecutionTasksStore.create({
        "id": "ex-1", "planId": "plan-1", "adapter": "opencode", "model": "m",
        "reqIds": ["req-1"], "connectivity": "ok", "status": "created",
        "sessionIds": [], "baseCommit": "abc123", "runCount": 1, "treeRevision": 0,
        "testIds": [], "amendments": [],
        "stats": {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0},
        "instanceId": "", "taskBranch": "arch/ex-1", "branchMode": "auto",
        "createdAt": now, "updatedAt": now,
    })


def test_run_submits_tree_and_persists(temp_ctx):
    _seed()
    res = asyncio.run(execution.run_execution_task("ex-1"))
    assert res["code"] == 0, res
    assert res["data"]["treeId"] == "tree-stub01"
    # runner 收到树(roots 形状) + context
    tree_dict, context = temp_ctx.submitted[0]
    assert "roots" in tree_dict and tree_dict["roots"][0]["id"] == "tp-1"
    assert context["branch"] == "arch/ex-1"
    assert context["baseCommit"] == "abc123"
    assert "订单重构" in context["requirement"]
    # 触发 run
    assert temp_ctx.run_calls == ["tree-stub01"]
    # 落库
    task = store.ExecutionTasksStore.get("ex-1")
    assert task["runnerTreeId"] == "tree-stub01"
    assert task["status"] == "running"
    assert task["runCount"] == 2


def test_run_runner_unreachable_502(temp_ctx, monkeypatch):
    _seed()
    monkeypatch.setattr(runner_gateway, "get_runner", lambda: StubRunner(tree_id=None))
    res = asyncio.run(execution.run_execution_task("ex-1"))
    assert _err_code(res) == 502


def test_run_missing_task_404(temp_ctx):
    res = asyncio.run(execution.run_execution_task("nope"))
    assert _err_code(res) == 404
