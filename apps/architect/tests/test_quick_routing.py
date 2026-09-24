"""快捷挡流程路由守门(cv-254) — analysisMode=quick 直出任务卡, 跳过需求链。

用户实证: 会话切 quick(闪电钮)后仍走「需求卡→specReady→/执行」完整链。
根因: 决策层对 quick 零消费——分类器 facts 与 when 匹配器均无
analysisMode, GU 照常注入 clarify/req.propose 指引。
修法(与 clarifyMode 同款决策面事实, 规则推展非硬编码): 决策表前置
quick 直通规则(requirement → propose-task), 抢占 clarify-first/
propose-requirement——与 gears.resolve_gear 的 quick=钉死 T0 同源
单值(执行挡位与流程路由消费同一会话字段)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_quick_routing.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance.flow_policy import DEFAULT_FLOW_POLICY
from topoone_app_architect.agent.turns.goal import (
    build_goal_profile, resolve_goal_directive)

POL = DEFAULT_FLOW_POLICY


def _req_profile(**kw):
    """UI 开发类输入的 requirement 面 profile(策略命中形态)。"""
    base = {"kind": "requirement", "target": "new", "strategy": "ui-component",
            "strategyLabel": "UI/组件封装", "strategyQuestions": [],
            "confidence": 0.9, "candidates": [], "explicit": False,
            "clarifyMode": "auto", "analysisMode": "strict",
            "sources": ["strategy"]}
    base.update(kw)
    return base


# ── 决策表: quick 直通 ────────────────────────────────────────────────

def test_quick_routes_requirement_to_task():
    """quick + requirement → propose-task(直出任务卡), 非 clarify/需求卡。"""
    out = resolve_goal_directive(_req_profile(analysisMode="quick"), POL)
    assert out["action"] == "propose-task"
    assert out["tools"] == ["task.propose"]


def test_strict_keeps_clarify_first():
    """strict(标准挡)回归: requirement+策略 → clarify-first(既有语义)。"""
    out = resolve_goal_directive(_req_profile(analysisMode="strict"), POL)
    assert out["action"] == "clarify-first"


def test_quick_no_clarify_choices_payload():
    """quick 直通不携带澄清问询卡(GU 确定性源②③不产 choices)。"""
    out = resolve_goal_directive(
        _req_profile(analysisMode="quick", strategyQuestions=[{"q": 1}]), POL)
    assert "choices" not in out


# ── 分类器 facts: analysisMode 进入决策面 ─────────────────────────────

def test_classifier_carries_analysis_mode(arch_env):
    """分类器 prof 携带会话 analysisMode(决策表 when 可消费的决策面事实)。"""
    from topoone_app_architect.agent.turns.goal import build_goal_profile
    prof = build_goal_profile("实现一个工作台顶栏", conv={"analysisMode": "quick"})
    assert prof.get("analysisMode") == "quick"
    prof2 = build_goal_profile("实现一个工作台顶栏", conv={})
    assert prof2.get("analysisMode") == "strict"     # 缺省 strict


# ── 端到端: 决策表 + 分类器(真实分类路径) ─────────────────────────────

def test_end_to_end_quick_direct_task(arch_env):
    """真实分类(策略词命中) → quick 会话 → propose-task 直通全链。"""
    prof = build_goal_profile(
        "给工作台加一个主题色切换按钮",
        conv={"analysisMode": "quick", "clarifyMode": "auto"})
    out = resolve_goal_directive(prof, POL)
    assert out["action"] == "propose-task"
    assert out["tools"] == ["task.propose"]


def test_end_to_end_strict_unchanged(arch_env):
    """strict 会话同输入 → 既有需求链(clarify/需求卡)不变。"""
    prof = build_goal_profile(
        "给工作台加一个主题色切换按钮",
        conv={"analysisMode": "strict", "clarifyMode": "auto"})
    out = resolve_goal_directive(prof, POL)
    assert out["action"] in ("clarify-first", "propose-requirement")


# ── 决策表校验器: when 键白名单放行 analysisMode(REST 自定义策略面) ────

def test_validate_accepts_analysis_mode_key():
    from topoone_app_architect.agent.governance.flow_policy import \
        _validate_goal
    errs = _validate_goal({"decision": [
        {"when": {"kind": "requirement", "analysisMode": "quick"},
         "then": "propose-task", "tools": ["task.propose"]}]})
    assert errs == []
    errs2 = _validate_goal({"decision": [
        {"when": {"bogus": 1}, "then": "continue"}]})
    assert any("未知条件键" in e for e in errs2)
