"""runner /api/implement 契约形状锁定(P0 黄金快照)。

九层重构 P3 将对 implement.py 做 schema 化(events.py JobEvent)与宿主重组。
本测试锁定对外形状——任何变更必须显式更新本文件(契约纪律: 只增不改)。

锁定面:
  - snapshot() 顶层键集 + 事件条目键集(含 changedFiles 附加)
  - emit 事件基础键 {seq,ts,kind,text} + extra 合并
  - user_input / finish 响应键集
  - WS 订阅事件 = 环内事件同形状(JSON 可序列化)

Run: cd <repo> && python -m pytest packages/core/tests/test_runner_contract.py -q
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner.turn_adapter import TurnAdapter, TurnOutcome  # noqa: E402
from topoone.plugins.runner.implement import ImplementJob  # noqa: E402

SNAPSHOT_KEYS = {"jobId", "status", "error", "branch", "worktree", "root",
                 "boundaries", "sessionId", "executorId", "lastActivityTs",
                 "turnContext", "pendingApprovals", "events"}
EVENT_BASE_KEYS = {"seq", "ts", "kind", "text"}


class _FakeAdapter(TurnAdapter):
    executor_id = "fake"

    async def start_session(self, job) -> None:
        job.session_id = "s1"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        return TurnOutcome(output=text, changed_files=[])

    async def probe(self, job):
        raise NotImplementedError


def _job(**kw) -> ImplementJob:
    return ImplementJob("j-contract", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                        branch="exec/t", instruction="do",
                        adapter=_FakeAdapter(), **kw)


def test_snapshot_shape_golden():
    """snapshot 顶层键集锁定(多键少键都算契约破坏)。"""
    j = _job()
    snap = j.snapshot()
    assert set(snap.keys()) == SNAPSHOT_KEYS, f"snapshot 键漂移: {set(snap.keys())}"
    assert snap["events"] == []
    assert snap["boundaries"] == {}
    assert snap["executorId"] == "fake"


def test_event_base_keys_and_extra_merge():
    """事件基础键 {seq,ts,kind,text} + extra 合并(done 带 changedFiles)。"""
    j = _job()
    s1 = j.emit("session_ready", "ready")
    ev1 = next(e for e in j.events if e["seq"] == s1)
    assert set(ev1.keys()) == EVENT_BASE_KEYS
    assert isinstance(ev1["ts"], int) and ev1["text"] == "ready"
    s2 = j.emit("input_required", "需要确认", changedFiles=["a.py"])
    ev2 = next(e for e in j.events if e["seq"] == s2)
    assert set(ev2.keys()) == EVENT_BASE_KEYS | {"changedFiles"}
    assert ev2["changedFiles"] == ["a.py"]
    # seq 单调递增; snapshot since 过滤
    assert s2 > s1
    assert [e["seq"] for e in j.snapshot(since=s1)["events"]] == [s2]


def test_turn_terminal_event_shapes():
    """run_turn 终态事件: done/input_required 均带 changedFiles(键集锁定)。"""
    j = _job()
    j.status = "running"
    asyncio.run(j._run_turn("完成 [[IMPLEMENT_DONE]] 摘要"))
    done = j.events[-1]
    assert done["kind"] == "done"
    assert set(done.keys()) == EVENT_BASE_KEYS | {"changedFiles"}
    j2 = _job()
    j2.status = "running"
    asyncio.run(j2._run_turn("无标记分析"))
    ask = j2.events[-1]
    assert ask["kind"] == "input_required"
    assert set(ask.keys()) == EVENT_BASE_KEYS | {"changedFiles"}


def test_user_input_response_shape():
    """user_input 响应: 排队 {ok,queued} / 终态 {ok,error}。"""
    j = _job()
    r = asyncio.run(j.user_input("补充"))
    # A6.4: delivery 协议位(steered|queued|started) + reason 必备
    assert {"ok", "queued", "delivery", "steered", "reason"} <= set(r.keys())
    assert r["queued"] is False and r["delivery"] == "started"
    j2 = _job()
    j2._busy = True
    r2 = asyncio.run(j2.user_input("排队"))
    assert r2["queued"] is True and r2["delivery"] == "queued"
    j3 = _job()
    j3.status = "done"
    r3 = asyncio.run(j3.user_input("拒收"))
    assert set(r3.keys()) == {"ok", "error"} and r3["ok"] is False


def test_finish_response_shape(tmp_path):
    """finish 响应键集: ok/status/worktree/branch/executorId + diff 四键。"""
    import subprocess
    repo = tmp_path / "repo"
    repo.mkdir()
    def _g(*a):
        subprocess.run(["git", *a], cwd=repo, check=True, capture_output=True)
    _g("init", "-q")
    _g("config", "user.email", "t@t")
    _g("config", "user.name", "t")
    (repo / "base.txt").write_text("base\n")
    _g("add", "-A")
    _g("commit", "-qm", "base")
    _g("worktree", "add", "-b", "exec/t", str(tmp_path / "wt"))
    (tmp_path / "wt" / "new.txt").write_text("hello\n")
    j = ImplementJob("j-contract", root=str(repo), wt=str(tmp_path / "wt"),
                     base="HEAD", branch="exec/t", instruction="do",
                     adapter=_FakeAdapter())
    out = asyncio.run(j.finish(keep_worktree=True))
    assert set(out.keys()) == {"ok", "status", "worktree", "branch", "executorId",
                               "changedFiles", "diff", "addLines", "delLines"}
    assert out["ok"] is True and out["status"] == "stopped"
    assert "new.txt" in out["changedFiles"]
    # cv-201 就地模式: 不产 diff 正文(不碰用户索引), 变更清单只读可用
    assert out["addLines"] == 0 and out["delLines"] == 0


def test_ws_subscriber_event_is_ring_event():
    """WS 订阅面扇出的事件 = 环内同一条(JSON 可序列化, 形状一致)。"""
    j = _job()
    q = j.subscribe()
    j.emit("progress", "", toolCount=3, msgCount=1)
    ev = q.get_nowait()
    assert set(ev.keys()) == EVENT_BASE_KEYS | {"toolCount", "msgCount"}
    assert json.loads(json.dumps(ev)) == ev     # WS 序列化保形
