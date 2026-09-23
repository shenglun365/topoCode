"""结构化问询卡(choices)特征测试 — cv-247 通用交互选项实体。

架构裁决: 「可交互选项」是卡片词汇表一等成员(choices 卡), 三源汇入同一
实体——①模型 ```choices 围栏 ②GU present-options 候选 ③策略 questions;
回复组装=普通文本消息走既有发送通道(与手打等价, GU/执法点/澄清续答面照旧);
问题自由度不设模板(最小可渲染校验), 开放题与选择题同卡混排。

Run: cd <repo> && python -m pytest apps/architect/tests/test_choices_card.py -q
"""
import asyncio
import json
import os
import sys
from types import SimpleNamespace

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.collab.cards import (
    KIND_CHOICES, extract_choices_fence, strip_choices_fence,
    valid_choices_payload)
from topoone_app_architect.agent.execution.items import item_from_card
from topoone_app_architect.agent.turns.goal import (
    _gu_choices_payload, build_goal_profile, resolve_goal_directive)
from topoone_app_architect.agent.governance.flow_policy import (
    DEFAULT_FLOW_POLICY)

CHOICES_FENCE = (
    '```choices\n{"title": "关键选型确认", "groups": ['
    '{"id": "1", "label": "后端框架", "question": "API 层用哪个框架？",'
    '"options": [{"id": "A", "label": "Fastify", "hint": "高性能", "recommended": true},'
    '{"id": "B", "label": "Express"}]},'
    '{"id": "2", "label": "复现步骤", "question": "问题如何复现？"}],'
    '"note": "确认后生成需求方案卡"}\n```')


def _land_fence(content, conv_id="conv-ch"):
    """跑一次回合后代落通道(含 choices 处理), 返回 final_content。"""
    from topoone_app_architect.agent.turns.chat import _post_turn_land
    from topoone_app_architect.arch_routes import ctx as _ctx, store
    store.ConversationsStore.create({"id": conv_id, "kind": "generic",
                                     "title": "t"})

    async def _send(ev):
        pass

    token = _ctx.set_conv(conv_id)
    try:
        fc, _c, used, errs = asyncio.run(_post_turn_land(
            SimpleNamespace(send=_send), conv_id, [], None, None, None, None,
            {}, set(), {}, content, None, allowed_tools=set()))
    finally:
        _ctx.reset_conv(token)
    return fc, used, errs


# ── 协议层: 显式标记提取/剥离(不进 json 候选扫描) ─────────────────────

def test_extract_choices_fence_explicit_only():
    d = extract_choices_fence(f"正文\n{CHOICES_FENCE}\n后记")
    assert d and len(d["groups"]) == 2
    # 开放题组(无 options)合法——自由度约束
    assert d["groups"][1].get("options") is None
    # 隐形 json 围栏不认领(cv-246 教训: 不参与围栏竞争)
    assert extract_choices_fence('```json\n{"title": "t", "requirementMd": "x"}\n```') is None
    assert extract_choices_fence('```json\n{"title": "x", "instruction": "做事情xx"}\n```') is None
    assert extract_choices_fence("无围栏") is None


def test_payload_minimal_validation_fail_soft():
    assert valid_choices_payload({"groups": [{"label": "q"}]})       # 开放题
    assert not valid_choices_payload({"groups": []})
    assert not valid_choices_payload({"groups": [{"options": [{}]}]})
    assert not valid_choices_payload({"groups": "x"})
    assert not valid_choices_payload(None)
    # 坏载荷不落卡
    assert extract_choices_fence('```choices\n{"groups": []}\n```') is None


def test_strip_choices_fence_scoped():
    task_fence = '```task\n{"title": "任务T", "instruction": "做事"}\n```'
    mixed = f"前\n{CHOICES_FENCE}\n中\n{task_fence}"
    out = strip_choices_fence(mixed)
    assert "关键选型" not in out and "任务T" in out


# ── 围栏源(①): _post_turn_land 落卡+剥离, 交互卡不验写权 ─────────────

