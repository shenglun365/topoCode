"""范围探针(环节十三)回归: 文件状态助手 / grounding / 探针解析 / 确认链路。

Run: cd <repo> && python -m pytest apps/architect/tests/test_scope_probe.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.governance.boundary import (
    changed_since, files_exist, list_repo_files)


@pytest.fixture()
def git_repo(tmp_path):
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

    def _g(*a, **k):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True,
                       env=env, **k)
    _g("init", "-q")
    (repo / "src").mkdir()
    (repo / "src" / "a.py").write_text("a = 1\n")
    (repo / ".gitignore").write_text("__pycache__/\n")
    _g("add", "-A")
    _g("commit", "-qm", "init")
    return repo, _g


# ── 文件状态助手 ─────────────────────────────────────────────────────

def test_list_repo_files(git_repo):
    repo, _ = git_repo
    files = list_repo_files(str(repo))
    assert "src/a.py" in files and ".gitignore" in files
    (repo / "junk.log").write_text("x")
    (repo / ".gitignore").write_text("__pycache__/\n*.log\n")
    files2 = list_repo_files(str(repo))          # ignored 不入清单
    assert "junk.log" not in files2


def test_files_exist(git_repo):
    repo, _ = git_repo
    existing, missing = files_exist(str(repo), ["src/a.py", "src/", "nope.py"])
    assert "src/a.py" in existing and "src" in existing   # 目录前缀归一(尾 / 剥除)
    assert missing == ["nope.py"]


def test_changed_since(git_repo):
    repo, g = git_repo
    base = subprocess_sha(repo)
    (repo / "src" / "a.py").write_text("a = 2\n")
    g("add", "-A")
    g("commit", "-qm", "move")
    assert changed_since(str(repo), base, ["src/a.py"]) == ["src/a.py"]
    assert changed_since(str(repo), base, ["other.py"]) == []
    assert changed_since(str(repo), "", ["src/a.py"]) == []
    assert changed_since(str(repo), "deadbeef", ["src/a.py"]) == []


def subprocess_sha(repo) -> str:
    import subprocess
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                       capture_output=True, text=True, check=True)
    return r.stdout.strip()


# ── grounding 与探针解析 ─────────────────────────────────────────────

def _isolate(arch_env, monkeypatch):
    from topoone_app_architect import ctx as C
    monkeypatch.setattr(C, "_project_var", C._project_var)
    return arch_env


def test_gather_grounding_tree_and_history(arch_env, git_repo):
    repo, _ = git_repo
    rid = "RQ-g1"
    store.RequirementsStore.create({
        "id": rid, "title": "本需求", "status": "ready", "projectId": "proj-p",
        "analysis": {}})
    other = "RQ-g0"
    store.RequirementsStore.create({
        "id": other, "title": "历史需求", "status": "ready", "projectId": "proj-p",
        "analysis": {"allowedScope": ["src/a.py"]}})
    from topoone_app_architect.agent.planning.scope_probe import gather_grounding
    g = gather_grounding(str(repo), "proj-p", "需求文本", exclude_rid=rid)
    assert "src/a.py" in g["tree"]
    assert any("RQ-g0" in h for h in g["history"])
    assert not any("RQ-g1" in h for h in g["history"])   # 自身排除


def test_probe_scope_normalizes_llm_output(arch_env, monkeypatch, git_repo):
    repo, _ = git_repo
    from topoone_app_architect.arch_routes import req_agent as ra

    def _fake_llm(messages, **kw):
        assert "范围探针" in messages[0]["content"]
        return {"output": {"files": [
            {"path": "src/a.py", "source": "tree"},
            {"path": "./src/b/", "source": "weird"},   # 归一+来源纠正
            {"path": "/abs/x.py", "source": "tree"},   # 绝对路径丢弃
            {"path": "src/a.py", "source": "tree"},    # 去重
            "junk",
        ], "note": "n"}}
    monkeypatch.setattr(ra, "llm_sync", _fake_llm)
    from topoone_app_architect.agent.planning.scope_probe import probe_scope
    pr = probe_scope(str(repo), "proj-p", "需求文本")
    assert pr["ok"]
    assert pr["files"] == [{"path": "src/a.py", "source": "tree"},
                           {"path": "src/b", "source": "inference"}]


def test_probe_scope_llm_unavailable(arch_env, monkeypatch, git_repo):
    repo, _ = git_repo
    from topoone_app_architect.arch_routes import req_agent as ra
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **k: (_ for _ in ()).throw(
        RuntimeError("down")))
    from topoone_app_architect.agent.planning.scope_probe import probe_scope
    assert probe_scope(str(repo), "proj-p", "需求")["ok"] is False


# ── 确认链路: 空边界探针补全 / 失败不阻断 / 卡片警示 ────────────────

def _mk_conv_req(arch_env, tmp_path, monkeypatch, rid="RQ-sp", with_scope=False,
                 mode="strict"):
    conv = store.ConversationsStore.create({
        "projectId": "proj-sp", "title": "sp",
        "meta": {"root": str(tmp_path / "repo")}, "reqId": rid,
        "analysisMode": mode})
    scope = ["src/a.py"] if with_scope else []
    store.RequirementsStore.create({
        "id": rid, "title": "T", "status": "ready", "projectId": "proj-sp",
        "analysis": {"allowedScope": scope, "requirementMd": "需求文本"},
        "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"allowedScope": scope, "designMd": "方案"},
                          "source": {}, "reason": "", "createdAt": 0}]})
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "repo"), "proj-sp"))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "config": {}}])
    calls = {"implement": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        calls["implement"].append((path, payload))
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-sp", "branch": "task/sp",
                    "worktree": str(tmp_path / "wt"), "sessionId": "s",
                    "baseCommit": "sha"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb, calls


def test_confirm_empty_scope_probe_enriches(arch_env, tmp_path, monkeypatch, git_repo):
    """空边界 + 探针命中 → 边界补全 + 回写需求 + 指令渲染。"""
    repo, _ = git_repo
    conv, eb, calls = _mk_conv_req(arch_env, tmp_path, monkeypatch)
    import topoone_app_architect.agent.planning.scope_probe as sp
    monkeypatch.setattr(sp, "probe_scope",
                        lambda root, project, text, rid="", tier="T1":
                        {"ok": True, "files": [{"path": "src/probed.py",
                                                "source": "tree"}], "note": ""})
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk"})
    res = eb.confirm_task(task["id"])
    assert res["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert "src/probed.py" in pl["boundaries"]["files"]
    assert "范围探针补全" in pl["instruction"]
    snap = store.RequirementsStore.spec_active("RQ-sp")["snapshot"]
    assert "src/probed.py" in snap["allowedScope"]      # 回写闭环


def test_confirm_probe_failure_degrades(arch_env, tmp_path, monkeypatch, git_repo):
    """探针异常 → 执行继续, 指令标注无互斥保护。"""
    repo, _ = git_repo
    conv, eb, calls = _mk_conv_req(arch_env, tmp_path, monkeypatch)
    import topoone_app_architect.agent.planning.scope_probe as sp
    def _boom(*a, **k):
        raise RuntimeError("down")
    monkeypatch.setattr(sp, "probe_scope", _boom)
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk"})
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert "无互斥保护" in pl["instruction"]


def test_propose_card_warns_on_empty_scope(arch_env, tmp_path, monkeypatch, git_repo):
    """空边界 → 任务卡显式警示(确认=显式接受)。"""
    repo, _ = git_repo
    conv, eb, _ = _mk_conv_req(arch_env, tmp_path, monkeypatch)
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk"})
    msgs = store.ConversationsStore.messages(conv["id"])
    card = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"][-1]
    assert "无互斥保护" in card["content"]
    # 有边界 → 不警示
    conv2, eb2, _ = _mk_conv_req(arch_env, tmp_path, monkeypatch, rid="RQ-sp2",
                                 with_scope=True)
    eb2.propose_task(conv2, "T2", "x", {"executorType": "cline-sdk"})
    msgs2 = store.ConversationsStore.messages(conv2["id"])
    card2 = [m for m in msgs2 if (m.get("meta") or {}).get("kind") == "task_card"][-1]
    assert "无互斥保护" not in card2["content"]


def test_propose_resume_staleness_warning(arch_env, tmp_path, monkeypatch, git_repo):
    """续跑: 失败任务基点以来边界文件已推进 → 卡片交接过期警示。"""
    repo, g = git_repo
    base = subprocess_sha(repo)
    (repo / "src" / "a.py").write_text("a = 9\n")
    g("add", "-A")
    g("commit", "-qm", "advance")
    conv, eb, _ = _mk_conv_req(arch_env, tmp_path, monkeypatch, with_scope=True)
    store.TasksStore.create({"conversationId": conv["id"], "projectId": "proj-sp",
                             "reqId": "RQ-sp2", "title": "旧任务",
                             "instruction": "x", "status": "failed",
                             "executorType": "cline-sdk", "executorId": "ex",
                             "branch": "task/77", "baseCommit": base})
    eb.propose_task(conv, "新任务", "x", {"executorType": "cline-sdk"})
    msgs = store.ConversationsStore.messages(conv["id"])
    card = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"][-1]
    assert "交接过期" in card["content"] and "src/a.py" in card["content"]
