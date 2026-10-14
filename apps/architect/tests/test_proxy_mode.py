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
    """记录 WS 回合帧(cv-259: 每分支必须以 done 收口)。"""

    def __init__(self):
        self.events: list = []

    async def __call__(self, payload):
        self.events.append(payload)

    @property
    def closed(self) -> bool:
        return bool(self.events) and self.events[-1].get("type") == "done"


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

    sn = _Send()
    handled = asyncio.run(proxy_turn(
        {}, _gate(conv), sn, root=str(tmp_path / "proj"),
        project="", executor=EXECUTOR_FIXTURE))

    assert handled is True
    assert sn.closed, "直通回合必须以 WS done 收口(cv-259)"
    _d = sn.events[-1]
    assert "已直通执行器" in _d["content"] and _d.get("messageId")
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
    sn2 = _Send()
    assert asyncio.run(proxy_turn({}, gate2, sn2, root=str(tmp_path / "proj"),
                                  project="", executor=EXECUTOR_FIXTURE)) is True
    # 纯转发静默成功: done(cardClosed) 收口清占位泡(执行器产出经泵+SSE 呈现)
    assert sn2.closed and sn2.events[-1].get("cardClosed") is True
    inputs = [pl for p, pl in captured if p.endswith("/input")]
    assert len(inputs) == 1 and inputs[0]["text"].startswith("补充:")
    assert len([p for p, _ in captured if p == "/api/implement"]) == n_impl


def test_proxy_dirty_repo_warns_and_proceeds(arch_env, tmp_path, monkeypatch,
                                             _isolate_proxy_state):
    """cv-269 软化: 直通=chat 角色(用户逐轮在环, 不强硬保底)——脏工作区
    警告+边界提醒后继续启动; 任务链 dispatch 硬闸不变(自治执行防互踩)。

    根因回归(cv-264): 架构注入文件(TOPO-CONTEXT-TOOLS.md)落盘自弄脏工作区
    → 下轮被自家门禁拒死。已改 instruction 并入(不落盘)+门禁软化。"""
    import subprocess
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    (root / "wip.txt").write_text("其它进程半成品")
    conv = _mk_conv(arch_env, tmp_path)
    starts = _isolate_proxy_state
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), ""))

    sn = _Send()
    assert asyncio.run(proxy_turn({}, _gate(conv), sn, root=str(root),
                                  project="", executor=EXECUTOR_FIXTURE)) is True
    assert sn.closed
    assert len(starts) == 1, "脏区应警告后继续启动(不再硬拒)"
    assert "未提交变更" in starts[0]["instruction"], "执行器侧边界提醒缺失"
    msgs = store.ConversationsStore.messages(conv["id"], limit=10)
    proxy_cards = [m for m in msgs if (m.get("meta") or {}).get("kind") == "proxy"]
    assert any("未提交变更" in (m.get("content") or "") for m in proxy_cards), \
        "用户侧提醒收执缺失"
    # cv-270: 警告并入直通回执单卡(独立警告卡=信息流污染实证 cv-266)
    receipt = [m for m in proxy_cards if "已直通执行器" in (m.get("content") or "")]
    assert receipt and "未提交变更" in receipt[0]["content"], \
        "警告应并入直通回执, 不应独立落卡"
    assert not [m for m in proxy_cards
                if "已直通执行器" not in (m.get("content") or "")
                and "工作区有未提交变更" in (m.get("content") or "")], \
        "独立警告卡不应存在"


