"""帮助意图面特征测试(批戊补) — 使用指南/帮助手册的意图处理与内容供给。

需求裁决(用户 2026-09-22): ①指南/帮助信息非最终版, 随迭代更新(内容走
flow_policy.goal.helpTopics 配置基座, PUT 零发版); ②纯寒暄/咨询零写面
(cv-242 修复: answer tools=[]——落卡权=确定性意图命中专属)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_help_intent.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance import flow_policy as fp
from topoone_app_architect.agent.governance.flow_policy import (
    DEFAULT_FLOW_POLICY, validate_flow_policy)
from topoone_app_architect.agent.turns import help_docs
from topoone_app_architect.agent.turns.goal import (
    build_goal_profile, resolve_goal_directive)


# ── 意图判定(match_help) ──────────────────────────────────────────────

@pytest.mark.parametrize("q", ("帮助", "怎么配置执行器？", "使用指南在哪",
                               "如何创建需求卡", "新手入门", "使用说明"))
def test_help_intent_hits(q):
    assert help_docs.match_help(q), q


@pytest.mark.parametrize("q", ("你好", "帮我写个使用手册", "做一个帮助中心页面",
                               "开发新的文档功能", ""))
def test_help_intent_excludes_build_and_noise(q):
    """构建标记排除: 「写个使用手册」是开发诉求(需求路线), 不是产品咨询。"""
    assert not help_docs.match_help(q), q


# ── GU 判定 → 决策表 → 工具面 ─────────────────────────────────────────

def test_gu_help_route_and_tools():
    p = build_goal_profile("怎么配置执行器？")
    assert p["kind"] == "help" and p["confidence"] == 0.85
    r = resolve_goal_directive(p, DEFAULT_FLOW_POLICY)
    assert r["action"] == "provide-help" and r["tools"] == ["help.lookup"]
    assert "help.lookup" in r["text"] and "不落任何卡" in r["text"]


def test_cv242_inquiry_zero_write_surface():
    """cv-242 复放: 「你好」→ inquiry 兜底纯读(零写面, 不再脑补落需求卡)。"""
    p = build_goal_profile("你好")
    assert p["kind"] == "inquiry"
    r = resolve_goal_directive(p, DEFAULT_FLOW_POLICY)
    assert r["action"] == "answer" and r["tools"] == []
    assert "不落任何卡" in r["text"]
    assert "收敛为需求规约" not in r["text"]     # 正向引导退役


def test_entire_decision_table_nondeterministic_actions_readonly():
    """通用性契约固化: 兜底/歧义/咨询类动作一律纯读——落卡权=确定性命中专属。"""
    rules = {r["then"]: r.get("tools", "__none__")
             for r in DEFAULT_FLOW_POLICY["goal"]["decision"]}
    for act in ("answer", "ask-one-question", "present-options"):
        assert rules[act] == [], act


# ── 内容供给(help.lookup) ─────────────────────────────────────────────

def test_lookup_keyword_hit_returns_body():
    res = help_docs.lookup_topics("执行器")
    assert res["topics"] and res["topics"][0]["body"]
    assert "滞后" in res["hint"]


def test_lookup_empty_query_returns_catalog():
    res = help_docs.lookup_topics("")
    assert len(res["topics"]) >= 8 and "body" not in res["topics"][0]


def test_lookup_miss_returns_catalog_hint():
    res = help_docs.lookup_topics("量子纠缠")
    assert res["topics"] and "未命中" in res["hint"]


# ── 配置基座(helpTopics 非最终版, PUT 零发版更新) ─────────────────────

def test_help_topics_config_override_and_validation(arch_env):
    """配置全量覆盖缺省表(与 strategies 同款); 写侧校验 key 唯一/body 非空。"""
    from topoone_app_architect import store
    store.CollabConfigStore.set(fp.POLICY_KEY, json.dumps({"goal": {
        "helpTopics": [
            {"key": "custom", "title": "自定义主题", "kws": ["自定义"],
             "body": "自定义内容正文", "updated": "2026-09-22"}]}}))
    rows = ((fp.load_flow_policy().get("goal") or {}).get("helpTopics"))
    topics = help_docs.load_topics(rows)
    assert [t["key"] for t in topics] == ["custom"]          # 覆盖缺省表
    # 非法配置(重复 key) → load 整体回落缺省(fail-soft), 校验器单独报重复
    ok, errs = validate_flow_policy({"goal": {"helpTopics": [
        {"key": "dup", "title": "A", "kws": ["k"], "body": "b"},
        {"key": "dup", "title": "B", "kws": ["k"], "body": "b"}]}})
    assert not ok and any("重复" in e for e in errs)
    store.CollabConfigStore.set(fp.POLICY_KEY, "")
