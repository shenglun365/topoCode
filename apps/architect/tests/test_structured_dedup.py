"""cv-185 生产回归: structured 受限生成通道连发 req.propose 只落一张卡。

事故还原: topo-game 会话 cv-185 单条用户消息 → structured 轮 4 次 req.propose
全部落库(RQ-104~107 重复卡)——cv-174 去重守卫只在流式文本轮分支,
structured_tool_round 与满轮收尾分支无守卫。本测试锁定三分支守卫。

Run: cd <repo> && python -m pytest apps/architect/tests/test_structured_dedup.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.req_agent as req_agent
from topoone_app_architect.arch_routes import store
from topoone_app_architect.server import build_app

WS_PATH = "/api/architect/ws/kb-analysis"


def test_structured_channel_duplicate_propose_deduped(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    import topoone_app_architect.arch_routes.ctx as C
    C._db = None; C._kb = None; C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)

    # 流式通道不可用 → structured 轮后走 sync 收尾
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)
    monkeypatch.setattr(req_agent, "run_tools_loop",
                        lambda msgs, **kw: {"content": "已为您创建需求卡与任务方案。"})
    # structured 位开启 + 弱模型连续三轮发 req.propose(事故形态)
    monkeypatch.setattr(req_agent, "structured_model_enabled", lambda m: True)
    rounds = {"n": 0}

    def _fake_structured_round(msgs, model_id="", **kw):
        rounds["n"] += 1
        if rounds["n"] <= 3:
            return {"error": None, "calls": [{
                "tool": "req.propose",
                "arguments": {"title": "动画建模中间层",
                              "requirementMd": "构建 2D/3D 动画建模中间层"}}]}
        return {"error": None, "calls": []}   # 第 4 轮示意无更多工具

    monkeypatch.setattr(req_agent, "structured_tool_round", _fake_structured_round)

    client = TestClient(build_app(data_dir=data))
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                          "conversationId": conv["id"],
                          "messages": [{"role": "user", "content": "新增 动画建模中间层组件"}]})
            ev = None
            for _ in range(30):
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    break
            assert ev and ev.get("type") == "done"

    reqs = [r for r in store.RequirementsStore.all()
            if r.get("ownerConv") == conv["id"]]
    assert len(reqs) == 1, f"structured 轮重复提案应去重, 实落 {len(reqs)} 张: {[r['id'] for r in reqs]}"
    # cv-196 收尾短路: 首轮落卡即收束——重复提案轮不再发生(更强的去重)
    assert rounds["n"] == 1


def test_final_round_branch_duplicate_propose_deduped(tmp_path, monkeypatch):
    """满轮收尾分支(流式文本轮 tool_round>=max)同样去重。"""
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    import topoone_app_architect.arch_routes.ctx as C
    C._db = None; C._kb = None; C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)

    # 构造: 流式每轮都吐 [TOOL_CALL] req.propose → 第 max 轮进收尾分支重复提案
    TOOL_BLOCK = ('[TOOL_CALL]\ntool: req.propose\narguments:\n'
                  '{"title": "重复卡", "requirementMd": "x"}\n[/TOOL_CALL]')
    monkeypatch.setattr(req_agent, "structured_model_enabled", lambda m: False)
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: "rid-x")
    monkeypatch.setattr(req_agent, "extract_tool_calls",
                        lambda text: [{"tool": "req.propose",
                                       "arguments": {"title": "重复卡",
                                                     "requirementMd": "x"}}])
    monkeypatch.setattr(req_agent, "record_tool_parse_audit",
                        lambda *a, **k: None)

    async def _fake_iter(rid, idle_timeout=None):
        yield "done", {"content": TOOL_BLOCK}

    from topoone_app_architect.agent.turns import chat as turns_chat
    monkeypatch.setattr(turns_chat, "_iter_llm_events", _fake_iter)

    def _fake_sync(msgs, **kw):
        return {"content": "收尾回答"}

    monkeypatch.setattr(req_agent, "run_tools_loop", _fake_sync)

    client = TestClient(build_app(data_dir=data))
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                          "conversationId": conv["id"],
                          "messages": [{"role": "user", "content": "建卡"}]})
            ev = None
            for _ in range(40):
                ev = ws.receive_json()
                if ev.get("type") == "done":
                    break
            assert ev and ev.get("type") == "done"

    reqs = [r for r in store.RequirementsStore.all()
            if r.get("ownerConv") == conv["id"]]
    assert len(reqs) == 1, f"满轮收尾分支重复提案应去重, 实落 {len(reqs)} 张"
