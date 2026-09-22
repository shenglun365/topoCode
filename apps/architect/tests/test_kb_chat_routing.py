"""_handle_kb_chat v2 subagent 路由分支特征测试(P0 契约固化)。

锁定混合触发路由的外显行为——P2 编排器重构以本文件为验收基准:
  - 归档会话 → error 事件(只读闸), 零 LLM
  - attachTo=taskId(活跃任务) → 定向转达回执(➡️/📥), 零 LLM, 提前收尾
  - attachTo 指向非活跃任务 → 落回 architect 自由对话
  - agent=executor 且活跃任务 executorType 匹配 → 转达
  - agent=executor 但仅 pending_confirm 任务 → 不吸收输入 → architect 对话
  - agent=executor 无活跃任务 → 注入指派契约走 architect 回合(评估建卡)
  - 缺省 → architect 自由对话(注入通用 agent 路由契约), user/assistant 落库

Run: cd <repo> && python -m pytest apps/architect/tests/test_kb_chat_routing.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.req_agent as req_agent
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.server import build_app

WS_PATH = "/api/architect/ws/kb-analysis"


def _client(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)
    captured = {"msgs": None, "calls": 0}

    def _fake_loop(msgs, **kw):
        captured["calls"] += 1
        captured["msgs"] = msgs
        return {"content": "ok-reply"}

    monkeypatch.setattr(req_agent, "run_tools_loop", _fake_loop)
    return TestClient(build_app(data_dir=data)), captured


def _recv_until(ws, *types):
    seen = []
    while True:
        ev = ws.receive_json()
        seen.append(ev["type"])
        if ev["type"] in types:
            return ev, seen


def _mk_task(conv_id, status="running", executor_type="opencode"):
    return store.TasksStore.create({
        "conversationId": conv_id, "title": "T", "instruction": "x",
        "status": status, "executorType": executor_type})


def _chat(ws, **extra):
    payload = {"type": "chat", "kind": "generic", "title": "t",
               "conversationId": "", "messages": [{"role": "user", "content": "hi"}]}
    payload.update(extra)
    ws.send_json(payload)


# ── 归档只读闸 ────────────────────────────────────────────────────────

def test_archived_session_rejects_chat(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "归档",
                                            "status": "archived"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"])
            err, seen = _recv_until(ws, "error")
            assert "归档" in err.get("message", ""), err
    assert captured["calls"] == 0, "归档闸必须在 LLM 前拦截"
    assert store.ConversationsStore.messages(conv["id"]) == []


# ── attachTo 定向转达 ────────────────────────────────────────────────

def test_attach_to_active_task_transfers(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    task = _mk_task(conv["id"], status="running")
    forwarded = {}

    def _fake_input(task_id, text):
        forwarded["task_id"], forwarded["text"] = task_id, text
        return {"ok": True, "queued": False}

    monkeypatch.setattr(eb, "task_input", _fake_input)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], attachTo=task["id"])
            done, _seen = _recv_until(ws, "done")
            assert "已转达" in done.get("content", ""), done
    assert forwarded == {"task_id": task["id"], "text": "hi"}
    assert captured["calls"] == 0, "定向转达不得进 LLM 回合"
    roles = [m["role"] for m in store.ConversationsStore.messages(conv["id"])]
    assert "assistant" in roles, "转达回执应落库"


def test_attach_to_transfer_queued_reply(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, _ = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    task = _mk_task(conv["id"], status="waiting_input")
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: {"ok": True, "queued": True})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], attachTo=task["id"])
            done, _ = _recv_until(ws, "done")
            assert "已排队" in done.get("content", ""), done


def test_attach_to_transfer_failure_reply(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    task = _mk_task(conv["id"], status="running")
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: {"ok": False, "error": "runner 不可达"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], attachTo=task["id"])
            done, _ = _recv_until(ws, "done")
            assert "转达失败" in done.get("content", ""), done
    assert captured["calls"] == 0


def test_attach_to_stale_task_falls_to_architect(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    task = _mk_task(conv["id"], status="cancelled")     # 非活跃 → 不转达
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], attachTo=task["id"])
            done, _ = _recv_until(ws, "done")
            assert done.get("content") == "ok-reply", "应落回 architect 对话"
    assert captured["calls"] == 1


# ── agent 显式指派 ───────────────────────────────────────────────────

def test_agent_pick_matching_task_transfers(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    _mk_task(conv["id"], status="running", executor_type="opencode")
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: {"ok": True, "queued": False})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], agent="opencode")
            done, _ = _recv_until(ws, "done")
            assert "已转达" in done.get("content", ""), done
    assert captured["calls"] == 0


def test_agent_pick_pending_confirm_not_absorbed(tmp_path, monkeypatch):
    """待确认任务不吸收输入——引导用户确认/取消, 本轮走 architect。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    _mk_task(conv["id"], status="pending_confirm", executor_type="opencode")
    forwarded = []
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: forwarded.append(tid) or {"ok": True})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], agent="opencode")
            done, _ = _recv_until(ws, "done")
            assert done.get("content") == "ok-reply"
    assert forwarded == [], "pending_confirm 任务不得吸收输入"
    assert captured["calls"] == 1


def test_agent_pick_no_task_injects_assign_contract(tmp_path, monkeypatch):
    """显式指派无活跃任务 → 注入指派契约走 architect 回合(评估后建卡)。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"], agent="cline")
            done, _ = _recv_until(ws, "done")
            assert done.get("content") == "ok-reply"
    assert captured["calls"] == 1
    msgs = captured["msgs"]
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    assign = [s for s in systems if "subagent 指派" in s]
    assert assign, f"应注入指派契约: {[s[:60] for s in systems]}"
    assert "cline" in assign[0] and "task.propose" in assign[0]


# ── 缺省: architect 自由对话 ─────────────────────────────────────────

def test_default_free_chat_persists_and_injects_routing_contract(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conversationId=conv["id"])
            done, _ = _recv_until(ws, "done")
            assert done.get("conversationId") == conv["id"]
            assert done.get("content") == "ok-reply"
    msgs = store.ConversationsStore.messages(conv["id"])
    roles = [(m["role"], (m.get("agent") or "")) for m in msgs]
    assert ("user", "") in roles and ("assistant", "") in roles, roles
    systems = [m["content"] for m in captured["msgs"] if m["role"] == "system"]
    assert any("目标理解" in s for s in systems), "应注入 GU 回合指引"
    assert any("task.propose" in s for s in systems)


def test_handle_chat_five_stage_pipeline_structure():
    """B3 结构守卫: handle_chat 为五段管线编排体, 阶段函数在案且被引用。

    防回内联——闸门/路由/上下文/落库逻辑曾全部堆在 handle_chat(~230 行)。
    """
    import inspect
    from topoone_app_architect.agent import orchestrator as orch
    for fn in ("_chat_gate", "_chat_route", "_chat_context", "_chat_land"):
        assert hasattr(orch, fn), f"管线阶段 {fn} 缺失"
    src = inspect.getsource(orch.handle_chat)
    for fn in ("_chat_gate(", "_chat_route(", "_chat_context(",
               "_run_llm_tool_loop(", "_chat_land("):
        assert fn in src, f"handle_chat 未引用阶段 {fn}"
    # 编排体保持精简(接线而非实现): 不再包含落库/系统段等实现细节
    assert "append_message" not in src
    assert "【工作模式(通用 agent 路由)】" not in src
