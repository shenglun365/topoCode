"""执行门禁特征测试(重定位 P3 前置项, 裁决 2026-09-26)。

cv-257 教训: 主工作区有其它开发进程的未提交变更时就地执行 → 互踩。
门禁语义: 就地(mutating)+git 工作区脏 → 显式失败并引导(处理变更/开会话隔离);
非 git 目录不拦(无从判断); worktree 隔离与 readonly 豁免。
"""
from __future__ import annotations

import subprocess

import pytest

from topoone_app_architect import store


def _mk_env(arch_env, tmp_path, monkeypatch, root):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "gate", "meta": {"root": str(root)},
        "reqId": "RQ-gate"})
    conv = store.ConversationsStore.get(conv_row["id"])
    store.RequirementsStore.create({
        "id": "RQ-gate", "title": "T", "status": "ready",
        "analysis": {"allowedScope": ["src/"]}, "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"allowedScope": ["src/"], "designMd": "方案"},
                          "source": {}, "reason": "", "createdAt": 0}]})
    from topoone_app_architect.agent.execution import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), ""))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "config": {}}])
    monkeypatch.setattr(eb, "_runner", lambda path, payload=None, timeout=12.0:
                        {"ok": True, "jobId": "j", "branch": payload["branchName"],
                         "worktree": str(tmp_path / "wt"), "sessionId": "s",
                         "baseCommit": "sha"} if path == "/api/implement"
                        else {"ok": True})
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb


def _git(root, *args):
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "README.md").write_text("init\n")   # 防 empty-commit
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"],
                   check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    for a in args:
        subprocess.run(["git", "-C", str(root)] + list(a), check=True)


def test_dirty_inplace_rejected(arch_env, tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, ("add", "-A"), ("commit", "-qm", "init"))
    (root / "wip.txt").write_text("其它进程的半成品")
    conv, eb = _mk_env(arch_env, tmp_path, monkeypatch, root)
    task = eb.propose_task(conv, "改动", "x", {"executorType": "cline-sdk"})
    res = eb.confirm_task(task["id"])
    assert not res["ok"]
    assert "未提交变更" in res["error"]
    assert (store.TasksStore.get(task["id"]) or {}).get("status") == "failed"


def test_clean_repo_inplace_passes(arch_env, tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    _git(root, ("add", "-A"), ("commit", "-qm", "init"))
    conv, eb = _mk_env(arch_env, tmp_path, monkeypatch, root)
    task = eb.propose_task(conv, "改动", "x", {"executorType": "cline-sdk"})
    res = eb.confirm_task(task["id"])
    assert res["ok"]


def test_non_git_dir_skips_gate(arch_env, tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    (root / "junk.txt").write_text("x")   # 非 git 目录, 无从判断 → 不拦
    conv, eb = _mk_env(arch_env, tmp_path, monkeypatch, root)
    task = eb.propose_task(conv, "改动", "x", {"executorType": "cline-sdk"})
    assert eb.confirm_task(task["id"])["ok"]


def test_dirty_worktree_helper(tmp_path):
    from topoone_app_architect.agent.execution.dispatch import _dirty_worktree
    assert _dirty_worktree(str(tmp_path)) is False     # 非 git → False
    _git(tmp_path, ("add", "-A"), ("commit", "-qm", "i"))
    assert _dirty_worktree(str(tmp_path)) is False     # 干净
    (tmp_path / "a.txt").write_text("x")
    assert _dirty_worktree(str(tmp_path)) is True      # 脏(未跟踪也算)
