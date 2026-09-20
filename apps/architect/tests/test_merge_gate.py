"""本地 PR 语义(环节十五扩展)回归: 链式基点 / 确认合并门禁 / 未合并预警。

Run: cd <repo> && python -m pytest apps/architect/tests/test_merge_gate.py -q
"""
import os
import subprocess
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store


@pytest.fixture()
def git_project(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def _g(*a, cwd=None):
        subprocess.run(["git", *a], cwd=cwd or repo, check=True,
                       capture_output=True, env=env)
    _g("init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base\n")
    _g("add", "-A")
    _g("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    return repo, _g, base, env


def _mk_conv_task(arch_env, tmp_path, monkeypatch, rid="RQ-mg", status="done",
                  branch="task/9", base=None):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "mg", "meta": {"root": str(tmp_path / "proj")},
        "reqId": rid})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({"conversationId": conv_id, "title": "T",
                                    "instruction": "x", "status": status,
                                    "executorType": "cline-sdk", "branch": branch,
                                    "workspace": "worktree",
                                    "baseCommit": base or ""})
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    return conv_id, task["id"], eb


# ── 确认合并(门禁+执行) ──────────────────────────────────────────────

def test_merge_ff_success_and_terminal(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    g("branch", "task/9")
    g("checkout", "-q", "task/9")
    (repo / "feat.txt").write_text("feat\n")
    g("add", "-A")
    g("commit", "-qm", "feat")
    g("checkout", "-q", "main")
    # 任务行带 worktree(真实注册的 worktree)——合并后应自动清理
    g("worktree", "add", "-q", str(tmp_path / "wt9"), "task/9")
    conv_id, task_id, eb = _mk_conv_task(arch_env, tmp_path, monkeypatch, base=base)
    store.TasksStore.update(task_id, {"worktree": str(tmp_path / "wt9"),
                                      "runnerJobId": "job-mg"})
    finish_calls = []
    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=12.0:
                        finish_calls.append(path) or {"ok": True})
    res = eb.merge_branch(task_id)
    assert res["ok"] and res["mode"] == "ff"
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    assert res["mergedHead"] == head
    row = store.TasksStore.get(task_id)
    assert int(row["mergedAt"] or 0) > 0 and row["mergedHead"] == head
    assert eb.merge_branch(task_id)["code"] == 400          # 幂等: 重复合并拒绝
    # 生命周期闭环: worktree 移除 + 分支删除 + runner 资源释放
    assert not os.path.isdir(str(tmp_path / "wt9"))
    branches = subprocess.run(["git", "branch", "--list", "task/9"], cwd=repo,
                              capture_output=True, text=True).stdout.strip()
    assert branches == ""                                   # -d 已删(内容在 master)
    assert any(p.endswith("/finish") for p in finish_calls)
    assert "worktree 已移除" in res["advice"] and "分支已删除" in res["advice"]


