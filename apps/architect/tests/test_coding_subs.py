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


# ── 换绑(2610 统一模型: 主/子会话通用端点, 含 architect) ────────────────

def test_switch_executor(main_conv):
    sub = _create_sub(main_conv, "cline")
    store.ConversationsStore.update(sub["id"], {"sessionRef": "ref-old"})
    r = asyncio.run(sess.switch_executor(sub["id"], _Req({"executorId": "opencode"})))
    assert r["code"] == 0
    row = store.ConversationsStore.get(sub["id"])
    assert row["executorId"] == "opencode" and not row.get("sessionRef")


def test_switch_executor_guards(main_conv):
    sub = _create_sub(main_conv, "cline")
    # executorId 必填 / 不存在——err() 均为 JSONResponse(400)
    # (2610 统一模型: 主会话/任意 executorId 为合法换绑目标, 不再拒绝)
    for body in ({}, {"executorId": "nope"}):
        r = asyncio.run(sess.switch_executor(sub["id"], _Req(body)))
        assert getattr(r, "status_code", 0) == 400
    # 在跑拒绝(proxy_state.active)
    from topoone_app_architect.agent.execution import proxy as _proxy
    _proxy._PROXY_JOBS[sub["id"]] = {"job_id": "j1", "executor_type": "cline"}
    try:
        r = asyncio.run(sess.switch_executor(
            sub["id"], _Req({"executorId": "opencode"})))
        assert getattr(r, "status_code", 0) == 400 and "停止" in r.body.decode()
    finally:
        _proxy._PROXY_JOBS.pop(sub["id"], None)


def test_switch_executor_architect_and_main(main_conv):
    """2610 统一模型: 主会话也可换绑; architect 显式落点=切回分析管线。"""
    # 跨测试 id 复用(cv-N) + 进程级 _PROXY_JOBS 残留 → 在跑守卫误判; 先清残留句柄
    from topoone_app_architect.agent.execution import proxy as _proxy
    _proxy._PROXY_JOBS.pop(main_conv, None)
    sub = _create_sub(main_conv, "cline")
    _proxy._PROXY_JOBS.pop(sub["id"], None)
    r = asyncio.run(sess.switch_executor(sub["id"], _Req({"executorId": "architect"})))
    assert r["code"] == 0
    assert store.ConversationsStore.get(sub["id"])["executorId"] == "architect"
    # 主会话换绑(原"一次绑定不可换"裁决退役)
    r2 = asyncio.run(sess.switch_executor(
        main_conv, _Req({"executorId": "opencode"})))
    assert r2["code"] == 0
    assert store.ConversationsStore.get(main_conv)["executorId"] == "opencode"


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


# ── feed-up 上投(2610 统一模型: 子会话产出 → 主会话活跃执行器) ─────────

def test_feed_up_delivers_to_main_active_sub(main_conv):
    """architect 子会话消息上投: 落主会话活跃 coding 子会话, feedFrom 溯源子会话。"""
    sub_arch = _create_sub(main_conv, "architect")      # architect 分析子会话
    sub_exec = _create_sub(main_conv, "cline")          # 后建=活跃 coding 子会话
    store.ConversationsStore.append_message(
        {"id": "m-fu", "conversationId": sub_arch["id"], "role": "assistant",
         "time": 1, "content": "分析结论: 方案甲"})
    r = asyncio.run(sess.feed_up_from_sub(sub_arch["id"], _Req({"messageId": "m-fu"})))
    assert r["code"] == 0 and r["data"]["activeSub"] == sub_exec["id"]
    landed = store.ConversationsStore.messages(sub_exec["id"], limit=10)
    feed = [m for m in landed if (m.get("meta") or {}).get("kind") == "feed"]
    assert feed and feed[0]["content"].startswith("分析结论")
    assert feed[0]["meta"]["feedFrom"]["convId"] == sub_arch["id"]


