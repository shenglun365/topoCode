"""TurnAdapter 适配层 + 回合看门狗单测(不经真实 coding agent)。

Run: cd <repo> && python -m pytest packages/core/tests/test_turn_adapter.py -q
"""
import asyncio
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner import turn_adapter as ta  # noqa: E402
from topoone.plugins.runner import implement as impl  # noqa: E402
from topoone.plugins.runner.turn_adapter import (  # noqa: E402
    TurnAdapter, TurnOutcome, TurnProbe, build_adapter)


# ── 工厂 ──

def test_build_adapter_defaults_to_opencode():
    a = build_adapter("", "", {})
    assert a.executor_type == "opencode"


def test_build_adapter_by_type():
    assert build_adapter("cline-sdk", "cline", {}).executor_type == "cline-sdk"
    assert build_adapter("codex-server", "codex",
                         {"codex_bin": "codex"}).executor_type == "codex-server"
    with pytest.raises(RuntimeError):
        build_adapter("remote-agent", "r", {})


# ── 看门狗(假 adapter 三态) ──

class _WatchFakeAdapter(TurnAdapter):
    """run_turn 挂起直至 job 终态——模拟执行器挂死; probe 返回预置快照。"""

    executor_id = "fake"

    def __init__(self, probe: TurnProbe):
        self._probe = probe
        self.abort_called = False

    async def start_session(self, job) -> None:
        job.session_id = "s1"
        job.serve_url = "fake://"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        for _ in range(400):
            await asyncio.sleep(0.05)
            if job.status in ("done", "failed", "stopped"):
                raise RuntimeError("回合已被中止")
        return TurnOutcome(output="[[IMPLEMENT_DONE]] ok")

    async def probe(self, job) -> TurnProbe:
        return self._probe

    async def abort(self, job) -> bool:
        self.abort_called = True
        return True


def _run_job_with_watch(adapter: TurnAdapter, stall_sec: float = 0.5) -> "impl.ImplementJob":
    async def _flow():
        j = impl.ImplementJob("jw", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                              branch="exec/t", instruction="do",
                              adapter=adapter, stall_sec=stall_sec)
        await j.start()          # start_session + 首轮(挂起) + 看门狗
        await asyncio.wait_for(j.turn_task, timeout=15)
        await asyncio.sleep(0.05)
        return j
    return asyncio.run(_flow())


def test_watchdog_kills_on_executor_error(monkeypatch):
    monkeypatch.setattr(impl, "_WATCH_INTERVAL", 0.1)
    a = _WatchFakeAdapter(TurnProbe("error", time.time(), "通道断流"))
    j = _run_job_with_watch(a)
    assert j.status == "failed"
    assert a.abort_called
    kinds = [e["kind"] for e in j.events]
    assert "failed" in kinds


def test_watchdog_kills_on_activity_stall(monkeypatch):
    monkeypatch.setattr(impl, "_WATCH_INTERVAL", 0.1)
    # 活动停在很久以前 + 非 busy → 停滞判定
    a = _WatchFakeAdapter(TurnProbe("idle", time.time() - 999, ""))
    j = _run_job_with_watch(a, stall_sec=0.5)
    assert j.status == "failed"
    assert a.abort_called


def test_watchdog_leaves_busy_alone(monkeypatch):
    monkeypatch.setattr(impl, "_WATCH_INTERVAL", 0.1)

    class _BusyDone(TurnAdapter):
        executor_id = "fake"

        async def start_session(self, job) -> None:
            job.session_id = "s1"
            job.serve_url = "fake://"

        async def run_turn(self, job, text: str) -> TurnOutcome:
            await asyncio.sleep(0.5)   # 正常回合(看门狗期间 busy)
            return TurnOutcome(output="完成 [[IMPLEMENT_DONE]]")

        async def probe(self, job) -> TurnProbe:
            return TurnProbe("busy", time.time())

        async def abort(self, job) -> bool:
            raise AssertionError("busy 状态不应被看门狗中止")

    async def _flow():
        j = impl.ImplementJob("jb", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                              branch="exec/t", instruction="do",
                              adapter=_BusyDone(), stall_sec=0.5)
        await j.start()
        await asyncio.wait_for(j.turn_task, timeout=10)
        await asyncio.sleep(0.05)
        return j
    j = asyncio.run(_flow())
    assert j.status == "done"
    assert not [e for e in j.events if e["kind"] == "failed"]


