"""问询卡 json 围栏兜底识别守门(cv-252) — 意图+schema 双门的形态归一。

症状: GU 判 clarify-first, 模型把问询载荷写进 ```json 围栏(协议漂移)——
显式 ```choices 识别 miss → 裸 JSON 漏到前端, 问询卡不激活。
修法: 协议单源不变(cv-247 显式标记); 意图佐证下(clarify-first)对 ```json
围栏做同一把尺(valid_choices_payload)的兜底识别——不做无差别 json 扫描
(cv-246 教训: 围栏竞争致误归属)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_choices_fallback.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.collab.cards import (
    extract_choices_fence, extract_choices_json_fence,
    resolve_choices_payload, strip_choices_fence, valid_choices_payload)

GOOD = {"title": "基础工作台UI需求澄清",
        "groups": [{"label": "技术栈", "question": "技术栈是什么？",
                    "options": [{"id": "vue3", "label": "Vue3 + TS",
                                 "hint": "主流"}]}]}


def _fence(payload, marker="json"):
    import json as _j
    return f"```{marker}\n{_j.dumps(payload, ensure_ascii=False)}\n```"


# ── 兜底识别: schema 同尺 ─────────────────────────────────────────────

def test_json_fence_payload_recognized():
    """```json 围栏 + 合法问询载荷 → 识别(cv-252 真实形态)。"""
    text = "请确认以下关键要素：\n\n" + _fence(GOOD)
    assert extract_choices_fence(text) is None        # 显式标记单源不认 json
    assert extract_choices_json_fence(text) == GOOD


def test_json_fence_bad_payload_rejected():
    """```json 围栏 + 非问询载荷(普通 json 代码块) → 不误识别。"""
    not_choices = _fence({"code": 1, "items": ["a", "b"]})
    assert extract_choices_json_fence(not_choices) is None
    # groups 空组/无 label 也拒(与 valid_choices_payload 同尺)
    assert extract_choices_json_fence(
        _fence({"groups": []})) is None
    assert extract_choices_json_fence(
        _fence({"groups": [{"options": [{"label": "x"}]}]})) is None


def test_explicit_choices_fence_takes_priority():
    """显式与 json 兜底两识别互不重叠(标记字面隔离)——调用方顺序
    (chat.py 先试显式)保证协议单源, 无围栏竞争。"""
    text = _fence(GOOD, "choices")
    assert extract_choices_fence(text) == GOOD
    assert extract_choices_json_fence(text) is None   # 字面不匹配 ```json
    json_text = _fence(GOOD, "json")
    assert extract_choices_fence(json_text) is None
    assert extract_choices_json_fence(json_text) == GOOD


# ── 剥离: 卡即回执(按命中标记精确剥离) ────────────────────────────────

def test_strip_by_marker_keeps_surrounding_prose():
    text = "引导语。\n\n" + _fence(GOOD) + "\n\n尾注。"
    out = strip_choices_fence(text, marker="json")
    assert "```" not in out and "技术栈" not in out
    assert "引导语" in out and "尾注" in out


def test_strip_choices_fence_untouched():
    """原显式剥离不受影响(回归, marker 默认值)。"""
    text = "前文\n\n" + _fence(GOOD, "choices")
    out = strip_choices_fence(text)
    assert "```choices" not in out and out == "前文"


# ── 识别单源入口: 显式优先 + 意图门 ───────────────────────────────────

def test_resolve_explicit_priority_and_marker():
    """显式 ```choices 优先(协议单源); marker 随命中标记返回。"""
    both = _fence({"title": "x", "groups": [{"label": "g"}]}, "json") \
        + _fence(GOOD, "choices")
    payload, marker = resolve_choices_payload(both)
    assert (payload, marker) == (GOOD, "choices")


def test_resolve_intent_gate_guards_json_fallback():
    """```json 兜底仅意图佐证(intent_clarify=True)时启用——双门在入口单源。"""
    text = _fence(GOOD, "json")
    assert resolve_choices_payload(text) == (None, "")          # 无意图不兜底
    payload, marker = resolve_choices_payload(text, intent_clarify=True)
    assert (payload, marker) == (GOOD, "json")


def test_intent_gate_is_caller_side():
    """chat 层门条件等价语义固化: 非 clarify-first 回合不启用兜底。"""
    text = _fence(GOOD)
    assert valid_choices_payload(extract_choices_json_fence(text))
    for gu_action in ("", "propose-plan", "task-status"):
        assert (gu_action == "clarify-first") is False


# ── cv-254: 回合动作记账随卡归位 → 澄清循环可收敛 ─────────────────────

def test_land_choices_carries_gu_action(arch_env):
    """代落问询卡 meta 携带回合 guAction(记账载体=回合产物); 空缺省兼容。"""
    from topoone_app_architect.agent.collab import cards as _cards
    from topoone_app_architect import store
    store.ConversationsStore.create({"id": "conv-ga", "kind": "generic",
                                     "title": "t"})
    _cards.land_choices("conv-ga", GOOD, gu_action="clarify-first")
    meta = (store.ConversationsStore.messages("conv-ga")[-1].get("meta")
            or {})
    assert meta.get("guAction") == "clarify-first"
    _cards.land_choices("conv-ga", GOOD)     # 空缺省: 不写记账(向后兼容)
    meta2 = (store.ConversationsStore.messages("conv-ga")[-1].get("meta")
             or {})
    assert "guAction" not in meta2


def test_focus_clarify_pending_from_card_ledger(arch_env):
    """全链: 代落+空收尾(回合只有卡) → 焦点帧 clarify_pending 由卡上
    记账派生 → 下回合 L0-2.8 消解为 continuation(澄清循环收敛出口)。"""
    from topoone_app_architect.agent.collab import cards as _cards
    from topoone_app_architect.agent.governance.focus import _pending_action
    from topoone_app_architect import store
    conv_id = "conv-ledger"
    store.ConversationsStore.create({"id": conv_id, "kind": "generic",
                                     "title": "t"})
    store.ConversationsStore.append_message(
        {"id": "m-u", "conversationId": conv_id, "role": "user",
         "time": 0, "content": "需求"})
    _cards.land_choices(conv_id, GOOD, gu_action="clarify-first")
    # 记账在卡上(最近 assistant) → 帧源可得
    pend = _pending_action(store, conv_id,
                           int(__import__("time").time() * 1000))
    assert pend.get("action") == "clarify-first"
    # 无记账卡: 最近无记账 → 向前找更早记账(cv-248 语义, 澄清仍在飞=有效);
    # 全会话无任何记账 → 不产生假帧(回归)
    store.ConversationsStore.append_message(
        {"id": "m-u2", "conversationId": conv_id, "role": "user",
         "time": 1, "content": "答复"})
    _cards.land_choices(conv_id, GOOD)       # 新卡无记账(如非 GU/兜底源)
    pend2 = _pending_action(store, conv_id,
                            int(__import__("time").time() * 1000))
    assert pend2.get("action") == "clarify-first"   # 向前找到第一张的记账
    conv2 = "conv-ledger2"
    store.ConversationsStore.create({"id": conv2, "kind": "generic",
                                     "title": "t"})
    _cards.land_choices(conv2, GOOD)
    assert _pending_action(store, conv2,
                           int(__import__("time").time() * 1000)) == {}


# ── 集成: 落流点(land_choices 消费同一 payload) ───────────────────────

def test_json_fallback_lands_choices_card(arch_env):
    """cv-252 端到端: json 围栏载荷经兜底识别落卡(ChoicesCard 激活)。"""
    from topoone_app_architect.agent.collab import cards as _cards
    from topoone_app_architect import store
    conv = store.ConversationsStore.create({"id": "conv-c252",
                                            "kind": "generic", "title": "t"})
    card = _cards.land_choices("conv-c252", extract_choices_json_fence(
        "请确认：\n" + _fence(GOOD)))
    assert card
    msg = store.ConversationsStore.messages("conv-c252")[-1]
    meta = msg.get("meta") or {}
    # 落卡 meta 扁平键(kind=choices), 前端投影组装 item.type=choices
    assert meta.get("kind") == "choices"
    assert meta.get("title") == GOOD["title"]
    assert meta.get("groups") == GOOD["groups"]


# ── cv-253: 正文只有围栏 → 代落成功后剥空 ≠ 空返回错误 ────────────────

def test_bare_fence_turn_returns_card_landed(arch_env):
    """模型只输出 json 围栏(无正文)时, 问询卡代落成功即回合产物——
    代落通道必须上抛 card_landed(与工具轮 card_closed 同规, cv-203),
    否则空收尾被误判 turnError(cv-253 实弹: 问询卡+假❌同时出现)。"""
    import asyncio
    from types import SimpleNamespace
    from topoone_app_architect.agent.turns.chat import _post_turn_land
    from topoone_app_architect import ctx as _ctx, store
    store.ConversationsStore.create({"id": "conv-bare", "kind": "generic",
                                     "title": "t"})

    async def _send(ev):
        pass

    token = _ctx.set_conv("conv-bare")
    try:
        fc, _c, _u, _e, landed = asyncio.run(_post_turn_land(
            SimpleNamespace(send=_send), "conv-bare", [], None, None, None,
            None, {}, set(), {}, _fence(GOOD), None,
            allowed_tools=set(), gu_action="clarify-first"))
    finally:
        _ctx.reset_conv(token)
    assert landed is True                 # 代落标记上抛(空收尾豁免依据)
    assert fc == ""                       # 正文剥空——卡即回合产物
    # 无意图佐证(非 clarify-first)时同载荷不代落、正文诚实保留
    token = _ctx.set_conv("conv-bare")
    try:
        fc2, _c2, _u2, _e2, landed2 = asyncio.run(_post_turn_land(
            SimpleNamespace(send=_send), "conv-bare", [], None, None, None,
            None, {}, set(), {}, _fence(GOOD), None,
            allowed_tools=set(), gu_action="propose-requirement"))
    finally:
        _ctx.reset_conv(token)
    assert landed2 is False and "```json" in fc2
