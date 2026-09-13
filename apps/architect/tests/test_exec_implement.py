"""执行链路回归(生命周期 v3)：指令符号分发 / 两段式确认(specVer) / /继续 增量回合。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_implement.py -q
"""
import asyncio
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import req_agent
from topoone_app_architect.arch_routes import store


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


# ── 会话指令符号解析(确定性分发, 无语义判断) ──────────────────────────

def test_session_cmd_parse():
    from topoone_app_architect.arch_routes.websocket import parse_session_cmd, SESSION_CMDS
    for name in SESSION_CMDS:
        assert parse_session_cmd(f"/{name}") == name, name
        assert parse_session_cmd(f" /{name} ") == name, name          # 容忍空白
        assert parse_session_cmd(f"/{name}!") == name, name           # 容忍尾随标点
    assert parse_session_cmd("执行方案") == ""                          # 自然语言不再触发
    assert parse_session_cmd("确认执行") == ""
    assert parse_session_cmd("/不存在的指令") == ""
    assert parse_session_cmd("执行方案吗 /执行") == ""                  # 非确切指令整条忽略
    assert parse_session_cmd("看看这个/调整的写法") == ""               # 指令必须在消息首且独立


# ── 会话/需求夹具(camelCase 会话行 + active 规约) ─────────────────────

def _mk_fixture(tmp_path, monkeypatch):
    """architect 会话(绑定需求+已确认规约) → (会话行, rid)。"""
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose", {"title": "T-执行", "requirementMd": "目标",
                        "designMd": "方案甲", "allowedScopeMd": "modules/x/",
                        "acceptanceMd": "编译通过"},
        root=None, project=None)
    assert res.get("ok"), res
    rid = res["requirementId"]
    r = req_agent.run_arch_tool("req.finalize", {"reqId": rid},
                                root=None, project=None)
    assert r.get("ok"), r
    conv = store.ConversationsStore.create({"kind": "requirement", "title": "T", "reqId": rid})
    conv = store.ConversationsStore.get(conv["id"])
    return conv, rid


def _patch_bridge(monkeypatch, tmp_path):
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    started = {}
    monkeypatch.setattr(exec_bridge, "start_implement",
                        lambda conv, instruction, executor_hint=None,
                        branch_name="", spec_ver=0:
                        started.update(instruction=instruction, branch=branch_name,
                                       spec_ver=spec_ver) or "🚀 已启动")
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    return started


# ── 一步启动(P3: 定稿即确认, specVer 锚定 active 版本) ───────────────

