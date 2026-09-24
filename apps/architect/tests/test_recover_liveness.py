"""对账循环 liveness 守门(cv-248) — 无出路状态不允许存在。

不变式 I1(出路): 任务判定不可操作时必须有一条不依赖丢失对象的出路。
N1 补口: runner 持续不可达超出容忍时限 → 显式 failed(既有「跳过等重启」
策略在 runner 进程级死亡时 = 永久 running 锁死执行互斥)。
回归面: 作业丢失显式 failed / runner 终态重放 / 重启窗口容忍(不误伤)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_recover_liveness.py -q
"""
import os
import sys
from types import SimpleNamespace

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.execution import recover as rc
from topoone_app_architect import store


@pytest.fixture()
def arch(arch_env):
    return arch_env


def _mk_running(arch, conv_id, job_id="job-x", age_min=20.0):
    """running 任务 + 历史化 updated_at(store 接口强制刷审计时间, 走 raw sqlite)。"""
    import sqlite3
    t = store.TasksStore.create({
        "conversationId": conv_id, "title": "T", "instruction": "x",
        "status": "running", "executorType": "cline-sdk",
        "runnerJobId": job_id,
    })
    past = int(__import__("time").time() * 1000 - age_min * 60 * 1000)
    con = sqlite3.connect(os.path.join(arch, "architect.db"))
    try:
        con.execute("UPDATE arch_tasks SET updated_at=? WHERE id=?",
                    (past, t["id"]))
        con.commit()
    finally:
        con.close()
    return t


def _stub_client(snapshot):
    class _C:
        def snapshot(self, job_id, timeout=0.0):
            return snapshot
    return _C()


def _patch_client(monkeypatch, snapshot):
    import topoone_app_architect.arch_routes.exec_bridge as eb
    monkeypatch.setattr(eb, "_client", lambda: _stub_client(snapshot))


# ── N1: 持续不可达 → 时限终态化(出路可达) ─────────────────────────────

def test_unreachable_beyond_limit_fails_task(arch, monkeypatch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running(arch, conv["id"], age_min=20.0)
    _patch_client(monkeypatch, None)            # runner 进程级不可达

    out = rc.recover_conv_tasks(conv["id"])

    assert out["finished"] == 1
    row = store.TasksStore.get(t["id"])
    assert (row.get("status") or "") == "failed"     # 出路: 终态释放执行互斥
    assert "不可达" in str(row.get("resultMd") or "")


def test_unreachable_within_window_still_skipped(arch, monkeypatch):
    """重启窗口容忍(≤15min): 跳过不误伤, 交下轮再判。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running(arch, conv["id"], age_min=2.0)
    _patch_client(monkeypatch, None)

    out = rc.recover_conv_tasks(conv["id"])

    assert out["finished"] == 0
    assert (store.TasksStore.get(t["id"]).get("status")) == "running"


# ── 回归: 既有出路保持 ────────────────────────────────────────────────

def test_lost_job_fails_explicitly(arch, monkeypatch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running(arch, conv["id"], job_id="job-gone", age_min=1.0)
    _patch_client(monkeypatch, SimpleNamespace(ok=False, error="作业不存在",
                                               events=[]))

    out = rc.recover_conv_tasks(conv["id"])

    assert out["finished"] == 1
    assert (store.TasksStore.get(t["id"]).get("status")) == "failed"


def test_runner_terminal_event_replayed(arch, monkeypatch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running(arch, conv["id"], age_min=1.0)
    _patch_client(monkeypatch, SimpleNamespace(
        ok=True, error="", events=[{"kind": "done", "text": "完成"}]))

    out = rc.recover_conv_tasks(conv["id"])

    assert out["finished"] == 1
    assert (store.TasksStore.get(t["id"]).get("status")) == "done"


# ── 不变式守门: 时限可配置(env), 非硬编码魔法数 ───────────────────────

def test_unreachable_limit_configurable(monkeypatch):
    monkeypatch.setenv("ARCH_RUNNER_UNREACHABLE_MIN", "7")
    import importlib
    importlib.reload(rc)
    assert rc._UNREACHABLE_LIMIT_MIN == 7.0
    monkeypatch.delenv("ARCH_RUNNER_UNREACHABLE_MIN")
    importlib.reload(rc)
    assert rc._UNREACHABLE_LIMIT_MIN == 15.0
