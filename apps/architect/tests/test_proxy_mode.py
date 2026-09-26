"""coding 直通模式(quick 挡语义升级, 裁决 2026-09-26)特征测试。

契约: quick 挡回合绕过需求/任务体系直达执行器(architect=通道代理)——
- 不落 arch_tasks / arch_requirements(直出卡体系退役);
- 首启注入上下文包契约 + 工作区约定文件(AGENTS.md 映射);
- 脏工作区首次启动显式拒绝(并行进程保护), 续话 /input 直发;
- 未配置执行器显式报错(不强硬保底回 architect 管线)。
"""
from __future__ import annotations

import pytest
import asyncio

from topoone_app_architect import store
from topoone_app_architect.agent.execution import proxy
from topoone_app_architect.agent.execution.proxy import proxy_turn, proxy_enabled


@pytest.fixture(autouse=True)
def _isolate_proxy_state(monkeypatch):
    """_PROXY_JOBS 进程级单例逐测清理; runner 客户端全 mock(测试绝不打真执行器)。"""
    proxy._PROXY_JOBS.clear()
    from topoone_app_architect.agent.execution import exec_bridge as eb

    class _FakeSR:
        ok = True
        job_id = "job-px"
        branch = "proxy/x"
        worktree = "/tmp/px"
        session_id = "s"
        base_commit = "sha"
        workspace = "inplace"
        raw = {}
        error = ""

    class _FakeClient:
        def start_implement(self, payload, timeout=20.0):
            return _FakeSR()

    starts: list = []

    class _FakeClient:
        def start_implement(self, payload, timeout=20.0):
            starts.append(payload)
            return _FakeSR()

    monkeypatch.setattr(eb, "_client", lambda: _FakeClient())
    # 事件泵 no-op(否则对 mock runner 无限轮询, 测试挂死)
    import topoone_app_architect.agent.execution.pumps as _pumps_mod

    async def _no_pump(*a, **k):
        return None

    monkeypatch.setattr(_pumps_mod, "run_event_pump", _no_pump)
    yield starts
    proxy._PROXY_JOBS.clear()


def _mk_conv(arch_env, tmp_path, mode="quick", isolated=0):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "proxy", "meta": {"root": str(tmp_path / "proj")},
        "analysisMode": mode, "isolated": isolated})
    conv = store.ConversationsStore.get(conv_row["id"])
    (tmp_path / "proj").mkdir(exist_ok=True)
    return conv


def _mock_executor(monkeypatch):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "default": True,
         "config": {"rulesMd": "# 仓库规约\n只改 src/"}}])


def _mock_runner(monkeypatch, captured):
    from topoone_app_architect.agent.execution import exec_bridge as eb

    def fake_runner(path, payload=None, timeout=12.0):
        captured.append((path, payload))
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-px", "branch": payload["branchName"],
                    "worktree": payload["root"], "sessionId": "s",
                    "baseCommit": "sha"}
        return {"ok": True}
    monkeypatch.setattr(eb, "_runner", fake_runner)


def _gate(conv):
    return {"conv_id": conv["id"], "conv": conv,
            "question": "把日志清理脚本写一下", "last_user_msg_id": "m1"}


class _Send:
    async def __call__(self, payload):
        pass


def test_quick_mode_enabled_strict_not(arch_env, tmp_path):
    assert proxy_enabled(_mk_conv(arch_env, tmp_path, mode="quick"))
    assert not proxy_enabled(_mk_conv(arch_env, tmp_path, mode="strict"))


def test_proxy_start_no_req_no_task(arch_env, tmp_path, monkeypatch,
                                    _isolate_proxy_state):
    """quick 首启: 直接起执行器会话——零需求卡/零任务卡; 契约段与仓库规约注入。"""
    conv = _mk_conv(arch_env, tmp_path)
    _mock_executor(monkeypatch)
    captured: list = []
    _mock_runner(monkeypatch, captured)
    starts = _isolate_proxy_state
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))

    handled = asyncio.run(proxy_turn({}, _gate(conv), _Send()))

    assert handled is True
    assert len(starts) == 1
    assert "把日志清理脚本写一下" in starts[0]["instruction"]
    assert "上下文包(执行契约)" in starts[0]["instruction"]
    assert starts[0]["workspaceFiles"], "规约需按 caps 映射下发(AGENTS.md/规则目录)"
    assert starts[0]["executorType"] == "cline-sdk"
    # 直通纪律: 不落需求/任务体系
    assert not store.TasksStore.of_conv(conv["id"])
    reqs = store.RequirementsStore.all() or []
    assert not [r for r in reqs if (r.get("ownerConv") or "") == conv["id"]]
    # 会话已登记活跃直通 job
    assert proxy.proxy_job_of(conv["id"])["job_id"] == "job-px"


def test_proxy_followup_forwards_input(arch_env, tmp_path, monkeypatch):
    conv = _mk_conv(arch_env, tmp_path)
    _mock_executor(monkeypatch)
    captured: list = []
    _mock_runner(monkeypatch, captured)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    asyncio.run(proxy_turn({}, _gate(conv), _Send()))
    n_impl = len([p for p, _ in captured if p == "/api/implement"])

    gate2 = {"conv_id": conv["id"], "conv": conv,
             "question": "补充: 只清 /var/log", "last_user_msg_id": "m2"}
    assert asyncio.run(proxy_turn({}, gate2, _Send())) is True
    inputs = [pl for p, pl in captured if p.endswith("/input")]
    assert len(inputs) == 1 and inputs[0]["text"].startswith("补充:")
    assert len([p for p, _ in captured if p == "/api/implement"]) == n_impl


def test_proxy_dirty_repo_rejected(arch_env, tmp_path, monkeypatch):
    import subprocess
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "wip.txt").write_text("其它进程半成品")
    conv = _mk_conv(arch_env, tmp_path)
    _mock_executor(monkeypatch)
    captured: list = []
    _mock_runner(monkeypatch, captured)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), ""))

    assert asyncio.run(proxy_turn({}, _gate(conv), _Send())) is True
    assert not [p for p, _ in captured if p == "/api/implement"]
    assert proxy.proxy_job_of(conv["id"]) is None


def test_proxy_without_executor_explicit_error(arch_env, tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [])
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    handled = asyncio.run(proxy_turn({}, _gate(conv), _Send()))
    assert handled is True    # 显式报错收束, 不回落 architect 管线
    assert proxy.proxy_job_of(conv["id"]) is None
