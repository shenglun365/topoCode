"""I4 测试：Coding Agent Runner 宿主（:3458 端点 → TaskTreeScheduler 接线冒烟）。

真实 uvicorn（测试端口）+ httpx + websockets；MockCodingExecutor 代替外部执行器。
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import threading
import time
import uuid

import httpx
import pytest
import uvicorn
import websockets

def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RunnerServer:
    def __init__(self, tmp_path, port: int = 0):
        self.tmp = tmp_path
        self.port = port
        self.thread = None
        self.server = None
        self.loop_thread = None

    def start(self):
        import topoone.plugins.runner.server as srv

        runner_dir = str(self.tmp / "runner")
        srv.RUNNER_DIR = runner_dir
        srv.RUNNER_DB = os.path.join(runner_dir, "runner.db")
        srv.STATE_DIR = os.path.join(runner_dir, "state")
        os.makedirs(srv.STATE_DIR, exist_ok=True)

        from topocode_agent.subagent import MockCodingExecutor
        srv.build_pool = lambda: _mock_pool()
        srv.init_runner()
        self.mock = srv.state.pool.get("mock")

        self.loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(self.loop)
            self.server = uvicorn.Server(
                uvicorn.Config(srv.app, host="127.0.0.1", port=self.port, log_level="error"))
            self.loop.run_until_complete(self.server.serve())

        self.loop_thread = threading.Thread(target=_run, daemon=True)
        self.loop_thread.start()
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.2):
                    break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError("runner server did not start")

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.loop_thread:
            self.loop_thread.join(timeout=5)


def _mock_pool():
    from topocode_agent.subagent import ExecutorPool, MockCodingExecutor
    return ExecutorPool(default_executor=MockCodingExecutor(), max_parallel=2)


def _tree_dict():
    return {"roots": [
        {"id": "t1", "title": "step one", "kind": "task", "files": ["a.py"]},
        {"id": "t2", "title": "step two", "kind": "task", "files": ["b.py"],
         "depends_on": ["t1"]},
    ]}


@pytest.fixture
def runner(tmp_path):
    r = RunnerServer(tmp_path, port=_free_port())
    r.start()
    yield r
    r.stop()


def test_health(runner):
    with httpx.Client(base_url=f"http://127.0.0.1:{runner.port}", timeout=5) as c:
        r = c.get("/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["executors"].get("mock") is True
        r2 = c.get("/healthz")
        assert r2.json()["ok"] is True


def test_submit_run_complete(runner):
    with httpx.Client(base_url=f"http://127.0.0.1:{runner.port}", timeout=10) as c:
        r = c.post("/api/trees", json={"tree": _tree_dict(),
                                       "context": {"requirement": "demo"}})
        assert r.status_code == 200
        tree_id = r.json()["tree_id"]
        assert tree_id

        r = c.post(f"/api/trees/{tree_id}/run")
        assert r.status_code == 200

        # 轮询到全部 done（t1 → t2 依赖序）
        deadline = time.time() + 15
        body = None
        while time.time() < deadline:
            body = c.get(f"/api/trees/{tree_id}").json()
            prog = body["progress"]
            if prog.get("done", 0) >= 2 or prog.get("status") in ("done", "completed"):
                break
            time.sleep(0.2)
        statuses = {n["id"]: n["status"] for n in _flatten(body["tree"])}
        assert statuses.get("t1") == "done", f"t1 not done: {statuses}"
        assert statuses.get("t2") == "done", f"t2 not done: {statuses}"
        assert runner.mock.executed.count("t1") == 1
        assert runner.mock.executed.count("t2") == 1

        # runner.db 已持久化
        import sqlite3
        conn = sqlite3.connect(runner.server and _runner_db_path(runner))
        row = conn.execute("SELECT id, status FROM task_trees WHERE id=?", (tree_id,)).fetchone()
        assert row is not None
        conn.close()


def test_ws_events(runner):
    import topoone.plugins.runner.server as srv
    base = f"http://127.0.0.1:{runner.port}"

    async def _run():
        events = []
        async with httpx.AsyncClient(base_url=base, timeout=10) as c:
            r = await c.post("/api/trees", json={"tree": _tree_dict()})
            tree_id = r.json()["tree_id"]
            ws_url = base.replace("http", "ws") + f"/api/trees/{tree_id}/events"
            async with websockets.connect(ws_url) as ws:
                await c.post(f"/api/trees/{tree_id}/run")
                while True:
                    msg = await asyncio.wait_for(ws.recv(), timeout=10)
                    ev = json.loads(msg)
                    events.append(ev)
                    if ev.get("type") == "status" and ev.get("data", {}).get("stage") == "completed":
                        break
        return tree_id, events

    tree_id, events = asyncio.run(_run())
    stages = [e.get("data", {}).get("stage") for e in events]
    assert "running" in stages
    assert "done" in stages
    assert "completed" in stages


def test_restart_restore(runner, tmp_path):
    """重启后未终态树以原 id 恢复。"""
    import topoone.plugins.runner.server as srv
    base = f"http://127.0.0.1:{runner.port}"

    # 提交树但不 run（pending 状态）
    with httpx.Client(base_url=base, timeout=10) as c:
        r = c.post("/api/trees", json={"tree": _tree_dict()})
        tree_id = r.json()["tree_id"]

    # 模拟重启：重新 init_runner（同一 runner.db）
    srv.build_pool = lambda: _mock_pool()
    srv.init_runner()

    with httpx.Client(base_url=base, timeout=10) as c:
        r = c.get(f"/api/trees/{tree_id}")
        assert r.status_code == 200
        body = r.json()
        assert "tree" in body  # 原 id 可查


def _runner_db_path(runner) -> str:
    return os.path.join(runner.tmp, "runner", "runner.db")


def _flatten(tree: dict) -> list:
    out = []

    def walk(n):
        out.append(n)
        for c in n.get("children", []):
            walk(c)

    for root in tree.get("roots", []):
        walk(root)
    return out
