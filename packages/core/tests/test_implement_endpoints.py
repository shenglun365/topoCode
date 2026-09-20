"""implement v2 内省端点测试（能力分派; fake adapter 不起真 sidecar）。

Run: cd <repo> && python -m pytest packages/core/tests/test_implement_endpoints.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner import implement as impl  # noqa: E402
from topoone.plugins.runner.turn_adapter import TurnAdapter, TurnProbe  # noqa: E402


class _CapableAdapter(TurnAdapter):
    """带 cline v2 内省能力的假执行器（记录调用）。"""

    executor_id = "fake-cline"
    executor_type = "cline-sdk"

    def __init__(self):
        self.calls: list = []

    async def start_session(self, job) -> None:
        job.session_id = job.id
        job.serve_url = "fake://"

    async def run_turn(self, job, text: str):
        from topoone.plugins.runner.turn_adapter import TurnOutcome
        return TurnOutcome(output=f"done: {text} [[IMPLEMENT_DONE]]")

    async def probe(self, job) -> TurnProbe:
        return TurnProbe("idle", job.last_activity_ts)

    async def read_messages(self, job, display: bool = True):
        self.calls.append(("read_messages", display))
        return [{"role": "user", "content": "hi"}]

    async def get_usage(self, job):
        self.calls.append(("get_usage",))
        return {"usage": {"inputTokens": 10, "outputTokens": 5}}

    async def compare_checkpoint(self, job, run_count: int):
        self.calls.append(("compare_checkpoint", run_count))
        return {"changedFiles": ["a.py"]}

    async def restore_checkpoint(self, job, run_count: int, options=None):
        self.calls.append(("restore_checkpoint", run_count, options))
        return {"sessionId": job.id}

    async def update_model(self, job, model_id: str):
        self.calls.append(("update_model", model_id))
        return True

    async def respond_approval(self, job, request_id, approved, reason=""):
        self.calls.append(("respond_approval", request_id, approved, reason))
        return True

    async def list_pending_prompts(self, job):
        self.calls.append(("list_pending_prompts",))
        return []

    async def proceed_while_running(self, job, tool_call_id=None):
        self.calls.append(("proceed_while_running", tool_call_id))
        return None


class _BareAdapter(TurnAdapter):
    """无内省能力的执行器（旧 opencode 型）。"""

    executor_id = "fake-bare"
    executor_type = "opencode"

    async def start_session(self, job) -> None:
        job.session_id = job.id
        job.serve_url = "fake://"

    async def run_turn(self, job, text: str):
        from topoone.plugins.runner.turn_adapter import TurnOutcome
        return TurnOutcome(output="ok")


@pytest.fixture()
def client():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    impl.register(app)
    impl._JOBS.clear()
    with TestClient(app) as c:
        yield c
    impl._JOBS.clear()


def _mk_job(adapter):
    j = impl.ImplementJob("impl-cap", "/tmp/x", "/tmp/x-wt", "HEAD", "b", "i",
                          adapter=adapter, auto_start=False)
    impl._JOBS[j.id] = j
    return j


def test_messages_endpoint(client):
    a = _CapableAdapter()
    _mk_job(a)
    r = client.get("/api/implement/impl-cap/messages").json()
    assert r["ok"] is True
    assert r["messages"][0]["content"] == "hi"
    assert a.calls == [("read_messages", True)]


def test_usage_endpoint(client):
    a = _CapableAdapter()
    _mk_job(a)
    r = client.get("/api/implement/impl-cap/usage").json()
    assert r["ok"] is True
    assert r["usage"]["usage"]["inputTokens"] == 10


def test_checkpoints_and_restore(client):
    a = _CapableAdapter()
    _mk_job(a)
    r = client.get("/api/implement/impl-cap/checkpoints?runCount=2").json()
    assert r["ok"] is True and r["compare"]["changedFiles"] == ["a.py"]
    r2 = client.post("/api/implement/impl-cap/restore",
                     json={"runCount": 2, "options": {"workspace": True}}).json()
    assert r2["ok"] is True
    assert ("restore_checkpoint", 2, {"workspace": True}) in a.calls


def test_model_and_approval_endpoints(client):
    a = _CapableAdapter()
    _mk_job(a)
    r = client.post("/api/implement/impl-cap/model",
                    json={"modelId": "gpt-x"}).json()
    assert r["ok"] is True
    r2 = client.post("/api/implement/impl-cap/approval",
                     json={"requestId": "apr-1", "approved": False,
                           "reason": "越界"}).json()
    assert r2["ok"] is True
    assert ("respond_approval", "apr-1", False, "越界") in a.calls


def test_bare_adapter_reports_unsupported(client):
    _mk_job(_BareAdapter())
    for path in ("/api/implement/impl-cap/messages",
                 "/api/implement/impl-cap/usage"):
        r = client.get(path).json()
        assert r["ok"] is False
        assert "不支持" in r["error"]
    r = client.post("/api/implement/impl-cap/approval",
                    json={"requestId": "x", "approved": True}).json()
    assert r["ok"] is False


def test_missing_job_404_shape(client):
    r = client.get("/api/implement/nope/messages").json()
    assert r["ok"] is False
    assert "不存在" in r["error"]


# ── P5: workspaceFiles 落盘（rules/agents 路径映射 + 穿越防护）──────────────

def test_workspace_files_written(tmp_path, monkeypatch):
    import asyncio
    import os
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from topoone.plugins.runner import implement as impl_mod

    app = FastAPI()
    impl_mod.register(app)
    impl_mod._JOBS.clear()

    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    import subprocess
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=root, capture_output=True)
    (root / "f.txt").write_text("x")
    subprocess.run(["git", "add", "-A"], cwd=root, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "i"], cwd=root, capture_output=True)

    captured = {}

    class _CapAdapter(_CapableAdapter):
        async def start_session(self, job):
            captured["wt"] = job.wt
            job.session_id = job.id
            job.serve_url = "fake://"

    saved = impl_mod._JOBS

    def fake_create(req):
        # 劫持真实 create 的 adapter 构建：直接注入能力假件
        return orig_create(req)

    with TestClient(app) as c:
        orig_create = None
        body = {
            "root": str(root),
            "instruction": "写代码",
            "workspaceFiles": [
                {"path": ".cline/rules/000-guide.md", "content": "规约文本"},
                {"path": ".cline/agents/helper.md", "content": "helper 角色"},
                {"path": "../escape.txt", "content": "恶意"},
            ],
        }
        # 直接调 _write_workspace_files 验证行为（不起真执行器）
        wt = str(tmp_path / "wt-x")
        os.makedirs(wt)
        written = impl_mod._write_workspace_files(wt, body["workspaceFiles"])
        assert ".cline/rules/000-guide.md" in written
        assert ".cline/agents/helper.md" in written
        assert all("escape" not in w for w in written)   # 穿越被拒
        assert (tmp_path / "escape.txt").exists() is False
        assert (tmp_path / "wt-x/.cline/rules/000-guide.md").read_text() == "规约文本"
    impl_mod._JOBS = saved


# ── 遗漏补齐: pending/proceed 透传端点 ─────────────────────────────────────

def test_pending_and_proceed_endpoints(client):
    a = _CapableAdapter()
    _mk_job(a)

    async def fake_pending(job):
        return [{"id": "p1", "prompt": "x"}]

    async def fake_proceed(job, tool_call_id=None):
        return 0

    a.list_pending_prompts = fake_pending
    a.proceed_while_running = fake_proceed
    r = client.get("/api/implement/impl-cap/pending").json()
    assert r["ok"] is True and r["prompts"][0]["id"] == "p1"
    r2 = client.post("/api/implement/impl-cap/proceed", json={}).json()
    assert r2["ok"] is True and r2["exitCode"] == 0


def test_pending_proceed_unsupported(client):
    _mk_job(_BareAdapter())
    r = client.get("/api/implement/impl-cap/pending").json()
    assert r["ok"] is False and "不支持" in r["error"]
    r2 = client.post("/api/implement/impl-cap/proceed", json={}).json()
    assert r2["ok"] is False


def test_inplace_always(client, tmp_path, monkeypatch):
    """cv-201 裁决: **无条件就地**——作业直接在项目 root 执行。

    与 git 状态无关: 非 git 目录、git init 的空项目, 一律就地;
    不建 worktree、不初始化仓库、不碰用户工作树的 git 状态。"""
    calls = []

    class _StartAdapter(_CapableAdapter):
        async def start_session(self, job) -> None:
            calls.append(job.wt)
            job.session_id = job.id
            job.serve_url = "fake://"

    monkeypatch.setattr(impl, "build_adapter", lambda *a, **k: _StartAdapter())

    import subprocess

    # ① 非 git 目录: 就地, 不产生 .git
    root = tmp_path / "blank"
    root.mkdir()
    r = client.post("/api/implement", json={
        "root": str(root), "instruction": "搭建环境",
        "executorType": "fake-cline", "autoStart": False}).json()
    assert r["ok"] is True, r
    assert r["workspace"] == "inplace" and r["worktree"] == str(root)
    assert calls[-1] == str(root)
    assert not (root / ".git").exists()

    # ② git init 的空项目: 同样就地(隔离目录里配依赖毫无意义)
    root2 = tmp_path / "inited"
    root2.mkdir()
    subprocess.run(["git", "init"], cwd=root2, capture_output=True)
    r2 = client.post("/api/implement", json={
        "root": str(root2), "instruction": "配依赖",
        "executorType": "fake-cline", "autoStart": False}).json()
    assert r2["ok"] is True and r2["workspace"] == "inplace"
    assert r2["worktree"] == str(root2)

    # ③ 有 git 仓库且带用户未提交工作: 作业后不卷入用户工作(不 auto-commit)
    root3 = tmp_path / "repo"
    root3.mkdir()
    subprocess.run(["git", "init"], cwd=root3, capture_output=True)
    (root3 / "user_wip.txt").write_text("用户的未提交工作")
    r3 = client.post("/api/implement", json={
        "root": str(root3), "instruction": "任务",
        "executorType": "fake-cline", "autoStart": False}).json()
    assert r3["ok"] is True
    st = subprocess.run(["git", "status", "--porcelain"], cwd=root3,
                        capture_output=True, text=True).stdout
    assert "user_wip.txt" in st   # 用户的改动仍在工作区(未被 auto-commit 卷走)
