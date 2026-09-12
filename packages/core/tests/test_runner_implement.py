"""runner implement 作业宿主单测：注册/快照/输入缓冲/标记分类(假 TurnAdapter)。

Run: cd <repo> && python -m pytest packages/core/tests/test_runner_implement.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner.turn_adapter import TurnAdapter, TurnOutcome  # noqa: E402
from topoone.plugins.runner.implement import ImplementJob  # noqa: E402


class _FakeAdapter(TurnAdapter):
    """可编程假执行器: run_turn 返回预置输出。"""

    executor_id = "fake"

    def __init__(self, output: str = ""):
        self._output = output

    async def start_session(self, job) -> None:
        job.session_id = "s1"
        job.serve_url = "fake://adapter"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        return TurnOutcome(output=self._output or text, changed_files=[])

    async def probe(self, job) -> "object":
        raise NotImplementedError


def _job(**kw) -> ImplementJob:
    output = kw.pop("output", "")
    return ImplementJob("j1", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                        branch="exec/t", instruction="do",
                        adapter=_FakeAdapter(output=output), **kw)


def test_snapshot_and_events():
    j = _job()
    s1 = j.emit("session_ready", "ok")
    s2 = j.emit("input_required", "需要确认 A 还是 B?")
    snap = j.snapshot(since=s1)
    assert snap["status"] == "starting"
    assert [e["seq"] for e in snap["events"]] == [s2]
    assert "A 还是 B" in snap["events"][0]["text"]
    assert snap["executorId"] == "fake"


def test_user_input_queues_while_busy():
    j = _job()
    j._busy = True                      # 模拟回合进行中
    j.status = "running"
    r = asyncio.run(j.user_input("用方案 B"))
    assert r["ok"] and r["queued"] is True
    assert j.pending_inputs == ["用方案 B"]
    # 终态拒收
    j.status = "done"
    r2 = asyncio.run(j.user_input("再改改"))
    assert not r2["ok"]


def test_turn_marker_classification():
    """回合输出标记 → 状态分类(done/waiting_input/兜底)。"""

    async def _turn(j, text):
        await j._run_turn(text)

    # done 标记
    j1 = _job(output="完成 [[IMPLEMENT_DONE]] 摘要")
    j1.status = "running"
    asyncio.run(_turn(j1, "x"))
    assert j1.status == "done"
    assert j1.events[-1]["kind"] == "done"
    # need_input 标记
    j2 = _job(output="需要确认 [[NEED_INPUT]] 用哪个方案?")
    j2.status = "running"
    asyncio.run(_turn(j2, "x"))
    assert j2.status == "waiting_input"
    assert j2.events[-1]["kind"] == "input_required"
    # 无标记 → 兜底 waiting_input
    j3 = _job(output="我先做了些分析…")
    j3.status = "running"
    asyncio.run(_turn(j3, "x"))
    assert j3.status == "waiting_input"
