"""会话指令直通(/定稿 /执行) + v2 契约单源 特征测试。

cv-152 实证回归锁定:
  - /定稿 直通: finalize 门禁路径 → specReady meta 回执, 零 LLM
  - /执行 直通: ready 规约 → propose_task 建任务卡(pending_confirm), 零 LLM
  - draft 规约 /执行 → 拒绝回执(先 /定稿); 无绑定需求 → 引导回执
  - 转达语境(attachTo)中的 /指令 不拦截(是发给 subagent 的内容)
  - 指令识别: 整条消息恰为 /定稿|/执行 才直通; /调整 /继续 等仍走对话
  - v1 死契约断言: skill 文档不含 coding.task.execute/任务执行页/不代建执行任务;
    coding 场景 no-op; plan/capability 文档含 v2 建卡口径

Run: cd <repo> && python -m pytest apps/architect/tests/test_direct_commands.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.req_agent as req_agent
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.agent.perception.commands import match_command
from topoone_app_architect.agent.perception import commands as cmds
from topoone_app_architect.arch_routes.asset_skill import _builtin_for, skill_docs
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
    captured = {"calls": 0}

    def _fake_loop(msgs, **kw):
        captured["calls"] += 1
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


def _mk_conv(**kw):
    return store.ConversationsStore.create({"kind": "generic", "title": "t", **kw})


def _mk_req(conv_id, design=True, confirmed=False):
    snap = {"title": "演示任务", "desc": "目标说明", "designMd": "改动 X" if design else "",
            "allowedScope": ["src/a.py"], "forbiddenScope": [], "acceptance": ["编译通过"],
            "functionalScope": [], "assessmentSummary": "", "estMin": 10}
    req = {"id": store.next_id("RQ"), "kind": "user-story", "status": "draft",
           "title": "演示任务", "priority": "P1", "activeVer": 1,
           "specVersions": [{"ver": 1, "state": "draft", "snapshot": snap,
                             "source": {}, "reason": "t", "createdAt": 0}],
           "ownerConv": conv_id, "projectId": "", "updatedAt": 0, "createdAt": 0}
    store.RequirementsStore.create(req)
    store.ConversationsStore.update(conv_id, {"reqId": req["id"]})
    if confirmed:
        store.RequirementsStore.spec_confirm(req["id"])
    return req["id"]


def _chat(ws, conv_id, content, **extra):
    payload = {"type": "chat", "kind": "generic", "title": "t",
               "conversationId": conv_id,
               "messages": [{"role": "user", "content": content}]}
    payload.update(extra)
    ws.send_json(payload)


# ── 指令识别 ─────────────────────────────────────────────────────────

def test_match_command_strict_shape():
    assert match_command("/定稿") == {"cmd": "定稿", "executor": ""}
    assert match_command(" /执行 ") == {"cmd": "执行", "executor": ""}
    assert match_command("@cline /执行") == {"cmd": "执行", "executor": "cline"}
    assert match_command("/定稿 帮我看看") is None       # 带正文 → 普通消息
    assert match_command("/调整") is None                 # 保留经 LLM
    assert match_command("/继续") is None
    assert match_command("/diff") is None
    assert match_command("普通话") is None


# ── /定稿 直通 ───────────────────────────────────────────────────────

def test_slash_finalize_direct(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    rid = _mk_req(conv["id"], design=True, confirmed=False)
    with client:   # MCP 会话管理器每实例仅可 run 一次: 两轮共用一个连接
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/定稿")
            ev, _ = _recv_until(ws, "done")
            assert captured["calls"] == 0                      # 零 LLM
            assert ev["meta"]["kind"] == "specReady"
            assert ev["meta"]["requirementId"] == rid
            active = store.RequirementsStore.spec_active(rid)
            assert active["state"] == "confirmed"
            # 幂等: 再发一次 /定稿 仍 ok(already)
            _chat(ws, conv["id"], "/定稿")
            ev2, _ = _recv_until(ws, "done")
    assert ev2["meta"]["kind"] == "specReady"


def test_slash_finalize_without_req_guides(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/定稿")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0
    assert "未绑定需求" in ev["content"]
    assert "meta" not in ev


# ── /执行 直通(建卡待确认) ───────────────────────────────────────────

def test_slash_execute_creates_task_card(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    rid = _mk_req(conv["id"], confirmed=True)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/执行")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0
    tasks = store.TasksStore.of_conv(conv["id"])
    assert len(tasks) == 1 and tasks[0]["status"] == "pending_confirm"
    assert tasks[0]["title"] == "演示任务"
    # instruction 由快照组装(目标/方案/边界/验收)
    ins = tasks[0]["instruction"]
    assert "需求目标" in ins and "方案" in ins and "src/a.py" in ins and "编译通过" in ins
    # 任务卡消息已落流(meta task_card, 前端确认按钮数据源)
    msgs = store.ConversationsStore.messages(conv["id"], limit=50)
    assert any((m.get("meta") or {}).get("kind") == "task_card" for m in msgs)


def test_slash_execute_rejects_draft(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    _mk_req(conv["id"], confirmed=False)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/执行")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0
    assert "尚未定稿" in ev["content"] and "/定稿" in ev["content"]
    assert store.TasksStore.of_conv(conv["id"]) == []


def test_slash_execute_without_req_guides(tmp_path, monkeypatch):
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/执行")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0
    assert "未绑定需求" in ev["content"]
    assert store.TasksStore.of_conv(conv["id"]) == []


# ── 转达语境不拦截 ───────────────────────────────────────────────────

def test_slash_in_transfer_not_intercepted(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    task = store.TasksStore.create({
        "conversationId": conv["id"], "title": "T", "instruction": "x",
        "status": "running", "executorType": "opencode"})
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: {"ok": True, "queued": False})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/执行", attachTo=task["id"])
            ev, _ = _recv_until(ws, "done")
    # 转达分支回执(零 LLM), 但不建新卡
    assert "已转达" in ev["content"]
    assert len(store.TasksStore.of_conv(conv["id"])) == 1


# ── v1 死契约断言(文档单源) ──────────────────────────────────────────

def test_v1_contract_removed_from_skill_docs(tmp_path, monkeypatch):
    _client(tmp_path, monkeypatch)   # 仅借 db 初始化
    assert _builtin_for("coding") == ""              # coding 场景 no-op
    docs = skill_docs(None, None, ["coding", "capability", "plan"])
    for dead in ("coding.task.execute", "任务执行页", "不代建执行任务",
                 "不代为定稿", "probe.run 方案草图"):
        assert dead not in docs, f"v1 死契约残留: {dead}"
    # v2 口径在场: plan/capability 指向建卡链
    assert "task.propose" in docs
    assert "`/执行`" in docs