def test_proxy_without_executor_explicit_error(arch_env, tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [])
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    sn = _Send()
    handled = asyncio.run(proxy_turn({}, _gate(conv), sn,
                                     root=str(tmp_path / "proj"), project="",
                                     executor={}))
    assert handled is True    # 显式报错收束, 不回落 architect 管线
    assert sn.closed and "未配置可用执行器" in sn.events[-1]["content"]
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

    sn = _Send()
    async def _go():
        await proxy_turn({}, _gate(conv), sn, root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    asyncio.run(_go())
    assert sn.closed, "新开成功也须 done 收口"
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

    sn = _Send()
    async def _go():
        await proxy_turn({}, _gate(conv), sn, root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    asyncio.run(_go())
    assert sn.closed
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


def test_proxy_stream_text_grows_single_card(arch_env, tmp_path,
                                             _isolate_proxy_state):
    """cv-263 流式可见性: text 事件增量落单卡(原位生长), 终态收尾同卡。

    用户实证(cv-261): 直通后 3.5 分钟执行期 UI 零反馈——此前 text 只累积,
    终态才一次性 flush。锁定: ①节流窗口内多段 text → 同一 messageId 原位
    UPDATE(不刷屏); ②SSE conv-message 随更新发出; ③done 收尾余量+后缀
    并入同卡; ④终态清 _PROXY_JOBS。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-px", "executor_type": "cline-sdk"}
    emitted: list = []
    import topoone_app_architect.agent.collab.cards as cards_mod
    import topoone_app_architect.agent.execution.proxy as _px
    orig_flush_ms, _px._PROXY_FLUSH_MS = _px._PROXY_FLUSH_MS, 0
    orig_emit = cards_mod.emit
    cards_mod.emit = lambda cid, mid, agent="", kind="": (
        emitted.append((cid, mid, kind)), orig_emit(cid, mid, agent=agent, kind=kind))
    try:
        on_event, _snap, _lost, _flush = _px._make_handlers(
            conv["id"], "job-px", "cline-sdk")
        on_event({"kind": "text", "text": "第一段 分析开始\n"})
        on_event({"kind": "text", "text": "第二段 依赖图\n"})
        on_event({"kind": "text", "text": "第三段"})
        msgs = store.ConversationsStore.messages(conv["id"], limit=10)
        body = [m for m in msgs if (m.get("meta") or {}).get("kind") == "proxy"]
        assert len(body) == 1, "多段 text 应落同一张卡(原位生长不刷屏)"
        first_id = body[0]["id"]
        for seg in ("第一段", "第二段", "第三段"):
            assert seg in body[0]["content"]
        on_event({"kind": "done", "text": ""})
        msgs3 = store.ConversationsStore.messages(conv["id"], limit=10)
        body3 = [m for m in msgs3 if (m.get("meta") or {}).get("kind") == "proxy"]
        assert len(body3) == 2, "done 后缀独立收尾卡"
        assert "✅ 本轮完成" in body3[0]["content"] and "第三段" in body3[0]["content"]
        assert conv["id"] not in proxy._PROXY_JOBS, "终态清句柄"
        assert any(e[0] == conv["id"] for e in emitted), "SSE conv-message 已通知"
    finally:
        cards_mod.emit = orig_emit
        _px._PROXY_FLUSH_MS = orig_flush_ms


def test_proxy_late_text_after_flush_no_crash(arch_env, tmp_path,
                                              _isolate_proxy_state):
    """cv-264 根因锁定: flush 后迟到/重放的 text 事件不得崩泵。

    用户实证(cv-262): 执行器等待输入(⏸ 后缀并入卡) → flush pop 掉缓冲键 →
    后续 text 事件 KeyError('text') → 泵崩死成僵尸(_PROXY_JOBS 不清) →
    用户续话被转发给死会话, 执行器响应全部黑洞。"""
    conv = _mk_conv(arch_env, tmp_path)
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-lt", "cline-sdk")
    on_event({"kind": "text", "text": "第一段"})
    on_event({"kind": "input_required"})          # flush: pop 掉缓冲键
    on_event({"kind": "text", "text": "迟到段"})   # 旧行为: KeyError 崩泵
    on_event({"kind": "done"})
    msgs = store.ConversationsStore.messages(conv["id"], limit=10)
    body = [m for m in msgs if (m.get("meta") or {}).get("kind") == "proxy"]
    assert len(body) == 3, "等待输入卡 + 迟到段新卡 + 会话结束卡"
    assert "⏸ 执行器有事项需要你确认" in body[0]["content"]
    assert "迟到段" in body[1]["content"] and "✅ 本轮完成" in body[1]["content"]


def test_proxy_pump_crash_cleans_handle(arch_env, tmp_path, monkeypatch,
                                        _isolate_proxy_state):
    """cv-264 僵尸泵根治: 泵核重抛 → _pump 兜底清 _PROXY_JOBS + 落可见回执。

    此前泵核吞异常正常返回 → 兜底不触发 → 死 job 永久占会话, 续话静默黑洞。"""
    import topoone_app_architect.agent.execution.pumps as _pumps_mod

    async def _boom(**kw):
        raise RuntimeError("回调崩了(模拟 KeyError 传播)")

    monkeypatch.setattr(_pumps_mod, "run_event_pump", _boom)
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-z", "executor_type": "cline-sdk"}
    import asyncio as _aio

    async def _drive():
        proxy._start_pump(conv["id"], "job-z", "cline-sdk")
        await _aio.sleep(0.01)   # 泵协程调度: boom → 兜底清句柄+落回执

    _aio.run(_drive())
    assert conv["id"] not in proxy._PROXY_JOBS, "泵崩溃后句柄必须清理"
    msgs = store.ConversationsStore.messages(conv["id"], limit=10)
    assert any("事件泵异常退出" in (m.get("content") or "") for m in msgs), \
        "泵崩溃须落可见回执(用户不蒙在鼓里)"


# ── cv-266 直通历史上下文(脉络注入/digest 接线/MCP 默认接线) ──────────────

_MCP_ENV = {"topoone_app_architect.agent.execution.exec_bridge.ARCH_BASE":
            "http://127.0.0.1:3470"}


def test_history_brief_injected_into_start(arch_env, tmp_path, monkeypatch,
                                           _isolate_proxy_state):
    """有历史 → start instruction 含脉络段(排除本轮 user); 无历史 → 不含。"""
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    # 预置两轮历史
    eb_ref = None
    from topoone_app_architect.agent.execution import exec_bridge as _eb
    _eb._append(conv["id"], "user", "评估一下项目进展")
    _eb._append(conv["id"], "assistant", "已完成评估, 共 3 个模块",
                msg_meta={"kind": "proxy"})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path / "arch"))

    asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=EXECUTOR_FIXTURE))
    assert len(starts) == 1
    instr = starts[0]["instruction"]
    assert "此前的对话记录" in instr, "历史脉络段未注入"
    assert "评估一下项目进展" in instr
    assert "把日志清理脚本写一下" not in instr.split("此前的对话记录")[1], \
        "本轮 user 消息不应出现在脉络里"


def test_history_brief_cap_zero_off(arch_env, tmp_path, monkeypatch,
                                    _isolate_proxy_state):
    """执行器 config historyContextChars=0 → 关闭注入。"""
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    from topoone_app_architect.agent.execution import exec_bridge as _eb
    _eb._append(conv["id"], "user", "历史轮次")
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    ex = dict(EXECUTOR_FIXTURE, config={"rulesMd": "# r",
                                        "historyContextChars": 0})
    asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=ex))
    assert "此前对话脉络" not in starts[0]["instruction"]
    assert "把日志清理脚本写一下" in starts[0]["instruction"], "当前消息仍在"


def test_digest_wired_into_start_and_forward(arch_env, tmp_path, monkeypatch,
                                             _isolate_proxy_state):
    """digest(语境摘要, 既有载荷)在直通分支不再被丢弃: start 并入 instruction,
    活跃 job 随 /input 携带。"""
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    ex = dict(EXECUTOR_FIXTURE, config={"rulesMd": "# r", "historyContextChars": 0})
    asyncio.run(proxy_turn({"digest": "摘要: 前情提要ABC"}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=ex))
    assert "前情提要ABC" in starts[0]["instruction"]
    # 活跃 job 转发
    captured: list = []
    inputs: list = []

    def fake_runner(path, payload=None, timeout=12.0):
        captured.append((path, payload))
        if path.startswith("/api/implement/") and path.endswith("/input"):
            inputs.append(payload)
            return {"ok": True}
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-px", "branch": "b",
                    "worktree": payload["root"], "sessionId": "s",
                    "baseCommit": "sha"}
        return {"ok": True, "status": "running"}

    from topoone_app_architect.agent.execution import exec_bridge as _eb
    monkeypatch.setattr(_eb, "_runner", fake_runner)
    asyncio.run(proxy_turn({"digest": "摘要: 续话语境XYZ"}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=ex))
    assert inputs and "续话语境XYZ" in inputs[-1]["text"], "digest 未随 /input 转发"


def test_mcp_default_wired_and_user_override(arch_env, tmp_path, monkeypatch,
                                             _isolate_proxy_state):
    """MCP 默认接线: cline=list(McpServerSpec)/opencode=dict; 用户同名自配优先;
    codex 不注入不告知(不虚报能力)。"""
    from topoone_app_architect.agent.execution import proxy as _px
    # cline list 形状 + 工具告知文件
    merged = _px._merge_mcp_servers({}, "cline-sdk")
    assert isinstance(merged, list) and merged[0]["name"] == "topo-architect"
    assert merged[0]["url"].endswith("/mcp")
    # 用户自配优先(不重复)
    user = [{"name": "topo-architect", "url": "http://custom/mcp"},
            {"name": "other", "url": "http://x"}]
    m2 = _px._merge_mcp_servers({"mcp_servers": user}, "cline-sdk")
    assert m2 == user
    # opencode dict 形状 + 同名覆盖
    m3 = _px._merge_mcp_servers(
        {"mcp_servers": {"topo-architect": {"url": "http://y"}}}, "opencode")
    assert m3["topo-architect"]["url"] == "http://y"
    # codex: 无 MCP 面
    assert _px._merge_mcp_servers({}, "codex") is None
    assert _px._mcp_tools_brief("cv-1", None) == ""

    # start 载荷端到端: cline 带 mcp_servers + TOPO-CONTEXT-TOOLS.md 告知
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    ex = dict(EXECUTOR_FIXTURE, config={"rulesMd": "# r", "historyContextChars": 0})
    asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=ex))
    p = starts[0]
    # 2610 P3: 注入落 executorConfig.mcp_servers(runner 唯一读取面; 顶层已退役)
    mcp_in_cfg = p["executorConfig"].get("mcp_servers")
    assert isinstance(mcp_in_cfg, list)
    assert mcp_in_cfg[0]["name"] == "topo-architect"
    assert "mcp_servers" not in p
    assert "workspaceFiles" not in p or not [
        f for f in p["workspaceFiles"] if f["path"] == "TOPO-CONTEXT-TOOLS.md"
    ], "工具告知不得再落盘(cv-269: 融合模式自弄脏工作区)"
    assert f'ctx.get(conversation="{conv["id"]}")' in p["instruction"]


# ── cv-267 对话回合制(sessionRole=chat 端到端) ───────────────────────────

def test_start_payload_carries_session_role_chat(arch_env, tmp_path, monkeypatch,
                                                 _isolate_proxy_state):
    """直通 start 载荷带 sessionRole=chat(runner 据此走对话回合制)。"""
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=EXECUTOR_FIXTURE))
    assert starts[0].get("sessionRole") == "chat"


def test_pump_turn_done_keeps_handle_and_reports(arch_env, tmp_path,
                                                 _isolate_proxy_state):
    """chat turn_done: 落"回答已结束"卡但**不清句柄**(作业保活, 续话直达)。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-td", "executor_type": "cline-sdk"}
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-td", "cline-sdk")
    on_event({"kind": "text", "text": "回答正文"})
    on_event({"kind": "turn_done"})
    msgs = store.ConversationsStore.messages(conv["id"], limit=10)
    tail = msgs[-1]
    assert "本轮回答已结束" in tail["content"]
    assert proxy.proxy_job_of(conv["id"]) is not None, "turn_done 非终态, 句柄保留"


def test_pump_input_required_copy(arch_env, tmp_path, _isolate_proxy_state):
    """chat input_required 文案: 有事项需确认(替代任务味"等待你的输入")。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-ir", "executor_type": "cline-sdk"}
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-ir", "cline-sdk")
    on_event({"kind": "text", "text": "请选择方案"})
    on_event({"kind": "input_required"})
    msgs = store.ConversationsStore.messages(conv["id"], limit=10)
    assert "有事项需要你确认" in msgs[-1]["content"]


def test_hint_whitelist_passes_system_prompt(arch_env, monkeypatch):
    """cv-267: 执行器配置 system_prompt 经 hint 白名单透传(接通断裂通道)。"""
    import topoone_app_architect.arch_routes.agent_executors as ae
    from topoone_app_architect.agent.execution.exec_bridge import (
        executor_hint_by_id)
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-sp", "type": "cline-sdk", "enabled": True, "default": True,
         "config": {"system_prompt": "自定义人格", "rulesMd": "# r"}}])
    hint = executor_hint_by_id("ex-sp") or {}
    assert (hint.get("executorConfig") or {}).get("system_prompt") == "自定义人格"


def test_pump_turn_done_folds_with_real_tool_count(arch_env, tmp_path,
                                                   _isolate_proxy_state):
    """cv-270 折叠快照: turn_done → folded SSE(toolCount=本轮环长) + 内存清空。

    用户实证(cv-266): "本轮共 0 次工具调用"——toolCount 依赖 progress 报数,
    而 cline 只发 tool 事件 → 恒 0。修复后 tool 自计数(取大) + 折叠快照。"""
    from topoone_app_architect.agent.execution import process_stream as _ps
    emitted: list = []
    from topoone_app_architect.agent.collab import sse as _sse
    orig = _sse.emit
    _sse.emit = lambda t, cid, **kw: emitted.append((t, cid, kw))
    try:
        conv = _mk_conv(arch_env, tmp_path)
        proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-f", "executor_type": "cline-sdk"}
        on_event, _snap, _lost, _flush = proxy._make_handlers(
            conv["id"], "job-f", "cline-sdk")
        on_event({"kind": "tool", "toolName": "read_file"})
        on_event({"kind": "tool", "toolName": "edit_file"})
        on_event({"kind": "tool", "toolName": "run_command"})
        assert _ps.proxy_progress(conv["id"])["toolCount"] == 3, "tool 自计数"
        on_event({"kind": "turn_done"})
        # 折叠快照: folded + 本轮环长; 过程态清空(下一轮从零)
        folds = [kw for t, _c, kw in emitted
                 if t == "progress" and kw.get("folded")]
        assert folds and folds[-1]["toolCount"] == 3, \
            "折叠快照 toolCount 应为本轮真实环长"
        assert _ps.proxy_progress(conv["id"]) == {}, "折叠后过程态应清空"
    finally:
        _sse.emit = orig
        _ps.proxy_clear(conv["id"])


def test_pump_long_output_head_preserved(arch_env, tmp_path, _isolate_proxy_state):
    """cv-271 头部截断回归: 缓冲即交付物, >6000 字符不丢开头。

    用户实证(cv-266): buf[-6000:] 尾部保留使长报告开头被逐步挤掉
    (m-2117 落库 6013 字符, HEAD 是 ASCII 图中间)。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-lg", "executor_type": "cline-sdk"}
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-lg", "cline-sdk")
    head = "报告开头：项目全景评估。\n"
    on_event({"kind": "text", "text": head})
    on_event({"kind": "text", "text": "填充" * 5000})   # 10000 字符
    on_event({"kind": "turn_done"})
    msgs = store.ConversationsStore.messages(conv["id"], limit=10)
    body = [m for m in msgs if (m.get("meta") or {}).get("kind") == "proxy"]
    full = body[0]["content"]
    assert full.startswith("报告开头"), "头部必须完整保留"
    assert len(full) > 10000, "全文累积(无 6000 上限)"
    assert "✅ 本轮回答已结束" in full


# ── cv-273 停止/复活/steer ─────────────────────────────────────────────

def test_session_ref_persisted_on_snapshot(arch_env, tmp_path):
    """复活链①: 泵快照回写 session_ref → 会话行持久化(变化才写)。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-sr", "executor_type": "cline-sdk"}
    on_event, on_snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-sr", "cline-sdk")
    on_snap({"sessionId": "sess-native-1"})
    row = store.ConversationsStore.get(conv["id"])
    assert row["sessionRef"] == "sess-native-1", "sessionRef 应持久化到会话行"


def test_start_payload_carries_session_ref_for_revive(arch_env, tmp_path,
                                                      monkeypatch,
                                                      _isolate_proxy_state):
    """复活链②: 会话行有 sessionRef → start 载荷携带(runner 复活原生会话)。"""
    starts = _isolate_proxy_state
    conv = _mk_conv(arch_env, tmp_path)
    store.ConversationsStore.update(conv["id"], {"sessionRef": "sess-native-9"})
    conv = store.ConversationsStore.get(conv["id"])   # cv-262 同款: 门禁重读新行
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "proj"), ""))
    asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=EXECUTOR_FIXTURE))
    assert starts[0].get("sessionRef") == "sess-native-9"


def test_forward_input_carries_steer_flag(arch_env, tmp_path, monkeypatch,
                                          _isolate_proxy_state):
    """cv-273 steer 消费: 转发 /input 带 steer=true——runner 按能力分流
    (cline 直达 turn/steer; 不支持回落排队, a64 语义 runner 侧已有)。"""
    inputs: list = []

    def fake_runner(path, payload=None, timeout=12.0):
        if path.endswith("/input"):
            inputs.append(payload)
            return {"ok": True}
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-px", "branch": "b",
                    "worktree": payload["root"], "sessionId": "s",
                    "baseCommit": "sha"}
        return {"ok": True, "status": "running"}

    from topoone_app_architect.agent.execution import exec_bridge as _eb
    monkeypatch.setattr(_eb, "_runner", fake_runner)
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-px",
                                     "executor_type": "cline-sdk"}
    asyncio.run(proxy_turn({}, _gate(conv), _Send(),
                           root=str(tmp_path / "proj"), project="",
                           executor=EXECUTOR_FIXTURE))
    assert inputs and inputs[-1].get("steer") is True


def test_proxy_stop_helper_aborts_runner(arch_env, tmp_path, monkeypatch):
    """cv-273 停止: 活跃句柄 → runner /abort; aborted 事件经泵清句柄;
    会话行 sessionRef 保留(恢复语义)。"""
    aborts: list = []
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-stop",
                                     "executor_type": "cline-sdk",
                                     "session_ref": "sess-keep"}
    store.ConversationsStore.update(conv["id"], {"sessionRef": "sess-keep"})

    def fake_runner(path, payload=None, timeout=12.0):
        if path.endswith("/abort"):
            aborts.append(path)
            return {"ok": True}
        return {"ok": True, "status": "running"}

    from topoone_app_architect.agent.execution import exec_bridge as _eb
    monkeypatch.setattr(_eb, "_runner", fake_runner)
    r = proxy.proxy_stop(conv["id"])
    assert r["ok"] and r["job_id"] == "job-stop"
    assert aborts, "runner /abort 未调用"
    # 泵收 aborted 终态(清句柄)——会话行 sessionRef 保留(恢复语义)
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-stop", "cline-sdk")
    on_event({"kind": "aborted"})
    assert proxy.proxy_job_of(conv["id"]) is None
    assert store.ConversationsStore.get(conv["id"])["sessionRef"] == "sess-keep"


def test_proxy_stop_without_active_job(arch_env, tmp_path):
    r = proxy.proxy_stop("cv-none")
    assert not r["ok"] and "无进行中" in r["error"]


def test_fold_snapshot_carries_turn_count(arch_env, tmp_path,
                                          _isolate_proxy_state):
    """折叠快照含累计轮次(turn_done 计数, 跨折叠)。"""
    from topoone_app_architect.agent.execution import process_stream as _ps
    conv = _mk_conv(arch_env, tmp_path)
    on_event, _snap, _lost, _flush = _ps and proxy._make_handlers(
        conv["id"], "job-tc", "cline-sdk")
    on_event({"kind": "tool", "toolName": "t1"})
    on_event({"kind": "turn_done"})
    on_event({"kind": "turn_done"})   # 边界: 连续 turn_done 轮次累计
    emitted: list = []
    # 直接断言模块态计数
    assert _ps._PROXY_TURNS.get(conv["id"], 0) == 2


def test_proxy_state_endpoint_shape(arch_env, tmp_path):
    """cv-275: proxy_state 查询——活跃句柄+会话行 sessionRef(刷新安全真相源)。"""
    conv = _mk_conv(arch_env, tmp_path)
    st = proxy.proxy_state(conv["id"])
    assert st["active"] is False and st["sessionRef"] == ""
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-st", "executor_type": "cline-sdk",
                                     "session_ref": "sess-x"}
    store.ConversationsStore.update(conv["id"], {"sessionRef": "sess-x"})
    st2 = proxy.proxy_state(conv["id"])
    assert st2 == {"active": True, "jobId": "job-st", "state": "running",
                   "executorType": "cline-sdk", "sessionRef": "sess-x",
                   "queued": 0}   # F5b: 调度排队位次(无=0)


def test_job_state_axis_turn_done_marks_idle(arch_env, tmp_path,
                                             _isolate_proxy_state):
    """cv-285f 状态轴: 回合完成(turn_done)=idle——句柄保活≠执行中。

    FE JobCard 经 proxy_state.state 渲染, chat 回合制作业完成后
    不再恒显「执行中」; 下一轮活动事件(text/tool)回 running。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-ax", "executor_type": "cline-sdk",
                                     "state": "running"}
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-ax", "cline-sdk")
    on_event({"kind": "text", "text": "执行中输出"})
    assert proxy.proxy_state(conv["id"])["state"] == "running"
    on_event({"kind": "turn_done"})
    st = proxy.proxy_state(conv["id"])
    assert st["state"] == "idle" and st["active"] is True   # 保活但非执行中
    assert proxy.proxy_job_of(conv["id"]) is not None       # 句柄仍保留
    on_event({"kind": "text", "text": "下一轮输出"})
    assert proxy.proxy_state(conv["id"])["state"] == "running"


def test_job_state_axis_input_required_marks_idle(arch_env, tmp_path,
                                                  _isolate_proxy_state):
    """cv-285f 状态轴: NEED_INPUT=input_required 也是 idle(等待用户)。"""
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-ir2", "executor_type": "cline-sdk",
                                     "state": "running"}
    on_event, _snap, _lost, _flush = proxy._make_handlers(
        conv["id"], "job-ir2", "cline-sdk")
    on_event({"kind": "input_required"})
    assert proxy.proxy_state(conv["id"])["state"] == "idle"


