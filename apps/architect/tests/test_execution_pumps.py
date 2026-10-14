"""执行层组件特征测试(P3): 单一事件泵 + 类型化 RunnerClient。

run_event_pump 三路径:
  ① 订阅降级 → snapshot 校准轮询(事件 seq 去重/终态退出)
  ② runner 连续不可达 → on_lost
  ③ runner 侧终态(done/failed/stopped) → on_finished

Run: cd <repo> && python -m pytest apps/architect/tests/test_execution_pumps.py -q
"""
import asyncio
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import pytest

from topoone_app_architect.agent.execution import pumps
from topoone_app_architect.agent.execution.runner_client import (
    RunnerClient,
    Snapshot,
    StartResult,
)


def _mk_events(start_seq=0):
    return [
        {"seq": start_seq + 1, "ts": 1, "kind": "progress", "toolCount": 3},
        {"seq": start_seq + 2, "ts": 2, "kind": "input_required", "text": "需要确认"},
    ]


async def _no_ws(*a, **k):
    """ws_connect 恒失败 → 泵走 snapshot 校准路径。"""
    return None


@pytest.mark.asyncio
async def test_pump_snapshot_calibration_path(monkeypatch):
    """WS 不可达(降级) → snapshot 轮询: 事件全量回调, 终态退出。"""
    calls = {"snap": 0}
    events = _mk_events()

    def fake_runner(path, payload=None, timeout=12.0):
        calls["snap"] += 1
        if calls["snap"] == 1:
            return {"ok": True, "status": "running", "sessionId": "s-1",
                    "events": events}
        return {"ok": True, "status": "done", "events": [
            {"seq": 3, "ts": 3, "kind": "done", "text": "完成", "changedFiles": ["a.py"]}]}
    monkeypatch.setattr(pumps, "ws_connect", _no_ws)

    got_events, snaps = [], []
    await pumps.run_event_pump(
        base="http://x", job_id="j1", runner=fake_runner,
        on_event=got_events.append, on_snapshot=snaps.append,
        on_lost=lambda r: pytest.fail("不应触发 lost"),
        poll_interval=0.01)
    assert [e["kind"] for e in got_events] == ["progress", "input_required", "done"]
    assert snaps and snaps[0]["sessionId"] == "s-1"


@pytest.mark.asyncio
async def test_pump_lost_after_consecutive_errors(monkeypatch):
    """runner 连续不可达 → on_lost 一次后退出。"""
    monkeypatch.setattr(pumps, "ws_connect", _no_ws)
    monkeypatch.setattr(pumps, "MAX_CONSECUTIVE_ERR", 3)
    lost = []
    calls = {"n": 0}

    def fake_runner(path, payload=None, timeout=12.0):
        calls["n"] += 1
        return None
    await pumps.run_event_pump(
        base="http://x", job_id="j1", runner=fake_runner,
        on_event=lambda ev: None, on_snapshot=lambda s: None,
        on_lost=lost.append, poll_interval=0.01)
    assert lost == ["runner 连续不可达"]


@pytest.mark.asyncio
async def test_pump_runner_side_terminal_calls_finished(monkeypatch):
    """runner snapshot 终态 stopped → on_finished("stopped")(stopped→cancelled 语义源)。"""
    monkeypatch.setattr(pumps, "ws_connect", _no_ws)
    finished, lost = [], []

    def fake_runner(path, payload=None, timeout=12.0):
        return {"ok": True, "status": "stopped", "events": []}
    await pumps.run_event_pump(
        base="http://x", job_id="j1", runner=fake_runner,
        on_event=lambda ev: None, on_snapshot=lambda s: None,
        on_lost=lost.append, on_finished=finished.append,
        poll_interval=0.01)
    assert finished == ["stopped"] and lost == []


@pytest.mark.asyncio
async def test_pump_ws_realtime_with_dedup(monkeypatch):
    """WS 断流 → snapshot 校准: 已消费 seq 不重放(去重), 未消费补漏。"""
    class _FakeWs:
        """推一条后断流(recv 抛错 → 泵降级校准)。"""
        def __init__(self, payloads):
            self._q = list(payloads)

        async def recv(self):
            if not self._q:
                raise ConnectionError("closed")
            import json
            return self._q.pop(0)

        async def close(self):
            pass

    async def fake_ws_connect(base, job_id, since, timeout=4.0):
        return _FakeWs(['{"seq": 1, "ts": 1, "kind": "progress", "toolCount": 1}'])
    monkeypatch.setattr(pumps, "ws_connect", fake_ws_connect)
    snaps = []
    calls = {"n": 0}

    def fake_runner(path, payload=None, timeout=12.0):
        calls["n"] += 1
        if calls["n"] == 1:
            # 校准: seq=1 已消费(去重跳过) + seq=3 未消费(补漏) + running 继续
            return {"ok": True, "status": "running", "events": [
                {"seq": 1, "ts": 1, "kind": "progress", "toolCount": 1},
                {"seq": 3, "ts": 3, "kind": "progress", "toolCount": 2}]}
        return {"ok": True, "status": "done", "events": []}

    got = []
    await pumps.run_event_pump(
        base="http://x", job_id="j1", runner=fake_runner,
        on_event=got.append, on_snapshot=snaps.append,
        on_lost=lambda r: pytest.fail("不应 lost"),
        poll_interval=0.01)
    kinds = [e["kind"] for e in got]
    assert kinds == ["progress", "progress"], f"seq 去重+补漏: {kinds}"
    counts = sorted(e["toolCount"] for e in got if e["kind"] == "progress")
    assert counts == [1, 2], f"seq=1 只处理一次, seq=3 补漏: {counts}"
