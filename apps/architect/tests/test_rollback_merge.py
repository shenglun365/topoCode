"""环节十五回归: 回退到消息 N(截断/守卫) + 合并入口 precheck(git 事实)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_rollback_merge.py -q
"""
import os
import subprocess
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store


# ── 回退到消息 N ─────────────────────────────────────────────────────

def _mk_conv(arch_env, tmp_path, n_msgs=4):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "rb", "meta": {"root": str(tmp_path)}})
    conv_id = conv_row["id"]
    ids = []
    for i in range(n_msgs):
        m = store.ConversationsStore.append_message({
            "id": f"msg-{i}", "conversationId": conv_id, "role": "user" if i % 2 else "assistant",
            "content": f"消息{i}", "time": 1000 + i})
        ids.append(m["id"])
    return conv_id, ids


def test_delete_messages_after_truncates(arch_env, tmp_path):
    conv_id, ids = _mk_conv(arch_env, tmp_path)
    removed = store.ConversationsStore.delete_messages_after(conv_id, ids[1])
    assert removed == 2
    msgs = store.ConversationsStore.messages(conv_id)
    assert [m["id"] for m in msgs] == ["msg-0", "msg-1"]
    # 幂等: 再删一次 → 0
    assert store.ConversationsStore.delete_messages_after(conv_id, ids[1]) == 0
    assert store.ConversationsStore.delete_messages_after(conv_id, "msg-nope") == -1


def test_rollback_route_guards_running_task(arch_env, tmp_path, monkeypatch, client):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv_id, ids = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(eb, "active_task_of",
                        lambda cid: {"id": "task-1", "status": "running"})
    r = client.delete(f"/api/architect/requirements/conversations/{conv_id}/messages/{ids[2]}/after")
    assert r.status_code == 409
    monkeypatch.setattr(eb, "active_task_of", lambda cid: None)
    r = client.delete(f"/api/architect/requirements/conversations/{conv_id}/messages/{ids[2]}/after")
    assert r.status_code == 200
    assert r.json()["data"]["removed"] == 1
    r = client.delete(f"/api/architect/requirements/conversations/{conv_id}/messages/msg-x/after")
    assert r.status_code == 404


# ── 合并入口 precheck ────────────────────────────────────────────────

@pytest.fixture()
def git_project(tmp_path):
    repo = tmp_path / "proj"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def _g(*a, cwd=repo):
        subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, env=env)
    _g("init", "-q", "-b", "main")
    (repo / "base.txt").write_text("base\n")
    _g("add", "-A")
    _g("commit", "-qm", "base")
    base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    return repo, _g, base, env


def _mk_done_task(arch_env, tmp_path, monkeypatch, base, branch="task/9"):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "mp", "meta": {"root": str(tmp_path / "proj")},
        "reqId": "RQ-mp"})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({"conversationId": conv_id, "title": "T",
                                    "instruction": "x", "status": "done",
                                    "executorType": "cline-sdk", "branch": branch,
                                    "workspace": "worktree",
                                    "baseCommit": base, "resultMd": "ok"})
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    return conv_id, task["id"], eb


def test_merge_precheck_fast_forward(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    # 任务分支推进(独立分支)
    g("branch", "task/9")
    conv_id, task_id, eb = _mk_done_task(arch_env, tmp_path, monkeypatch, base)
    res = eb.merge_precheck(task_id)
    assert res["ok"] and res["fastForward"] is True
    assert res["branchCommits"] == []
    assert "可直接合并" in res["advice"]


def test_merge_precheck_main_advanced(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    g("branch", "task/9")
    (repo / "other.txt").write_text("x\n")
    g("add", "-A")
    g("commit", "-qm", "main moved on")
    conv_id, task_id, eb = _mk_done_task(arch_env, tmp_path, monkeypatch, base)
    res = eb.merge_precheck(task_id)
    assert res["ok"] and res["fastForward"] is False
    assert len(res["mainNewCommits"]) == 1 and "rebase" in res["advice"]


def test_merge_precheck_no_base_and_non_terminal(arch_env, tmp_path, monkeypatch, git_project):
    repo, g, base, env = git_project
    conv_id, task_id, eb = _mk_done_task(arch_env, tmp_path, monkeypatch, base="")
    res = eb.merge_precheck(task_id)
    assert res["ok"] and res["checkable"] is False and "无基点" in res["advice"]
    # 非终态 → 400
    t2 = store.TasksStore.create({"conversationId": conv_id, "title": "T2",
                                  "instruction": "x", "status": "running",
                                  "executorType": "cline-sdk", "baseCommit": base})
    res2 = eb.merge_precheck(t2["id"])
    assert not res2["ok"] and res2["code"] == 400


def test_merge_precheck_route(arch_env, tmp_path, monkeypatch, client, git_project):
    repo, g, base, env = git_project
    conv_id, task_id, eb = _mk_done_task(arch_env, tmp_path, monkeypatch, base)
    r = client.get(f"/api/architect/tasks/{task_id}/merge-precheck")
    assert r.status_code == 200 and r.json()["data"]["ok"] is True
    r = client.get("/api/architect/tasks/task-nope/merge-precheck")
    assert r.status_code == 404
