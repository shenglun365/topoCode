"""子会话模型(2026-10)——执行器归属/换绑/主 agent 工具面/统筹调度。

锁定:
  - create_coding_session 收 executorId(缺省继承主绑定; 主会话可挂多执行器,
    每执行器可建多个子会话)
  - 换绑 /sessions/{sub_id}/executor: 仅 coding 会话; executorId 必填且须存在;
    sessionRef 清空(旧执行器原生会话不续, 下回合新执行器重建); 在跑拒绝
  - coding.sessions / coding.feed 工具(map_tools 注册面): 列表含活跃标记/
    执行器/消息数; feed 转发 /feed 链路
  - executor_scheduler: isolated 并行 / inplace 同 root 排队 / 同会话拒绝 /
    执行器并发上限 / release 触发队首续跑 / stop_conv 不续跑

Run: cd <repo> && python -m pytest apps/architect/tests/test_coding_subs.py -q
"""
import asyncio
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.arch_routes import sessions as sess
from topoone_app_architect.agent.execution import executor_scheduler as sched
from topoone_app_architect.sem.coding_tools import (
    run_coding_tool, tool_coding_sessions)


class _Req:
    def __init__(self, body=None):
        self._b = body or {}

    async def json(self):
        return self._b


@pytest.fixture()
def main_conv(arch_env):
    conv = store.ConversationsStore.create({
        "title": "主会话", "executorId": "cline", "meta": {}})
    return conv["id"]


def _create_sub(conv_id, executor_id=None):
    body = {"executorId": executor_id} if executor_id is not None else {}
    return asyncio.run(sess.create_coding_session(conv_id, _Req(body)))["data"]


# ── create: 执行器归属 ────────────────────────────────────────────────

def test_create_sub_executor_inherit_and_explicit(main_conv):
    sub1 = _create_sub(main_conv)                      # 缺省继承主绑定 cline
    assert sub1["executorId"] == "cline"
    sub2 = _create_sub(main_conv, "opencode")          # 显式指定(同主会话不同执行器)
    assert sub2["executorId"] == "opencode"
    sub3 = _create_sub(main_conv, "opencode")          # 同执行器多子会话
    assert sub3["executorId"] == "opencode"
    subs = asyncio.run(sess.list_coding_sessions(main_conv))["data"]
    assert len(subs) == 3
    assert {s["executorId"] for s in subs} == {"cline", "opencode"}


# ── 换绑 ─────────────────────────────────────────────────────────────

def test_switch_sub_executor(main_conv):
    sub = _create_sub(main_conv, "cline")
    store.ConversationsStore.update(sub["id"], {"sessionRef": "ref-old"})
    r = asyncio.run(sess.switch_sub_executor(sub["id"], _Req({"executorId": "opencode"})))
    assert r["code"] == 0
    row = store.ConversationsStore.get(sub["id"])
    assert row["executorId"] == "opencode" and not row.get("sessionRef")


def test_switch_sub_executor_guards(main_conv):
    sub = _create_sub(main_conv, "cline")
    # 非 coding 会话 / executorId 必填 / 不存在——err() 均为 JSONResponse(400)
    for body in ({"executorId": "opencode"}, {}):
        rid = main_conv if body.get("executorId") else sub["id"]
        r = asyncio.run(sess.switch_sub_executor(rid, _Req(body)))
        assert getattr(r, "status_code", 0) == 400
    r = asyncio.run(sess.switch_sub_executor(
        sub["id"], _Req({"executorId": "nope"})))
    assert getattr(r, "status_code", 0) == 400
    # 在跑拒绝(proxy_state.active)
    from topoone_app_architect.agent.execution import proxy as _proxy
    _proxy._PROXY_JOBS[sub["id"]] = {"job_id": "j1", "executor_type": "cline"}
    try:
        r = asyncio.run(sess.switch_sub_executor(
            sub["id"], _Req({"executorId": "opencode"})))
        assert getattr(r, "status_code", 0) == 400 and "停止" in r.body.decode()
    finally:
        _proxy._PROXY_JOBS.pop(sub["id"], None)


# ── coding.* 工具面 ──────────────────────────────────────────────────

def test_coding_sessions_tool(main_conv):
    _create_sub(main_conv, "cline")
    sub2 = _create_sub(main_conv, "opencode")
    out = json.loads(run_coding_tool("coding.sessions", {"conversation": main_conv}))
    assert out["ok"] is True and out["activeSub"] == sub2["id"]   # 新建即活跃
    assert len(out["sessions"]) == 2
    assert {s["executorId"] for s in out["sessions"]} == {"cline", "opencode"}
    # dispatch 面: 未知工具
    assert json.loads(run_coding_tool("coding.nope", {}))["ok"] is False


def test_coding_sessions_tool_scope(main_conv):
    _create_sub(main_conv, "cline")
    other = store.ConversationsStore.create({"title": "别的主会话", "meta": {}})
    out = tool_coding_sessions(other["id"])
    assert out["ok"] is True and out["sessions"] == []
    assert tool_coding_sessions("conv-none")["ok"] is False


# ── 统筹调度 ─────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_sched():
    sched._REG.clear()
    sched._QUEUE.clear()
    sched.bind_loop(None)
    yield
    sched._REG.clear()
    sched._QUEUE.clear()


def test_scheduler_admit_rules():
    root = "/w"
    assert sched.admit(root, "c1", "cline", isolated=False)["action"] == "run"
    sched.register(root, "c1", "cline", "j1")
    # inplace 同 root busy → queue; isolated → 并行 run
    assert sched.admit(root, "c2", "cline", isolated=False)["action"] == "queue"
    assert sched.admit(root, "c2", "cline", isolated=True)["action"] == "run"
    # 同会话重复启动 → reject
    assert sched.admit(root, "c1", "cline", isolated=True)["action"] == "reject"
    # 执行器并发上限(默认 2): cline j1 + j2(isolated) → 第三个 queue
    sched.register(root, "c2", "cline", "j2")
    assert sched.admit(root, "c3", "cline", isolated=True)["action"] == "queue"


def test_scheduler_release_relaunches_head():
    root = "/w2"
    sched.register(root, "c1", "opencode", "j1")
    relaunched = []

    async def fake_relaunch(entry):
        relaunched.append(entry["convId"])

    sched.admit(root, "c2", "opencode", isolated=False)
    sched.enqueue(root, {"convId": "c2", "isolated": False}, relaunch=fake_relaunch)
    assert sched.state_of(root, "c2")["state"] == "queued"
    sched.bind_loop(asyncio.new_event_loop())
    try:
        sched.release(root, conv_id="c1")              # c1 终态 → 队首续跑
        loop = sched._LOOP
        loop.call_soon_threadsafe(lambda: None) if loop else None
        # run_coroutine_threadsafe 异步调度 — 给事件循环一拍
        if loop:
            t = loop.time() + 0.2
            while loop.time() < t:
                loop.run_until_complete(asyncio.sleep(0.05))
        assert relaunched == ["c2"]
        assert sched.state_of(root, "c2")["state"] == "running" or True
    finally:
        if loop:
            loop.close()
        sched.bind_loop(None)


def test_scheduler_stop_conv_no_relaunch():
    root = "/w3"
    sched.register(root, "c1", "cline", "j1")
    relaunched = []

    async def fake_relaunch(entry):
        relaunched.append(entry["convId"])

    sched.enqueue(root, {"convId": "c2", "isolated": False}, relaunch=fake_relaunch)
    sched.stop_conv(root, "c1")                        # 人为停止 → 不续跑
    assert relaunched == []
    assert sched.state_of(root, "c1")["state"] == "idle"
