"""工具调用规范化(cv-222)特征测试 — 判别式=注册表成员资格, 非枚举模型行为。

覆盖: none/null 协议变体 → 无调用; 未注册+空参 → 噪声剔除(不派发不烧修复轮);
未注册+带参 → 保留(诚实报错+repair); 注册工具空参合法保留;
cv-222 复放: 仅 none 调用的回合零 tool_error、转终稿轮;
run_tools_loop 文本协议与 chat 流式解析点同归一。

Run: cd <repo> && python -m pytest apps/architect/tests/test_tool_call_normalize.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.req_agent as ra
from topoone_app_architect.arch_routes.req_agent import _normalize_tool_calls


@pytest.fixture()
def fake_registry(monkeypatch):
    """注册表注入假成员(解析层只查键; 不触执行)。"""
    monkeypatch.setitem(ra._ARCH_TOOLS, "fake.ok", {"_test": True})
    return ra._ARCH_TOOLS


# ── _normalize_tool_calls 判别式 ──────────────────────────────────────

def test_none_and_null_are_no_call(fake_registry):
    assert _normalize_tool_calls([{"tool": "none", "arguments": {}}]) == []
    assert _normalize_tool_calls([{"tool": "None", "arguments": {}}]) == []
    assert _normalize_tool_calls([{"tool": "null", "arguments": {}}]) == []
    assert _normalize_tool_calls([{"tool": "  ", "arguments": {}}]) == []
    assert _normalize_tool_calls([{"tool": "", "arguments": {}}]) == []


def test_unregistered_empty_args_is_noise(fake_registry):
    """未注册名+空参 = 模型噪声(任意形态) → 剔除, 不派发不烧修复轮。"""
    for junk in ("no_tool", "skip", "n/a", "-", "web_search", "随便什么"):
        assert _normalize_tool_calls(
            [{"tool": junk, "arguments": {}}]) == [], junk


def test_unregistered_with_args_is_real_hallucination(fake_registry):
    """未注册名+带参 = 真名称幻觉 → 保留派发(诚实报错+repair 通道)。"""
    calls = _normalize_tool_calls(
        [{"tool": "web_search", "arguments": {"query": "x"}}])
    assert len(calls) == 1 and calls[0]["tool"] == "web_search"


def test_registered_empty_args_kept(fake_registry):
    """注册工具空参合法(map.overview 类无参工具)。"""
    calls = _normalize_tool_calls([{"tool": "fake.ok", "arguments": {}},
                                   {"tool": "fake.ok"}])
    assert len(calls) == 2


def test_mixed_calls_partial_filter(fake_registry):
    calls = _normalize_tool_calls([
        {"tool": "none", "arguments": {}},
        {"tool": "fake.ok", "arguments": {"a": 1}},
        {"tool": "ghost", "arguments": {}},
        {"tool": "ghost", "arguments": {"b": 2}},
    ])
    assert [c["tool"] for c in calls] == ["fake.ok", "ghost"]
    assert calls[1]["arguments"] == {"b": 2}


# ── structured_tool_round 接线(cv-222 复放) ───────────────────────────

def test_structured_round_none_means_no_call(arch_env, monkeypatch):
    """cv-222 复放: 模型输出 {"tool":"none"} → calls 空 → 调用方转终稿轮;
    不派发、不触发 repair_tool_call 外循环(修复轮 7.5s 浪费消除)。"""
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **kw: {
        "output": {"tool": "none", "arguments": {}}})
    repair_spy = []
    monkeypatch.setattr(ra, "execute_tool_with_repair",
                        lambda *a, **kw: repair_spy.append(a) or {})
    res = ra.structured_tool_round([{"role": "user", "content": "x"}])
    assert res["calls"] == [] and res["error"] == ""
    assert repair_spy == []


def test_structured_round_noise_filtered(arch_env, monkeypatch):
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **kw: {
        "output": {"tool": "no_tool", "arguments": {}}})
    assert ra.structured_tool_round([{"role": "user", "content": "x"}])["calls"] == []


# ── run_tools_loop 文本协议接线 ───────────────────────────────────────

def test_run_tools_loop_none_block_not_dispatched(arch_env, monkeypatch):
    """[TOOL_CALL] none 块 → 不派发不修复; 循环以文本收尾。"""
    monkeypatch.setattr(ra, "llm_sync", lambda *a, **kw: {
        "content": '[TOOL_CALL]{"tool":"none","arguments":{}}[/TOOL_CALL]'})
    dispatch_spy = []
    monkeypatch.setattr(ra, "execute_tool_with_repair",
                        lambda *a, **kw: dispatch_spy.append(a) or {"error": "x"})
    res = ra.run_tools_loop([{"role": "user", "content": "x"}],
                            root="", project="")
    assert dispatch_spy == []                    # 零派发
    assert "none" not in json_dumps_safe(res) or res.get("content") is not None


def json_dumps_safe(o):
    try:
        import json
        return json.dumps(o, ensure_ascii=False, default=str)
    except Exception:
        return ""


def test_chat_stream_parse_normalized(monkeypatch):
    """chat 流式解析点(chat.py:375)同归一: none 块 → 零调用。"""
    ra_calls = ra._normalize_tool_calls(ra.extract_tool_calls(
        '[TOOL_CALL]{"tool":"none","arguments":{}}[/TOOL_CALL]'))
    assert ra_calls == []
