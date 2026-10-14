"""P5 端到端：workspaceFiles 组装映射 + team/mcp 事件面。

Run: cd <repo> && python -m pytest apps/architect/tests/test_p5_workspace_rules.py -q
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.agent.execution import exec_bridge as eb


# ── workspaceFiles 组装（per-executor 路径映射）─────────────────────────────

def test_rules_cline_path_mapping():
    files = eb._build_workspace_files(
        "cline-sdk", {"rulesMd": "项目约定：Python 3.10"}, {"rulesMd": "任务规约"})
    paths = [f["path"] for f in files]
    assert ".cline/rules/000-guide.md" in paths
    content = [f for f in files if f["path"].endswith("000-guide.md")][0]["content"]
    assert "任务规约" in content and "项目约定" in content   # 双源合并


def test_rules_opencode_agents_md():
    files = eb._build_workspace_files("opencode", {"rulesMd": "约定"}, {})
    assert files[0]["path"] == "AGENTS.md"


def test_no_rules_no_files():
    assert eb._build_workspace_files("cline-sdk", {}, {}) == []
    assert eb._build_workspace_files("opencode", {"rulesMd": "  "}, {}) == []


def test_cline_teams_agents_files():
    files = eb._build_workspace_files(
        "cline-sdk",
        {"teams": {"enabled": True, "agents": [
            {"name": "helper agent", "content": "你是辅助代理"},
            {"name": "", "content": "无名跳过"},
        ]}},
        {})
    assert len(files) == 1
    assert files[0]["path"] == ".cline/agents/helperagent.md"   # 非法字符清洗
    assert files[0]["content"] == "你是辅助代理"


def test_opencode_teams_not_emitted():
    files = eb._build_workspace_files(
        "opencode", {"teams": {"enabled": True, "agents": [
            {"name": "x", "content": "y"}]}}, {})
    assert files == []      # agents 仅 cline 消费


# ── team/mcp 事件面 ─────────────────────────────────────────────────────────

def _ctx():
    return {"convId": "c1", "taskId": "t1", "jobId": "j1",
            "rid": "r1", "pid": "p1", "agent": "executor"}


def test_team_event_progress_only(monkeypatch):
    appended, seen = [], {}
    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: {"progress": {}})
    monkeypatch.setattr(eb.store.TasksStore, "set_progress",
                        lambda tid, p: seen.update(p))
    monkeypatch.setattr(eb, "_append", lambda *a, **k: appended.append(a))
    monkeypatch.setattr(eb, "_publish_progress", lambda *a, **k: None)
    eb._handle_task_event({"kind": "team", "text": "teammate spawned"}, _ctx())
    assert appended == []                    # 不落消息
    assert seen.get("lastTeam") == "teammate spawned"


def test_mcp_event_progress(monkeypatch):
    seen = {}
    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: {"progress": {}})
    monkeypatch.setattr(eb.store.TasksStore, "set_progress",
                        lambda tid, p: seen.update(p))
    monkeypatch.setattr(eb, "_append", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_publish_progress", lambda *a, **k: None)
    eb._handle_task_event({"kind": "mcp", "text": "arch: 注入失败(已跳过)",
                           "server": "arch", "ok": False}, _ctx())
    assert seen.get("lastMcp") == "arch:failed"
