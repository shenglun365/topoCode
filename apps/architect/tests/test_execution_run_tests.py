"""P2-B B3 测试：POST /exec/{task_id}/run-tests — 闭环真实执行任务关联单测。

临时 DB + TestClient + 真实脚本，零真实 LLM。验证：
- 任务 testIds 关联的单测经真实 subprocess 执行，结果回写 lastResult/status
- 汇总 ran/passed/failed/allPassed 正确
- 无关联单测 → ran:0(明确，不伪造)
- 任务不存在 → 404
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from topoone_app_architect.arch_routes import ctx, store
from topoone_app_architect.arch_routes.common import _ts
from topoone_app_architect.server import build_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ctx, "_db", None, raising=False)
    monkeypatch.setattr(ctx, "_data_dir", None, raising=False)
    app = build_app(data_dir=str(tmp_path / "arch"))
    return TestClient(app), str(tmp_path)


def _mk_script(root: str, name: str, body: str):
    with open(os.path.join(root, name), "w") as f:
        f.write(body)


def _seed_task_with_tests(root: str, test_ids):
    now = _ts()
    store.RequirementsStore.create({
        "id": "req-1", "kind": "user-story", "tier": "analyzed", "location": "pool",
        "status": "planned", "title": "订单", "priority": "P1", "desc": "x",
        "analysis": {"assessmentSummary": "可行"}, "updatedAt": now,
    })
    store.PlansStore.create({
        "id": "plan-1", "reqIds": ["req-1"], "title": "批次", "approach": "x",
        "changes": [], "impact": {"affected": [], "grade": "S"},
        "status": "confirmed", "taskPlanId": "tp-1", "baseCommit": "abc", "updatedAt": now,
    })
    store.ExecutionTasksStore.create({
        "id": "ex-1", "planId": "plan-1", "adapter": "opencode", "model": "m",
        "reqIds": ["req-1"], "connectivity": "ok", "status": "running",
        "sessionIds": [], "baseCommit": "abc", "runCount": 1, "treeRevision": 0,
        "testIds": test_ids, "amendments": [],
        "stats": {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0},
        "instanceId": "", "taskBranch": "arch/ex-1", "branchMode": "auto",
        "createdAt": now, "updatedAt": now,
    })


def test_run_linked_tests_real(client):
    c, base = client
    root = os.path.join(base, "proj")
    os.makedirs(root)
    _mk_script(root, "pass.sh", "#!/bin/bash\necho 'ok'\nexit 0\n")
    _mk_script(root, "fail.sh", "#!/bin/bash\necho 'boom'\nexit 1\n")
    now = _ts()
    t1 = store.UnitTestsStore.create({"id": "ut-1", "name": "通过", "levels": ["L2"],
                                      "scriptPath": "pass.sh", "source": "manual",
                                      "status": "idle", "assetRefs": [], "createdAt": now, "updatedAt": now})
    t2 = store.UnitTestsStore.create({"id": "ut-2", "name": "失败", "levels": ["L2"],
                                      "scriptPath": "fail.sh", "source": "manual",
                                      "status": "idle", "assetRefs": [], "createdAt": now, "updatedAt": now})
    _seed_task_with_tests(root, ["ut-1", "ut-2"])

    res = c.post("/api/architect/exec/ex-1/run-tests", json={"root": root})
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    assert d["ran"] == 2 and d["passed"] == 1 and d["failed"] == 1, d
    assert d["allPassed"] is False, d
    by_id = {r["testId"]: r for r in d["results"]}
    assert by_id["ut-1"]["status"] == "passed" and "ok" in by_id["ut-1"]["lastResult"]["note"], d
    assert by_id["ut-2"]["status"] == "failed" and "boom" in by_id["ut-2"]["lastResult"]["error"], d
    # 结果回写单测
    assert store.UnitTestsStore.get("ut-1")["status"] == "passed"
    assert store.UnitTestsStore.get("ut-2")["status"] == "failed"


def test_run_no_linked_tests(client):
    c, base = client
    root = os.path.join(base, "proj")
    os.makedirs(root)
    _seed_task_with_tests(root, [])
    res = c.post("/api/architect/exec/ex-1/run-tests", json={"root": root})
    assert res.status_code == 200, res.text
    d = res.json()["data"]
    assert d["ran"] == 0 and d["allPassed"] is True, d
    assert "未关联" in d["note"], d


def test_run_missing_task_404(client):
    c, _ = client
    res = c.post("/api/architect/exec/nope/run-tests", json={})
    assert res.status_code == 400, res.text  # err() 恒 400，业务码在 body.code
    assert res.json()["code"] == 404