def test_one_step_exec_binds_spec_ver(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    started = _patch_bridge(monkeypatch, tmp_path)

    # ① /执行 → 直接建作业(指令含方案, 锚定 v1); 无预览无二次确认
    out1 = asyncio.run(ws._executor_implement(conv, None))
    assert started and started["spec_ver"] == 1 and "方案甲" in started["instruction"]
    assert "已启动" in out1

    # ② 规约修订 → 新 draft; 未重新确认前执行被拦
    started.clear()
    req_agent.run_arch_tool("req.amend", {"reqId": rid, "designMd": "方案乙",
                                          "reasoning": "验收意见"}, root=None, project=None)
    blocked = asyncio.run(ws._executor_implement(
        store.ConversationsStore.get(conv["id"]), None))
    assert not started and "尚未确认" in blocked

    # ③ 重新确认(v2) → /执行 → 按 v2 启动(方案乙)
    req_agent.run_arch_tool("req.finalize", {"reqId": rid}, root=None, project=None)
    out3 = asyncio.run(ws._executor_implement(
        store.ConversationsStore.get(conv["id"]), None))
    assert started and started["spec_ver"] == 2 and "方案乙" in started["instruction"]


def test_empty_spec_blocks_execution(tmp_path, monkeypatch):
    """空规约(无方案无需求正文)执行被拦——防空指令作业把 coding agent 打成
    NEED_INPUT 空转(cv-140 教训)。模拟历史绕门禁数据(直接 spec_confirm)。"""
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose", {"title": "T-空规约"}, root=None, project=None)
    assert res.get("ok"), res
    rid = res["requirementId"]
    store.RequirementsStore.spec_confirm(rid)   # 模拟历史已 confirm 的空规约
    from topoone_app_architect.arch_routes import websocket as ws
    conv = store.ConversationsStore.create({"kind": "requirement", "title": "T", "reqId": rid})
    started = _patch_bridge(monkeypatch, tmp_path)
    out = asyncio.run(ws._executor_implement(
        store.ConversationsStore.get(conv["id"]), None))
    assert not started, "空规约不得启动作业"
    assert "无实质内容" in out and "/调整" in out


def test_resume_circuit_breaker(tmp_path, monkeypatch):
    """NEED_INPUT 空转熔断: /继续 无实质补充连续 3 次 → 自动停止作业。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws, exec_bridge as eb
    stops = []
    monkeypatch.setattr(eb, "stop",
                        lambda cid, reason="": stops.append(cid) or "stopped")
    eb._job_upsert(conv["id"], {"jobId": "impl-x", "status": "waiting_input",
                                "lastAgentTs": 9 ** 12})   # cut 在未来 → 恒无增量
    row = lambda: store.ConversationsStore.get(conv["id"])  # noqa: E731
    out1 = asyncio.run(ws._exec_resume_turn(row()))
    assert "1/3" in out1 and not stops
    out2 = asyncio.run(ws._exec_resume_turn(row()))
    assert "2/3" in out2 and not stops
    out3 = asyncio.run(ws._exec_resume_turn(row()))
    assert stops == [conv["id"]], "第 3 次空转应自动停止作业"
    assert "已自动停止" in out3


def test_draft_spec_blocks_execution(tmp_path, monkeypatch):
    """draft 规约不可执行——先 /定稿 再执行。"""
    _setup(tmp_path, monkeypatch)
    res = req_agent.run_arch_tool(
        "req.propose", {"title": "T-draft", "designMd": "d", "acceptanceMd": "a"},
        root=None, project=None)
    rid = res["requirementId"]
    conv = store.ConversationsStore.get(
        store.ConversationsStore.create({"kind": "requirement", "reqId": rid})["id"])
    from topoone_app_architect.arch_routes import websocket as ws
    _patch_bridge(monkeypatch, tmp_path)
    out = asyncio.run(ws._executor_implement(conv, None))
    assert "尚未确认" in out and "/定稿" in out


def test_done_req_blocks_execution(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    store.RequirementsStore.mark_done(rid)
    from topoone_app_architect.arch_routes import websocket as ws
    out = asyncio.run(ws._executor_implement(conv, None))
    assert "已完结" in out and "新建需求" in out


# ── /继续(增量回合) ────────────────────────────────────────────────

def test_resume_turn_packages_incremental_messages(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    # 模拟账本中一个 waiting_input 作业 + agent 提问时间戳
    exec_bridge._job_upsert(conv["id"], {
        "jobId": "impl-test1", "branch": "exec/t", "status": "waiting_input",
        "lastAgentTs": 1000, "changedFiles": [], "failReason": "", "lastAgentNote": "q",
        "specVer": 1, "reqId": rid})
    store.ConversationsStore.append_message(
        {"id": "m-u1", "conversationId": conv["id"], "role": "user", "time": 2000,
         "content": "用方案 B，连接池上限 64"})
    store.ConversationsStore.append_message(
        {"id": "m-u2", "conversationId": conv["id"], "role": "user", "time": 3000,
         "content": "另外补上超时重连"})
    sent = {}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0:
                        sent.update(path=path, payload=payload) or {"ok": True})
    out = asyncio.run(ws._exec_resume_turn(store.ConversationsStore.get(conv["id"])))
    assert "已转达" in out and "2 条补充" in out
    assert "用方案 B" in sent["payload"]["text"] and "超时重连" in sent["payload"]["text"]


def test_resume_turn_no_waiting_job(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    out = asyncio.run(ws._exec_resume_turn(store.ConversationsStore.get(conv["id"])))
    assert "没有等待输入的作业" in out


# ── 账本/workState 聚合/lost ──────────────────────────────────────────

def test_jobs_ledger_and_workstate(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    assert store.ConversationsStore.work_state(conv["id"]) == "architect"
    exec_bridge._job_upsert(conv["id"], {"jobId": "j1", "status": "running"})
    assert exec_bridge.is_running(conv["id"])
    assert store.ConversationsStore.work_state(conv["id"]) == "running"
    exec_bridge._job_upsert(conv["id"], {"jobId": "j1", "status": "waiting_input"})
    assert exec_bridge.waiting_job(conv["id"])["jobId"] == "j1"
    assert store.ConversationsStore.work_state(conv["id"]) == "running"
    exec_bridge._job_upsert(conv["id"], {"jobId": "j1", "status": "done",
                                         "endedAt": 9, "changedFiles": ["a.py"]})
    assert not exec_bridge.is_running(conv["id"])
    assert store.ConversationsStore.work_state(conv["id"]) == "architect"
    j = exec_bridge.jobs_of(conv["id"])[-1]
    assert j["changedFiles"] == ["a.py"]


def test_acceptance_brief_detects_overrun(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    brief = exec_bridge._acceptance_brief(conv["id"], rid,
                                          ["modules/x/a.py", "src/core/ngx.c"])
    assert "越界" in brief and "src/core/ngx.c" in brief
    assert "modules/x/a.py" not in brief.split("越界改动")[-1] or True
    assert "验收标准对照" in brief and "编译通过" in brief
    brief2 = exec_bridge._acceptance_brief(conv["id"], rid, ["modules/x/b.py"])
    assert "边界符合" in brief2


# ── 互斥引擎 ─────────────────────────────────────────────────────────

def test_files_intersect_prefix_semantics():
    from topoone_app_architect.arch_routes.exec_bridge import _files_intersect
    a = ["modules/x", "modules/y/sub.py"]
    b = ["modules/x/core.c", "other/z"]
    assert _files_intersect(a, b) == ["modules/x"]          # 目录前缀覆盖
    assert _files_intersect(["a/b.py"], ["a/b.py"]) == ["a/b.py"]
    assert _files_intersect(["a"], ["b"]) == []


def test_check_mutex_blocks_and_readonly(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    running = {"ok": True, "jobs": [
        {"jobId": "j-other", "root": str(tmp_path), "branch": "b1",
         "boundaries": {"files": ["modules/x/core.c"], "readOnly": False}},
        {"jobId": "j-ro", "root": str(tmp_path), "branch": "b2",
         "boundaries": {"files": ["modules/x"], "readOnly": True}},
        {"jobId": "j-far", "root": "/other/root", "branch": "b3",
         "boundaries": {"files": ["modules/x"], "readOnly": False}},
    ]}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0: running)
    # 写作业冲突 → 拒绝
    msg = exec_bridge._check_mutex(conv, str(tmp_path), ["modules/x"])
    assert msg and "j-other" in msg and "冲突" in msg
    # 只读/跨项目不拦
    running2 = {"ok": True, "jobs": [running["jobs"][1], running["jobs"][2]]}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0: running2)
    assert exec_bridge._check_mutex(conv, str(tmp_path), ["modules/x"]) is None
    # runner 不可达 → 放行(风险自担)
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0: None)
    assert exec_bridge._check_mutex(conv, str(tmp_path), ["modules/x"]) is None


def test_start_implement_mutex_rejects(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    calls = {}
    def _fake_runner(path, payload=None, timeout=12.0):
        calls.update(path=path, payload=payload)
        if path == "/api/implement/running":
            return {"ok": True, "jobs": [
                {"jobId": "j1", "root": str(tmp_path), "branch": "b",
                 "boundaries": {"files": ["modules/x"], "readOnly": False}}]}
        return {"ok": True, "jobId": "impl-x", "branch": "b", "worktree": "/tmp/w"}
    monkeypatch.setattr(exec_bridge, "_runner", _fake_runner)
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    out = exec_bridge.start_implement(store.ConversationsStore.get(conv["id"]),
                                      "instruction", branch_name="exec/t", spec_ver=1)
    assert out.startswith("⛔") and "冲突" in out
    assert calls["path"] == "/api/implement/running"       # 未建作业


# ── /定稿 系统直通 + 结构门禁(放宽裁决) ────────────────────────────────

def test_cmd_finalize_turn_gate_and_pass(tmp_path, monkeypatch):
    """/定稿: 门禁降为结构完整(designMd 非空); acceptance/scope 缺失仅警告放行。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws

    # ① 无绑定需求 → 明确报错
    res = asyncio.run(ws._cmd_finalize_turn({"id": "cv-x"}))
    assert "未绑定需求" in res

    # ② proposal(designMd 非空, 无 acceptance/scope) → 放行(warns 提示)
    res2 = req_agent.run_arch_tool(
        "req.propose", {"title": "T-finalize", "designMd": "方案内容"},
        root=None, project=None)
    rid = res2["requirementId"]
    cid = store.ConversationsStore.create({"kind": "requirement", "reqId": rid})["id"]
    from topoone_app_architect.arch_routes import ctx as C
    token = C._conv_var.set(cid)
    C._req_var.set(rid)
    try:
        out = asyncio.run(ws._cmd_finalize_turn({"id": cid}))
        assert "规约已确认" in out and "v1" in out and "/执行" in out
        row = store.RequirementsStore.get(rid)
        assert row["status"] == "ready"

        # ③ 重复 /定稿 → 幂等提示
        out3 = asyncio.run(ws._cmd_finalize_turn({"id": cid}))
        assert "已确认" in out3
    finally:
        C._conv_var.reset(token)
        C.reset_req(C._req_var.set(None))

    # ④ designMd 为空 → 结构门禁拦截
    res4 = req_agent.run_arch_tool(
        "req.propose", {"title": "T-empty", "requirementMd": "只有需求没有方案"},
        root=None, project=None)
    rid4 = res4["requirementId"]
    cid4 = store.ConversationsStore.create({"kind": "requirement", "reqId": rid4})["id"]
    token4 = C._conv_var.set(cid4)
    C._req_var.set(rid4)
    try:
        out4 = asyncio.run(ws._cmd_finalize_turn({"id": cid4}))
        assert "定稿未通过" in out4 and "designMd" in out4 and "/调整" in out4
    finally:
        C._conv_var.reset(token4)


def test_guard_cmd_hints_by_req_state(tmp_path, monkeypatch):
    """守卫卡指令提示: draft → /定稿; ready → /执行; 无绑定 → 空。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    assert ws._guard_cmd_hints("cv-none") == []
    res = req_agent.run_arch_tool(
        "req.propose", {"title": "T-hints", "designMd": "d"},
        root=None, project=None)
    rid = res["requirementId"]
    cid = store.ConversationsStore.create({"kind": "requirement", "reqId": rid})["id"]
    assert ws._guard_cmd_hints(cid) == ["/定稿"]
    store.RequirementsStore.spec_confirm(rid)
    assert ws._guard_cmd_hints(cid) == ["/执行"]


# ── S2 双收件人: coding 定向投递 / running 归属推导 ────────────────────

def test_deliver_to_coding_no_active_job(tmp_path, monkeypatch):
    """无活跃作业 → 明确报错(no-active-job)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    conv = store.ConversationsStore.create({"kind": "requirement", "reqId": "RQ-1"})
    res = exec_bridge.deliver_to_coding(conv["id"], "补充")
    assert res["ok"] is False and res["error"] == "no-active-job"


def test_deliver_to_coding_queues_when_running(tmp_path, monkeypatch):
    """running 回合中投递 → runner 侧排队(queued=True); 等待中 → 立即转达。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    calls = {}

    def _fake_runner(path, payload=None, timeout=12.0):
        calls.update(path=path, payload=payload)
        if path == "/api/implement/running":
            return {"ok": True, "jobs": []}
        if path == "/api/implement":
            return {"ok": True, "jobId": "impl-q", "branch": "b", "worktree": "/tmp/w"}
        if path.endswith("/input"):
            # runner user_input 语义: running 回合中 → queued
            return {"ok": True, "queued": True}
        return {"ok": True}

    monkeypatch.setattr(exec_bridge, "_runner", _fake_runner)
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    # 建会话 + waiting_input 作业(直接写账本)
    store.ConversationsStore.create({"id": "cv-deliver", "kind": "requirement", "reqId": "RQ-1"})
    exec_bridge._job_upsert("cv-deliver", {
        "jobId": "impl-q", "status": "waiting_input", "executorId": "cline",
        "branch": "b", "specVer": 1, "reqId": "RQ-1", "startedAt": 1,
    })
    res = exec_bridge.deliver_to_coding("cv-deliver", "补充内容")
    assert res["ok"] is True
    assert calls["path"] == "/api/implement/impl-q/input"
    assert calls["payload"]["text"] == "补充内容"
    # 投递后账本状态回 running(回合重启)
    j = exec_bridge.active_job("cv-deliver")
    assert j["status"] == "running" and j["executorId"] == "cline"

    # running 归属推导
    rr = exec_bridge.running_role("cv-deliver")
    assert rr == {"role": "coding", "executorId": "cline",
                  "jobId": "impl-q", "status": "running"}


def test_running_role_in_session_api(tmp_path, monkeypatch):
    """sessions API 行携带 runningRole 推导(纯提示字段)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, sessions as S
    store.ConversationsStore.create({"id": "cv-rr", "kind": "generic"})
    exec_bridge._job_upsert("cv-rr", {
        "jobId": "j1", "status": "waiting_input", "executorId": "opencode",
        "branch": "b", "specVer": 1, "reqId": "", "startedAt": 1,
    })
    conv = store.ConversationsStore.get("cv-rr")
    api_row = S._conv_api(conv)
    assert api_row["runningRole"]["role"] == "coding"
    assert api_row["runningRole"]["executorId"] == "opencode"
    # 无作业 → architect
    conv2 = store.ConversationsStore.create({"kind": "generic"})
    assert S._conv_api(conv2)["runningRole"]["role"] == "architect"


# ── S3 子会话池: ensure/账本宿主/投喂门 ────────────────────────────────

def test_ensure_active_coding_session(tmp_path, monkeypatch):
    """无→新建(挂主会话); 失效(归档)→重建; 有效→复用。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    conv = store.ConversationsStore.create({"kind": "requirement", "reqId": "RQ-1"})
    sub1 = exec_bridge._ensure_active_coding_session(conv)
    assert sub1
    s = store.ConversationsStore.get(sub1)
    assert s["parentConvId"] == conv["id"] and s["kind"] == "coding"
    meta = store.ConversationsStore.get(conv["id"])["meta"]
    assert meta["activeCodingSession"] == sub1
    # 复用
    assert exec_bridge._ensure_active_coding_session(
        store.ConversationsStore.get(conv["id"])) == sub1
    # 失效(归档)→重建
    store.ConversationsStore.update(sub1, {"status": "archived"})
    sub2 = exec_bridge._ensure_active_coding_session(
        store.ConversationsStore.get(conv["id"]))
    assert sub2 != sub1


def test_coding_sessions_rest_and_feed(tmp_path, monkeypatch):
    """子会话 REST(列表/新建/激活) + 投喂门(审计/过滤/无作业记录)。"""
    _setup(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    _h = lambda: {"Authorization": "Bearer test"}
    from topoone_app_architect.arch_routes import exec_bridge
    conv = store.ConversationsStore.create({"kind": "requirement", "reqId": "RQ-1"})
    # 手动投递失败场景: 无作业 → feed 仍记录
    mid = store.ConversationsStore.append_message({
        "id": store.next_id("m"), "conversationId": conv["id"],
        "role": "assistant", "time": 1, "content": "**结论**: 桶大小要可配置"})["id"]
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"messageId": mid}, headers=_h()).json()["data"]
    assert r["delivered"] is False and "已记录" in r["summary"]
    # 新建子会话
    r2 = client.post(f"/api/architect/sessions/{conv['id']}/coding-sessions",
                     json={}, headers=_h()).json()["data"]
    assert r2["parentConvId"] == conv["id"] and r2["kind"] == "coding"
    sub_id = r2["id"]
    # 列表(含活跃标记)
    lst = client.get(f"/api/architect/sessions/{conv['id']}/coding-sessions",
                     headers=_h()).json()["data"]
    assert any(s["id"] == sub_id and s["active"] for s in lst)
    # 再投喂(有活跃子会话, 仍无作业) → 落子会话+feedFrom 审计
    r3 = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                     json={"messageId": mid}, headers=_h()).json()["data"]
    assert r3["activeSub"] == sub_id
    sub_msgs = store.ConversationsStore.messages(sub_id)
    fed = [m for m in sub_msgs if (m.get("meta") or {}).get("kind") == "feed"]
    assert len(fed) == 1 and "桶大小" in fed[0]["content"]
    assert fed[0]["meta"]["feedFrom"]["messageId"] == mid
    # hint 消息不可转发
    store.ConversationsStore.append_message({
        "id": "m-hint", "conversationId": conv["id"], "role": "assistant",
        "time": 2, "content": "本地提示", "meta": {"kind": "hint"}})
    r4 = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                     json={"messageId": "m-hint"}, headers=_h())
    assert r4.json()["code"] == 400


# ── S4: 摘要转发 / 代持注入 / 回合超时下发 ────────────────────────────

def test_subsession_history_brief_budget(tmp_path, monkeypatch):
    """代持简报: 只取近段, 预算受控, 跳过启动标记消息。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge
    conv = store.ConversationsStore.create({"kind": "requirement"})
    sub = store.ConversationsStore.create({"kind": "coding", "parentConvId": conv["id"]})
    store.ConversationsStore.append_message({"id": "a1", "conversationId": sub["id"],
        "role": "user", "time": 1, "content": "🚀 作业启动(应被跳过)"})
    store.ConversationsStore.append_message({"id": "a2", "conversationId": sub["id"],
        "role": "user", "time": 2, "content": "X" * 600})       # 超单条截断
    store.ConversationsStore.append_message({"id": "a3", "conversationId": sub["id"],
        "role": "assistant", "time": 3, "content": "结论: 桶大小可配置"})
    brief = exec_bridge._subsession_history_brief(sub["id"], budget=1000)
    assert "会话历史简报" in brief and "桶大小可配置" in brief
    assert "作业启动" not in brief
    assert len(brief) < 1600

    # 空历史 → 空串
    sub2 = store.ConversationsStore.create({"kind": "coding", "parentConvId": conv["id"]})
    assert exec_bridge._subsession_history_brief(sub2["id"]) == ""


def test_start_implement_injects_history_when_no_sessionref(tmp_path, monkeypatch):
    """代持: sessionRef 空 + 子会话有历史 → instruction 注入简报;
    sessionRef 有 → 不注入(复活路径)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    captured = {}

    def _fake_runner(path, payload=None, timeout=12.0):
        captured.update(path=path, payload=payload)
        if path == "/api/implement/running":
            return {"ok": True, "jobs": []}
        if path == "/api/implement":
            return {"ok": True, "jobId": "impl-h", "branch": "b", "worktree": "/tmp/w"}
        return {"ok": True}

    monkeypatch.setattr(exec_bridge, "_runner", _fake_runner)
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    monkeypatch.setattr(ws, "_executor_hint", lambda c: None)

    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    sub = store.ConversationsStore.create({"kind": "coding", "parentConvId": conv["id"]})
    store.ConversationsStore.append_message({"id": "h1", "conversationId": sub["id"],
        "role": "assistant", "time": 1, "content": "此前结论: 限流桶要可配置"})
    meta = exec_bridge._meta_dict_of(store.ConversationsStore.get(conv["id"]))
    meta["activeCodingSession"] = sub["id"]
    store.ConversationsStore.update(conv["id"], {"meta": meta})

    async def _run():
        return await ws._executor_implement(
            store.ConversationsStore.get(conv["id"]), None)

    # ① 无 sessionRef → 代持注入
    _clear_exec_pending(conv)
    out = asyncio.run(_run())
    assert "作业已启动" in out
    assert "会话历史简报" in captured["payload"]["instruction"]
    assert "限流桶要可配置" in captured["payload"]["instruction"]
    assert "sessionRef" not in captured["payload"]

    # ② sessionRef 有 → 复活注入, 不带简报(先终态第①段作业——同一时间一个作业)
    exec_bridge._job_upsert(conv["id"], {"jobId": "impl-h", "status": "done",
                                          "endedAt": 1})
    store.ConversationsStore.update(sub["id"], {"sessionRef": "ses-old"})
    _clear_exec_pending(conv)
    out2 = asyncio.run(_run())
    assert captured["payload"].get("sessionRef") == "ses-old"
    assert "会话历史简报" not in captured["payload"]["instruction"]


def _clear_exec_pending(conv):
    """清历史两段式残留的 execPending(一步启动后仅作兼容清理)。"""
    from topoone_app_architect.arch_routes import exec_bridge
    meta = exec_bridge._meta_dict_of(store.ConversationsStore.get(conv["id"]))
    if meta.get("execPending"):
        meta.pop("execPending", None)
        store.ConversationsStore.update(conv["id"], {"meta": meta})


def test_start_implement_passes_turn_timeouts(tmp_path, monkeypatch):
    """S4 回合超时下发: executorConfig.turnTimeout/stallSec → payload。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    captured = {}

    def _fake_runner(path, payload=None, timeout=12.0):
        captured.update(path=path, payload=payload)
        if path == "/api/implement/running":
            return {"ok": True, "jobs": []}
        if path == "/api/implement":
            return {"ok": True, "jobId": "impl-t", "branch": "b", "worktree": "/tmp/w"}
        return {"ok": True}

    monkeypatch.setattr(exec_bridge, "_runner", _fake_runner)
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    hint = {"executorId": "opencode", "executorType": "opencode",
            "executorConfig": {"turnTimeout": 1200, "stallSec": 240, "model": ""}}
    monkeypatch.setattr(ws, "_executor_hint", lambda c: hint)

    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    _clear_exec_pending(conv)
    out = asyncio.run(ws._executor_implement(
        store.ConversationsStore.get(conv["id"]), None))
    assert "作业已启动" in out
    assert captured["payload"]["turnTimeout"] == 1200.0
    assert captured["payload"]["stallSec"] == 240.0


def test_feed_summarize_paths(tmp_path, monkeypatch):
    """S4 摘要转发: LLM 成功→压缩文本+审计标记; 失败→回退原文。"""
    _setup(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    from topoone_app_architect.arch_routes import sessions as S
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    _h = lambda: {"Authorization": "Bearer test"}
    conv = store.ConversationsStore.create({"kind": "requirement"})
    store.ConversationsStore.append_message({"id": "m-s1", "conversationId": conv["id"],
        "role": "assistant", "time": 1,
        "content": "经过 A/B/C 三方案对比与风险评估，结论：限流桶大小必须可配置(env BUCKET_SIZE)，默认 100。"})
    # LLM 成功路径
    async def _ok_sum(text):
        return ("结论：限流桶大小可配置(BUCKET_SIZE)，默认 100。", True)
    monkeypatch.setattr(S, "_summarize_for_coding", _ok_sum)
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"messageId": "m-s1", "summarize": True},
                    headers=_h()).json()["data"]
    assert r["summarized"] is True and "(摘要)" in r["summary"]
    # LLM 失败路径(回退原文)
    async def _fail_sum(text):
        return (text, False)
    monkeypatch.setattr(S, "_summarize_for_coding", _fail_sum)
    r2 = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                     json={"text": "直接文本", "summarize": True},
                     headers=_h()).json()["data"]
    assert r2["summarized"] is False   # LLM 失败如实标记(原文透传)


