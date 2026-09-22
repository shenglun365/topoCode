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
import tempfile

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.req_agent as req_agent
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.agent.perception.commands import match_imperative
from topoone_app_architect.agent.perception import commands as cmds
from topoone_app_architect.agent.governance.focus import build_focus, resolve_intent
from topoone_app_architect.arch_routes.asset_skill import _builtin_for, skill_docs
from topoone_app_architect.server import build_app

WS_PATH = "/api/architect/ws/kb-analysis"


def _client(tmp_path, monkeypatch):
    from tests.conftest import isolate_arch
    data = isolate_arch(tmp_path, monkeypatch)
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)
    captured = {"calls": 0}

    def _fake_loop(msgs, **kw):
        captured["calls"] += 1
        return {"content": "ok-reply"}

    monkeypatch.setattr(req_agent, "run_tools_loop", _fake_loop)
    return TestClient(build_app(data_dir=data)), captured


from tests.ws_helpers import recv_until as _recv_until_base


def _recv_until(ws, *types):
    return _recv_until_base(ws, *types)


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


# ── 意图原语分类(批戊: 词表定意图) ───────────────────────────────────

def test_match_imperative_intents():
    assert match_imperative("/提取需求") == {"intent": "extract", "executor": ""}
    assert match_imperative(" /执行 ") == {"intent": "execute", "executor": ""}
    assert match_imperative("@cline /执行") == {"intent": "execute", "executor": "cline"}
    assert match_imperative("确认") == {"intent": "confirm", "executor": ""}
    assert match_imperative("确认执行") == {"intent": "confirm", "executor": ""}
    assert match_imperative("@cline 确认") == {"intent": "confirm", "executor": "cline"}
    assert match_imperative("好的。") == {"intent": "confirm", "executor": ""}
    assert match_imperative("继续执行") == {"intent": "continue", "executor": ""}
    assert match_imperative("继续") == {"intent": "continue", "executor": ""}
    assert match_imperative("重试") == {"intent": "retry", "executor": ""}
    # 带正文/非指令 → 普通消息
    for neg in ("/提取需求 帮我看看", "/调整", "/继续", "/diff", "普通话",
                "确认一下这个方案", "不确认"):
        assert match_imperative(neg) is None, neg


# ── 焦点栈就近消解(批戊: 焦点定指代) ─────────────────────────────────

def test_resolve_intent_matrix():
    """消解矩阵: 意图 × top 帧 → 动作(cv-241 病灶根治面)。"""
    def _focus(top=None, kinds=(), recent=()):
        stack = [{"kind": k, "taskId": f"task-{k}", "label": k} for k in kinds]
        if top:
            stack.insert(0, {**top})
        return {"stack": stack, "recent": list(recent),
                "top": stack[0] if stack else None}
    # 推进/确认类 × 待确认帧 → 就近启动栈顶(cv-241 复放)
    step = {"kind": "plan_step_ready", "taskId": "task-38", "label": "步骤 2/4"}
    r = resolve_intent("continue", _focus(top=step))
    assert r["action"] == "confirm_task" and r["frame"]["taskId"] == "task-38"
    r = resolve_intent("confirm", _focus(top=step))
    assert r["action"] == "confirm_task"
    r = resolve_intent("execute", _focus(
        top={"kind": "task_confirm", "taskId": "task-9", "label": ""}))
    assert r["action"] == "confirm_task"
    # confirm 无待确认焦点 → 回落 GU(旧行为: 无卡=普通对话)
    assert resolve_intent("confirm", _focus(kinds=("reviewing",)))["action"] == "fallthrough"
    assert resolve_intent("confirm", _focus())["action"] == "fallthrough"
    # execute/continue × spec_ready → 生成计划/单卡; × 无焦点 → 既有路径
    assert resolve_intent("execute", _focus(kinds=("spec_ready",)))["action"] == "execute"
    assert resolve_intent("execute", _focus())["action"] == "execute"
    # 运行占用/等待输入 → 焦点态提示(零 LLM)
    assert resolve_intent("execute", _focus(
        top={"kind": "task_running", "taskId": "t", "label": "A 执行中"}))["action"] == "none"
    r = resolve_intent("continue", _focus(
        top={"kind": "task_input_wait", "taskId": "t", "label": "A 等待输入"}))
    assert r["action"] == "relay_hint"
    # retry: recent.failed 指代; 无失败 → 明确提示
    r = resolve_intent("retry", _focus(recent=(
        {"kind": "task_failed", "taskId": "task-f", "ts": 1},)))
    assert r["action"] == "retry_failed" and r["frame"]["taskId"] == "task-f"
    assert resolve_intent("retry", _focus())["action"] == "none"