def test_proxy_stop_dispatch_by_job_status(arch_env, tmp_path, monkeypatch):
    """cv-275 停止分型: running→abort(暂停语义) / 空闲→finish(结束会话)。"""
    calls: list = []

    def fake_runner(path, payload=None, timeout=12.0):
        calls.append(path)
        if path.endswith("/abort"):
            return {"ok": True}
        if path.endswith("/finish"):
            return {"ok": True}
        return {"ok": True, "status": "running"}

    from topoone_app_architect.agent.execution import exec_bridge as _eb
    monkeypatch.setattr(_eb, "_runner", fake_runner)
    conv = _mk_conv(arch_env, tmp_path)
    proxy._PROXY_JOBS[conv["id"]] = {"job_id": "job-dd", "executor_type": "cline-sdk"}
    r1 = proxy.proxy_stop(conv["id"])
    assert r1["ok"] and r1["action"] == "abort" and any(
        p.endswith("/abort") for p in calls), "执行中应走 abort(暂停)"
    # 空闲(waiting_input)
    def idle_runner(path, payload=None, timeout=12.0):
        calls.append(path)
        if path.endswith("/abort"):
            return {"ok": True}
        if path.endswith("/finish"):
            return {"ok": True}
        return {"ok": True, "status": "waiting_input"}
    monkeypatch.setattr(_eb, "_runner", idle_runner)
    r2 = proxy.proxy_stop(conv["id"])
    assert r2["ok"] and r2["action"] == "finish" and any(
        p.endswith("/finish") for p in calls), "空闲应走 finish(结束会话)"