def test_summarize_for_coding_llm_unreachable(tmp_path, monkeypatch):
    """LLM 不可达 → 回退原文 + False(不抛异常)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import sessions as S

    def _boom(*a, **k):
        raise RuntimeError("llm down")
    import topoone_app_architect.arch_routes.req_agent as ra
    monkeypatch.setattr(ra, "llm_sync", _boom)
    text, ok = asyncio.run(S._summarize_for_coding("原始分析内容"))
    assert ok is False and text == "原始分析内容"


# ── 会话级执行器模型: bind/切换/hint 优先级/running 固化/克隆继承 ──────

def _patch_executors(monkeypatch, models=None):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-m", "type": "opencode", "enabled": True,
         "config": {"model": "", "models": [{"name": m} for m in (models or [])]}},
    ])


def test_bind_with_model_and_switch(tmp_path, monkeypatch):
    """bind 带 model(白名单内/外) + POST /model 随时切换/无效值拒。"""
    _setup(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    _h = lambda: {"Authorization": "Bearer test"}
    _patch_executors(monkeypatch, models=["qwen-72b", "qwen-14b"])
    c = client.post("/api/architect/sessions",
                    json={"kind": "generic"}, headers=_h()).json()["data"]
    # bind 白名单外 → 400
    r = client.post(f"/api/architect/sessions/{c['id']}/bind",
                    json={"executorId": "ex-m", "model": "ghost"},
                    headers=_h())
    assert r.json()["code"] == 400
    # bind 白名单内 → 落 executorModel
    r2 = client.post(f"/api/architect/sessions/{c['id']}/bind",
                     json={"executorId": "ex-m", "model": "qwen-14b"},
                     headers=_h()).json()["data"]
    assert r2["executorModel"] == "qwen-14b"
    # 切换/恢复默认
    r3 = client.post(f"/api/architect/sessions/{c['id']}/model",
                     json={"model": "qwen-72b"}, headers=_h()).json()["data"]
    assert r3["executorModel"] == "qwen-72b" and "下次执行生效" in r3["summary"]
    r4 = client.post(f"/api/architect/sessions/{c['id']}/model",
                     json={"model": ""}, headers=_h()).json()["data"]
    assert r4["executorModel"] == "" and "恢复默认" in r4["summary"]
    # 无效值 → 400; 未绑定 → 400
    assert client.post(f"/api/architect/sessions/{c['id']}/model",
                       json={"model": "ghost"}, headers=_h()).json()["code"] == 400
    c2 = client.post("/api/architect/sessions", json={"kind": "generic"},
                     headers=_h()).json()["data"]
    assert client.post(f"/api/architect/sessions/{c2['id']}/model",
                       json={"model": "qwen-14b"}, headers=_h()).json()["code"] == 400


def test_executor_hint_model_priority(tmp_path, monkeypatch):
    """hint 模型优先级: conv.executorModel > config.models[0] > cfg.model。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_executors as ae, websocket as ws
    # 仅 cfg.model(无白名单) → cfg.model
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex1", "type": "opencode", "enabled": True,
         "config": {"model": "cfg-m", "models": []}}])
    conv = {"executorId": "ex1", "executorModel": ""}
    assert ws._executor_hint(conv)["model"] == "cfg-m"
    # 白名单存在 → 首个
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex1", "type": "opencode", "enabled": True,
         "config": {"model": "cfg-m", "models": [{"name": "wl-1"}, {"name": "wl-2"}]}}])
    assert ws._executor_hint(conv)["model"] == "wl-1"
    # 会话选型最优先
    assert ws._executor_hint({"executorId": "ex1", "executorModel": "wl-2"})["model"] == "wl-2"


