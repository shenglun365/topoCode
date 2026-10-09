"""执行器会话留痕+档案(2610 B1/B2)——泵双写/幂等/聚合/关联/增量。"""
from __future__ import annotations

import asyncio

from topoone_app_architect import store
from topoone_app_architect.store import exec_events


def _ev(seq, kind, text="", **extra):
    return {"seq": seq, "kind": kind, "text": text, "ts": 1_000 + seq, **extra}


def test_record_idempotent_and_truncate(arch_env):
    exec_events.record_event("job-1", _ev(1, "session_ready", "ok"))
    exec_events.record_event("job-1", _ev(1, "session_ready", "ok"))  # 重放幂等
    exec_events.record_event("job-1", _ev(2, "text", "长" * 5000))
    evs = exec_events.events_of("job-1")
    assert len(evs) == 2
    assert len(evs[1]["text"]) == 2000                     # 截断
    # extra 字段保留
    exec_events.record_event("job-1", _ev(3, "tool", "▶ bash",
                                          toolName="bash", toolInput={"cmd": "ls"}))
    evs = exec_events.events_of("job-1")
    assert evs[2]["toolName"] == "bash"
    # 增量
    assert [e["seq"] for e in exec_events.events_of("job-1", since_seq=2)] == [3]


def test_sessions_aggregate_and_last_status(arch_env):
    for s, k in [(1, "session_ready"), (2, "tool"), (3, "done")]:
        exec_events.record_event("job-a", _ev(s, k))
    exec_events.record_event("job-b", _ev(1, "session_ready"))
    rows = exec_events.sessions()
    by_job = {r["jobId"]: r for r in rows}
    assert by_job["job-a"]["eventCount"] == 3
    assert by_job["job-a"]["lastStatus"] == "done"
    assert by_job["job-b"]["lastStatus"] == ""


def test_pump_persists_events(arch_env, monkeypatch):
    """run_event_pump 双写: 订阅/校准两路事件都落库。"""
    from topoone_app_architect.agent.execution import pumps

    snap = {"ok": True, "status": "running",
            "events": [{"seq": 5, "kind": "tool", "text": "▶x",
                        "ts": 1}, {"seq": 6, "kind": "done", "ts": 2}]}

    async def fake_ws_connect(base, job_id, last_seq):
        return None                                       # 走校准路径

    monkeypatch.setattr(pumps, "ws_connect", fake_ws_connect)

    def fake_runner(path, payload, timeout):
        # 第二轮返回终态
        snap["status"] = "done"
        return dict(snap)

    seen = []

    async def run():
        await pumps.run_event_pump(
            base="http://x", job_id="job-p", runner=fake_runner,
            on_event=lambda ev: seen.append(ev.get("kind")),
            on_snapshot=lambda s: None,
            on_lost=lambda r: None)

    asyncio.run(run())
    assert seen == ["tool", "done"]
    evs = exec_events.events_of("job-p")                   # 留痕落库
    assert [e["seq"] for e in evs] == [5, 6]


def test_sessions_rest_enrich(arch_env):
    import asyncio
    from topoone_app_architect.arch_routes import exec_sessions as es
    exec_events.record_event("job-r", _ev(1, "session_ready"))
    store.ConversationsStore.create(
        {"id": "conv-r", "projectId": "p1", "title": "t"})
    store.TasksStore.create({
        "id": "task-r", "conversationId": "conv-r", "projectId": "p1",
        "title": "实现X", "executorType": "cline", "reqId": "rq-1",
        "runnerJobId": "job-r", "sessionRef": "sr-1"})
    rows = asyncio.run(es.list_sessions(limit=10))["data"]
    row = next(r for r in rows if r["jobId"] == "job-r")
    assert row["title"] == "实现X" and row["executorType"] == "cline"
    assert row["sessionRef"] == "sr-1" and row["taskId"] == "task-r"
    r2 = asyncio.run(es.list_events("job-r"))["data"]
    assert r2["events"][0]["kind"] == "session_ready" and not r2["empty"]
    r3 = asyncio.run(es.list_events("job-none"))["data"]
    assert r3["empty"] is True


class _Req:
    def __init__(self, body=None):
        self._b = body or {}

    async def json(self):
        return self._b


class _FakeClient:
    """runner 转发桩: input/abort 可编程应答。"""

    def __init__(self, input_result=None, abort_result=None):
        from dataclasses import dataclass
        self._in = input_result or {"ok": True, "queued": False,
                                    "delivery": "steered", "reason": ""}
        self._ab = abort_result or {"ok": True}

    def input(self, job_id, text, steer=False, timeout=15.0):
        return type("R", (), self._in)() if isinstance(self._in, dict) else self._in

    def abort(self, job_id, timeout=15.0):
        return self._ab


def test_serve_input_forward(arch_env, monkeypatch):
    """深链会话页输入转发: 空 text 400 / 成功透传 delivery / runner 失败 400。"""
    import asyncio
    from dataclasses import dataclass
    from topoone_app_architect.arch_routes import exec_sessions as es
    from topoone_app_architect.agent.execution import exec_bridge as eb

    @dataclass
    class _In:
        ok: bool = True
        queued: bool = False
        delivery: str = "steered"
        error: str = ""
        reason: str = ""

    calls = []

    class C:
        def input(self, job_id, text, steer=False, timeout=15.0):
            calls.append((job_id, text, steer))
            return _In()

        def abort(self, job_id, timeout=15.0):
            calls.append(("abort", job_id))
            return {"ok": True}

    monkeypatch.setattr(eb, "_client", lambda: C())

    # 空 text → 400
    r = asyncio.run(es.send_input("job-x", _Req({"text": "  "})))
    assert r.status_code == 400
    # 成功 → delivery 透传
    r = asyncio.run(es.send_input("job-x", _Req({"text": "继续", "steer": True})))
    assert r["data"]["delivery"] == "steered"
    assert calls == [("job-x", "继续", True)]
    # 停止转发
    r = asyncio.run(es.stop_job("job-x"))
    assert r["data"]["stopped"] is True


def test_serve_input_runner_down(arch_env, monkeypatch):
    """runner 不可达/作业结束 → 400(错误文案透出)。"""
    import asyncio
    from dataclasses import dataclass
    from topoone_app_architect.arch_routes import exec_sessions as es
    from topoone_app_architect.agent.execution import exec_bridge as eb

    @dataclass
    class _In:
        ok: bool = False
        queued: bool = False
        delivery: str = ""
        error: str = "作业不存在"
        reason: str = ""

    class C:
        def input(self, job_id, text, steer=False, timeout=15.0):
            return _In()

    monkeypatch.setattr(eb, "_client", lambda: C())
    r = asyncio.run(es.send_input("job-y", _Req({"text": "hi"})))
    assert r.status_code == 400 and "作业不存在" in r.body.decode()