def test_fence_source_lands_choices_card(arch_env):
    from topoone_app_architect.agent.collab import cards as _cards
    from topoone_app_architect.arch_routes import store
    fc, used, _errs = _land_fence(f"请确认选型：\n{CHOICES_FENCE}")
    assert used == set()                       # 交互卡不计入写工具
    assert "choices" not in fc                 # 围栏剥离
    cards = [m for m in store.ConversationsStore.messages("conv-ch")
             if (m.get("meta") or {}).get("kind") == KIND_CHOICES]
    assert len(cards) == 1
    it = item_from_card(cards[0]["meta"], cards[0]["content"],
                        cards[0]["time"], cards[0]["id"])
    assert it["type"] == "choices" and len(it["payload"]["groups"]) == 2
    # 纯读面下 choices 卡仍落(非实体写卡——执法点管「写实体权力」)
    assert _cards.valid_choices_payload({"groups": [{"label": "x"}]})


def test_no_card_on_invalid_payload(arch_env):
    from topoone_app_architect.arch_routes import store
    fc, _used, _e = _land_fence('问题：\n```choices\n{"groups": []}\n```')
    cards = [m for m in store.ConversationsStore.messages("conv-ch")
             if (m.get("meta") or {}).get("kind") == KIND_CHOICES]
    assert cards == [] and "```choices" in fc   # 坏载荷正文保留(信息不丢)


# ── GU 确定性源(②③) + 原位更新 ───────────────────────────────────────

def test_gu_payload_strategy_questions_open_groups():
    p = _gu_choices_payload("clarify-first", {
        "strategyLabel": "环境搭建",
        "strategyQuestions": ["方案要点: 包管理器用哪个？",
                              "允许范围: 可改哪些目录？"]})
    assert [g["label"] for g in p["groups"]] == ["方案要点", "允许范围"]
    assert all(not g.get("options") for g in p["groups"])   # 开放题组
    assert _gu_choices_payload("clarify-first", {"strategyQuestions": []}) is None


def test_gu_payload_present_options_candidates():
    p = _gu_choices_payload("present-options", {"candidates": [
        {"id": "requirement", "label": "需求规约", "hint": "长期迭代"},
        {"id": "operation", "label": "一次性操作", "hint": "单卡直达"}]})
    opts = p["groups"][0]["options"]
    assert [o["id"] for o in opts] == ["requirement", "operation"]


def test_gu_decision_attaches_choices(arch_env):
    prof = build_goal_profile("搭建开发环境")
    r = resolve_goal_directive(prof, DEFAULT_FLOW_POLICY)
    assert r["action"] == "clarify-first" and r.get("choices")
    assert r["choicesFingerprint"] == "strategy:env_setup"


def test_upsert_same_fingerprint_in_place(arch_env):
    """同 fingerprint 原位更新(多回合澄清单锚位, 不刷屏——进度锚同款)。"""
    from topoone_app_architect.agent.collab.cards import land_choices
    from topoone_app_architect.arch_routes import store
    store.ConversationsStore.create({"id": "conv-ch", "kind": "generic",
                                     "title": "t"})
    pay1 = {"title": "澄清 v1", "groups": [{"label": "q1", "question": "a"}]}
    pay2 = {"title": "澄清 v2", "groups": [{"label": "q1", "question": "a"},
                                           {"label": "q2", "question": "b"}]}
    r1 = land_choices("conv-ch", pay1, fingerprint="strategy:env_setup")
    r2 = land_choices("conv-ch", pay2, fingerprint="strategy:env_setup")
    assert r1 and r2
    cards = [m for m in store.ConversationsStore.messages("conv-ch")
             if (m.get("meta") or {}).get("kind") == KIND_CHOICES]
    assert len(cards) == 1                     # 原位更新, 不追加
    meta = cards[0]["meta"]
    assert (json.loads(meta) if isinstance(meta, str) else meta)["title"] == "澄清 v2"
    # 不同指纹/空指纹(模型围栏源) → 独立卡
    r3 = land_choices("conv-ch", pay1)
    r4 = land_choices("conv-ch", pay1, fingerprint="strategy:other")
    assert r3 and r4
    cards = [m for m in store.ConversationsStore.messages("conv-ch")
             if (m.get("meta") or {}).get("kind") == KIND_CHOICES]
    assert len(cards) == 3