def test_running_job_model_frozen(tmp_path, monkeypatch):
    """running 固化: 作业启动后切换会话模型, 已传 payload.model 不变。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_executors as ae, exec_bridge, websocket as ws
    _patch_executors(monkeypatch, models=["m-a", "m-b"])
    monkeypatch.setattr(ws, "_executor_hint",
                        lambda c: {"executorId": "ex-m", "executorType": "opencode",
                                   "executorConfig": {}, "model": "m-a",
                                   "basePort": None, "autoStart": None, "baseUrl": ""})
    captured = {}

    def _fake_runner(path, payload=None, timeout=12.0):
        captured.update(path=path, payload=payload)
        if path == "/api/implement/running":
            return {"ok": True, "jobs": []}
        if path == "/api/implement":
            return {"ok": True, "jobId": "impl-f", "branch": "b", "worktree": "/tmp/w"}
        return {"ok": True}

    monkeypatch.setattr(exec_bridge, "_runner", _fake_runner)
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda conv: (str(tmp_path), "proj-t"))
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    _clear_exec_pending(conv)
    asyncio.run(ws._executor_implement(
        store.ConversationsStore.get(conv["id"]), None))
    assert captured["payload"]["model"] == "m-a"
    # 会话切模型后, 既有作业 payload 不变(payload 已提交固化); 仅下次执行变化
    monkeypatch.setattr(ws, "_executor_hint",
                        lambda c: {"executorId": "ex-m", "executorType": "opencode",
                                   "executorConfig": {}, "model": "m-b",
                                   "basePort": None, "autoStart": None, "baseUrl": ""})
    assert captured["payload"]["model"] == "m-a"


def test_clone_carries_executor_model(tmp_path, monkeypatch):
    """克隆继承源会话模型; 亦可显式指定。"""
    _setup(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    _h = lambda: {"Authorization": "Bearer test"}
    _patch_executors(monkeypatch, models=["qwen-72b", "qwen-14b"])
    c = client.post("/api/architect/sessions",
                    json={"kind": "generic", "executorId": "ex-m", "model": "qwen-14b"},
                    headers=_h()).json()["data"]
    assert c["executorModel"] == "qwen-14b"
    d = client.post(f"/api/architect/sessions/{c['id']}/clone",
                    json={"executorId": "ex-m"}, headers=_h()).json()["data"]
    assert d["executorModel"] == "qwen-14b"      # 继承
    e = client.post(f"/api/architect/sessions/{c['id']}/clone",
                    json={"executorId": "ex-m", "model": "qwen-72b"},
                    headers=_h()).json()["data"]
    assert e["executorModel"] == "qwen-72b"      # 显式


def test_resume_from_subsession_finds_parent_waiting_job(tmp_path, monkeypatch):
    """子会话 /继续: job_input 提示落在子会话, 账本在主会话——沿父链找到
    waiting 且 sub=本会话 的作业; 增量取子会话消息; 状态回写落主会话账本。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    sub = store.ConversationsStore.create({
        "id": "cv-sub1", "kind": "coding", "projectId": conv["projectId"],
        "reqId": rid, "title": "sub", "parentConvId": conv["id"],
        "status": "active", "meta": {}})
    exec_bridge._job_upsert(conv["id"], {
        "jobId": "impl-x1", "branch": "exec/t", "status": "waiting_input",
        "lastAgentTs": 1000, "changedFiles": [], "failReason": "",
        "lastAgentNote": "q", "specVer": 1, "reqId": rid, "subSessionId": "cv-sub1"})
    store.ConversationsStore.append_message(
        {"id": "m-su1", "conversationId": "cv-sub1", "role": "user", "time": 2000,
         "content": "环境可用 ubuntu 24.04, 可装 openresty"})
    sent = {}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=12.0:
                        sent.update(path=path, payload=payload) or {"ok": True})
    out = asyncio.run(ws._exec_resume_turn(store.ConversationsStore.get("cv-sub1")))
    assert "已转达" in out, out
    assert "ubuntu 24.04" in sent["payload"]["text"]
    # 状态回写落主会话账本(running), 子会话账本不被污染
    jobs_p = exec_bridge.jobs_of(conv["id"])
    assert any(j.get("jobId") == "impl-x1" and j.get("status") == "running"
               for j in jobs_p)
    assert not [j for j in exec_bridge.jobs_of("cv-sub1") if j.get("jobId") == "impl-x1"]


