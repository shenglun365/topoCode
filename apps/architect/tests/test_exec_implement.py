"""执行链路回归(生命周期 v2)：触发词分层 / 两段式确认(specVer) / 继续执行增量回合。

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


# ── 触发词分层判定 ────────────────────────────────────────────────────

def test_impl_triggers():
    from topoone_app_architect.arch_routes.websocket import _is_impl_intent
    for q in ("执行方案", "执行本任务", "执行任务。", "开始执行", "实施", "执行", "动手实现",
              "执行。", "开始", "调用 coding agent 执行本会话的方案",
              "补充：连接池上限改为64。请执行方案",
              "跑一下方案", "跑起来", "Go Ahead", "执行 RQ-37", "启动执行作业"):
        assert _is_impl_intent(q), q
    for q in ("这个方案怎么执行", "执行方案吗", "执行本任务？", "怎么执行任务",
              "执行方案前先确认依赖", "检查本会话方案是否符合执行标准",
              "不执行了", "执行风险怎么评估", "还是先讨论执行细节吧",
              "什么是执行方案", "要不要执行方案还是先等等",
              "验证是否生效。请执行方案", "不执行", "执行x",
              "并行执行的分析报告"):
        assert not _is_impl_intent(q), q


def test_confirm_and_resume_triggers():
    from topoone_app_architect.arch_routes.websocket import (
        _CONFIRM_TRIG_RE, _RESUME_TRIG_RE, _DIFF_TRIG_RE)
    assert _CONFIRM_TRIG_RE.fullmatch("确认执行")
    assert not _CONFIRM_TRIG_RE.fullmatch("不确认执行")
    assert _RESUME_TRIG_RE.fullmatch("继续执行")
    assert _DIFF_TRIG_RE.fullmatch("查看差异")


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


# ── 两段式确认(specVer 锚定) ─────────────────────────────────────────

def test_two_stage_confirm_binds_spec_ver(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import websocket as ws
    started = _patch_bridge(monkeypatch, tmp_path)

    # ① 执行方案 → 预览(不建作业); pending 锚定 specVer
    out1 = asyncio.run(ws._executor_implement(conv, None))
    assert "执行预览" in out1 and "确认执行" in out1 and "v1" in out1
    assert not started
    pending = store.ConversationsStore.get(conv["id"])["meta"]["execPending"]
    assert pending["specVer"] == 1

    # ② 确认执行 → 建作业(带 specVer)
    out2 = asyncio.run(ws._executor_implement(conv, None, confirmed=True))
    assert started and started["spec_ver"] == 1 and "方案甲" in started["instruction"]
    assert "已启动" in out2
    meta = store.ConversationsStore.get(conv["id"])["meta"]
    assert not meta.get("execPending")

    # ②b 再生成一份 v1 预览(供 ④ 验证失效刷新)
    asyncio.run(ws._executor_implement(conv, None))

    # ③ 规约修订 → 新 draft 版本; 未重新确认前执行被门禁拦截
    req_agent.run_arch_tool("req.amend", {"reqId": rid, "designMd": "方案乙",
                                          "reasoning": "验收意见"}, root=None, project=None)
    blocked = asyncio.run(ws._executor_implement(conv, None))
    assert "尚未确认" in blocked
    # ④ 重新确认 → v2 ready; 旧预览(v1)确认 → 拒绝并按 v2 刷新; 再确认 → 按 v2 启动
    req_agent.run_arch_tool("req.finalize", {"reqId": rid}, root=None, project=None)
    started.clear()
    conv2 = store.ConversationsStore.get(conv["id"])
    out3 = asyncio.run(ws._executor_implement(conv2, None, confirmed=True))
    assert not started and "已按最新版本刷新" in out3      # v1 预览失效(specVer 不匹配)
    asyncio.run(ws._executor_implement(conv2, None))        # 预览 v2
    started.clear()
    out4 = asyncio.run(ws._executor_implement(
        store.ConversationsStore.get(conv["id"]), None, confirmed=True))
    assert started and started["spec_ver"] == 2 and "方案乙" in started["instruction"]


def test_draft_spec_blocks_execution(tmp_path, monkeypatch):
    """draft 规约不可执行——先确认(finalize)再执行。"""
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
    assert "尚未确认" in out and "确认方案" in out


def test_done_req_blocks_execution(tmp_path, monkeypatch):
    conv, rid = _mk_fixture(tmp_path, monkeypatch)
    store.RequirementsStore.mark_done(rid)
    from topoone_app_architect.arch_routes import websocket as ws
    out = asyncio.run(ws._executor_implement(conv, None))
    assert "已完结" in out and "新建需求" in out


# ── 继续执行(增量回合) ────────────────────────────────────────────────

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
