"""CallTurn 单项调用语义测试(R3.1 链3收编, 整体设计 §4/§9-M3)。

覆盖: 分目的脚手架(仅 T2 追加)/按挡重试策略(T0 即报 T1 nudge1 T2 nudge2)/
确定性兜底(degraded 语义)/校验失败 nudge 提示。llm_sync 经 req_agent 模块
属性打桩(与既有测试同款接缝)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_call_turn.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.agent.tools.req_agent as _ra
from topoone_app_architect.agent.compensation.ctx import Purpose
from topoone_app_architect.agent.turns.call import call, retry_for, scaffold_for

_OK = {"title": "T", "requirementMd": "R"}


def test_scaffold_only_appends_for_t2():
    assert scaffold_for(Purpose.EXTRACTION, "T0") == ""
    assert scaffold_for(Purpose.EXTRACTION, "T1") == ""
    s = scaffold_for(Purpose.EXTRACTION, "T2")
    assert "逐项" in s and "禁止编造" in s
    assert "禁止跨模块" in scaffold_for(Purpose.SPLIT, "T2")
    assert "source" in scaffold_for(Purpose.PROBE, "T2")
    assert scaffold_for(Purpose.SUMMARY, "T2") == ""      # 未登记目的无脚手架


def test_retry_policy_by_tier():
    """2610 挡位退役: 统一策略 nudge 恒 1(dict 形状保留)。"""
    assert retry_for("T0").max_nudges == 1
    assert retry_for("T1").max_nudges == 1
    assert retry_for("T2").max_nudges == 1


def test_call_first_attempt_ok(monkeypatch):
    seen = {}

    def _ok(msgs, **kw):
        seen["msgs"] = msgs
        return {"output": dict(_OK), "content": ""}

    monkeypatch.setattr(_ra, "llm_sync", _ok)
    r = call(Purpose.EXTRACTION, [{"role": "user", "content": "x"}],
             tier="T2", schema={"type": "object"})
    assert r["ok"] and r["attempts"] == 1 and not r["degraded"]
    assert r["output"]["title"] == "T"
    assert seen["msgs"][-1]["role"] == "user"           # T2 脚手架已注入


def test_call_retry_then_success(monkeypatch):
    calls = {"n": 0, "last_msgs": []}

    def _flaky(msgs, **kw):
        calls["n"] += 1
        calls["last_msgs"] = msgs
        if calls["n"] == 1:
            return {"output": None, "content": ""}
        return {"output": dict(_OK), "content": ""}

    monkeypatch.setattr(_ra, "llm_sync", _flaky)
    r = call(Purpose.EXTRACTION, [{"role": "user", "content": "x"}],
             tier="T1", schema={"type": "object"},
             validate=lambda p: (isinstance(p, dict) and bool(p.get("title")),
                                 "缺少 title"))
    assert r["ok"] and r["attempts"] == 2
    assert any("未通过校验" in m["content"] for m in calls["last_msgs"])


def test_call_t0_fails_fast(monkeypatch):
    calls = {"n": 0}

    def _always_none(msgs, **kw):
        calls["n"] += 1
        return {"output": None, "content": ""}

    monkeypatch.setattr(_ra, "llm_sync", _always_none)
    r = call(Purpose.EXTRACTION, [{"role": "user", "content": "x"}],
             tier="T1", schema={"type": "object"})
    assert not r["ok"] and calls["n"] == 2 and not r["degraded"]   # 1 原始 + 1 nudge


def test_call_exhausted_falls_back(monkeypatch):
    calls = {"n": 0}

    def _always_none(msgs, **kw):
        calls["n"] += 1
        return {"output": None, "content": ""}

    monkeypatch.setattr(_ra, "llm_sync", _always_none)
    r = call(Purpose.EXTRACTION, [{"role": "user", "content": "x"}],
             tier="T1", schema={"type": "object"},
             fallback=lambda: {"__clarify__": True})
    assert r["ok"] and r["degraded"] and r["output"] == {"__clarify__": True}
    assert calls["n"] == 2                              # 1 次原始 + 1 次 nudge(统一)


def test_call_exhausted_no_fallback(monkeypatch):
    monkeypatch.setattr(_ra, "llm_sync",
                        lambda msgs, **kw: {"output": None, "content": ""})
    r = call(Purpose.SPLIT, [{"role": "user", "content": "x"}],
             tier="T1", schema={"type": "object"}, fallback=lambda: None)
    assert not r["ok"] and not r["degraded"]