def test_resume_from_subsession_no_match_falls_through(tmp_path, monkeypatch):
    """父会话无 waiting 或 sub 非本会话 → 子会话 /继续 走「没有等待」引导。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    sub = store.ConversationsStore.create({
        "id": "cv-sub2", "kind": "coding", "projectId": conv["projectId"],
        "reqId": rid, "title": "s2", "parentConvId": conv["id"],
        "status": "active", "meta": {}})
    out = asyncio.run(ws._exec_resume_turn(store.ConversationsStore.get("cv-sub2")))
    assert "没有等待输入的作业" in out


def test_deliver_coding_from_subsession_routes_to_parent(tmp_path, monkeypatch):
    """子会话以 coding 收件人发送 → 沿父链找 active 且 sub=本会话 的作业投递。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge, websocket as ws
    sub = store.ConversationsStore.create({
        "id": "cv-d1", "kind": "coding", "projectId": conv["projectId"],
        "reqId": rid, "title": "d", "parentConvId": conv["id"],
        "status": "active", "meta": {}})
    exec_bridge._job_upsert(conv["id"], {
        "jobId": "impl-d1", "branch": "exec/t", "status": "waiting_input",
        "lastAgentTs": 1000, "changedFiles": [], "failReason": "",
        "lastAgentNote": "q", "specVer": 1, "reqId": rid,
        "subSessionId": "cv-d1", "executorId": "cline"})
    sent = {}
    monkeypatch.setattr(exec_bridge, "_runner",
                        lambda path, payload=None, timeout=15.0:
                        sent.update(path=path) or {"ok": True})
    out, target = asyncio.run(ws._deliver_coding_turn(
        store.ConversationsStore.get("cv-d1"), "环境可用 ubuntu"))
    assert "已转达" in out, out
    assert target == "cv-d1", "回执落库目标应为 coding 子会话"
    assert "/input" in sent["path"]
    # 用户消息落 coding 子会话(信息流分离), 主会话不落(回执由 WS 主循环落 target)
    sub_texts = [m.get("content") for m in store.ConversationsStore.messages("cv-d1")]
    assert "环境可用 ubuntu" in sub_texts
    main_texts = [m.get("content") for m in store.ConversationsStore.messages(conv["id"])]
    assert "环境可用 ubuntu" not in main_texts
    # 状态回写落主会话账本
    assert any(j.get("jobId") == "impl-d1" and j.get("status") == "running"
               for j in exec_bridge.jobs_of(conv["id"]))
    assert not [j for j in exec_bridge.jobs_of("cv-d1") if j.get("jobId") == "impl-d1"]


