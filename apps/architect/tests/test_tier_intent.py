"""P1 特征测试: tierSuggested 挡位建议(#3) + 受限 LLM 意图兜底(#5)。

防守线②: 建议纯读永不写档案, 人工已设(manual)让位。
#5: 误路由遥测恒开只观测; LLM 兜底缺省关; 正则命中短路; 缓存; 失败 fail-soft;
LLM 意图只产软提示不入硬闸(由 S0 flow_policy 确定性匹配器保证)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_tier_intent.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.reflection import dataset as llm_dataset
from topoone_app_architect.agent.reflection import tier_suggest
from topoone_app_architect.agent.turns import goal as gu
from topoone_app_architect.agent.turns import intent_llm


def _set_policy(raw: dict) -> None:
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.agent.governance import flow_policy as fp
    store.CollabConfigStore.set(fp.POLICY_KEY, json.dumps(raw, ensure_ascii=False))


def _seed(model: str, calls: int, fails: int) -> None:
    for i in range(calls):
        llm_dataset.record("llm_call", model=model, ok=i >= fails)


# ── #3 tierSuggested(建议值+人审) ─────────────────────────────────────

def test_suggest_never_writes_and_yields_manual(arch_env):
    """防守线②: 纯读; manual 让位; 采纳只能走人工端点。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    _seed("ma", 10, 8)                      # 失败率 0.8 → 建议升档
    _seed("mb", 10, 8)
    mp.set_manual_tier("mb", 1)             # 人工已设
    before = json.dumps(mp.all_profiles(), sort_keys=True)
    res = tier_suggest.suggest_tiers()
    after = json.dumps(mp.all_profiles(), sort_keys=True)
    assert before == after                  # 纯读: 档案零写入
    rows = {r["modelId"]: r for r in res["suggestions"]}
    assert rows["ma"]["tierSuggested"] == 0  # heuristic 档1 → 建议升到 0
    assert rows["mb"]["manualPinned"] is True
    assert rows["mb"]["tierSuggested"] is None


def test_suggest_low_fail_suggests_downgrade(arch_env):
    from topoone_app_architect.agent.cognition import model_profile as mp
    _seed("mc", 10, 0)                      # 失败率 0 → 建议降档省算力
    res = tier_suggest.suggest_tiers()
    rows = {r["modelId"]: r for r in res["suggestions"]}
    assert rows["mc"]["tierSuggested"] == 2


def test_suggest_min_calls_gate(arch_env):
    _seed("md", 5, 5)                       # 调用量不足 → 不建议
    _set_policy({"tierSuggestion": {"minCalls": 50}})
    try:
        res = tier_suggest.suggest_tiers()
        rows = {r["modelId"]: r for r in res["suggestions"]}
        assert rows["md"]["tierSuggested"] is None
    finally:
        _set_policy({})


def test_tier_suggestions_rest(arch_env, client):
    _seed("me", 10, 9)
    r = client.get("/api/architect/llm/model-profiles/tier-suggestions")
    assert r.status_code == 200
    rows = {x["modelId"]: x for x in r.json()["data"]["suggestions"]}
    assert rows["me"]["tierSuggested"] == 0


# ── #5 受限 LLM 意图分类(GU-L2) ───────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_cache():
    intent_llm._CACHE.clear()
    yield
    intent_llm._CACHE.clear()


def _stub_llm(monkeypatch, payload=None, counter=None):
    import topoone_app_architect.arch_routes.req_agent as ra

    def _fake(*a, **kw):
        if counter is not None:
            counter.append(1)
        if payload is None:
            return {}
        return {"output": payload}
    monkeypatch.setattr(ra, "llm_sync", _fake)


def _set_escalation(on: bool) -> None:
    from topoone_app_architect.agent.governance import flow_policy as fp
    from topoone_app_architect.arch_routes import store
    store.CollabConfigStore.set(fp.POLICY_KEY, json.dumps(
        {"goal": {"escalation": {"llmFallback": on, "minConfidence": 0.7,
                                 "maxTextChars": 200}}}))


def test_l2_off_by_default(arch_env, monkeypatch):
    """缺省关: escalation.llmFallback=False → 零 LLM 调用, profile 原样。"""
    calls: list = []
    _stub_llm(monkeypatch, counter=calls)
    p = gu.build_goal_profile("帮我把这个项目跑起来", {})
    assert p["kind"] == "inquiry" and calls == []