def test_merge_ff_blocked_when_main_advanced(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    g("branch", "task/9")
    g("checkout", "-q", "task/9")
    (repo / "feat.txt").write_text("feat\n")
    g("add", "-A")
    g("commit", "-qm", "feat")
    g("checkout", "-q", "main")
    (repo / "other.txt").write_text("x\n")
    g("add", "-A")
    g("commit", "-qm", "main moved")
    conv_id, task_id, eb = _mk_conv_task(arch_env, tmp_path, monkeypatch, base=base)
    res = eb.merge_branch(task_id, mode="ff")
    assert not res["ok"] and res["code"] == 400 and "rebase" in res["error"]
    # no-ff 强制合并(无冲突文件) → 成功, 产生合并提交
    res2 = eb.merge_branch(task_id, mode="no-ff")
    assert res2["ok"]
    log = subprocess.run(["git", "log", "--oneline", "-1"], cwd=repo,
                         capture_output=True, text=True).stdout
    assert "merge task/9" in log


def test_merge_conflict_aborts_clean(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    # 分支与主目录改同一文件 → no-ff 冲突 → 中止且主目录保持干净
    g("checkout", "-q", "-b", "task/9")
    (repo / "base.txt").write_text("branch version\n")
    g("add", "-A")
    g("commit", "-qm", "branch edit")
    g("checkout", "-q", "main")
    (repo / "base.txt").write_text("main version\n")
    g("add", "-A")
    g("commit", "-qm", "main edit")
    conv_id, task_id, eb = _mk_conv_task(arch_env, tmp_path, monkeypatch, base=base)
    res = eb.merge_branch(task_id, mode="no-ff")
    assert not res["ok"] and res["code"] == 409 and "冲突" in res["error"]
    assert "MERGE_HEAD" not in subprocess.run(
        ["git", "status", "--porcelain"], cwd=repo,
        capture_output=True, text=True).stdout + str(
        subprocess.run(["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
                       cwd=repo, capture_output=True).returncode)
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip() != ""
    # 主目录内容未被合并污染
    assert (repo / "base.txt").read_text() == "main version\n"


def test_merge_dirty_main_rejected(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    g("branch", "task/9")
    conv_id, task_id, eb = _mk_conv_task(arch_env, tmp_path, monkeypatch, base=base)
    (repo / "dirty.txt").write_text("uncommitted\n")
    res = eb.merge_branch(task_id)
    assert not res["ok"] and "未提交改动" in res["error"]


def test_merge_rejects_non_done(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    g("branch", "task/9")
    conv_id, task_id, eb = _mk_conv_task(arch_env, tmp_path, monkeypatch,
                                         status="running", base=base)
    assert eb.merge_branch(task_id)["code"] == 400


# ── 链式基点 + 未合并预警 ────────────────────────────────────────────

def test_chain_base_prefers_unmerged_branch(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    # 前序 done 任务分支(未合并, 有推进)
    g("branch", "task/1")
    g("checkout", "-q", "task/1")
    (repo / "prev.txt").write_text("prev work\n")
    g("add", "-A")
    g("commit", "-qm", "prev work")
    g("checkout", "-q", "main")
    branch_head = subprocess.run(["git", "rev-parse", "task/1"], cwd=repo,
                                 capture_output=True, text=True).stdout.strip()
    conv_id, t1, eb = _mk_conv_task(arch_env, tmp_path, monkeypatch,
                                    branch="task/1", base=base)
    # 同会话新任务 → 基点 = 未合并分支 head
    assert eb._chain_base(conv_id, "task-other", str(repo)) == branch_head
    # 合并该分支进主 → 回落 HEAD(返回 "")
    g("merge", "--no-ff", "-m", "merge task/1", "task/1")
    assert eb._chain_base(conv_id, "task-other", str(repo)) == ""


def test_propose_card_warns_unmerged(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    g("branch", "task/1")
    g("checkout", "-q", "task/1")
    (repo / "prev.txt").write_text("prev\n")
    g("add", "-A")
    g("commit", "-qm", "prev")
    g("checkout", "-q", "main")
    rid = "RQ-mg"
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "mg2", "meta": {"root": str(repo)}, "reqId": rid,
        "analysisMode": "quick"})
    conv = store.ConversationsStore.get(conv_row["id"])
    store.RequirementsStore.create({
        "id": rid, "title": "T", "status": "ready",
        "analysis": {"allowedScope": ["src/"]}, "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"allowedScope": ["src/"]},
                          "source": {}, "reason": "", "createdAt": 0}]})
    store.TasksStore.create({"conversationId": conv["id"], "title": "前任务",
                             "instruction": "x", "status": "done",
                             "executorType": "cline-sdk", "branch": "task/1",
                             "baseCommit": base})
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(repo), ""))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "config": {}}])
    monkeypatch.setattr(eb, "_runner", lambda *a, **k: {"ok": True})
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    eb.propose_task(conv, "新任务", "x", {"executorType": "cline-sdk"})
    msgs = store.ConversationsStore.messages(conv["id"])
    card = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"][-1]
    assert "未合并分支" in card["content"] and "task/1" in card["content"]