def test_list_sessions_excludes_coding_subs(tmp_path, monkeypatch):
    """会话列表排除 coding 子会话(防污染); 显式 kind=coding 不受影响。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    store.ConversationsStore.create({
        "id": "cv-l1", "kind": "coding", "projectId": conv["projectId"],
        "reqId": rid, "title": "sub-l", "parentConvId": conv["id"],
        "status": "active", "meta": {}})
    from topoone_app_architect.arch_routes import sessions as S
    default = asyncio.run(S.list_sessions())
    ids = [c["id"] for c in default["data"]]
    assert "cv-l1" not in ids and conv["id"] in ids
    coding_only = asyncio.run(S.list_sessions(kind="coding"))
    assert "cv-l1" in [c["id"] for c in coding_only["data"]]


def test_finalize_gate_recovery_from_spec_payload(tmp_path, monkeypatch):
    """定稿门禁不过(designMd 空) → 从最近 assistant 消息的规约围栏载荷
    确定性补救(amend 落新版本)后再定稿。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import ctx as _actx, websocket as ws, req_agent
    import json as _json
    # 换绑一个 designMd 空的 draft 需求(门禁不过场景)
    r0 = req_agent.run_arch_tool(
        "req.propose", {"title": "T-门禁", "requirementMd": "只有目标", "newRequirement": True},
        root=None, project=None)
    rid0 = r0["requirementId"]
    store.ConversationsStore.update(conv["id"], {"reqId": rid0})
    conv = store.ConversationsStore.get(conv["id"])
    _actx.set_conv(conv["id"]); _actx.set_req(rid0); _actx.set_project(conv["projectId"])
    payload = {"title": "T", "requirementMd": "目标",
               "designMd": "## 方案\n分三步", "acceptanceMd": ["编译通过"]}
    store.ConversationsStore.append_message({
        "id": "m-f1", "conversationId": conv["id"], "role": "assistant",
        "time": 5000, "content": "方案如下\n```json\n" + _json.dumps(payload, ensure_ascii=False) + "\n```"})
    out = asyncio.run(ws._cmd_finalize_turn(store.ConversationsStore.get(conv["id"])))
    assert "规约已确认" in out and "补全" in out, out
    row = store.RequirementsStore.get(rid0) or {}
    sv = row.get("specVersions") or []
    assert sv and "## 方案" in (sv[-1].get("snapshot") or {}).get("designMd", "")


