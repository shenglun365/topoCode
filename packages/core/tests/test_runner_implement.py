"""runner implement 作业宿主单测：注册/快照/输入缓冲/标记分类(不经真实 opencode)。

Run: cd <repo> && python -m pytest packages/core/tests/test_runner_implement.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner.implement import ImplementJob  # noqa: E402


def _job(**kw) -> ImplementJob:
    return ImplementJob("j1", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                        branch="exec/t", instruction="do", **kw)


def test_snapshot_and_events():
    j = _job()
    s1 = j.emit("session_ready", "ok")
    s2 = j.emit("input_required", "需要确认 A 还是 B?")
    snap = j.snapshot(since=s1)
    assert snap["status"] == "starting"
    assert [e["seq"] for e in snap["events"]] == [s2]
    assert "A 还是 B" in snap["events"][0]["text"]


def test_user_input_queues_while_busy():
    j = _job()
    j._busy = True                      # 模拟回合进行中
    j.status = "running"
    r = asyncio.run(j.user_input("用方案 B"))
    assert r["ok"] and r["queued"] is True
    assert j.pending_inputs == ["用方案 B"]
    # 终态拒收
    j.status = "done"
    r2 = asyncio.run(j.user_input("再改改"))
    assert not r2["ok"]


def test_turn_marker_classification(monkeypatch):
    """回合输出标记 → 状态分类(done/waiting_input)。"""
    class _FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"parts": [{"type": "text", "text": self._text}]}
    class _FakeClient:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        def post(self, url, json=None):
            r = _FakeResp(); r._text = json["parts"][0]["text"]; return _wrap(r)
        async def get(self, url): return _wrap(_FakeResp())
    class _Wrap:
        def __init__(self, r): self._r = r
        def raise_for_status(self): pass
        def json(self): return self._r.json()
    def _wrap(r): return _Wrap(r)

    async def _fake_turn(j, text):
        # 以假 client 跑真分类逻辑: 直接调内部方法并拦截 httpx
        import topoone.plugins.runner.implement as impl
        class _AC:
            def __init__(self, *a, **k): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None):
                out = {"parts": [{"type": "text", "text": json["parts"][0]["text"]}]}
                return _Resp(out)
            async def get(self, url): return _Resp({})
        class _Resp:
            def __init__(self, data): self._d = data
            def raise_for_status(self): pass
            def json(self): return self._d
        monkeypatch.setattr(impl.httpx, "AsyncClient", _AC)
        await impl.ImplementJob._run_turn(j, text)

    # done 标记
    j1 = _job(); j1.status = "running"; j1.session_id = "s"; j1.serve_url = "http://x"
    asyncio.run(_fake_turn(j1, "完成 [[IMPLEMENT_DONE]] 摘要"))
    assert j1.status == "done"
    assert j1.events[-1]["kind"] == "done"
    # need_input 标记
    j2 = _job(); j2.status = "running"; j2.session_id = "s"; j2.serve_url = "http://x"
    asyncio.run(_fake_turn(j2, "需要确认 [[NEED_INPUT]] 用哪个方案?"))
    assert j2.status == "waiting_input"
    assert j2.events[-1]["kind"] == "input_required"
    # 无标记 → 兜底 waiting_input
    j3 = _job(); j3.status = "running"; j3.session_id = "s"; j3.serve_url = "http://x"
    asyncio.run(_fake_turn(j3, "我先做了些分析…"))
    assert j3.status == "waiting_input"
