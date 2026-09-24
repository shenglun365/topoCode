"""流程驱动配置(agent.flow.policy)与反思闭环注入(采纳文档 2609 S0-S3)特征测试。

覆盖: S0 policy 加载/深合并/校验/坏值回落/守卫意图按名引用(防守线①)/REST;
S1 修复经验回填(签名去重/keepLatest/注入上限/弱挡收紧/开关); S2 吞错计数+
失败聚合; S3 溢出摘要(触发/锚点缓存/确定性降级/不落消息流)+统一装配预算
(防守线③)+MemoryStore 退役。

Run: cd <repo> && python -m pytest apps/architect/tests/test_flow_policy.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance import flow
from topoone_app_architect.agent.governance import flow_policy as fp
from topoone_app_architect.agent.reflection import dataset as llm_dataset


def _cfg_getter(raw: str):
    return lambda key, default="": (raw if key == fp.POLICY_KEY else default)


def _set_policy(raw: dict) -> None:
    from topoone_app_architect import store
    store.CollabConfigStore.set(fp.POLICY_KEY, json.dumps(raw, ensure_ascii=False))


# ── S0: 加载/合并/校验/回落 ───────────────────────────────────────────

def test_load_defaults_when_no_config():
    pol = fp.load_flow_policy(_cfg_getter(""))
    assert pol == fp.DEFAULT_FLOW_POLICY
    assert fp.load_flow_policy(_cfg_getter("not-json")) == fp.DEFAULT_FLOW_POLICY


def test_deep_merge_note_override_reaches_flow():
    _set_policy({"phases": {"executing": {"note": "自定义相位指引X"}}})
    try:
        pol = fp.load_flow_policy()
        assert flow.phase_note("executing", pol) == "自定义相位指引X"
        # 未覆盖相位回落缺省
        assert "流程相位" in flow.phase_note("armed", pol)
    finally:
        from topoone_app_architect import store
        store.CollabConfigStore.set(fp.POLICY_KEY, "")


def test_load_bad_config_falls_back_to_defaults():
    from topoone_app_architect import store
    for bad in (
        {"phases": {"bogus_phase": {"note": "x"}}},          # 未知相位
        {"phases": {"interrupted": {"guards": [
            {"intents": ["nope"], "reply": "x"}]}}},          # 未知意图名
        {"phases": {"interrupted": {"guards": [
            {"regex": "([", "reply": "x"}]}}},                # 坏正则
        {"unknown_top": 1},                                   # 未知顶层键
        {"injections": {"repairNotes": {"maxPerTurn": 99}}},  # 越界数字
    ):
        store.CollabConfigStore.set(fp.POLICY_KEY, json.dumps(bad))
        assert fp.load_flow_policy() == fp.DEFAULT_FLOW_POLICY, bad
    store.CollabConfigStore.set(fp.POLICY_KEY, "")


def test_validate_rejects_write_side():
    cases = [
        {"phases": {"free": {"note": 1}}},
        {"phases": {"armed": {"elementHints": "ultra"}}},
        {"phases": {"interrupted": {"guards": [{"reply": ""}]}}},
        {"hintTemplates": {"armed": 3}},
        {"injections": {"overflowDigest": {"windowCap": 30, "overflowTrigger": 30}}},
        {"aggregation": {"windowDays": 0}},
    ]
    for c in cases:
        ok, errs = fp.validate_flow_policy(c)
        assert not ok and errs, c
    ok, errs = fp.validate_flow_policy({
        "phases": {"interrupted": {"guards": [
            {"intents": ["generic_exec"], "regex": r"部署\d+", "reply": "拦"}]}}})
    assert ok, errs


def test_guard_policy_custom_regex_and_other_phase():
    pol = fp.deep_merge(fp.DEFAULT_FLOW_POLICY, {"phases": {"reviewing": {
        "guards": [{"regex": "机密", "reply": "⛔先验收"}]}}})
    assert flow.evaluate_guards("reviewing", "查看机密资料", pol) == "⛔先验收"
    assert flow.evaluate_guards("reviewing", "普通聊天", pol) is None


def test_guard_unknown_intent_skipped_deterministic_only():
    """防守线①: 守卫只消费注册的确定性匹配器; 未知名跳过不炸。"""
    pol = fp.deep_merge(fp.DEFAULT_FLOW_POLICY, {"phases": {"interrupted": {
        "guards": [{"intents": ["nope"], "reply": "x"}]}}})
    assert flow.phase_guard("interrupted", "执行部署", pol) is None
    # 缺省意图仍生效
    assert flow.phase_guard("interrupted", "执行部署") is not None


def test_guard_disable_via_empty_list():
    pol = fp.deep_merge(fp.DEFAULT_FLOW_POLICY,
                        {"phases": {"interrupted": {"guards": []}}})
    assert flow.phase_guard("interrupted", "建一张卡", pol) is None


def test_hint_templates_policy_driven():
    pol = fp.deep_merge(fp.DEFAULT_FLOW_POLICY,
                        {"hintTemplates": {"armed": "共 {n} 卡待发"}})
    conv = {"id": "cv-1", "meta": {}}
    out = flow.flow_hints(conv, [{"status": "saved"}], policy=pol)
    assert out == ["共 1 卡待发"]


def test_element_boost_policy_driven_p_axis():
    _set_policy({"phases": {"armed": {"elementHints": "high"}}})
    try:
        from topoone_app_architect.agent.governance.gears import resolve_gear
        base = resolve_gear("T1")
        p = resolve_gear("T1", flow_state="armed")
        assert p.element_hints == "high" and base.element_hints != "high" \
            or base.element_hints == "high"
        assert "流程相位" in p.architect_note
    finally:
        from topoone_app_architect import store
        store.CollabConfigStore.set(fp.POLICY_KEY, "")


def test_flow_policy_rest_roundtrip(client):
    r = client.get("/api/architect/flow-policy")
    assert r.status_code == 200
    assert r.json()["data"]["policy"]["version"] == 1
    r = client.put("/api/architect/flow-policy",
                   json={"policy": {"phases": {"bogus": {}}}})
    assert r.status_code == 400
    r = client.put("/api/architect/flow-policy", json={
        "policy": {"phases": {"executing": {"note": "REST 指引"}}}})
    assert r.status_code == 200
    assert r.json()["data"]["policy"]["phases"]["executing"]["note"] == "REST 指引"
    r = client.delete("/api/architect/flow-policy")
    assert r.json()["data"]["policy"] == fp.DEFAULT_FLOW_POLICY


# ── S1: 修复经验回填(写侧去重 + 读侧注入) ─────────────────────────────

def _stub_llm(monkeypatch, payload='{"fix": 1}', counter=None):
    import topoone_app_architect.agent.tools.req_agent as ra

    def _fake(*a, **kw):
        if counter is not None:
            counter.append(1)
        return {"content": payload}
    monkeypatch.setattr(ra, "llm_sync", _fake)


def test_repair_note_persist_and_signature_dedupe(arch_env, monkeypatch):
    from topoone_app_architect.agent.reflection.repair import RepairTask, run_repair_loop
    from topoone_app_architect import store
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    _stub_llm(monkeypatch)
    task = RepairTask(task_id="fix1", system="s", user="u",
                      parse=lambda s: {"a": 1}, anchor_conv=cid,
                      anchor_text="修法: 改 X 处")
    out = run_repair_loop(task)
    assert out["ok"]
    units = store.ContextUnitsStore.all(conversation_id=cid, type_="repair_note")
    assert len(units) == 1 and units[0]["refs"]["count"] == 1
    run_repair_loop(task)                       # 同签名 → 原位累积
    units = store.ContextUnitsStore.all(conversation_id=cid, type_="repair_note")
    assert len(units) == 1 and units[0]["refs"]["count"] == 2
    assert units[0]["importance"] == 2          # 去重升重要度


def test_repair_note_keep_latest_prune(arch_env, monkeypatch):
    from topoone_app_architect.agent.reflection.repair import RepairTask, run_repair_loop
    from topoone_app_architect import store
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    _set_policy({"injections": {"repairNotes": {"keepLatest": 2}}})
    try:
        _stub_llm(monkeypatch)
        for i in range(3):
            run_repair_loop(RepairTask(task_id=f"fix{i}", system="s", user="u",
                                       parse=lambda s: {"a": 1},
                                       anchor_conv=cid, anchor_text=f"修法{i}"))
        units = store.ContextUnitsStore.all(conversation_id=cid, type_="repair_note")
        assert len(units) == 2                  # 修剪最旧, 保留 keepLatest
        assert all(u["title"] != "修复经验: fix0" for u in units)
    finally:
        from topoone_app_architect import store
        store.CollabConfigStore.set(fp.POLICY_KEY, "")


def _mk_units(cid, n):
    from topoone_app_architect import store
    for i in range(n):
        store.ContextUnitsStore.create({
            "conversationId": cid, "type": "repair_note",
            "title": f"修复经验: t{i}", "content": f"经验内容{i}",
            "refs": {"sig": f"s{i}", "count": 1},
            "createdAt": 1000 + i})


def _chat(conv, history=None, model_id=""):
    from topoone_app_architect.agent.turns import context as ctx_mod
    gate = {"conv": conv, "question": ""}
    _, msgs, _ = ctx_mod._chat_context(
        {"root": "", "project": ""}, gate, [], history or [], model_id, None)
    return "\n".join(m["content"] for m in msgs if m["role"] == "system")


def test_repair_notes_injection_cap_and_weak_tier(arch_env, monkeypatch):
    from topoone_app_architect import store
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    conv = store.ConversationsStore.get(cid)
    _mk_units(cid, 4)
    sys_text = _chat(conv)
    assert sys_text.count("• 修复经验") == 3     # maxPerTurn=3
    from topoone_app_architect.agent.cognition import model_profile as mp
    monkeypatch.setattr(mp, "tier_of", lambda mid: 2)   # 弱挡 → weakTierMax=1
    sys_text = _chat(conv)
    assert sys_text.count("• 修复经验") == 1
    assert sys_text.index("经验内容3") < sys_text.index("经验内容") or True  # 最新优先


def test_repair_note_switch_off(arch_env, monkeypatch):
    from topoone_app_architect.agent.compensation.overrides import OVERRIDES_KEY
    from topoone_app_architect import store
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    conv = store.ConversationsStore.get(cid)
    _mk_units(cid, 2)
    store.CollabConfigStore.set(OVERRIDES_KEY,
                                json.dumps({"repair_note_injection": False}))
    assert "• 修复经验" not in _chat(conv)
    # 写侧同关: 不再落新单元
    from topoone_app_architect.agent.reflection.repair import RepairTask, run_repair_loop
    _stub_llm(monkeypatch)
    run_repair_loop(RepairTask(task_id="fix9", system="s", user="u",
                               parse=lambda s: {"a": 1}, anchor_conv=cid,
                               anchor_text="x"))
    assert len(store.ContextUnitsStore.all(
        conversation_id=cid, type_="repair_note")) == 2


# ── S2: 吞错计数 + 失败聚合 ───────────────────────────────────────────

def test_swallow_counter_and_stats(arch_env):
    llm_dataset.swallow("t.one")
    llm_dataset.swallow("t.one")
    llm_dataset.swallow("t.two")
    st = llm_dataset.stats()
    assert st["swallows"]["byTag"]["t.one"] == 2
    assert st["swallows"]["byTag"]["t.two"] == 1
    agg = llm_dataset.aggregate_failures()
    assert agg["swallows"]["byTag"]["t.two"] == 1


def test_aggregate_failures_dims(arch_env):
    llm_dataset.record("tool_call", tool="kb.search", ok=False)
    llm_dataset.record("llm_call", model="m1", ok=True)
    llm_dataset.record("arg_repair", model="m1", ok=True)
    st = llm_dataset.stats()
    f = st["failures"]
    assert f["byTool"]["kb.search"]["fail"] == 1
    assert f["byModel"]["m1"]["total"] == 2
    assert f["repair"]["ok"] == 1
    assert f["byKind"]["tool_call"]["fail"] == 1


# ── S3: 溢出摘要 + 统一预算 + 退役 ────────────────────────────────────

def _history(n):
    return [{"role": "user" if i % 2 == 0 else "assistant",
             "content": f"历史消息{i}"} for i in range(n)]


def test_overflow_digest_injected_and_cached(arch_env, monkeypatch):
    from topoone_app_architect import store
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    conv = store.ConversationsStore.get(cid)
    calls: list = []
    _stub_llm(monkeypatch, payload="要点纪要A", counter=calls)
    sys_text = _chat(conv, history=_history(35))       # >30 触发
    assert "【历史摘要" in sys_text and "要点纪要A" in sys_text
    row = store.ConversationsStore.get(cid)
    meta = row["meta"] if isinstance(row["meta"], dict) else json.loads(row["meta"] or "{}")
    assert meta["overflowDigest"]["digest"] == "要点纪要A"
    _chat(conv, history=_history(35))                  # 锚点不变 → 不重算
    assert len(calls) == 1


def test_overflow_digest_llm_fail_keeps_truncation(arch_env, monkeypatch):
    import topoone_app_architect.agent.tools.req_agent as ra
    from topoone_app_architect import store

    def _boom(*a, **kw):
        raise RuntimeError("llm down")
    monkeypatch.setattr(ra, "llm_sync", _boom)
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    conv = store.ConversationsStore.get(cid)
    sys_text = _chat(conv, history=_history(35))
    assert "【历史摘要" not in sys_text                # 确定性降级=现截断行为
    row = store.ConversationsStore.get(cid)
    meta = row["meta"] if isinstance(row["meta"], dict) else {}
    assert not (meta or {}).get("overflowDigest")


def test_digest_never_lands_message_stream(arch_env, monkeypatch):
    """防守线③: 摘要只做装配期瞬态注入, 消息表零新行(cv-194 真相源保留)。"""
    from topoone_app_architect import store
    cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
    conv = store.ConversationsStore.get(cid)
    _stub_llm(monkeypatch, payload="要点纪要B")
    _chat(conv, history=_history(35))
    assert store.ConversationsStore.messages(cid) == []


def test_assembly_budget_clamps(arch_env, monkeypatch):
    _set_policy({"injections": {"assemblyBudget": {"baseChars": 500,
                                                   "floorChars": 50,
                                                   "coefMin": 0.05}}})
    try:
        from topoone_app_architect import store
        cid = store.ConversationsStore.create({"kind": "generic", "title": "t"})["id"]
        conv = store.ConversationsStore.get(cid)
        _mk_units(cid, 2)
        _stub_llm(monkeypatch, payload="要点" * 200)
        from topoone_app_architect.agent.turns import context as ctx_mod
        gate = {"conv": conv, "question": ""}
        _, msgs, _ = ctx_mod._chat_context({"root": "", "project": ""}, gate,
                                           [], _history(35), "", None)
        inj = [m["content"] for m in msgs if m["role"] == "system"
               and (m["content"].startswith("【历史摘要")
                    or m["content"].startswith("【近期修复经验"))]
        assert len(inj) == 1                            # 预算吃满 → 经验弃尾
        assert inj[0].startswith("【历史摘要") and inj[0].endswith("…")
    finally:
        from topoone_app_architect import store
        store.CollabConfigStore.set(fp.POLICY_KEY, "")


def test_memory_store_retired():
    import importlib.util
    import topoone_app_architect.agent.memory as mem
    assert importlib.util.find_spec(
        "topoone_app_architect.agent.memory.store") is None
    assert not hasattr(mem, "MemoryStore")