def test_directive_templates_carry_protocol():
    """指引模板带围栏协议说明(三源中模型源的行为面)。"""
    d = DEFAULT_FLOW_POLICY["goal"]["directives"]
    for k in ("clarify-first", "clarify-first-generic", "present-options"):
        assert "choices" in d[k], k


# ── 通用持久化契约(cv-248 裁决固化) ──────────────────────────────────

def test_card_vocabulary_projected_registry_consistent():
    """架构完整性守门: 词汇表**结构卡/交互卡**必须有读侧投影(CARD_ITEM_MAP)——
    漏投影 = 刷新后卡片降级为正文(持久化观感断裂, cv-248 实证根因);
    **文本回执类**显式豁免登记(正文渲染即预期形态, 但豁免必须列出——
    静默缺失与显式豁免在测试上可区分)。
    反向: 投影注册表不得出现词汇表外 kind(遗留白名单除外)。"""
    from topoone_app_architect.agent.collab.cards import _KNOWN_KINDS
    from topoone_app_architect.agent.execution.items import CARD_ITEM_MAP
    # 文本回执类(显式豁免: 正文渲染即预期; 新增豁免须在此登记并注明理由)
    TEXT_RECEIPT_KINDS = {
        "task_ignored", "req_ignored",      # 置灰回执(文本即形态)
        "task_progress",                    # 进度回执(cv-203 前遗产, 文本)
        "task_start", "task_input", "task_done", "task_failed",
        "task_approval_done", "taskPlanDone",
        "turnError", "digest_sent",
    }
    structural = [k for k in _KNOWN_KINDS if k not in TEXT_RECEIPT_KINDS]
    missing = [k for k in structural if k not in CARD_ITEM_MAP]
    assert not missing, f"结构卡缺读侧投影(刷新后降级正文): {missing}"
    legacy = {"specCreated", "task_verify"}          # 历史遗留(仅旧数据)
    unknown = [k for k in CARD_ITEM_MAP
               if k not in _KNOWN_KINDS and k not in legacy]
    assert not unknown, f"投影注册表出现词汇表外 kind: {unknown}"


def test_choices_card_tracking_entry(arch_env):
    """需求跟踪资产条目: 问询发出即挂账留档(category=问询, ref=卡消息行);
    原位更新不重复挂账。"""
    from topoone_app_architect.agent.collab.cards import land_choices
    from topoone_app_architect.arch_routes import store
    store.ConversationsStore.create({"id": "conv-tr", "kind": "generic",
                                     "title": "t"})
    pay = {"title": "选型确认", "groups": [{"label": "后端框架",
                                            "question": "用哪个？"}]}
    land_choices("conv-tr", pay, fingerprint="strategy:env_setup")
    rows = _tracking_all()
    hit = [r for r in rows if (r.get("refType") or "") == "choices_card"
           and (r.get("title") or "") == "选型确认"]
    assert hit, "问询卡落流必须挂跟踪条目"
    assert hit[0].get("state") == "done"
    # 原位更新 → 不重复挂账
    pay2 = {"title": "选型确认 v2", "groups": pay["groups"]}
    land_choices("conv-tr", pay2, fingerprint="strategy:env_setup")
    rows2 = _tracking_all()
    hit2 = [r for r in rows2 if (r.get("refType") or "") == "choices_card"]
    assert len(hit2) == 1, "原位更新不得重复挂账"


def _tracking_all():
    from topoone_app_architect.arch_routes.store import tracking as _tr
    # all() 项目硬隔离(无请求上下文→[]); 测试面走 all_across
    return _tr.TrackingItemsStore.all_across(category="问询")
