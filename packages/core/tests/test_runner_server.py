"""Runner 宿主回归(:3458)——健康探活 + probe 一次性回合(FakeAdapter)。

树调度器(TaskTreeScheduler/ExecutorPool/runner.db)已退役; 本文件只覆盖
单一执行面: /health 与 /api/probe(TurnAdapter 同面)。
"""

from __future__ import annotations

import asyncio
import socket
import threading

import httpx
import pytest
import uvicorn


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class RunnerServer:
    def __init__(self, tmp_path, port: int = 0):
        self.tmp = tmp_path
        self.port = port or _free_port()
        self.thread = None
        self.server = None

    def start(self):
        import topoone.plugins.runner.server as srv

        self.server = uvicorn.Server(uvicorn.Config(
            srv.app, host="127.0.0.1", port=self.port, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        for _ in range(60):
            try:
                httpx.get(f"http://127.0.0.1:{self.port}/health", timeout=1.0)
                return
            except Exception:  # noqa: BLE001
                import time
                time.sleep(0.2)
        raise RuntimeError("runner server 未起来")

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=8)


@pytest.fixture()
def runner(tmp_path):
    rs = RunnerServer(tmp_path)
    rs.start()
    yield rs
    rs.stop()


def test_health(runner):
    r = httpx.get(f"http://127.0.0.1:{runner.port}/health", timeout=5.0)
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_probe_one_shot_turn(runner, tmp_path, monkeypatch):
    """probe: worktree 快照 + 单回合 + diff 提取 + 清理(FakeAdapter)。"""
    import subprocess

    # 最小 git 仓库
    root = tmp_path / "repo"
    root.mkdir()
    def _g(*a):
        subprocess.run(["git", *a], cwd=str(root), check=True,
                       capture_output=True)
    _g("init", "-q")
    _g("config", "user.email", "t@t")
    _g("config", "user.name", "t")
    (root / "hello.txt").write_text("v1\n")
    _g("add", "-A")
    _g("commit", "-qm", "init")

    from topoone.plugins.runner import turn_adapter as ta

    class _FakeAdapter(ta.TurnAdapter):
        executor_id = "fake"
        executor_type = "fake"

        async def start_session(self, job) -> None:
            job.session_id = "s-fake"

        async def run_turn(self, job, text: str) -> ta.TurnOutcome:
            import os
            with open(os.path.join(job.wt, "hello.txt"), "a") as fh:
                fh.write("v2\n")
            return ta.TurnOutcome(output="done")

        async def probe(self, job) -> ta.TurnProbe:
            return ta.TurnProbe(status="idle", last_activity_ts=1.0)

    monkeypatch.setattr(ta, "build_adapter",
                        lambda t, i, c: _FakeAdapter())

    r = httpx.post(f"http://127.0.0.1:{runner.port}/api/probe", timeout=30.0, json={
        "root": str(root), "instruction": "追加一行",
        "executorType": "fake", "timeoutS": 60,
    })
    data = r.json()
    assert data["ok"] is True and data["status"] == "done"
    assert "hello.txt" in data["changedFiles"]
    assert "+v2" in data["diff"]
    # worktree 已清理
    r2 = subprocess.run(["git", "worktree", "list"], cwd=str(root),
                        capture_output=True, text=True)
    assert "probe-" not in r2.stdout


def test_probe_invalid_body(runner):
    r = httpx.post(f"http://127.0.0.1:{runner.port}/api/probe", timeout=10.0,
                   json={"root": "", "instruction": ""})
    assert r.json()["ok"] is False
