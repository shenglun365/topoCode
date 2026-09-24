"""规约落库归属三分守门(cv-248) — 新需求应有新标题新版本, 内容互斥不污染。

用户裁决: 交付完结(计划非空且全部 done)的需求是已交付历史——新载荷立新
需求(新编号/v1/标题生效), 不再 amend 进旧需求旧版本(旧标题挂新内容的
瑕疵实证: RQ-154 v2 快照 title 仍是旧主题); 活跃需求(计划进行中/打磨期/
失败待处理)→ 修订演进。命名兜底链: 载荷 title → 会话标题·需求 → 需求。

Run: cd <repo> && python -m pytest apps/architect/tests/test_spec_routing.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.planning.req_spec import (
    _fallback_title, _plan_delivered, apply_spec_payload)
from topoone_app_architect import store

PAYLOAD = {"title": "[UI开发] 基础工作台界面",
           "requirementMd": "**背景**：工作台界面实现",
           "acceptanceMd": "界面可渲染"}


@pytest.fixture()
def arch(arch_env):
    return arch_env


def _mk_bound(conv_id="conv-rt", delivered_plan=False, active_plan=False,
              failed_plan=False, done_mark=0):
    """绑定需求 + 会话(reqId 回写) + 可选计划形态。"""
    rid = store.RequirementsStore.create({"id": "RQ-OLD", "kind": "user-story",
                                          "status": "ready",
                                          "title": "[环境搭建] 旧主题",
                                          "activeVer": 1,
                                          "doneMark": done_mark})["id"]
    conv = store.ConversationsStore.create({"id": conv_id, "kind": "generic",
                                            "title": "t"})
    store.ConversationsStore.update(conv_id, {"reqId": rid})
    tids = []
    if delivered_plan or active_plan or failed_plan:
        st2 = "done" if delivered_plan else ("pending" if active_plan
                                             else "failed")
        for i, st in enumerate(["done", st2] if active_plan else
                               ["done", "done"] if delivered_plan else
                               ["failed", "failed"] if failed_plan else
                               ["done"]):
            t = store.TasksStore.create({
                "conversationId": conv_id, "title": f"S{i + 1}",
                "instruction": "x", "status": st,
                "executorType": "cline-sdk", "reqId": rid})
            tids.append(t["id"])
        store.RequirementsStore.update(rid, {"taskPlan": [
            {"seq": i + 1, "title": f"S{i + 1}", "instruction": "x",
             "taskId": tid, "status": tids and store.TasksStore.get(
                 tid)["status"]}
            for i, tid in enumerate(tids)]})
    return rid, conv["id"]


# ── 归属三分 ──────────────────────────────────────────────────────────

def test_delivered_plan_routes_to_new_requirement(arch):
    """计划全 done(交付完结) + 新载荷 → 新建: 新编号/v1/载荷标题生效/绑定翻页。"""
    rid, conv_id = _mk_bound(delivered_plan=True)
    from topoone_app_architect import ctx as _ctx
    token = _ctx.set_conv(conv_id)                # 生产收口同款(ctx 内调用)
    try:
        res = apply_spec_payload(dict(PAYLOAD), req_id=rid, project="p")
    finally:
        _ctx.reset_conv(token)
    assert res.get("ok") and res.get("action") == "proposed"
    new_rid = res.get("reqId")
    assert new_rid and new_rid != rid                    # 新编号
    row = store.RequirementsStore.get(new_rid)
    assert row["title"] == PAYLOAD["title"]              # 载荷标题生效(不丢)
    assert "交付完结" in res.get("summary", "")
    # 会话绑定翻页 → 新需求(propose 内部回写)
    assert (store.ConversationsStore.get(conv_id) or {}).get("reqId") == new_rid


def test_active_plan_still_amends(arch):
    """计划进行中(done+pending) → 修订(活跃需求演进)。"""
    rid, _ = _mk_bound(active_plan=True)
    res = apply_spec_payload(dict(PAYLOAD), req_id=rid, project="p")
    assert res.get("action") == "amended"
    assert res.get("reqId") == rid


def test_polishing_stage_amends(arch):
    """计划为空(打磨期) → 修订。"""
    rid, _ = _mk_bound()
    res = apply_spec_payload(dict(PAYLOAD), req_id=rid, project="p")
    assert res.get("action") == "amended"


def test_failed_plan_amends(arch):
    """计划全 failed(未交付完结, 待修正重跑) → 修订而非弃旧开新。"""
    rid, _ = _mk_bound(failed_plan=True)
    res = apply_spec_payload(dict(PAYLOAD), req_id=rid, project="p")
    assert res.get("action") == "amended"


def test_done_mark_routes_to_new(arch):
    """doneMark=1(显式完结) → 新建(现状回归)。"""
    rid, _ = _mk_bound(done_mark=1)
    res = apply_spec_payload(dict(PAYLOAD), req_id=rid, project="p")
    assert res.get("action") == "proposed"


# ── 命名兜底链 ────────────────────────────────────────────────────────

def test_title_fallback_chain(arch):
    """命名兜底链分层: ①载荷 title ②内容首行(L0 既有) ③会话标题·需求→需求。

    本例 designMd 有实质内容而 requirementMd 缺失(首行兜底不触发)——
    验证最后环节生效; 不烧 L2 修复通道。"""
    conv = store.ConversationsStore.create({"id": "conv-fb", "kind": "generic",
                                            "title": "动画引擎会话"})
    from topoone_app_architect import ctx as _ctx
    token = _ctx.set_conv("conv-fb")
    try:
        assert _fallback_title() == "动画引擎会话·需求"
        res = apply_spec_payload({"designMd": "界面方案：左栏导航+主区画布",
                                  "acceptanceMd": "界面可渲染"},
                                 req_id="", project="p")
    finally:
        _ctx.reset_conv(token)
    assert res.get("ok") and res.get("action") == "proposed"
    new_rid = res.get("reqId")
    assert (store.RequirementsStore.get(new_rid)
            or {}).get("title") == "动画引擎会话·需求"


def test_plan_delivered_pure_logic(arch):
    assert _plan_delivered("") is False
    assert _plan_delivered("RQ-404") is False
    rid = store.RequirementsStore.create({"id": "RQ-PD", "kind": "user-story",
                                          "status": "ready", "title": "T",
                                          "activeVer": 1})["id"]
    assert _plan_delivered(rid) is False               # 计划为空≠完结
    store.RequirementsStore.update(rid, {"taskPlan": [
        {"seq": 1, "status": "done"}, {"seq": 2, "status": "done"}]})
    assert _plan_delivered(rid) is True
    store.RequirementsStore.update(rid, {"taskPlan": [
        {"seq": 1, "status": "done"}, {"seq": 2, "status": "pending"}]})
    assert _plan_delivered(rid) is False
