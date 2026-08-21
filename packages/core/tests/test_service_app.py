"""P3 服务拆分脚手架测试 — MethodServer + service_app + llm 服务注册。

验证：
  1. MethodServer 注册/发布接口（兼容 ZMQServer.register/publish）。
  2. create_service_app 的 /zmq/{method} + /health 端点。
  3. llm_service_app.register_methods 可脱离 core 独立注册 llm.*/session.* 方法。
"""

import json
import os
import sys
import tempfile

import pytest

_BACKEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "backend-core",
)
sys.path.insert(0, _BACKEND)


@pytest.fixture()
def data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_method_server_register_and_publish():
    from topoone.rpc.service_app import MethodServer

    srv = MethodServer(pub_port=None)
    events = []

    @srv.register("demo.echo")
    def echo(msg: str):
        events.append(("called", msg))
        return {"echo": msg}

    assert "demo.echo" in srv.methods
    assert srv.methods["demo.echo"](msg="hi") == {"echo": "hi"}
    assert events == [("called", "hi")]
    # 无 pub 时 publish 为 no-op（不抛异常）
    srv.publish("task", "progress", {"x": 1})
    assert srv.get_status()["methods"] == 1


def test_service_app_zmq_and_health(data_dir):
    from topoone.rpc.service_app import MethodServer, create_service_app
    from fastapi.testclient import TestClient

    srv = MethodServer()

    @srv.register("demo.add")
    def add(a: int, b: int):
        return a + b

    app = create_service_app(srv, None, title="test-svc")
    client = TestClient(app)

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "test-svc"

    r = client.post("/zmq/demo.add", json={"a": 2, "b": 3})
    assert r.status_code == 200
    assert r.json() == {"result": 5}

    r = client.post("/zmq/demo.missing", json={})
    assert r.status_code == 404


def test_llm_service_methods_register(data_dir):
    """llm 服务可脱离 core 独立注册全部 llm/session/analysisSession/promptTemplate 方法。"""
    from topoone.db.manager import MultiDBManager
    from topoone.rpc.service_app import MethodServer
    from topoone.llm.__main__ import register_methods

    multi_db = MultiDBManager(data_dir)
    srv = MethodServer(pub_port=None)
    register_methods(srv, multi_db)

    names = set(srv.methods.keys())
    for ns in ("llm", "session", "analysisSession", "promptTemplate"):
        assert any(n.startswith(ns + ".") for n in names), f"missing {ns} methods"
    # 关键方法存在
    assert "llm.chat" in names
    assert "session.list" in names
    assert "promptTemplate.getDefaultLocale" in names

    # 实际调用 session.list（空库返回空列表）
    res = srv.methods["session.list"]()
    assert "sessions" in res
    multi_db.close_all()


def test_agent_service_methods_register(data_dir):
    """agent 服务可脱离 core 独立注册 agent.* 方法（dispatch/config/listRunning 等）。"""
    import asyncio
    from topoone.db.manager import MultiDBManager
    from topoone.rpc.service_app import MethodServer
    from topoone.agent.__main__ import register_methods

    multi_db = MultiDBManager(data_dir)
    srv = MethodServer(pub_port=None)
    register_methods(srv, multi_db)

    names = set(srv.methods.keys())
    for m in ("agent.dispatch", "agent.getConfig", "agent.getProgress",
              "agent.cancel", "agent.pause", "agent.resume",
              "agent.getHistory", "agent.clearHistory",
              "agent.listRunning", "agent.raw"):
        assert m in names, f"missing {m}"

    # getConfig / listRunning 实际调用（async 方法）
    async def _call():
        cfg = srv.methods["agent.getConfig"]()
        if asyncio.iscoroutine(cfg):
            cfg = await cfg
        running = srv.methods["agent.listRunning"]()
        if asyncio.iscoroutine(running):
            running = await running
        return cfg, running

    cfg, running = asyncio.run(_call())
    assert isinstance(cfg["routes"], list) and cfg["routes"]
    assert "tasks" in running
    multi_db.close_all()


def test_doc_service_methods_register(data_dir):
    """docs 服务注册 render.* 方法（plantuml 渲染；M11 迁 apps/docs/topoone_app_docs）。"""
    from topoone.db.manager import MultiDBManager
    from topoone.rpc.service_app import MethodServer
    from topoone_app_docs.main import register_methods

    multi_db = MultiDBManager(data_dir)
    srv = MethodServer(pub_port=None)
    register_methods(srv, multi_db)

    names = set(srv.methods.keys())
    assert "render.plantuml" in names
    assert "render.testPlantuml" in names
    multi_db.close_all()


def test_chat_service_importable(data_dir):
    """chat 服务入口可加载（M12 迁 apps/chat/topoone_app_chat，独立进程可用）。"""
    import subprocess
    import sys as _sys

    # 直接 import topoone_app_chat.main 应成功（验证 chat 子项目包可独立加载）
    code = (
        "import os\n"
        "os.environ.setdefault('TOPO_MODE', 'monolith')\n"
        "import topoone_app_chat.main\n"
        "print('topoone_app_chat import OK')\n"
    )
    r = subprocess.run([_sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert "OK" in r.stdout, f"import failed: {r.stderr[:500]}"
    assert "error" not in r.stderr.lower() or "Traceback" not in r.stderr, r.stderr[:500]


def test_http_agent_manager_call(monkeypatch):
    """HttpAgentManager（P3e agent 移交）按 agent 服务 /zmq 协议转发。"""
    from topoone.messaging.remote import HttpAgentManager

    calls = []

    def fake_urlopen(req, timeout=60):
        calls.append((req.full_url, req.data))
        import io
        body = json.dumps({"result": {"routes": []}}).encode()
        class _Resp:
            status = 200
            def read(self):
                return body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _Resp()

    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

    mgr = HttpAgentManager("http://127.0.0.1:3482")
    res = mgr._call("agent.getConfig", {})
    assert res == {"routes": []}
    assert calls[0][0] == "http://127.0.0.1:3482/zmq/agent.getConfig"

    # dispatch 映射到 agent.dispatch
    res = mgr.dispatch("overview", "t1", {"k": "v"}, project_id="p1")
    assert res == {"routes": []}
    url, body = calls[-1]
    assert url == "http://127.0.0.1:3482/zmq/agent.dispatch"
    payload = json.loads(body)
    assert payload["route"] == "overview" and payload["task_id"] == "t1"
    assert payload["context"] == {"k": "v"}

    # _send 兼容旧协议 → agent.raw
    res = mgr._send("presummary_chain", {"task_id": "t1"})
    url, body = calls[-1]
    assert url == "http://127.0.0.1:3482/zmq/agent.raw"
    assert json.loads(body)["action"] == "presummary_chain"
