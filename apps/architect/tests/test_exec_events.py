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


def test_sessions_rest_main_conv_enrich(arch_env):
    """主会话定位: coding 子会话沿 parent_conv_id 上溯一层; 无父回退自身。"""
    import asyncio
    from topoone_app_architect.arch_routes import exec_sessions as es
    store.ConversationsStore.create(
        {"id": "conv-main", "projectId": "p1", "title": "主线需求"})
    store.ConversationsStore.create(
        {"id": "conv-sub", "projectId": "p1", "title": "执行",
         "parentConvId": "conv-main"})
    # 无父会话(quick 直通, 会话行缺失 → 主会话回退空)
    store.TasksStore.create({
        "id": "task-sub", "conversationId": "conv-sub", "projectId": "p1",
        "title": "子会话作业", "executorType": "cline",
        "runnerJobId": "job-sub"})
    store.TasksStore.create({
        "id": "task-direct", "conversationId": "conv-main", "projectId": "p1",
        "title": "主会话直发", "executorType": "opencode",
        "runnerJobId": "job-direct"})
    store.TasksStore.create({
        "id": "task-orphan", "conversationId": "conv-gone", "projectId": "p1",
        "title": "会话已删", "executorType": "codex",
        "runnerJobId": "job-orphan"})
    for job in ("job-sub", "job-direct", "job-orphan"):
        exec_events.record_event(job, _ev(1, "session_ready"))
    # 关联会话标题/首条用户消息摘要(convTitle/convPreview)
    store.ConversationsStore.append_message({
        "id": store.next_id("m"), "conversationId": "conv-sub",
        "role": "user", "time": 1, "content": "帮我实现登录功能的改造"})
    rows = {r["jobId"]: r for r in asyncio.run(es.list_sessions(limit=10))["data"]}
    assert rows["job-sub"]["mainConvId"] == "conv-main"
    assert rows["job-sub"]["mainConvTitle"] == "主线需求"
    assert rows["job-sub"]["convTitle"] == "执行"
    assert rows["job-sub"]["convPreview"] == "帮我实现登录功能的改造"
    assert rows["job-direct"]["mainConvId"] == "conv-main"
    assert rows["job-direct"]["mainConvTitle"] == "主线需求"
    assert rows["job-direct"]["convTitle"] == "主线需求"
    assert rows["job-orphan"]["mainConvId"] == ""      # 会话不存在 → 空定位
    assert rows["job-orphan"]["mainConvTitle"] == ""
    assert rows["job-orphan"]["convTitle"] == ""
    assert rows["job-orphan"]["convPreview"] == ""


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


# ── 作业档案删除(2610 统一列表: 留痕 + 终态任务行, 活跃拒绝) ───────────

def test_delete_job_archive_terminal_and_active(arch_env):
    from topoone_app_architect.arch_routes import exec_sessions as ES
    # 终态作业: done 事件 + 终态任务行 → 档案+任务一并删
    exec_events.record_event("job-d1", _ev(1, "session_ready"))
    exec_events.record_event("job-d1", _ev(2, "done"))
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T",
                                            "projectId": "proj-arch"})
    _t = store.TasksStore.create({"conversationId": conv["id"], "projectId": "proj-arch",
                                  "status": "done", "title": "T-完", "runnerJobId": "job-d1"})
    r = asyncio.run(ES.delete_job_archive("job-d1"))
    assert r["code"] == 0 and r["data"]["eventsRemoved"] == 2 and r["data"]["tasksRemoved"] == 1
    assert exec_events.events_of("job-d1") == []
    assert not store.TasksStore.get(_t["id"]), "关联任务行应随档案删除"

    # 活跃作业(无终态事件) → 409 拒绝
    exec_events.record_event("job-d2", _ev(1, "session_ready"))
    r2 = asyncio.run(ES.delete_job_archive("job-d2"))
    assert getattr(r2, "status_code", 0) == 409
    assert exec_events.events_of("job-d2"), "拒绝时留痕不动"

    # 活跃任务(有终态事件但任务 running) → 409 拒绝
    exec_events.record_event("job-d3", _ev(1, "session_ready"))
    exec_events.record_event("job-d3", _ev(2, "done"))
    store.TasksStore.create({"conversationId": conv["id"], "projectId": "proj-arch",
                             "status": "running", "title": "T-跑", "runnerJobId": "job-d3"})
    r3 = asyncio.run(ES.delete_job_archive("job-d3"))
    assert getattr(r3, "status_code", 0) == 409

    # 不存在的作业 → 404
    r4 = asyncio.run(ES.delete_job_archive("job-ghost"))
    assert getattr(r4, "status_code", 0) == 404


