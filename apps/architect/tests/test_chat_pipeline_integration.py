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

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.kb_gateway as kb_gateway
import topoone_app_architect.arch_routes.store as store
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


def test_full_pipeline_task_fence_autoland(pipeline):
    """任务围栏代落: 真实 extract_task_fence→propose_task→执行器选定链
    (注册表默认 cline → type+id 同源)→任务卡落流。"""
    client, gw, _tmp = pipeline
    store.CollabConfigStore.set("agent.executors", json.dumps([
        {"id": "cline", "type": "cline-sdk", "enabled": True, "default": True,
         "config": {"provider_id": "openai-compatible",
                    "models": [{"name": "M1", "model": "m-1", "url": "http://x/v1"}]}},
    ]))
    gw.sync_script = [
        '好的，我将该任务整理如下：\n```task\n{"title": "集成验证任务",'
        ' "instruction": "编写冒烟测试覆盖主流程"}\n```',
    ]
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t",
                                            "analysisMode": "quick"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, "把这个活交给 coding 干", conv_id=conv["id"])
            ev = _recv_until(ws, "done")
    tasks = store.TasksStore.of_conv(ev["conversationId"])
    assert len(tasks) == 1
    assert tasks[0]["status"] == "pending_confirm"
    assert tasks[0]["executorType"] == "cline-sdk"
    assert tasks[0]["executorId"] == "cline"     # id/配置同源(cv-158 回归)
    msgs = store.ConversationsStore.messages(ev["conversationId"], limit=20)
    assert any((m.get("meta") or {}).get("kind") == "task_card" for m in msgs)


def test_full_pipeline_text_confirm_runs_task(pipeline, monkeypatch):
    """文字「确认」直通: 真实 confirm_task→选定链→runner 载荷(带执行器配置)。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
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
    assert impl_payload.get("model") == "M1"
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
