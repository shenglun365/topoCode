"""空白态挡位预置 特征测试(cv-260)。

锁定(用户实证: 空白会话无法点击模式设置按钮):
  - WS chat 载荷带 analysisMode/clarifyMode/isolated 且无 conversationId
    → 会话创建即携带三挡位(首条消息就按预置模式处理, 无需先发一条走默认模式)
  - 已存在会话: 载荷挡位字段被忽略(挡位真相源=会话行+REST 切换, 载荷不覆写)
  - 非法值静默丢弃(校验口径与 REST 切换端点同源: normalize_mode / auto|forced / bool)

Run: cd <repo> && python -m pytest apps/architect/tests/test_preset_modes.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.ctx as C
import topoone_app_architect.agent.tools.req_agent as req_agent
import topoone_app_architect.store as store
from topoone_app_architect.server import build_app

WS_PATH = "/api/architect/ws/kb-analysis"


def _client(tmp_path, monkeypatch, *, llm_content="ok-reply"):
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

    def _fake_loop(msgs, **kw):
        return {"content": llm_content}

    monkeypatch.setattr(req_agent, "run_tools_loop", _fake_loop)
    return TestClient(build_app(data_dir=data))


def _recv_until(ws, *types):
    while True:
        ev = ws.receive_json()
        if ev["type"] in types:
            return ev


def _chat(ws, conv_id, content="hi", **extra):
    ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                  "conversationId": conv_id,
                  "messages": [{"role": "user", "content": content}], **extra})


def test_blank_state_preset_applied_at_creation(tmp_path, monkeypatch):
    """空白态首条消息带预置挡位 → 会话创建即生效。"""
    client = _client(tmp_path, monkeypatch)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, None, analysisMode="quick", clarifyMode="forced",
                  isolated=True)
            ev = _recv_until(ws, "done")
    conv = store.ConversationsStore.get(ev["conversationId"])
    assert conv["analysisMode"] == "quick"
    assert conv["clarifyMode"] == "forced"
    assert conv["isolated"] == 1


def test_existing_conv_preset_fields_ignored(tmp_path, monkeypatch):
    """已存在会话: 载荷挡位不覆写(真相源=会话行+REST)。"""
    client = _client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"], analysisMode="quick")
            _recv_until(ws, "done")
    after = store.ConversationsStore.get(conv["id"])
    assert after["analysisMode"] == "strict"   # 创建缺省, 载荷未覆写


def test_invalid_preset_values_dropped(tmp_path, monkeypatch):
    """非法值静默丢弃(不落库脏值), 合法值保留。"""
    client = _client(tmp_path, monkeypatch)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, None, analysisMode="T9-bogus", clarifyMode="weird",
                  isolated="yes")
            ev = _recv_until(ws, "done")
    conv = store.ConversationsStore.get(ev["conversationId"])
    assert conv["analysisMode"] == "strict"
    assert conv["clarifyMode"] == "auto"
    assert conv["isolated"] == 0