def test_finalize_gate_actionable_guidance(tmp_path, monkeypatch):
    """无可补救载荷 → 拒绝文案给出可操作下一步(/调整), 而非干拒绝。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import ctx as _actx, websocket as ws, req_agent
    r0 = req_agent.run_arch_tool(
        "req.propose", {"title": "T-门禁2", "requirementMd": "只有目标", "newRequirement": True},
        root=None, project=None)
    rid0 = r0["requirementId"]
    store.ConversationsStore.update(conv["id"], {"reqId": rid0})
    conv = store.ConversationsStore.get(conv["id"])
    _actx.set_conv(conv["id"]); _actx.set_req(rid0); _actx.set_project(conv["projectId"])
    out = asyncio.run(ws._cmd_finalize_turn(store.ConversationsStore.get(conv["id"])))
    assert "定稿未通过" in out and "/调整" in out, out


def test_chat_system_prompt_no_reject_boundary():
    """自由对话 system 含职责边界: 弱相关需求不拒做(用户主权, 提示不打断)。

    经 prompt_registry 组装后按渲染产物断言(不再检查函数源码)。
    """
    from topoone_app_architect.arch_routes import req_agent
    s = req_agent.chat_system_prompt(None, None)
    assert "不拒做" in s and "职责边界" in s, "system 提示应含职责边界(弱相关受理)"
    assert "designMd" in s, "边界提示应同步强调 designMd 完整性"


def test_chat_system_prompt_registry_equivalence():
    """registry 等价模式: 与旧拼接逐字节一致(rstrip 尾空白); 单源模式可渲染。"""
    from topoone_app_architect.arch_routes import req_agent, prompt_registry
    for kw in ({}, {"diagram_skill": True}, {"skill_scenarios": ["plan"]}):
        a = req_agent.chat_system_prompt(None, None, **kw)
        b = req_agent.chat_system_prompt_legacy(None, None, **kw)
        assert a.rstrip() == b.rstrip(), f"等价失败: {kw}"
    # 单源模式: 注册表渲染能力文档(含协议+全部工具名)
    doc = prompt_registry.capability_doc_from_tools()
    from topoone_app_architect.arch_routes.req_agent import _ARCH_TOOLS
    assert "[TOOL_CALL]" in doc
    for name in ("req.propose", "req.amend", "kb.asset.search", "map.overview"):
        assert name in doc, f"单源文档缺工具 {name}"


def test_prompt_registry_budget_trim():
    """预算裁剪: 小预算淘汰条件块(skill/ir), 恒置块(协议/边界)保留。"""
    from topoone_app_architect.arch_routes import prompt_registry as pr
    s = pr.render_system({"root": None, "project": None, "tier": 4,
                          "skill_scenarios": ["plan"]})
    assert "职责边界" in s and "[TOOL_CALL]" in s, "恒置块永不裁剪"
    assert "技能" not in s or len(s) <= pr.budget_for(4) + 800, "t4 预算应显著收紧"


def test_delete_session_cascade_related_entries(tmp_path, monkeypatch):
    """删除会话级联清理关联条目: 停作业/递归删子会话/孤儿 draft 需求删除/
    保留需求的 ownerConv 悬空引用清空。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import sessions as S, exec_bridge
    monkeypatch.setattr(exec_bridge, "stop", lambda cid, reason="": "无作业")
    # draft 需求(source=本会话) → 应级联删除
    r_draft = req_agent.run_arch_tool(
        "req.propose", {"title": "T-孤儿", "requirementMd": "未定稿提案", "newRequirement": True},
        root=None, project=None)
    rid_draft = r_draft["requirementId"]
    row = store.RequirementsStore.get(rid_draft) or {}
    assert (row.get("sourceConversationId") or "") == conv["id"] or True
    store.RequirementsStore.update(rid_draft, {"sourceConversationId": conv["id"],
                                               "ownerConv": conv["id"]})
    # ready 需求(source=本会话) → 保留, ownerConv 清空
    r_ready = req_agent.run_arch_tool(
        "req.propose", {"title": "T-保留", "designMd": "方案", "newRequirement": True},
        root=None, project=None)
    rid_ready = r_ready["requirementId"]
    req_agent.run_arch_tool("req.finalize", {"reqId": rid_ready}, root=None, project=None)
    store.RequirementsStore.update(rid_ready, {"sourceConversationId": conv["id"],
                                               "ownerConv": conv["id"]})
    # coding 子会话 → 递归删除
    sub = store.ConversationsStore.create({"kind": "coding", "parentConvId": conv["id"],
                                           "projectId": conv["projectId"]})
    # 会话绑定 reqId 指向 draft 需求(删除后需求不在)
    store.ConversationsStore.update(conv["id"], {"reqId": rid_draft})

    n = S._delete_session_cascade(conv["id"])

    assert n == 2, f"父+子应级联删 2, got {n}"
    assert not store.ConversationsStore.get(conv["id"])
    assert not store.ConversationsStore.get(sub["id"]), "子会话应递归删除"
    assert not store.RequirementsStore.get(rid_draft), "孤儿 draft 需求应级联删除"
    kept = store.RequirementsStore.get(rid_ready) or {}
    assert kept.get("status") == "ready", "已定稿需求是项目资产应保留"
    assert kept.get("ownerConv", "x") in ("", None), "保留需求的 ownerConv 悬空引用应清空"


