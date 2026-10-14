"""薄 mock 全链路集成测试(cv-156/157 教训固化)。

历史事故形态: mock 粒度过粗(整段 monkeypatch run_tools_loop/llm_chat_start)
→ 真实函数体丢失(_req_chat_stream 空壳/_ws_send 幻影)测试全绿两天。

本文件纪律: **只 mock 网络边界**——
  - `KbGateway.call`(llm.chat/llm.sync/KB 方法) → 假响应序列
  - `exec_bridge._runner`(runner HTTP)
其余(handle_chat/_req_chat_stream/run_tools_loop/run_arch_tool/propose_task/
confirm_task/commands 直通/守卫)全部真实执行。

Run: cd <repo> && python -m pytest apps/architect/tests/test_chat_pipeline_integration.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import pytest
from fastapi.testclient import TestClient

import topoone_app_architect.ctx as C
import topoone_app_architect.kb_gateway as kb_gateway
import topoone_app_architect.store as store
from topoone_app_architect.server import build_app

WS_PATH = "/api/architect/ws/kb-analysis"


class _FakeGateway:
    """网络边界替身: 按 kb_method 发放脚本化响应; 全部调用留痕。"""

    def __init__(self, sync_script, chat_rid=None):
        self.sync_script = list(sync_script)   # 每次 llm.sync 弹出一个响应
        self.chat_rid = chat_rid               # 非 None = 流式可用(返回 requestId)
        self.calls = []

    def call(self, kb_method: str, timeout=None, **params):
        self.calls.append(kb_method)
        if kb_method == "llm.chat":
            if self.chat_rid:
                return {"requestId": self.chat_rid}
            return None    # 流式不可用 → 走真实降级链(_req_chat_stream 返回 None)
        if kb_method == "llm.sync":
            return {"ok": True,
                    "content": self.sync_script.pop(0) if self.sync_script else ""}
        if kb_method.startswith("map."):
            return "# 组件\n- core (L0, 3 文件)"
        return {"ok": True, "text": "(kb)"}


@pytest.fixture()
def pipeline(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    # 测试环境同样走真实模型解析链——显式配偏好(不依赖已移除的 KB 默认兜底)
    store.CollabConfigStore.set("llm.modelId", "test-model")

    gw = _FakeGateway(sync_script=[])
    monkeypatch.setattr(kb_gateway.KbGateway, "call",
                        lambda self, method, timeout=None, **params:
                        gw.call(method, timeout=timeout, **params))
    client = TestClient(build_app(data_dir=data))
    return client, gw, tmp_path


from tests.ws_helpers import chat as _ws_chat  # 规范化环节六: 收发助手单源
from tests.ws_helpers import recv_until as _recv_until_base


def _recv_until(ws, *types):
    ev, _seen = _recv_until_base(ws, *types)
    return ev


def _chat(ws, content, conv_id=""):
    _ws_chat(ws, content, conv_id=conv_id, kind="generic", title="t",
             messages=[{"role": "user", "content": content}])


def test_full_pipeline_real_bodies_chat_with_tool_round(pipeline):
    """普通对话: 真实 _req_chat_stream(流式不可用)→真实降级→真实工具轮→落库。

    锁定: llm.chat 必须被真实尝试(_req_chat_stream 函数体回归);
    工具轮(map.overview 真实 handler)→ 最终回答落库。"""
    client, gw, _tmp = pipeline
    gw.sync_script = [
        '[TOOL_CALL]{"tool":"map.overview","arguments":{}}[/TOOL_CALL]',
        "根据资产地图, 项目含 core 组件(3 文件)。",
    ]
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, "项目有哪些组件")
            ev = _recv_until(ws, "done")
    assert "core 组件" in ev["content"]
    assert "llm.chat" in gw.calls, "流式入口必须被真实尝试(降级也要先尝试)"
    # 两轮 llm.sync = 工具轮真实发生(round1 工具调用 + round2 结果回喂)
    assert gw.calls.count("llm.sync") == 2
    assert gw.calls[-1] == "llm.sync"
    msgs = store.ConversationsStore.messages(ev["conversationId"], limit=20)
    assistant = [m for m in msgs if m["role"] == "assistant"]
    assert any("core 组件" in m["content"] for m in assistant)


def test_full_pipeline_quick_proxy_passthrough(pipeline, monkeypatch):
    """quick 挡语义升级(定位裁决 2026-09-26): coding 执行器模式=直通对话——
    回合绕过需求/任务体系直达执行器(零任务卡/零需求卡), architect 仅通道代理
    + 上下文包装配。原「任务围栏代落」行为随之退役。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    from topoone_app_architect.agent.execution import proxy
    client, gw, tmp = pipeline
    store.CollabConfigStore.set("agent.executors", json.dumps([
        {"id": "cline", "type": "cline-sdk", "enabled": True, "default": True,
         "config": {"provider_id": "openai-compatible",
                    "models": [{"name": "M1", "model": "m-1", "url": "http://x/v1"}]}},
    ]))
    root = tmp / "proj"
    root.mkdir()
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-it"))
    captured: list = []

    class _FakeSR:
        ok = True
        job_id = "job-qx"
        branch = "proxy/x"
        worktree = str(root)
        session_id = "s"
        base_commit = "sha"
        workspace = "inplace"
        raw = {}
        error = ""

    class _FakeClient:
        def start_implement(self, payload, timeout=20.0):
            captured.append(payload)
            return _FakeSR()

    monkeypatch.setattr(eb, "_client", lambda: _FakeClient())
    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=12.0: {"ok": True})
    import topoone_app_architect.agent.execution.pumps as _pumps_mod

    async def _no_pump(*a, **k):
        return None

    monkeypatch.setattr(_pumps_mod, "run_event_pump", _no_pump)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t",
                                            "analysisMode": "quick"})
    import time as _time
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, "把这个活交给 coding 干", conv_id=conv["id"])
            # 直通终态经 cards.land(conv-message) 承载(不走 done 帧, 见 proxy 模块注记)
            deadline = _time.time() + 10
            cid = conv["id"]
            while _time.time() < deadline:
                msgs_now = store.ConversationsStore.messages(cid, limit=10)
                if any((m.get("meta") or {}).get("kind") == "proxy"
                       for m in msgs_now):
                    break
                _time.sleep(0.2)
    cid = conv["id"]
    # 直通纪律: 零任务卡/零需求卡
    assert store.TasksStore.of_conv(cid) == []
    msgs = store.ConversationsStore.messages(cid, limit=20)
    assert not any((m.get("meta") or {}).get("kind") == "task_card" for m in msgs)
    # 执行器会话已起, 载荷=用户文本+上下文包契约
    assert len(captured) == 1
    assert "把这个活交给 coding 干" in captured[0]["instruction"]
    assert "上下文包(执行契约)" in captured[0]["instruction"]
    assert captured[0]["executorType"] == "cline-sdk"
    assert proxy.proxy_job_of(cid) is not None
    proxy._PROXY_JOBS.pop(cid, None)


