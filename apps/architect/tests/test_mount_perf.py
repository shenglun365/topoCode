"""挂载热路径性能治理 — 事件循环阻塞回归锁定(2026-10 双窗口卡死事故)。

事故机制: /agent/executors/env 在 async 路由内同步跑 3 次
subprocess(--version), 冻结事件循环(实测 0.54s/次, 4 并发完美串行 2.17s,
同刻 5ms 端点被拖到 0.54s)。锁定:
  - env detect: 进程级 TTL 缓存 + to_thread + force 绕过
  - runner health: to_thread + 2s 短缓存
  - repo_status: 单次 git status -b 解析 branch/ahead/behind + 2s 缓存
  - /agent/executors/env 与 /agent/executors 路由可并发(不串行)

Run: cd <repo> && python -m pytest apps/architect/tests/test_mount_perf.py -q
"""
import asyncio
import os
import sys
import time

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import agent_executors as ae
from topoone_app_architect.arch_routes import arch_git


@pytest.fixture()
def env_isolated(monkeypatch):
    """清空 env/runner 缓存, 隔离 _env_detect 真实 spawn。"""
    ae._ENV_CACHE.update(data=None, ts=0.0)
    ae._runner_health_cache.update(data=None, ts=0.0)
    monkeypatch.setattr(ae, "_env_detect", lambda: {"opencode": {"installed": False}})
    yield


@pytest.mark.asyncio
async def test_env_cache_ttl_and_force(env_isolated):
    r1 = await ae.executors_env()
    r2 = await ae.executors_env()
    assert r1["data"] == r2["data"]
    calls = {"n": 0}
    orig = ae._env_detect

    def counting():
        calls["n"] += 1
        return orig()

    ae._ENV_CACHE.update(data={"cached": True}, ts=time.monotonic())
    r3 = await ae.executors_env()
    assert r3["data"] == {"cached": True}          # TTL 内命中, 不再 spawn
    r4 = await ae.executors_env(force=True)         # force 绕过
    assert "cached" not in r4["data"]


@pytest.mark.asyncio
async def test_env_concurrent_not_serialized(env_isolated, monkeypatch):
    """并发 env 不串行(to_thread)——事故回归锁定。"""
    def slow():
        time.sleep(0.3)
        return {"slow": True}

    monkeypatch.setattr(ae, "_env_detect", slow)
    ae._ENV_CACHE.update(data=None, ts=0.0)
    t0 = time.monotonic()
    await asyncio.gather(ae.executors_env(), ae.executors_env(force=True))
    elapsed = time.monotonic() - t0
    assert elapsed < 0.6, f"并发 env 被串行化: {elapsed:.2f}s (应 ≈0.3s)"


@pytest.mark.asyncio
async def test_runner_health_cached(env_isolated, monkeypatch):
    calls = {"n": 0}

    def fake_runner(path, timeout=5.0):
        calls["n"] += 1
        return {"ok": True}

    monkeypatch.setattr(ae, "_get_runner", fake_runner)
    r1 = await ae._runner_health()
    r2 = await ae._runner_health()
    assert r1 == r2 and calls["n"] == 1             # 2s TTL 内只打一次


def test_repo_status_parses_branch_and_dirty(tmp_path):
    """真实临时仓库: status -b 单次解析 branch/dirty; 2s 缓存命中。"""
    import subprocess
    r = str(tmp_path / "repo")
    os.makedirs(r)
    def g(*args):
        subprocess.run(["git", "-C", r, *args], capture_output=True, check=True)
    g("init", "-q")
    g("config", "user.email", "t@t")
    g("config", "user.name", "t")
    arch_git._status_cache.clear()
    st = arch_git.repo_status(r)
    assert st["dirty"] is False and st["branch"]    # main/master 视 git 版本
    (open(os.path.join(r, "f.txt"), "w")).write("x")
    arch_git._status_cache.clear()
    st2 = arch_git.repo_status(r)
    assert st2["dirty"] is True
    # 缓存: 再查(文件又改)仍返回缓存快照
    (open(os.path.join(r, "f.txt"), "a")).write("y")
    st3 = arch_git.repo_status(r)
    assert st3 == st2


def test_repo_status_non_repo(tmp_path):
    arch_git._status_cache.clear()
    st = arch_git.repo_status(str(tmp_path))
    assert st["dirty"] is True and st["branch"] == ""   # 非 git 目录: 保守 dirty