def test_slash_text_confirm_starts_task(tmp_path, monkeypatch):
    """cv-153 实证回归: 打「确认」文字 = 卡片确认按钮(直通 confirm_task, 零 LLM)。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    task = store.TasksStore.create({
        "conversationId": conv["id"], "title": "T卡", "instruction": "x",
        "status": "pending_confirm", "executorType": "opencode"})
    from topoone_app_architect.arch_routes import exec_bridge as eb
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-c"))
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=20.0: (
                            {"ok": True, "jobId": "impl-t1", "worktree": "/tmp/w",
                             "branch": "task/t1", "sessionId": "s"}
                            if path == "/api/implement" else None))
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "确认")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0                        # 零 LLM
    assert "已确认任务" in ev["content"]
    assert store.TasksStore.get(task["id"])["status"] == "running"


def test_text_confirm_without_pending_falls_to_llm(tmp_path, monkeypatch):
    """无待确认卡时「确认」是普通对话 → 不拦, 走 LLM。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "确认")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 1                        # 进了 LLM 回合
    assert ev["content"] == "ok-reply"


# ── /定稿 直通 ───────────────────────────────────────────────────────

def test_slash_extract_req_direct(tmp_path, monkeypatch):
    """/提取需求: LLM 结构化提取 → apply_spec_payload 落需求卡(ready)。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    store.ConversationsStore.append_message({
        "id": store.next_id("m"), "conversationId": conv["id"],
        "role": "user", "time": 1, "content": "给项目写一个连通性探测脚本"})
    from topoone_app_architect.arch_routes import req_agent as _ra
    monkeypatch.setattr(_ra, "llm_sync",
                        lambda *a, **k: {"output": {"title": "连通性探测脚本",
                                                    "requirementMd": "实现探测"}, "content": ""})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/提取需求")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0                        # 零额外 LLM(llm_sync 已 mock)
    assert "已提取" in ev["content"]
    assert (store.ConversationsStore.get(conv["id"]) or {}).get("reqId")
    # cv-177 回归: 卡片(specReady)只由 apply 路径落一条 + 文本回执一条 = 共 2 条
    tail = store.ConversationsStore.messages(conv["id"])[-4:]
    ready_cards = [m for m in tail
                   if (m.get("meta") or "") and "specReady" in str(m.get("meta"))]
    assert len(ready_cards) == 1, f"specReady 卡应仅 1 条, got {len(ready_cards)}"


def test_slash_extract_req_without_content_guides(tmp_path, monkeypatch):
    """空会话 → 明确引导, 不调 LLM。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/提取需求")
            ev, _ = _recv_until(ws, "done")
    assert "还没有内容" in ev["content"]


