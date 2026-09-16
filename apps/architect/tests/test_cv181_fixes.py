"""cv-181 完整链路修复回归: 续跑分支单源 / 复制实现检测 / 指令别名 / 双标题。

Run: cd <repo> && python -m pytest apps/architect/tests/test_cv181_fixes.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store


# ── 修复1: 续跑分支单源(propose 决定, confirm 消费) ──────────────────

def _mk_env(arch_env, tmp_path, monkeypatch, failed_branch="task/17"):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "mg", "meta": {"root": str(tmp_path / "proj")},
        "reqId": "RQ-rb"})
    conv_id = conv_row["id"]
    conv = store.ConversationsStore.get(conv_id)
    store.RequirementsStore.create({
        "id": "RQ-rb", "title": "T", "status": "ready",
        "analysis": {"allowedScope": ["src/"]}, "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"allowedScope": ["src/"], "designMd": "方案"},
                          "source": {}, "reason": "", "createdAt": 0}]})
    if failed_branch:
        store.TasksStore.create({"conversationId": conv_id, "title": "旧任务",
                                 "instruction": "x", "status": "failed",
                                 "executorType": "cline-sdk", "branch": failed_branch,
                                 "baseCommit": ""})
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "config": {}}])
    calls = {"implement": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        calls["implement"].append((path, payload))
        if path == "/api/implement":
            # runner 语义: 分支已存在 → resumed 承接(返回同名分支)
            return {"ok": True, "jobId": "job-rb", "branch": payload["branchName"],
                    "worktree": str(tmp_path / "wt"), "sessionId": "s",
                    "baseCommit": "sha", "resumed": payload["branchName"] == "task/17"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb, calls


def test_resume_branch_survives_confirm(arch_env, tmp_path, monkeypatch):
    """同会话失败任务 → 新任务卡继承其分支 → confirm 下发同名分支(端到端)。"""
    conv, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch)
    task = eb.propose_task(conv, "重跑", "x", {"executorType": "cline-sdk"})
    assert task["branch"] == "task/17"                 # propose 即继承
    res = eb.confirm_task(task["id"])
    assert res["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["branchName"] == "task/17"               # confirm 消费(此前被覆盖为 task/18)
    row = store.TasksStore.get(task["id"])
    assert row["branch"] == "task/17"


def test_fresh_task_gets_own_branch(arch_env, tmp_path, monkeypatch):
    conv, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch, failed_branch="")
    task = eb.propose_task(conv, "新任务", "x", {"executorType": "cline-sdk"})
    res = eb.confirm_task(task["id"])
    assert res["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["branchName"] == f"task/{task['id'].replace('task-', '')}"


# ── 修复2: 复制实现检测 ──────────────────────────────────────────────

C_SELF_CONTAINED = '''
typedef unsigned char u_char;
unsigned long f1(u_char *a) { return a[0]; }
unsigned long f2(u_char *a) { return a[1]; }
unsigned long f3(u_char *a) { return a[2]; }
int main(void) { return 0; }
'''


def _mk_wt(tmp_path, rel, content):
    wt = tmp_path / "wt"
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return str(wt)


def test_copy_impl_flag_detects_selfcontained(tmp_path):
    from topoone_app_architect.arch_routes.exec_bridge import _copy_impl_flag
    wt = _mk_wt(tmp_path, "tests/unit/test_x.c", C_SELF_CONTAINED)
    note = _copy_impl_flag(wt, ["tests/unit/test_x.c"])
    assert "疑似复制实现" in note and "未触及真实代码" in note


def test_copy_impl_flag_passes_production_linked(tmp_path):
    from topoone_app_architect.arch_routes.exec_bridge import _copy_impl_flag
    wt_dir = tmp_path / "wt"
    (wt_dir / "src").mkdir(parents=True)
    (wt_dir / "src" / "calc.h").write_text("int add(int,int);\n")
    content = '''#include "src/calc.h"
int main(void) { return add(1, 2) == 3 ? 0 : 1; }
'''
    (wt_dir / "tests").mkdir()
    (wt_dir / "tests" / "test_x.c").write_text(content)
    assert _copy_impl_flag(str(wt_dir), ["tests/test_x.c"]) == ""


def test_copy_impl_flag_declared_downgrades(tmp_path):
    from topoone_app_architect.arch_routes.exec_bridge import _copy_impl_flag
    wt = _mk_wt(tmp_path, "tests/test_y.c", C_SELF_CONTAINED)
    note = _copy_impl_flag(wt, ["tests/test_y.c"],
                           turn_text="内部函数未导出, 采用复制实现, 原因是无法链接")
    assert "复制实现声明已收到" in note and "疑似" not in note


def test_copy_impl_flag_ignores_non_test(tmp_path):
    from topoone_app_architect.arch_routes.exec_bridge import _copy_impl_flag
    wt = _mk_wt(tmp_path, "src/helper.c", C_SELF_CONTAINED)
    assert _copy_impl_flag(wt, ["src/helper.c"]) == ""


# ── 修复3: 继续执行别名 ──────────────────────────────────────────────

def test_command_aliases():
    from topoone_app_architect.agent.perception.commands import match_command as mc
    assert mc("继续执行") == {"cmd": "执行", "executor": ""}
    assert mc("继续") == {"cmd": "执行", "executor": ""}
    assert mc("重试") == {"cmd": "执行", "executor": ""}
    assert mc("@cline 继续执行") == {"cmd": "执行", "executor": "cline"}
    assert mc("/执行") == {"cmd": "执行", "executor": ""}
    # 自然语言不误触
    assert mc("继续讨论这个方案") is None
    assert mc("我们继续吧") is None
    assert mc("重试了三次都失败") is None


# ── 修复4: 指令双标题 ────────────────────────────────────────────────

def test_instruction_no_double_header():
    from topoone_app_architect.agent.perception.commands import _instruction_from_snapshot
    snap = {"desc": "## 需求目标\n\n为验证 Agent Coding 全流程创建测试用例。",
            "designMd": "方案"}
    out = _instruction_from_snapshot(snap)
    assert out.count("## 需求目标") == 1


def test_spec_snapshot_strips_leading_header():
    from topoone_app_architect.agent.planning.req_spec import _spec_snapshot
    snap = _spec_snapshot("T", "## 需求目标\n\n正文内容", "", [], [], [], [], "", 0)
    assert not snap["desc"].startswith("#")
    assert snap["desc"] == "正文内容"
