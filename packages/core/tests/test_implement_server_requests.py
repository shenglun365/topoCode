"""A6.1 反向请求登记 + A6.3 TurnContext 快照回归。

Run: cd <repo> && python -m pytest packages/core/tests/test_implement_server_requests.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner.events import (  # noqa: E402
    SERVER_REQUEST_TYPES, is_server_request)
from topoone.plugins.runner.turn_adapter import TurnAdapter, TurnOutcome  # noqa: E402
from topoone.plugins.runner.implement import ImplementJob  # noqa: E402


class _FakeAdapter(TurnAdapter):
    executor_id = "fake"

    async def start_session(self, job) -> None:
        job.session_id = "s1"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        return TurnOutcome(output=text, changed_files=[])

    async def probe(self, job):
        raise NotImplementedError


def _job(**kw) -> ImplementJob:
    return ImplementJob("j-sr", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                        branch="exec/t", instruction="do",
                        adapter=_FakeAdapter(), **kw)


def test_server_request_contract_kinds():
    """A6.1 契约: 反向请求类型单源; done/failed 为终态通知非请求。"""
    assert SERVER_REQUEST_TYPES == ("approval_request", "input_required")
    assert is_server_request("approval_request") and is_server_request("input_required")
    assert not any(is_server_request(k) for k in ("done", "failed", "text", "progress"))


def test_pending_request_register_resolve():
    """登记 → snapshot 可见(dsh queued-minus-delivered 最小形态) → 应答销账。"""
    j = _job()
    j.register_pending_request("req-1", "editor", {"path": "a.py"})
    j.register_pending_request("req-2", "run_commands")
    pending = {row["requestId"] for row in j.snapshot()["pendingApprovals"]}
    assert pending == {"req-1", "req-2"}
    row = next(r for r in j.snapshot()["pendingApprovals"] if r["requestId"] == "req-1")
    assert row["toolName"] == "editor" and row["toolInput"] == {"path": "a.py"}
    assert j.resolve_pending_request("req-1")["toolName"] == "editor"
    assert {r["requestId"] for r in j.snapshot()["pendingApprovals"]} == {"req-2"}
    assert j.resolve_pending_request("nope") is None     # 幂等: 未知 id 不抛


def test_empty_request_id_ignored():
    j = _job()
    j.register_pending_request("", "editor")
    assert j.snapshot()["pendingApprovals"] == []


def test_turn_context_base_shape():
    """A6.3: 作业级上下文事实 + snapshot 暴露(turns 尾窗)。"""
    j = _job(model="m-1")
    tc = j.turn_context
    assert tc["branch"] == "exec/t" and tc["model"] == "m-1"
    assert tc["executorId"] == "fake" and tc["turns"] == []
    exposed = j.snapshot()["turnContext"]
    assert set(exposed.keys()) >= {"model", "base", "branch", "root",
                                   "executorId", "turns"}


def test_turn_context_records_per_turn():
    """每轮追加 {turn, startedAt, model}, snapshot 只暴露尾窗 5 条。"""
    j = _job(model="m-1")
    j.status = "running"
    asyncio.run(j._run_turn("第一轮 [[IMPLEMENT_DONE]]"))
    j.status = "running"
    asyncio.run(j._run_turn("第二轮 [[IMPLEMENT_DONE]]"))
    turns = j.turn_context["turns"]
    assert [t["turn"] for t in turns] == [1, 2]
    assert all(t["model"] == "m-1" and t["startedAt"] for t in turns)
    for i in range(3, 10):                               # 推到 9 轮, 验证尾窗 5
        j.status = "running"
        asyncio.run(j._run_turn(f"第{i}轮 [[IMPLEMENT_DONE]]"))
    exposed = j.snapshot()["turnContext"]["turns"]
    assert [t["turn"] for t in exposed] == [5, 6, 7, 8, 9]