def test_direct_job_enrich_via_session_ref(arch_env):
    """2610 F3: 直通作业(无任务行)经 session_ref=job_id 回退关联会话。"""
    from topoone_app_architect.arch_routes import exec_sessions as ES
    conv = store.ConversationsStore.create({"kind": "generic", "title": "直通主",
                                            "executorId": "cline-sdk",
                                            "projectId": "proj-arch"})
    store.ConversationsStore.update(conv["id"], {"sessionRef": "job-direct-1"})
    exec_events.record_event("job-direct-1", _ev(1, "session_ready"))
    exec_events.record_event("job-direct-1", _ev(2, "input_required"))
    rows = asyncio.run(ES.list_sessions(limit=50))
    row = next((r for r in (rows["data"] or []) if r["jobId"] == "job-direct-1"), None)
    assert row, "直通作业应出现在档案列表"
    assert row["conversationId"] == conv["id"], "session_ref 回退映射应命中会话"
    assert row["executorType"] == "cline-sdk", "executorType 回退会话行"
    assert row["lastStatus"] == "input_required", "保活状态应可见(非空态)"
    assert row["mainConvId"] == conv["id"]


def test_delete_guard_rejects_input_required(arch_env):
    """2610 F3: input_required=保活非终态——删除必须 409(与弹窗 isActive 同口径)。"""
    from topoone_app_architect.arch_routes import exec_sessions as ES
    exec_events.record_event("job-keep", _ev(1, "session_ready"))
    exec_events.record_event("job-keep", _ev(2, "input_required"))
    r = asyncio.run(ES.delete_job_archive("job-keep"))
    assert getattr(r, "status_code", 0) == 409
    assert exec_events.events_of("job-keep"), "拒绝时留痕不动"
    # stopped=用户中止(终态) → 可删
    exec_events.record_event("job-stop", _ev(1, "session_ready"))
    exec_events.record_event("job-stop", _ev(2, "stopped"))
    r2 = asyncio.run(ES.delete_job_archive("job-stop"))
    assert r2["code"] == 0 and r2["data"]["eventsRemoved"] == 2


def test_direct_job_enrich_via_start_card_meta(arch_env):
    """2610 P2: sessionRef 被原生会话 id 覆写后, 启动卡 meta.jobId 兜底映射。"""
    from topoone_app_architect.arch_routes import exec_sessions as ES
    conv = store.ConversationsStore.create({"kind": "generic", "title": "覆盖场景",
                                            "executorId": "opencode",
                                            "projectId": "proj-arch"})
    # 直通启动卡(proxy start 落 meta.jobId+jobCard) + sessionRef 已被覆写为原生 id
    from topoone_app_architect.agent.execution.exec_bridge import _append as _eb_append
    _eb_append(conv["id"], "assistant",
               "🔗 已直通执行器 `opencode`(job `job-ovw`，融合模式)",
               msg_meta={"kind": "proxy", "jobId": "job-ovw", "jobCard": 1,
                         "jobState": "idle", "fingerprint": "proxyjob:ovw"},
               project_id="proj-arch")
    store.ConversationsStore.update(conv["id"], {"sessionRef": "ses_native_1"})
    exec_events.record_event("job-ovw", _ev(1, "session_ready"))
    exec_events.record_event("job-ovw", _ev(2, "turn_done"))
    rows = asyncio.run(ES.list_sessions(limit=50))
    row = next((r for r in (rows["data"] or []) if r["jobId"] == "job-ovw"), None)
    assert row, "作业行应存在"
    assert row["conversationId"] == conv["id"], \
        "sessionRef 覆写后应经启动卡 meta 兜底映射"
    assert row["executorType"] == "opencode"


def test_pump_anchor_single_source_enrich(arch_env):
    """2610 B1: 泵留痕 conversationId=job↔conv 单源——历史三层回退仅存量兜底。"""
    from topoone_app_architect.arch_routes import exec_sessions as ES
    conv = store.ConversationsStore.create({"kind": "generic", "title": "锚点会话",
                                            "executorId": "opencode",
                                            "projectId": "proj-arch"})
    # 场景: 无任务行; sessionRef 被原生覆写(≠job_id); 无启动卡——仅事件锚点可依
    store.ConversationsStore.update(conv["id"], {"sessionRef": "ses_native_9"})
    exec_events.record_event("job-anchor", _ev(1, "session_ready",
                                               conversationId=conv["id"]))
    rows = asyncio.run(ES.list_sessions(limit=50))
    row = next((r for r in (rows["data"] or []) if r["jobId"] == "job-anchor"), None)
    assert row and row["conversationId"] == conv["id"], \
        "事件锚点应直达会话映射(不再依赖回退链)"
    assert row["executorType"] == "opencode"