# ── 2610 统一模型: 直通判定/生效执行器单源 ─────────────────────────────

def test_uses_direct_channel_matrix(arch_env, tmp_path):
    """路由分支判定: 绑定 coding→True / architect 显式→False / legacy quick→True。"""
    from topoone_app_architect.agent.execution.exec_bridge import (
        effective_executor_id, uses_direct_channel)

    def _c(**kw):
        return kw
    # 绑定 coding 执行器 → 直通, 生效 id=绑定
    assert uses_direct_channel(_c(executorId="cline")) is True
    assert effective_executor_id(_c(executorId="cline")) == "cline"
    # 显式 architect(换绑落点, 粘滞) → 分析管线, 不走 legacy 回落
    assert uses_direct_channel(_c(executorId="architect", analysisMode="quick")) is False
    assert effective_executor_id(_c(executorId="architect")) == ""
    # 空 + legacy quick → 直通, 生效 id=注册表默认 coding 执行器(读侧兼容)
    assert uses_direct_channel(_c(analysisMode="quick")) is True
    _def = effective_executor_id(_c(analysisMode="quick"))
    assert _def and _def != "architect"
    # 空 + 无 legacy → 分析管线
    assert uses_direct_channel(_c()) is False
    assert effective_executor_id(_c()) == ""


