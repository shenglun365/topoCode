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
# 收集期绑定原始泵(夹具 monkeypatch 只改模块属性, 不影响此引用)
from topoone_app_architect.agent.execution.pumps import \
    run_event_pump as REAL_RUN_EVENT_PUMP


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


EXECUTOR_FIXTURE = {"id": "ex", "type": "cline-sdk", "enabled": True,
                    "default": True,
                    "config": {"rulesMd": "# 仓库规约\n只改 src/"}}


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
    captured: list = []
    _mock_runner(monkeypatch, captured)
    starts = _isolate_proxy_state
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))

    handled = asyncio.run(proxy_turn(
        {}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
        project="", executor=EXECUTOR_FIXTURE))

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
    captured: list = []
    _mock_runner(monkeypatch, captured)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    asyncio.run(proxy_turn({}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
                           project="", executor=EXECUTOR_FIXTURE))
    n_impl = len([p for p, _ in captured if p == "/api/implement"])

    gate2 = {"conv_id": conv["id"], "conv": conv,
             "question": "补充: 只清 /var/log", "last_user_msg_id": "m2"}
    assert asyncio.run(proxy_turn({}, gate2, _Send(), root=str(tmp_path / "proj"),
                                  project="", executor=EXECUTOR_FIXTURE)) is True
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
    captured: list = []
    _mock_runner(monkeypatch, captured)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), ""))

    assert asyncio.run(proxy_turn({}, _gate(conv), _Send(), root=str(root),
                                  project="", executor=EXECUTOR_FIXTURE)) is True
    assert not [p for p, _ in captured if p == "/api/implement"]
    assert proxy.proxy_job_of(conv["id"]) is None


def test_proxy_without_executor_explicit_error(arch_env, tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [])
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    handled = asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                                     root=str(tmp_path / "proj"), project="",
                                     executor={}))
    assert handled is True    # 显式报错收束, 不回落 architect 管线
    assert proxy.proxy_job_of(conv["id"]) is None


# ══════════ cv-259 回归: 直通泵签名 / 配置同源 / 死作业转发 ══════════


def _run(corofn):
    async def _main():
        await corofn()
        await asyncio.sleep(0.05)   # 让 create_task 的泵协程真正跑一拍
    return asyncio.run(_main())


def test_pump_passes_required_on_snapshot(arch_env, tmp_path, monkeypatch,
                                          _isolate_proxy_state):
    """泵调用必须带全 run_event_pump 必填 kwargs(cv-259 缺 on_snapshot →
    协程 TypeError 即死, 事件全丢且死 job 句柄永久占住直通会话)。"""
    import inspect
    import topoone_app_architect.agent.execution.pumps as _pumps_mod

    captured: dict = {}

    async def _rec(**kw):
        captured.update(kw)

    monkeypatch.setattr(_pumps_mod, "run_event_pump", _rec)
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))

    async def _go():
        await proxy_turn({}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    _run(_go)
    required = {p for p, prm in inspect.signature(REAL_RUN_EVENT_PUMP).parameters.items()
                if prm.kind is prm.KEYWORD_ONLY and prm.default is prm.empty}
    assert required and required <= captured.keys(), \
        f"泵调用缺必填参数: {required - set(captured)}"


def test_pump_crash_clears_handle_and_lands_receipt(arch_env, tmp_path,
                                                    monkeypatch):
    """泵异常退出: 句柄必须清空 + 落可见回执(死会话不再吞后续消息)。"""
    import topoone_app_architect.agent.execution.pumps as _pumps_mod

    async def _boom(**kw):
        raise TypeError("missing 1 required keyword-only argument: 'on_snapshot'")

    monkeypatch.setattr(_pumps_mod, "run_event_pump", _boom)
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-px",
                                     "executor_type": "cline-sdk"}

    async def _go():
        proxy._start_pump(conv["id"], "job-px", "cline-sdk")
    _run(_go)
    assert proxy.proxy_job_of(conv["id"]) is None
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any("事件泵异常退出" in str(m.get("content") or "") for m in msgs)


def test_proxy_start_carries_executor_config(arch_env, tmp_path, monkeypatch,
                                             _isolate_proxy_state):
    """启动 payload 必须经 executor_hint_by_id 同源带 full executorConfig
    (cv-259: 只发 executorType → runner _resolve_model 空 models → failed)。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    starts = _isolate_proxy_state
    monkeypatch.setattr(eb, "executor_hint_by_id", lambda eid, c=None: {
        "executorId": "cline", "executorType": "cline-sdk",
        "executorConfig": {
            "model_id": "LMS-x",
            "models": [{"name": "LMS-x", "model": "LMS-x",
                        "url": "http://10.0.0.75:1234/v1"}]},
        "model": "LMS-x"})
    conv = _mk_conv(arch_env, tmp_path)

    async def _go():
        await proxy_turn({}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    asyncio.run(_go())
    p = starts[0]
    assert p["executorId"] == "cline"
    assert p["executorType"] == "cline-sdk"
    assert (p["executorConfig"].get("models")
            or []), "models 投影必须随作业下发(runner 解析链依赖)"
    assert p["model"] == "LMS-x"


def test_proxy_forward_terminal_job_starts_new(arch_env, tmp_path, monkeypatch,
                                               _isolate_proxy_state):
    """活跃 job 已终态: 不再盲发 /input, 弹出句柄并开启新直通会话。"""
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-old",
                                     "executor_type": "cline-sdk"}
    captured: list = []

    def fake_runner(path, payload=None, timeout=12.0):
        captured.append((path, payload))
        return {"ok": True, "status": "failed"}
    monkeypatch.setattr(
        "topoone_app_architect.agent.execution.exec_bridge._runner",
        fake_runner)

    async def _go():
        await proxy_turn({}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    asyncio.run(_go())
    assert not [p for p, _ in captured if p.endswith("/input")], \
        "终态 job 不得再转发消息"
    assert len(starts) == 1, "应开启新的直通作业"
    assert proxy.proxy_job_of(conv["id"])["job_id"] == "job-px"


def test_proxy_forward_unreachable_runner_reports(arch_env, tmp_path,
                                                  monkeypatch):
    """runner 失联: 显式回执 + 清句柄(不静默吞消息)。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-old",
                                     "executor_type": "cline-sdk"}
    monkeypatch.setattr(
        "topoone_app_architect.agent.execution.exec_bridge._runner",
        lambda path, payload=None, timeout=12.0: None)

    async def _go():
        await proxy_turn({}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    asyncio.run(_go())
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any("失联" in str(m.get("content") or "") for m in msgs)


def test_executor_model_names_cline_live_projection(monkeypatch):
    """内置 cline 的模型校验面 = 实例模型实时投影(cv-259: 落盘快照空 →
    /sessions/{id}/model 误报 400"无可选模型", 与 GET 展示面口径分裂)。"""
    from topoone_app_architect.arch_routes import sessions as s
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "_builtin_cline_models", lambda: [
        {"name": "LMS-a", "model": "a"}, {"name": "LMS-b", "model": "b"}])
    cline = {"id": "cline", "type": "cline-sdk", "config": {"models": []}}
    assert s._executor_model_names(cline) == ["LMS-a", "LMS-b"]
    other = {"id": "ex", "type": "opencode", "config": {"models": [{"name": "x"}]}}
    assert s._executor_model_names(other) == ["x"]