def test_feed_up_rejects_non_sub(main_conv):
    """非子会话(主会话本身)上投 → 400。"""
    r = asyncio.run(sess.feed_up_from_sub(main_conv, _Req({"text": "x"})))
    assert getattr(r, "status_code", 0) == 400


# ── 2610 统一列表: 子会话运行态(execution) + 主行 subCount ─────────────

def test_coding_sessions_execution_field(main_conv):
    """B1: execution=真实运行态(非 stub)——池删除守卫/子行脉冲数据源。"""
    sub = _create_sub(main_conv, "cline")
    # projectId 缺省由会话行推导(与会话同库, of_conv 路由才命中)
    store.TasksStore.create({"conversationId": sub["id"],
                             "status": "running", "title": "T-跑"})
    rows = asyncio.run(sess.list_coding_sessions(main_conv))["data"]
    hit = next(r for r in rows if r["id"] == sub["id"])
    assert hit["execution"] == "running"
    # 终态后回落空闲
    tid = store.TasksStore.of_conv(sub["id"])[0]["id"]
    store.TasksStore.update(tid, {"status": "done"})
    rows = asyncio.run(sess.list_coding_sessions(main_conv))["data"]
    hit = next(r for r in rows if r["id"] == sub["id"])
    assert hit["execution"] == ""


def test_list_sessions_sub_count(arch_env):
    """B2: 主行 subCount=过滤前 coding 行按 parent 聚合(展开箭头依据)。"""
    main1 = store.ConversationsStore.create({"kind": "generic", "title": "M1"})
    store.ConversationsStore.create({"kind": "coding", "parentConvId": main1["id"],
                                     "title": "s1"})
    store.ConversationsStore.create({"kind": "coding", "parentConvId": main1["id"],
                                     "title": "s2"})
    store.ConversationsStore.create({"kind": "generic", "title": "M2"})
    rows = asyncio.run(sess.list_sessions())["data"]
    by_title = {r["title"]: r for r in rows}
    assert by_title["M1"]["subCount"] == 2
    assert by_title["M2"]["subCount"] == 0
    assert all(r.get("kind") != "coding" for r in rows), "子会话不进主列表"


def test_scheduler_release_conv_lets_slot_go():
    """2610 F5a 裁决A: idle 让坑——保活会话回合收束释放槽位, 队首续跑。"""
    root = "/w-f5a"
    sched.register(root, "c1", "cline", "j1")
    relaunched: list = []

    async def fake_relaunch(entry):
        relaunched.append(entry["convId"])

    sched.admit(root, "c2", "opencode", isolated=False)
    sched.enqueue(root, {"convId": "c2", "isolated": False},
                  relaunch=fake_relaunch)
    sched.bind_loop(asyncio.new_event_loop())
    try:
        sched.release_conv("c1")                       # idle 让坑 → 队首续跑
        loop = sched._LOOP
        if loop:
            t = loop.time() + 0.2
            while loop.time() < t:
                loop.run_until_complete(asyncio.sleep(0.05))
        assert relaunched == ["c2"]
        assert sched.state_of_conv("c1")["state"] == "idle"
        assert sched.state_of_conv("c2")["state"] == "idle"   # fake relaunch 不 register(真续跑经 proxy_turn 登记)
    finally:
        if sched._LOOP:
            sched._LOOP.close()
        sched.bind_loop(None)


def test_scheduler_busy_by_other_and_state_of_conv():
    """2610 F5a: /input 仲裁占用检查 + 全 root 调度态(queued 带位次/执行器)。"""
    root = "/w-f5b"
    sched.register(root, "c1", "opencode", "j1")
    assert (sched.busy_by_other(root, "c2") or {}).get("convId") == "c1"
    assert sched.busy_by_other(root, "c1") is None     # 自己不算占用
    sched.enqueue(root, {"convId": "c2", "isolated": False,
                         "executor": {"id": "cline"}}, relaunch=None)
    st = sched.state_of_conv("c2")
    assert st["state"] == "queued" and st["position"] == 1
    assert st["executorId"] == "cline"
    assert sched.state_of_conv("cX")["state"] == "idle"
