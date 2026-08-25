"""I3 测试：AgentTaskManager.enqueue_async（宿主薄接线队列入口）。

覆盖：终态判定（COMPLETED/PARTIAL/FAILED/CANCELLED）、进度上报、on_complete 回调、并发槽位。
"""

from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from topoone.agent.agent_workflow.agent_queue import (
    AgentTaskManager,
    TaskState,
)


def _result(success=True, done=4, total=4, error=""):
    return SimpleNamespace(
        success=success, steps_completed=done, steps_total=total,
        error=error, data={}, tool_calls=None,
    )


def _progress(weighted=100.0):
    return SimpleNamespace(
        steps=[], item_logs=[], step_current=4, step_total=4,
        file_current=2, file_total=2, tokens_used=100, elapsed_sec=1.0,
        message="done", weighted_progress=weighted, weighted_total=100,
        weighted_done=100, total_files=2, total_comps=1,
        done_files=2, done_comps=1, failed_count=0, retry_count=0,
    )


def _wait_state(mgr: AgentTaskManager, agent_id: str,
                terminal=True, timeout=10.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        d = mgr.get_progress(agent_id)
        assert d is not None
        if terminal and d["status"] in ("completed", "partial", "failed", "cancelled"):
            return d
        if not terminal and d["status"] == "running":
            return d
        time.sleep(0.05)
    raise AssertionError(f"timeout waiting for state: {mgr.get_progress(agent_id)}")


def test_enqueue_async_completed():
    mgr = AgentTaskManager(max_concurrency=2)
    complete_payload = {}

    def make_coro(on_progress):
        async def _run():
            on_progress(_progress())
            return _result(success=True)
        return _run()

    aid = mgr.enqueue_async("task-1", make_coro, threading.Event(),
                            on_complete=lambda d: complete_payload.update(d))
    d = _wait_state(mgr, aid)
    assert d["status"] == TaskState.COMPLETED.value
    assert d["weighted_progress"] == 100.0
    assert complete_payload["agent_id"] == aid
    assert complete_payload["status"] == "completed"


def test_enqueue_async_partial():
    mgr = AgentTaskManager(max_concurrency=2)

    def make_coro(on_progress):
        async def _run():
            on_progress(_progress(weighted=60.0))
            return _result(success=False, done=2, total=4, error="overview failed")
        return _run()

    aid = mgr.enqueue_async("task-2", make_coro, threading.Event())
    d = _wait_state(mgr, aid)
    assert d["status"] == TaskState.PARTIAL.value
    assert d["error"] == "overview failed"
    # stats 派生（前端"部分完成"展示）
    assert d["stats"]["total_steps"] == 4


def test_enqueue_async_failed():
    mgr = AgentTaskManager(max_concurrency=2)

    def make_coro(on_progress):
        async def _run():
            return _result(success=False, done=0, total=4, error="no llm")
        return _run()

    aid = mgr.enqueue_async("task-3", make_coro, threading.Event())
    d = _wait_state(mgr, aid)
    assert d["status"] == TaskState.FAILED.value
    assert d["error"] == "no llm"


def test_enqueue_async_cancelled():
    mgr = AgentTaskManager(max_concurrency=2)
    ev = threading.Event()

    def make_coro(on_progress):
        async def _run():
            # 模拟运行时轮询宿主取消事件
            while not ev.is_set():
                await asyncio.sleep(0.02)
            return _result(success=False, done=1, total=4)
        return _run()

    aid = mgr.enqueue_async("task-4", make_coro, ev)
    _wait_state(mgr, aid, terminal=False)
    assert mgr.cancel(aid) is True
    d = _wait_state(mgr, aid)
    assert d["status"] == TaskState.CANCELLED.value
    assert d["error"] == "cancelled"


def test_enqueue_async_slot_serialization():
    """max_concurrency=1：第二任务等第一任务释放槽位（入队调用方阻塞等槽，既有语义）。"""
    mgr = AgentTaskManager(max_concurrency=1)
    release = threading.Event()
    order = []
    b_result = {}

    def make_coro_a(on_progress):
        async def _run():
            order.append("a-start")
            while not release.is_set():
                await asyncio.sleep(0.02)
            order.append("a-end")
            return _result(success=True)
        return _run()

    def make_coro_b(on_progress):
        async def _run():
            order.append("b-start")
            return _result(success=True)
        return _run()

    def _enqueue_b():
        b_result["aid"] = mgr.enqueue_async("t-b", make_coro_b, threading.Event())

    aid_a = mgr.enqueue_async("t-a", make_coro_a, threading.Event())
    t = threading.Thread(target=_enqueue_b, daemon=True)
    t.start()

    _wait_state(mgr, aid_a, terminal=False)
    # b 入队阻塞在槽位（a 占槽中）
    time.sleep(0.2)
    assert not b_result
    release.set()
    t.join(timeout=10)
    _wait_state(mgr, aid_a)
    _wait_state(mgr, b_result["aid"])
    assert order == ["a-start", "a-end", "b-start"]


def test_enqueue_async_crash_marks_failed():
    mgr = AgentTaskManager(max_concurrency=2)

    def make_coro(on_progress):
        async def _run():
            raise RuntimeError("boom")
        return _run()

    aid = mgr.enqueue_async("task-5", make_coro, threading.Event())
    d = _wait_state(mgr, aid)
    assert d["status"] == TaskState.FAILED.value
    # 与旧 enqueue 路径一致：协程异常被捕获记录，状态置 FAILED（通用错误语）
    assert d["error"]