# ── OpenCodeTurnAdapter.probe(/session/status 解析) ──

def test_opencode_probe_parses_status(monkeypatch):
    a = ta.OpenCodeTurnAdapter(auto_start=False)

    class _Resp:
        def __init__(self, data, code=200):
            self._d, self._c = data, code
            self.status_code = code
        def json(self): return self._d

    class _AC:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, url): return _Resp({"s1": {"status": "error",
                                                       "message": "LLM quota exceeded"}})

    monkeypatch.setattr(ta.httpx, "AsyncClient", _AC)

    class _Job:
        id = "j1"; session_id = "s1"; serve_url = "http://x"
        last_activity_ts = 123.0; last_error = ""

    p = asyncio.run(a.probe(_Job()))
    assert p.status == "error"
    assert "quota" in p.last_error


# ── CodexTurnAdapter(notifications 聚合 + 活动时间戳) ──

class _FakeCodexProc:
    """假 app-server: call 记录方法; events 可编程注入。"""

    def __init__(self):
        self.events: list = []
        self.calls: list = []

    async def call(self, method, params=None, timeout=None):
        self.calls.append(method)
        if method == "thread/start":
            return {"thread": {"id": "th1"}}
        if method == "turn/start":
            # 模拟服务端 notifications: 过程事件 + 终态
            self.events.append({"method": "item/updated",
                                "params": {"item": {"type": "agentMessage",
                                                    "content": [{"text": "工作中"}]}}})
            self.events.append({"method": "turn/completed",
                                "params": {"turn": {"status": "completed"}}})
            return {"turn": {"id": "t1"}}
        if method == "turn/interrupt":
            return {}
        return {}

    def events_since(self, idx):
        return self.events[idx:]


def test_codex_run_turn_aggregates_and_touches_activity(monkeypatch):
    fake = _FakeCodexProc()
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _Job:
            id = "jc"; session_id = ""; serve_url = ""
            wt = "/tmp/x-wt"; model = ""; turn_timeout = 10.0
            last_activity_ts = 0.0; last_error = ""
        j = _Job()
        await a.start_session(j)
        assert j.session_id == "th1"
        t0 = j.last_activity_ts
        await asyncio.sleep(0.01)
        out = await a.run_turn(j, "做任务")
        return j, t0, out
    j, t0, out = asyncio.run(_flow())
    assert "工作中" in out.output
    assert j.last_activity_ts > t0          # notifications 刷新活动
    assert "turn/interrupt" not in fake.calls


def test_codex_run_turn_error_event_fails(monkeypatch):
    fake = _FakeCodexProc()

    async def _turn_start_error(method, params=None, timeout=None):
        fake.calls.append(method)
        if method == "thread/start":
            return {"thread": {"id": "th1"}}
        if method == "turn/start":
            fake.events.append({"method": "error",
                                "params": {"error": {"message": "unauthorized"},
                                            "willRetry": False}})
            return {"turn": {"id": "t1"}}
        return {}

    fake.call = _turn_start_error
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _Job:
            id = "jc2"; session_id = ""; serve_url = ""
            wt = "/tmp/x-wt"; model = ""; turn_timeout = 10.0
            last_activity_ts = 0.0; last_error = ""
        j = _Job()
        await a.start_session(j)
        await a.run_turn(j, "x")
    with pytest.raises(RuntimeError, match="unauthorized"):
        asyncio.run(_flow())


def test_codex_abort_sends_interrupt(monkeypatch):
    fake = _FakeCodexProc()
    proxy = type("P", (), {"proc": fake, "dead": False, "dead_reason": ""})()
    monkeypatch.setitem(ta._CODEX_SERVERS, "codex:", proxy)
    a = ta.CodexTurnAdapter({"codex_bin": "codex"})

    async def _flow():
        class _Job:
            id = "jc3"; session_id = ""; serve_url = ""
            wt = "/tmp/x-wt"; model = ""; turn_timeout = 10.0
            last_activity_ts = 0.0; last_error = ""
        j = _Job()
        await a.start_session(j)
        return await a.abort(j)
    assert asyncio.run(_flow()) is True
    assert "turn/interrupt" in fake.calls