# ── 2610 P1/P3: workState 状态轴 + MCP 注入 executorConfig ────────────

def test_entry_mark_syncs_work_state(arch_env, tmp_path):
    """P1: 直通状态轴驱动 workState——idle(回合收束)回落, running(新回合)置位。"""
    from topoone_app_architect.agent.execution import proxy as _px
    from topoone_app_architect import store
    conv = _mk_conv(arch_env, tmp_path)
    cid = conv["id"]
    _px._PROXY_JOBS[cid] = {"job_id": "j-ws", "executor_type": "cline-sdk",
                            "state": "running"}
    try:
        _px._entry_mark(cid, "j-ws", "idle")
        assert store.ConversationsStore.get(cid)["workState"] == "architect", \
            "回合收束(等待输入)应回落 workState"
        _px._entry_mark(cid, "j-ws", "running")
        assert store.ConversationsStore.get(cid)["workState"] == "running"
        _px._entry_mark(cid, "j-ws", "running")   # 状态不变零写(幂等)
    finally:
        _px._PROXY_JOBS.pop(cid, None)


def test_proxy_start_injects_mcp_into_executor_config(arch_env, tmp_path,
                                                      monkeypatch, _isolate_proxy_state):
    """P3: 默认 MCP 落 executorConfig.mcp_servers(runner 适配器唯一读取面;
    原 payload 顶层字段被 implement 忽略 → cline 从未收到 topo-architect)。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    monkeypatch.setattr(eb, "executor_hint_by_id", lambda eid, c=None: {
        "executorId": "cline", "executorType": "cline-sdk",
        "executorConfig": {"model_id": "m", "models": [
            {"name": "m", "model": "m", "url": "http://x/v1"}]},
        "model": "m"})
    conv = _mk_conv(arch_env, tmp_path)

    async def _go():
        await proxy_turn({}, _gate(conv), _Send(), root=str(tmp_path / "proj"),
                         project="", executor=EXECUTOR_FIXTURE)
    asyncio.run(_go())
    p = _isolate_proxy_state[0]
    mcp = p["executorConfig"].get("mcp_servers")
    assert isinstance(mcp, list) and any(
        e.get("name") == "topo-architect" for e in mcp), \
        "cline 形状(list)应含默认 topo-architect 服务"
    assert "mcp_servers" not in p, "顶层 payload.mcp_servers 已退役(runner 不读)"


def test_recover_sweep_resets_stale_work_state(arch_env, tmp_path):
    """P1: 重启对账——workState=running 且无任务/无直通句柄 → 回落。"""
    from topoone_app_architect.agent.execution import recover as _rc
    from topoone_app_architect import store
    conv = _mk_conv(arch_env, tmp_path)
    cid = conv["id"]
    store.ConversationsStore.set_work_state(cid, "running")
    n = _rc.recover_sweep()
    assert n >= 1
    assert store.ConversationsStore.get(cid)["workState"] == "architect"


def test_entry_mark_idle_releases_scheduler_slot(arch_env, tmp_path, monkeypatch):
    """F5a 裁决A: 回合收束(idle)让坑——调度槽释放, 同 root 排队会话可续跑。"""
    from topoone_app_architect.agent.execution import proxy as _px
    from topoone_app_architect.agent.execution import executor_scheduler as _sched
    conv = _mk_conv(arch_env, tmp_path)
    cid = conv["id"]
    _px._PROXY_JOBS[cid] = {"job_id": "j-slot", "executor_type": "cline-sdk",
                            "state": "running"}
    _sched.register("/w-mark", cid, "cline", "j-slot")
    try:
        _px._entry_mark(cid, "j-slot", "idle")
        assert _sched.state_of_conv(cid)["state"] == "idle", \
            "idle(等待输入)应释放调度槽(裁决A: 等待输入让坑)"
        _px._entry_mark(cid, "j-slot", "running")   # 幂等: 无槽零动作
    finally:
        _px._PROXY_JOBS.pop(cid, None)
        _sched.stop_conv("/w-mark", cid)


def test_mcp_tools_brief_project_and_naming():
    """2610 cv-12/14 统筹升级: brief 含 map.*/project 内联/命名形态说明。"""
    from topoone_app_architect.agent.execution.proxy_ctx import _mcp_tools_brief
    mcp = [{"name": "topo-architect", "url": "http://x/mcp"}]
    b = _mcp_tools_brief("cv-x", mcp, "proj-1")
    assert "map.overview" in b and "map.assets" in b and "ctx.get" in b
    assert 'project="proj-1"' in b, "projectId 应内联(免执行器摸索)"
    assert "topo-architect__" in b and "topo-architect_" in b, "命名形态说明"
    b2 = _mcp_tools_brief("cv-x", mcp, "")
    assert "一律传" not in b2, "无 pid 时省略 project 行"
    assert _mcp_tools_brief("cv-x", [{"name": "other"}]) == ""
    assert "topo-architect MCP 已接线" in _mcp_tools_brief(
        "cv-x", {"topo-architect": {"url": "u"}}), "dict 形状(opencode)同源"


def test_proxy_stop_mode_override(arch_env, monkeypatch, _isolate_proxy_state):
    """2610 cv-15: mode 按钮语义显式覆盖——running 态允许直接 finish
    (任务卡按钮跟随状态: idle 仅结束会话, running=暂停+结束)。"""
    from topoone_app_architect.agent.execution import proxy_state as _pst
    calls: list = []

    def fake_runner(path, body, timeout):
        calls.append(path)
        if path.endswith("/api/implement/j-mo"):
            return {"status": "running"}          # runner 侧真在跑
        return {"ok": True}                       # abort/finish 调用
    monkeypatch.setattr(_pst.eb if hasattr(_pst, "eb") else __import__(
        "topoone_app_architect.agent.execution.exec_bridge",
        fromlist=["_runner"]), "_runner", fake_runner)
    _pst.PROXY_JOBS["cv-mo"] = {"job_id": "j-mo", "executor_type": "cline-sdk",
                                "state": "running"}
    try:
        r = _pst.proxy_stop("cv-mo", mode="finish")   # running 但显式结束
        assert r.get("ok") and r.get("action") == "finish"
        assert any(p.endswith("/finish") for p in calls), "finish 应显式直达"
        r2 = _pst.proxy_stop("cv-mo", mode="abort")   # 缺省自动分型被覆盖为 abort
        assert r2.get("action") == "abort"
    finally:
        _pst.PROXY_JOBS.pop("cv-mo", None)