def test_full_pipeline_text_confirm_runs_task(pipeline, monkeypatch):
    """文字「确认」直通: 真实 confirm_task→选定链→runner 载荷(带执行器配置)。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    client, gw, tmp = pipeline
    store.CollabConfigStore.set("agent.executors", json.dumps([
        {"id": "cline", "type": "cline-sdk", "enabled": True, "default": True,
         "config": {"provider_id": "openai-compatible",
                    "models": [{"name": "M1", "model": "m-1", "url": "http://x/v1"}]}},
    ]))
    root = tmp / "proj"
    root.mkdir()
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-it"))
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_acceptance_brief", lambda *a, **k: "(简报)")
    impl_payload = {}

    def _fake_runner(path, payload=None, timeout=20.0):
        if path == "/api/implement":
            impl_payload.update(payload or {})
            return {"ok": True, "jobId": "impl-it", "worktree": "/tmp/w",
                    "branch": "task/it", "sessionId": "s"}
        return None

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = store.TasksStore.create({
        "conversationId": conv["id"], "title": "T卡", "instruction": "x",
        "status": "pending_confirm", "executorType": "cline-sdk"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, "确认", conv_id=conv["id"])
            ev = _recv_until(ws, "done")
    assert "已确认任务" in ev["content"]
    assert store.TasksStore.get(t["id"])["status"] == "running"
    assert impl_payload.get("executorId") == "cline"
    # models[0] 回落取全名/模型 id(展示名跨 provider 可重复; _resolve_model 三级匹配)
    assert impl_payload.get("model") == "m-1"
    assert (impl_payload.get("executorConfig") or {}).get("models")


def test_turn_budget_exhaustion_terminates_hang(pipeline, monkeypatch):
    """cv-162 回归: 模型 hang(流式无事件+同步空返回)时回合必须在总预算内
    终止并落 turnError——不再串联 60s 空闲×N 轮 + 191s sync 卡 6.5 分钟。"""
    import time as _t
    import topoone_app_architect.agent.turns.base as turns_base
    import topoone_app_architect.agent.turns.chat as turns_chat
    # M1 拆分: 常量单源在 turns.base, chat.py 导入绑定——patch 两处读取点
    monkeypatch.setattr(turns_base, "_STREAM_IDLE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(turns_chat, "_STREAM_IDLE_TIMEOUT_S", 0.3)
    monkeypatch.setattr(turns_base, "_TURN_BUDGET_S", 1.5)
    monkeypatch.setattr(turns_chat, "_TURN_BUDGET_S", 1.5)
    client, gw, _tmp = pipeline
    gw.chat_rid = "rid-hang"    # 流式"可用"但 ZMQ 永远不来事件 → 每轮 idle
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            t0 = _t.time()
            _chat(ws, "hi")
            conv_id = _recv_until(ws, "chat_start").get("conversationId") or ""
            ev = _recv_until(ws, "error")
            wall = _t.time() - t0
    assert wall < 30, f"回合未在预算内终止: {wall:.1f}s"
    assert "预算" in ev["message"]
    msgs = store.ConversationsStore.messages(conv_id, limit=5)
    assert any((m.get("meta") or {}).get("kind") == "turnError" for m in msgs)


def test_event_bus_emit_typed_and_audited(monkeypatch):
    """B 统一事件出口: 形状单点({type, conversationId, **payload})+审计环+publish 接线。"""
    from topoone_app_architect.agent.collab import sse

    captured = []
    monkeypatch.setattr(sse, "publish", lambda ev: captured.append(ev))
    ev = sse.emit("conv-message", "cv-x", msgId="m1", agent="cline-sdk", kind="task_card")
    assert ev == {"type": "conv-message", "conversationId": "cv-x",
                  "msgId": "m1", "agent": "cline-sdk", "kind": "task_card"}
    assert captured and captured[-1]["type"] == "conv-message"
    assert sse.recent_events(1)[0]["conversationId"] == "cv-x"
    assert sse.EV_TASK == "task" and sse.EV_PROGRESS == "progress"


def test_resolve_call_model_raises_when_unconfigured(monkeypatch):
    """模型解析单源(cv-168 用户裁决): 显式 > architect 偏好(llm.modelId);
    均空 → 抛 ModelNotConfigured 明确报错——KB 默认不得静默接管。"""
    import pytest as _pt
    from topoone_app_architect.agent.cognition import llm
    monkeypatch.setattr(llm, "get_model_preference", lambda: "model-arch-pref")
    assert llm.resolve_call_model("model-explicit") == "model-explicit"
    assert llm.resolve_call_model("") == "model-arch-pref"
    assert llm.resolve_call_model(None) == "model-arch-pref"
    monkeypatch.setattr(llm, "get_model_preference", lambda: "")
    with _pt.raises(llm.ModelNotConfigured):
        llm.resolve_call_model("")
    with _pt.raises(llm.ModelNotConfigured):
        llm.resolve_call_model(None)


def test_probe_context_window_parsers(monkeypatch):
    """探测解析: llama.cpp /props n_ctx 与 LM Studio v0 max_context_length 两种形态。"""
    from topoone_app_architect.agent.cognition import llm

    class _R:
        def __init__(self, body): self._b = json.dumps(body).encode()
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    # llama.cpp /props
    monkeypatch.setattr(llm, "_CTX_CACHE", {})
    monkeypatch.setattr("urllib.request.urlopen",
                        lambda req, timeout=0: _R({"default_generation_settings": {"n_ctx": 262144}}))
    assert llm.probe_context_window("http://h:8082") == 262144
    # LM Studio v0(/props 404 → 回退)
    monkeypatch.setattr(llm, "_CTX_CACHE", {})
    calls = []
    def _fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if "/props" in req.full_url:
            raise OSError("404")
        return _R({"data": [{"id": "other", "max_context_length": 4096},
                            {"id": "qwen3.5-9b-mtp", "max_context_length": 262144}]})
    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    assert llm.probe_context_window("http://h:1234", "qwen3.5-9b-mtp") == 262144
    assert any("/api/v0/models" in u for u in calls)


def test_resolve_context_budget_priority(monkeypatch):
    """上下文预算: 显式 > llm.contextBudget 偏好 > 探测容量−生成预留−余量; 全空 → None。"""
    from topoone_app_architect.agent.cognition import llm
    monkeypatch.setattr(llm, "get_context_budget_preference", lambda: 0)
    monkeypatch.setattr(llm, "get_max_tokens_preference", lambda: None)
    monkeypatch.setattr(llm, "_catalog_entry", lambda mid: {"url": "http://h:8082", "model": "q"})
    monkeypatch.setattr(llm, "probe_context_window", lambda url, hint="": 262144)
    assert llm.resolve_context_budget(8192, "m") == 8192
    assert llm.resolve_context_budget(None, "m") == 262144 - 8192 - 2048   # 261904
    monkeypatch.setattr(llm, "probe_context_window", lambda url, hint="": None)
    assert llm.resolve_context_budget(None, "m") is None
    monkeypatch.setattr(llm, "get_context_budget_preference", lambda: 16384)
    assert llm.resolve_context_budget(None, "m") == 16384


def test_card_round_short_circuit_skips_narration(pipeline):
    """cv-196 收尾短路 + cv-203 卡片独立: 整回合无可见正文 + 全为落卡工具
    → 跳过叙述轮(只烧一轮 llm.sync), 且**不再落合成收尾文本**——需求卡
    (specReady)是独立一条消息, 合成文案 = 与卡片重复的第二条文本(cv-203 裁决)。"""
    client, gw, _tmp = pipeline
    gw.sync_script = [
        '[TOOL_CALL]{"tool":"req.propose","arguments":{"title":"短路验证",'
        '"requirementMd":"目标: 验证落卡轮不再触发叙述轮"}}[/TOOL_CALL]',
    ]
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, "帮我建需求卡：短路验证")
            ev = _recv_until(ws, "done")
    # 落卡轮空文本收尾(cardClosed), 不再合成"需求卡已创建"重复文本
    assert ev.get("content") == "" and ev.get("cardClosed") is True
    msgs = store.ConversationsStore.messages(ev["conversationId"], limit=10)
    assert not [m for m in msgs if m["content"].strip() == "(已调用工具)"]
    # 需求卡独立落流(单条 specReady 卡), 且无第二条重复宣告文本
    specs = [m for m in msgs if (m.get("meta") or {}).get("kind") == "specReady"]
    assert len(specs) == 1
    dupes = [m for m in msgs if m["role"] == "assistant"
             and (m.get("meta") or {}).get("kind") != "specReady"
             and "需求卡已创建" in (m.get("content") or "")]
    assert dupes == [], "落卡轮不得再落合成收尾文本(cv-203)"


# ── 上下文用量记账(cognition/ctx_usage 通用链: 估算/merge_meta/落账/透传) ──

def test_estimate_msgs_tokens_char_ratio():
    from topoone_app_architect.agent.cognition.ctx_usage import (
        CHARS_PER_TOKEN, estimate_msgs_tokens)
    assert CHARS_PER_TOKEN == 2, "口径须与主后端 TokenBudget 一致"
    msgs = [{"role": "system", "content": "x" * 100},
            {"role": "user", "content": "y" * 50},
            {"role": "assistant", "content": ""}]
    assert estimate_msgs_tokens(msgs) == 75
    assert estimate_msgs_tokens([]) == 0
    assert estimate_msgs_tokens(None) == 0


def test_merge_meta_preserves_existing_keys(arch_env):
    assert store.ConversationsStore.merge_meta("cv-not-exist", {"a": 1}) is None
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    assert store.ConversationsStore.merge_meta(conv["id"], {"a": 1}) is not None
    store.ConversationsStore.merge_meta(conv["id"], {"b": {"nested": True}})
    meta = store.ConversationsStore.get(conv["id"])["meta"]
    assert meta["a"] == 1 and meta["b"] == {"nested": True}, "merge 不得覆盖既有键"


def test_record_turn_writes_ctx_usage_fail_soft(arch_env, monkeypatch):
    from topoone_app_architect.agent.cognition import ctx_usage
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    store.ConversationsStore.merge_meta(conv["id"], {"keep": "me"})
    monkeypatch.setattr(ctx_usage, "resolve_budget", lambda mid: 32000)
    ctx_usage.record_turn(conv["id"],
                          [{"role": "user", "content": "z" * 200}], "m1")
    meta = store.ConversationsStore.get(conv["id"])["meta"]
    u = meta["ctxUsage"]
    assert u["used"] == 100 and u["budget"] == 32000 and u["at"] > 0
    assert meta["keep"] == "me", "落账不得覆盖 meta 其余键"
    monkeypatch.setattr(ctx_usage, "resolve_budget", lambda mid: 0)
    ctx_usage.record_turn(conv["id"], [], "")
    assert store.ConversationsStore.get(conv["id"])["meta"]["ctxUsage"]["budget"] == 0


def test_sessions_list_passthrough_meta(client):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    store.ConversationsStore.merge_meta(
        conv["id"], {"ctxUsage": {"used": 7, "budget": 0, "at": 1}})
    rows = client.get("/api/architect/sessions").json()["data"]
    hit = next(r for r in rows if r["id"] == conv["id"])
    assert hit["meta"]["ctxUsage"]["used"] == 7


def test_full_pipeline_proxy_process_events_sse(pipeline, monkeypatch):
    """cv-273 e2e: 直通回合的 runner 过程事件(text/tool)经真实泵 → SSE progress
    (conversationId 键, 无 taskId)——控制条数据链后端实锤。

    复现断点排查(用户实证 cv-268 控制条不显示): 后端形状逐帧可查。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    from topoone_app_architect.agent.collab import sse
    client, gw, tmp = pipeline
    store.CollabConfigStore.set("agent.executors", json.dumps([
        {"id": "cline", "type": "cline-sdk", "enabled": True, "default": True,
         "config": {"models": [{"name": "M1", "model": "m-1",
                                "url": "http://x/v1"}]}}]))
    root = tmp / "proj"
    root.mkdir()
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-it"))

    class _FakeSR:
        ok = True
        job_id = "job-pe"
        branch = "proxy/x"
        worktree = str(root)
        session_id = "sess-native-e2e"
        base_commit = "sha"
        workspace = "inplace"
        raw = {}
        error = ""

    class _FakeClient:
        def start_implement(self, payload, timeout=20.0):
            return _FakeSR()

    monkeypatch.setattr(eb, "_client", lambda: _FakeClient())
    _snap_calls = {"n": 0}

    def _fake_runner(path, payload=None, timeout=12.0):
        if path.endswith("/events"):      # WS 订阅面(无真 runner WS) → 失败回落
            return None
        if path.startswith("/api/implement/job-pe?"):
            _snap_calls["n"] += 1
            if _snap_calls["n"] == 1:
                return {"ok": True, "status": "running", "sessionId": "sess-x",
                        "seq": 3,
                        "events": [
                            {"seq": 1, "kind": "text", "text": "开始分析"},
                            {"seq": 2, "kind": "tool", "toolName": "read_file"},
                            {"seq": 3, "kind": "tool", "toolName": "grep"}]}
            return {"ok": True, "status": "waiting_input", "sessionId": "sess-x",
                    "seq": 3, "events": []}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)

    conv = store.ConversationsStore.create({"kind": "generic", "title": "t",
                                            "analysisMode": "quick"})
    cid = conv["id"]
    import time as _time
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, "分析一下", conv_id=cid)
            deadline = _time.time() + 8
            progs: list = []
            while _time.time() < deadline:
                progs = [e for e in sse.recent_events(200)
                         if e.get("type") == "progress"
                         and e.get("conversationId") == cid]
                if progs and progs[-1].get("toolCount") == 2:
                    break   # 等 grep 工具事件落地(时序鲁棒)
                _time.sleep(0.2)
    progs = [e for e in sse.recent_events(200)
             if e.get("type") == "progress" and e.get("conversationId") == cid]
    assert progs, "过程事件未进 SSE 环(后端发射断链)"
    assert all("taskId" not in p for p in progs), "直通过程帧不应带 taskId(FE 分流键)"
    newest = progs[0]                       # recent_events 新→旧
    assert newest.get("lastTool") == "grep" and newest.get("toolCount") == 2, \
        f"过程帧序列(新→旧): {[(p.get('lastTool'), p.get('toolCount')) for p in progs]}"
    assert newest.get("lastText"), f"newest 帧: {newest}"
    # 过程态(内存)与轮次快照面
    from topoone_app_architect.agent.execution import process_stream as _ps
    assert _ps.proxy_progress(cid).get("toolCount") == 2