def test_l2_upgrades_inquiry_to_operation(arch_env, monkeypatch):
    _set_escalation(True)
    calls: list = []
    _stub_llm(monkeypatch, payload={"intent": "generic_exec", "confidence": 0.9},
              counter=calls)
    q = "帮我把这个项目跑起来"            # L0 未命中(无 检测/运行/跑一下 等词)
    p = gu.build_goal_profile(q, {}, escalation={
        "llmFallback": True, "minConfidence": 0.7, "maxTextChars": 200})
    assert p["kind"] == "operation" and "llm" in p["sources"]
    # 缓存: 二次分类零 LLM 调用
    gu.build_goal_profile(q, {}, escalation={
        "llmFallback": True, "minConfidence": 0.7, "maxTextChars": 200})
    assert len(calls) == 1
    # 低置信 → 不升格(负结果缓存)
    _stub_llm(monkeypatch, payload={"intent": "generic_exec", "confidence": 0.3},
              counter=calls)
    intent_llm._CACHE.clear()
    p2 = gu.build_goal_profile("把临时日志目录清一清", {}, escalation={
        "llmFallback": True, "minConfidence": 0.7, "maxTextChars": 200})
    assert p2["kind"] == "inquiry" and len(calls) == 2


def test_l2_never_overrides_deterministic_hits(arch_env, monkeypatch):
    """防守线①: L2 只在 L0 无信号时参与, 确定性命中不被改写。"""
    _set_escalation(True)
    _stub_llm(monkeypatch, payload={"intent": "kb_analysis", "confidence": 0.99})
    # L0 策略命中(requirement)不受 LLM 影响
    p = gu.build_goal_profile("帮我搭建开发环境", {}, escalation={
        "llmFallback": True, "minConfidence": 0.5, "maxTextChars": 200})
    assert p["kind"] == "requirement" and p["strategy"] == "env_setup"


def test_classify_intent_direct(arch_env, monkeypatch):
    calls: list = []
    _stub_llm(monkeypatch, payload={"intent": "kb_analysis", "confidence": 0.8},
              counter=calls)
    r = intent_llm.classify_intent("帮我把这个项目跑起来")
    assert r == {"intent": "kb_analysis", "confidence": 0.8}
    assert intent_llm.classify_intent("帮我把这个项目跑起来") == r
    assert len(calls) == 1                       # 缓存生效
    assert intent_llm.classify_intent("") is None


def test_misroute_telemetry_observes_only(arch_env):
    intent_llm.misroute_telemetry(
        "把这个服务跑起来看看", "我无法直接运行服务, 需要先调用检索工具查询。")
    st = llm_dataset.stats()
    assert "intent_misroute" in st["kinds"]
    # 问题命中正则 → 非误路由, 不记
    n0 = st["kinds"].get("intent_misroute", {}).get("count", 0)
    intent_llm.misroute_telemetry(
        "检测一下编译环境", "我无法直接检测, 需要先查询。")
    n1 = llm_dataset.stats()["kinds"].get("intent_misroute", {}).get("count", 0)
    assert n1 == n0
    # 回复无推诿话术 → 不记
    intent_llm.misroute_telemetry("把这个服务跑起来看看", "好的, 已为你建卡。")
    n2 = llm_dataset.stats()["kinds"].get("intent_misroute", {}).get("count", 0)
    assert n2 == n0


def test_policy_new_keys_validation():
    from topoone_app_architect.agent.governance import flow_policy as fp
    ok, errs = fp.validate_flow_policy({"goal": {
        "escalation": {"maxTextChars": 10},
        "strategies": [{"key": "x", "kws": ["a"],
                        "questions": [["乱写", "q"]]}]}})
    assert not ok and any("maxTextChars" in e for e in errs) \
        and any("要素非法" in e for e in errs)
    ok, errs = fp.validate_flow_policy({"goal": {
        "escalation": {"llmFallback": True, "minConfidence": 0.8,
                       "maxTextChars": 200}}})
    assert ok, errs


def test_guard_stays_regex_only_with_llm_switch_on(arch_env, monkeypatch):
    """防守线①: L2 开启也不影响相位硬闸——硬闸只消费确定性匹配器。"""
    from topoone_app_architect.agent.governance import flow
    from topoone_app_architect.agent.governance.flow_policy import (
        deep_merge, DEFAULT_FLOW_POLICY)
    from topoone_app_architect.arch_routes.store.states import FLOW_INTERRUPTED
    _stub_llm(monkeypatch, payload={"intent": "generic_exec", "confidence": 0.9})
    pol = deep_merge(DEFAULT_FLOW_POLICY, {"phases": {"interrupted": {
        "guards": [{"intents": ["generic_exec"], "reply": "⛔拦截"}]}}})
    # 硬闸判定与文本匹配有关, 与 LLM 无关(本测试不触 LLM 通道)
    assert flow.phase_guard(FLOW_INTERRUPTED, "帮我部署服务", pol) == "⛔拦截"
    assert flow.phase_guard(FLOW_INTERRUPTED, "刚才为什么失败?", pol) is None