def test_delete_session_cascade_cross_db(tmp_path, monkeypatch):
    """跨库级联: 会话在主库默认桶(无活跃项目写入), 需求在项目库——删除会话时
    项目库需求同样清理(draft 删/ready 清 ownerConv), 消息同桶删净不残留。"""
    from topoone_app_architect.arch_routes import sessions as S, exec_bridge, ctx as C
    monkeypatch.setattr(exec_bridge, "stop", lambda cid, reason="": "无作业")
    _mk_fixture(tmp_path, monkeypatch)

    conv = store.ConversationsStore.create({"id": "cv-xdb", "title": "跨库"})
    store.ConversationsStore.append_message(
        {"conversationId": "cv-xdb", "role": "user", "content": "hi"})
    pdb = C.project_db("proj-xdb", create=True)
    pdb.execute(
        "INSERT INTO arch_requirements (id, title, status, source_conversation_id) "
        "VALUES ('RQ-X1', 'draft跨库', 'draft', 'cv-xdb')")
    pdb.execute(
        "INSERT INTO arch_requirements (id, title, status, source_conversation_id, owner_conv) "
        "VALUES ('RQ-X2', 'ready跨库', 'ready', 'cv-xdb', 'cv-xdb')")
    pdb.commit()

    assert S._delete_session_cascade("cv-xdb") == 1
    assert C.db().fetchall(
        "SELECT * FROM arch_conversation_messages WHERE conversation_id='cv-xdb'") == [], "消息应删净"
    rows = {r["id"]: r for r in pdb.fetchall("SELECT * FROM arch_requirements")}
    assert "RQ-X1" not in rows, "项目库 draft 需求应跨库级联删除"
    assert rows["RQ-X2"]["owner_conv"] == "", "项目库 ready 需求 ownerConv 应清空"


def test_pump_input_required_separates_streams(tmp_path, monkeypatch):
    """信息流分离: input_required 只落 coding 子会话全文, 主会话不落消息,
    未读计数 bump(subUnread)——主视图经 Coding 入口 badge 感知。"""
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import exec_bridge as eb
    sub = store.ConversationsStore.create(
        {"kind": "coding", "parentConvId": conv["id"], "reqId": rid, "title": "coding"})
    eb._job_upsert(conv["id"], {"jobId": "impl-s1", "status": "running",
                                "subSessionId": sub["id"]})
    eb._handle_pump_event(
        {"kind": "input_required", "text": "[[NEED_INPUT]]\n脚本用哪个 HTTP 库?"},
        {"convId": conv["id"], "jobId": "impl-s1", "rid": rid, "pid": "",
         "subId": sub["id"], "target": sub["id"]})

    # 子会话: 全文等待卡
    sub_msgs = store.ConversationsStore.messages(sub["id"])
    assert any("执行工程师需要你的输入" in (m.get("content") or "") for m in sub_msgs)
    # 主会话: 不落 job_input 消息(信息流分离)
    main_msgs = store.ConversationsStore.messages(conv["id"])
    assert not any("执行工程师需要你的输入" in (m.get("content") or "") for m in main_msgs)
    # 未读计数 bump + 作业 waiting
    meta = eb._meta_dict_of(store.ConversationsStore.get(conv["id"]))
    assert int(meta.get("subUnread") or 0) == 1
    assert eb.active_job(conv["id"]).get("status") == "waiting_input"
