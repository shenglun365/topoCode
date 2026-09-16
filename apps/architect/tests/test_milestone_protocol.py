"""里程碑协议(环节十一)回归: 指令协议注入 / 报告解析 / 边界回写 / 事件链路。

Run: cd <repo> && python -m pytest apps/architect/tests/test_milestone_protocol.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store

# ── 任务指令: 里程碑协议 + DoD 一致性 ────────────────────────────────

def test_instruction_contains_milestone_protocol():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    text = assemble_task_instruction({"title": "T", "instruction": "做事情"}, "")
    assert "里程碑协议" in text
    assert "里程碑计划" in text and "等待用户确认" in text
    assert "改动文件:" in text and "验证:" in text and "下一里程碑:" in text
    assert "禁止未提交报告就连续跨里程碑推进" in text
    assert "15 次工具调用" in text            # 复杂度分界: 简单任务直通


def test_instruction_dod_aligned_with_verification_boundary():
    """DoD 与执行器验证边界一致(单测=自主选用, 非强制; 禁为测试改结构)。"""
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    text = assemble_task_instruction({"title": "T", "instruction": "做"}, "")
    assert "单元测试是自主选用的验证手段" in text
    assert "编写并运行单元测试(全部通过)" not in text   # 旧强制单测条款已废
    assert "禁止为迁就测试而改动源码结构" in text
    assert "运行冒烟" in text


# ── 里程碑报告解析 ───────────────────────────────────────────────────

def test_milestone_report_files_parse():
    from topoone_app_architect.arch_routes.exec_bridge import _milestone_report_files
    text = ("里程碑 1 完成。\n改动文件: src/a.c, `src/http/b.h`, conf/x.conf\n"
            "验证: 编译通过\n下一里程碑: 配置集成")
    assert _milestone_report_files(text) == ["src/a.c", "src/http/b.h", "conf/x.conf"]


def test_milestone_report_files_absent():
    from topoone_app_architect.arch_routes.exec_bridge import _milestone_report_files
    assert _milestone_report_files("普通提问: 需要端口号?") == []
    assert _milestone_report_files("") == []


# ── 边界回写(自我修正闭环) ───────────────────────────────────────────

def _mk_req_spec(arch_env, tmp_path, monkeypatch, with_spec=True):
    rid = "RQ-ms"
    store.RequirementsStore.create({
        "id": rid, "title": "T", "status": "ready",
        "analysis": {"allowedScope": ["src/existing/"]}})
    if with_spec:
        store.RequirementsStore.spec_append(
            rid, {"allowedScope": ["src/existing/"], "designMd": "方案"},
            actor="user", conv_id="cv-1")
        store.RequirementsStore.spec_confirm(rid)
    return rid


def test_merge_req_scope_into_active_snapshot(arch_env, tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes.exec_bridge import _merge_req_scope
    rid = _mk_req_spec(arch_env, tmp_path, monkeypatch, with_spec=True)
    n = _merge_req_scope(rid, ["src/existing/", "src/new/a.c", "src/new/b.c"])
    assert n == 2
    active = store.RequirementsStore.spec_active(rid)
    assert active["snapshot"]["allowedScope"] == ["src/existing/", "src/new/a.c",
                                                  "src/new/b.c"]
    assert _merge_req_scope(rid, ["src/new/a.c"]) == 0     # 幂等


def test_merge_req_scope_fallback_to_analysis(arch_env, tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes.exec_bridge import _merge_req_scope
    rid = _mk_req_spec(arch_env, tmp_path, monkeypatch, with_spec=False)
    assert _merge_req_scope(rid, ["docs/x.md"]) == 1
    assert store.RequirementsStore.get(rid)["analysis"]["allowedScope"] == \
        ["src/existing/", "docs/x.md"]


def test_merge_req_scope_no_req(arch_env, tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes.exec_bridge import _merge_req_scope
    assert _merge_req_scope("RQ-none", ["a.py"]) == 0


# ── 事件链路: input_required 携里程碑报告 → 回执 + 回写 ─────────────

def _mk_conv_task_fixture(arch_env, tmp_path, monkeypatch, rid=""):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    conv = store.ConversationsStore.create({
        "projectId": "proj-ms", "title": "ms",
        "meta": {"root": str(root)}, **({"reqId": rid} if rid else {})})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-ms"))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors",
                        lambda: [{"id": "ex", "type": "cline-sdk", "enabled": True,
                                  "config": {}}])
    calls = {"implement": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        calls["implement"].append((path, payload))
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-ms-1", "branch": "task/ms-1",
                    "worktree": str(tmp_path / "wt"), "sessionId": "s-1",
                    "baseCommit": "abc1234"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb, calls


def test_confirm_task_records_base_commit(arch_env, tmp_path, monkeypatch):
    conv, eb, calls = _mk_conv_task_fixture(arch_env, tmp_path, monkeypatch)
    task = eb.propose_task(conv, "实现 X", "目标 X", {"executorType": "cline-sdk"})
    res = eb.confirm_task(task["id"])
    assert res["ok"]
    row = store.TasksStore.get(task["id"])
    assert row["baseCommit"] == "abc1234"


def test_input_required_milestone_event_flow(arch_env, tmp_path, monkeypatch):
    rid = _mk_req_spec(arch_env, tmp_path, monkeypatch, with_spec=True)
    conv, eb, _ = _mk_conv_task_fixture(arch_env, tmp_path, monkeypatch)
    task = eb.propose_task(conv, "实现 Y", "目标 Y", {"executorType": "cline-sdk"})
    eb.confirm_task(task["id"])
    text = ("里程碑 1 完成\n改动文件: src/added.c\n验证: 编译通过\n"
            "下一里程碑: 集成\n[[NEED_INPUT]] 是否继续?")
    eb._handle_task_event(
        {"kind": "input_required", "text": text},
        {"convId": conv["id"], "taskId": task["id"], "jobId": "job-ms-1",
         "pid": "proj-ms", "agent": "cline", "rid": rid})
    row = store.TasksStore.get(task["id"])
    assert row["status"] == "waiting_input"
    active = store.RequirementsStore.spec_active(rid)
    assert "src/added.c" in active["snapshot"]["allowedScope"]
    msgs = store.ConversationsStore.messages(conv["id"])
    receipt = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_input"]
    assert receipt and "里程碑报告" in receipt[-1]["content"]
    assert "src/added.c" in receipt[-1]["content"]


def test_input_required_plain_question_no_scope_change(arch_env, tmp_path, monkeypatch):
    rid = _mk_req_spec(arch_env, tmp_path, monkeypatch, with_spec=True)
    conv, eb, _ = _mk_conv_task_fixture(arch_env, tmp_path, monkeypatch)
    task = eb.propose_task(conv, "实现 Z", "目标 Z", {"executorType": "cline-sdk"})
    eb.confirm_task(task["id"])
    before = store.RequirementsStore.spec_active(rid)["snapshot"]["allowedScope"]
    eb._handle_task_event(
        {"kind": "input_required", "text": "需要确认端口号? [[NEED_INPUT]]"},
        {"convId": conv["id"], "taskId": task["id"], "jobId": "job-ms-1",
         "pid": "proj-ms", "agent": "cline", "rid": rid})
    assert store.RequirementsStore.spec_active(rid)["snapshot"]["allowedScope"] == before