def test_slash_execute_autoconfirms_legacy_draft(tmp_path, monkeypatch):
    """历史 draft 需求(旧流程产物) → /执行 就地确认后建卡, 不再要求 /定稿。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    _mk_req(conv["id"], confirmed=False)
    import topoone_app_architect.arch_routes.execution as ex
    root = tmp_path / "proj-ex"
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(ex, "conv_root_project", lambda c: (str(root), "proj-x"))
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=20.0: (
                            {"ok": True, "jobId": "impl-d1", "worktree": "/w",
                             "branch": "task/x", "sessionId": "s"}
                            if path == "/api/implement" else None))
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], "/执行")
            ev, _ = _recv_until(ws, "done")
    assert captured["calls"] == 0
    assert "任务卡" in ev["content"]
    assert any((t.get("status") or "") == "saved"
               for t in store.TasksStore.of_conv(conv["id"]))


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


def test_finalize_route_idempotent_ready(tmp_path, monkeypatch):
    """cv-175 回归: /requirements/{id}/finalize 退化为幂等就位——
    ready 直接返回行(不再走已退役的 tool_req_finalize), 历史 draft 就地确认。"""
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    data = tmp_path / "arch-fin"
    monkeypatch.setenv("ARCH_DATA_DIR", str(data))
    C._db = None; C._kb = None; C._data_dir = None; C._project_dbs.clear()
    C.setup(data_dir=str(data))
    client = TestClient(build_app(data_dir=str(data)))
    rid = store.next_id("RQ")
    store.RequirementsStore.create({"id": rid, "kind": "user-story",
                                    "status": "ready", "title": "T", "activeVer": 1})
    r = client.post(f"/api/architect/requirements/{rid}/finalize")
    assert r.status_code == 200
    assert r.json()["data"]["status"] == "ready"
    # 历史 draft → 就地确认
    rid2 = store.next_id("RQ")
    store.RequirementsStore.create({"id": rid2, "kind": "user-story",
                                    "status": "draft", "title": "T2", "activeVer": 1})
    r2 = client.post(f"/api/architect/requirements/{rid2}/finalize")
    assert r2.status_code == 200
    assert r2.json()["data"]["status"] == "ready"


def test_error_contract_shapes(tmp_path, monkeypatch):
    """环节三: 主链错误形状契约——直通 {ok,receipt} / 执行器任务 dict 含 ok / REST err 状态码映射。"""
    client, captured = _client(tmp_path, monkeypatch)
    conv = _mk_conv()
    # ① 直通失败形状: {ok: False, receipt}
    from topoone_app_architect.agent.perception import commands as cmds
    res = cmds.run_execute(conv)
    assert res["ok"] is False and "receipt" in res and "error" not in res
    # ② 执行器成功形状: 任务 dict 显式 ok=True
    from topoone_app_architect.arch_routes import exec_bridge as eb
    r = eb.propose_task(conv, "T-契约", "目标: x")
    assert r.get("ok") is True and r.get("id")
    # ③ REST err: HTTP 状态码与 body.code 一致(前端只解析 body.code, 修正透明)
    resp = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                       json={"mode": "bogus"})
    assert resp.status_code == 400 and resp.json()["code"] == 400
    resp404 = client.get("/api/architect/sessions/cv-nope/messages")
    assert resp404.status_code == 404 and resp404.json()["code"] == 404


def test_llm_catalog_url_strips_v1_and_probes_context(monkeypatch):
    """环节四: llm.models 目录 url 存根(剥 /v1, 探测友好); contextWindow 探测落库。"""
    import asyncio
    data = tempfile.mkdtemp(prefix="topo-cat-")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None; C._kb = None; C._data_dir = None; C._project_dbs.clear()
    C.setup(data_dir=data)
    from topoone_app_architect.arch_routes import mcp_collab as mc
    from topoone_app_architect.agent.cognition import llm as _cllm

    monkeypatch.setattr(_cllm, "probe_context_window",
                        lambda url, hint="": 262144 if url == "http://h:8082" else None)
    catalog = [{"source": "imported", "id": "model-x", "name": "35B",
                "provider": "custom-local", "model": "Qwen3.6-35B",
                "url": "http://h:8082/v1", "type": "local"}]
    monkeypatch.setattr("topoone_app_architect.arch_routes.kb_gateway.call_kb",
                        lambda method, **kw: [{"id": "model-x", "name": "35B",
                                               "provider": "custom-local", "model": "Qwen3.6-35B",
                                               "url": "http://h:8082/v1", "type": "local"}])
    asyncio.run(mc.import_llm_models_route())
    saved = mc.get_llm_models()
    assert saved and saved[0]["url"] == "http://h:8082"          # /v1 剥离(存根)
    assert saved[0]["contextWindow"] == 262144                    # 探测落库
