"""W1-3 WS 事件 seq 协议 — 连接级单调性测试。

后端 _seq_sender 给两通道(/ws/kb-analysis, /ws/unit-test)每帧注入单调 seq;
前端 ArchWs 丢弃 seq<=lastSeq 的迟到事件(见 tests/ws-seq.test.ts)。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from topoone_app_architect.server import build_app


def _client(arch_env) -> TestClient:
    return TestClient(build_app(data_dir=arch_env))


def test_kb_analysis_pong_seq_monotonic(arch_env):
    with _client(arch_env).websocket_connect("/api/architect/ws/kb-analysis") as ws:
        ws.send_json({"type": "ping"})
        p1 = ws.receive_json()
        ws.send_json({"type": "ping"})
        p2 = ws.receive_json()
        assert p1["type"] == "pong" and p2["type"] == "pong"
        assert isinstance(p1.get("seq"), int) and p2["seq"] > p1["seq"]


def test_unit_test_pong_seq_monotonic(arch_env):
    with _client(arch_env).websocket_connect("/api/architect/ws/unit-test") as ws:
        ws.send_json({"type": "ping"})
        p1 = ws.receive_json()
        ws.send_json({"type": "ping"})
        p2 = ws.receive_json()
        assert p1["type"] == "pong" and p2["seq"] > p1["seq"]


def test_unit_test_message_flow_seq_increases(arch_env):
    client = _client(arch_env)
    r = client.post("/api/architect/unit-test-sessions",
                    json={"title": "seq 会话", "channel": "cli", "adapter": "pytest"})
    assert r.status_code == 200, r.text
    sid = r.json()["data"]["id"]
    with client.websocket_connect("/api/architect/ws/unit-test") as ws:
        ws.send_json({"type": "message", "sessionId": sid, "content": "看看失败原因"})
        frames = []
        while True:
            ev = ws.receive_json()
            frames.append(ev)
            if ev["type"] == "message" and ev.get("role") == "assistant":
                break
        seqs = [f["seq"] for f in frames]
        assert all(isinstance(s, int) for s in seqs)
        assert seqs == sorted(seqs), f"seq 非单调: {seqs}"
        assert len(set(seqs)) == len(seqs), f"seq 重复: {seqs}"
