"""会话流程相位机(governance/flow.py)特征测试 — 状态机×策略引擎协作定稿。

覆盖: 派生纯函数(6 态)/interrupted 粘滞/硬闸(仅 interrupted×下发意图)/
P 轴面分离与单调收紧(R2 裁决)/注册面禁触清单/recompute 事件迁移(集成)/
dismiss 消化出口(集成)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_flow_states.py -q
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance import flow
from topoone_app_architect.agent.governance.gears import resolve_gear
from topoone_app_architect.arch_routes.store import states as ST


# ── 派生(纯函数) ──────────────────────────────────────────────────────

def _conv(meta=None):
    return {"id": "cv-1", "status": "active", "meta": meta or {}}


def _t(status, **kw):
    return {"id": kw.get("id", "task-1"), "status": status,
            "dismissedAt": kw.get("dismissedAt", 0)}


def test_derive_free_default():
    assert flow.derive_flow_state(_conv(), []) == ST.FLOW_FREE
    assert flow.derive_flow_state(_conv(), [_t("failed"), _t("cancelled"),
                                            _t("ignored")]) == ST.FLOW_FREE


def test_derive_executing_priority():
    tasks = [_t("saved"), _t("running"), _t("done")]
    assert flow.derive_flow_state(_conv(), tasks) == ST.FLOW_EXECUTING
    assert flow.derive_flow_state(
        _conv(), [_t("waiting_input")]) == ST.FLOW_EXECUTING


def test_derive_armed():
    assert flow.derive_flow_state(
        _conv(), [_t("saved")]) == ST.FLOW_ARMED
    # 存量确认门禁态同样属 armed(不真实占用执行)
    assert flow.derive_flow_state(
        _conv(), [_t("pending_confirm")]) == ST.FLOW_ARMED


def test_derive_reviewing():
    assert flow.derive_flow_state(
        _conv(), [_t("done")]) == ST.FLOW_REVIEWING
    # 需求已 done → 回执视为已消化(裁决: req done 出口)
    req = {"status": ST.REQ_DONE}
    assert flow.derive_flow_state(_conv(), [_t("done")], req) == ST.FLOW_FREE


def test_derive_reviewing_dismiss_exits():
    tasks = [_t("done", dismissedAt=123)]
    assert flow.derive_flow_state(_conv(), tasks) == ST.FLOW_FREE


def test_derive_clarifying_anchor_is_spec_draft():
    assert flow.derive_flow_state(
        _conv({"specDraft": {"title": "x"}}), []) == ST.FLOW_CLARIFYING
    # meta 为 JSON 字符串(库内形态)同样可读
    import json
    assert flow.derive_flow_state(
        _conv(json.dumps({"specDraft": {}})), []) == ST.FLOW_CLARIFYING


def test_interrupted_sticky_unless_force():
    """粘滞语义: 中断态不被无关事件洗白; 仅自愈/恢复(force)可解除。"""
    tasks = [_t("running")]
    assert flow.derive_flow_state(_conv(), tasks, cached="interrupted") \
        == ST.FLOW_INTERRUPTED
    assert flow.derive_flow_state(_conv(), tasks, cached="interrupted",
                                  force=True) == ST.FLOW_EXECUTING


def test_drift_check_ignores_sticky():
    assert flow.drift_check("armed", "executing") is True
    assert flow.drift_check("armed", "armed") is False
    assert flow.drift_check("interrupted", "executing") is False


# ── 硬闸(仅 interrupted × 下发意图) ──────────────────────────────────

def test_guard_only_interrupted():
    assert flow.phase_guard(ST.FLOW_EXECUTING, "执行部署") is None
    assert flow.phase_guard(ST.FLOW_FREE, "随便聊聊") is None


def test_guard_blocks_dispatch_intent():
    reply = flow.phase_guard(ST.FLOW_INTERRUPTED, "帮我执行一次部署")
    assert reply and "异常中断" in reply
    assert flow.phase_guard(ST.FLOW_INTERRUPTED, "建一张新任务卡")
    assert flow.phase_guard(ST.FLOW_INTERRUPTED, "检测一下编译环境")


def test_guard_allows_plain_chat_in_interrupted():
    """中断态不锁死对话(互斥锁死会话是事故模式)——普通讨论放行。"""
    assert flow.phase_guard(ST.FLOW_INTERRUPTED, "刚才失败了是什么原因?") is None


def test_custom_guard_registration():
    flow.register_flow_guard("t-custom", lambda p, x: "custom-block" if "敏感" in x else None,
                             phases=[ST.FLOW_REVIEWING])
    assert flow.evaluate_guards(ST.FLOW_REVIEWING, "敏感操作") == "custom-block"
    assert flow.evaluate_guards(ST.FLOW_REVIEWING, "普通") is None
    # 内置优先于自定义
    assert flow.evaluate_guards(ST.FLOW_INTERRUPTED, "执行部署") != "custom-block"


# ── P 轴(R2 面分离 / 单调收紧 / R3 开关) ─────────────────────────────

def test_p_axis_appends_architect_note():
    base = resolve_gear("T1")
    p = resolve_gear("T1", flow_state="executing")
    assert "流程相位" in p.architect_note
    assert base.architect_note in p.architect_note


def test_p_axis_never_touches_task_face():
    """R2 面分离: 任务面字段(agent_note/cadence/max_iterations)必须零变化。"""
    base = resolve_gear("T2")
    p = resolve_gear("T2", flow_state="clarifying")
    assert p.agent_note == base.agent_note
    assert p.cadence == base.cadence
    assert p.max_iterations == base.max_iterations
    assert p.tool_rounds == base.tool_rounds


def test_p_axis_element_boost_only_up():
    p = resolve_gear("T1", flow_state="clarifying")
    assert p.element_hints == "high"
    # 单调: A 轴已上调(high)时不被 P 轴降级
    strong = {"tierProbed": "T1"}
    weak_arch = resolve_gear("T1", strong, architect_model_id="weak-model")
    stacked = resolve_gear("T1", strong, architect_model_id="weak-model",
                           flow_state="executing")
    assert stacked.element_hints == weak_arch.element_hints


def test_p_axis_override_off_rolls_back():
    """R3: p_axis_phase_overlay=false → 回退 flow-blind(相位不进策略)。"""
    base = resolve_gear("T1")
    p = resolve_gear("T1", flow_state="executing",
                     overrides={"p_axis_phase_overlay": False})
    assert p.architect_note == base.architect_note
    assert p.element_hints == base.element_hints


def test_p_axis_applies_after_legacy_shortcircuit():
    """P 轴独立于 r2_1_axis_stack 旧短路(叠加在最终基线之后)。"""
    p = resolve_gear("T1", flow_state="reviewing",
                     overrides={"r2_1_axis_stack": False})
    assert "流程相位" in p.architect_note


def test_register_overlay_forbids_task_face():
    with pytest.raises(ValueError):
        flow.register_phase_overlay("free", {"agent_note": "x"})
    flow.register_phase_overlay("free", {"element_hints": "high"})  # 合法


def test_register_hint_consumed_by_flow_hints():
    """注册制提示面闭环: 自定义 hint 提供方进入 flow_hints 输出(去重/故障静默)。"""
    flow.register_flow_hint(lambda conv, tasks, req: ["自定义建议A"])
    flow.register_flow_hint(lambda conv, tasks, req: (_ for _ in ()).throw(RuntimeError))
    flow.register_flow_hint(lambda conv, tasks, req: ["自定义建议A", "建议B"])
    out = flow.flow_hints(_conv(), [])
    assert "自定义建议A" in out and "建议B" in out
    assert out.count("自定义建议A") == 1      # 去重


# ── 集成(store): 事件迁移 / 审计 / dismiss ───────────────────────────

def test_recompute_transitions(arch_env):
    from topoone_app_architect.arch_routes import store
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    cid = conv["id"]
    # free(空缓存惰性回填)
    r1 = flow.recompute(cid, trigger="test")
    assert r1["flowState"] == ST.FLOW_FREE and r1["changed"]
    # 幂等: 同事实重复 recompute 零写入
    r2 = flow.recompute(cid, trigger="test")
    assert r2["flowState"] == ST.FLOW_FREE and not r2["changed"]
    # armed(建卡)
    task = store.TasksStore.create({"conversationId": cid, "title": "T",
                                    "instruction": "I", "status": "saved"})
    assert flow.recompute(cid)["flowState"] == ST.FLOW_ARMED
    # executing(运行)
    store.TasksStore.update(task["id"], {"status": "running"})
    assert flow.recompute(cid)["flowState"] == ST.FLOW_EXECUTING
    # reviewing(终态回执)
    store.TasksStore.finish(task["id"], "done", "ok")
    assert flow.recompute(cid)["flowState"] == ST.FLOW_REVIEWING
    # 审计留痕(stream_items; UI 流不混入, 审计走 transitions())
    assert store.StreamItemsStore.for_conv(cid) == [
        i for i in store.StreamItemsStore.for_conv(cid)
        if i["type"] != "flow_transition"]
    audits = store.StreamItemsStore.transitions(cid)
    assert len(audits) >= 4 and audits[0]["payload"]["to"] == ST.FLOW_REVIEWING


def test_interrupted_recovery_cycle(arch_env):
    from topoone_app_architect.arch_routes import store
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    cid = conv["id"]
    store.TasksStore.create({"conversationId": cid, "title": "T",
                             "instruction": "I", "status": "running"})
    assert flow.recompute(cid)["flowState"] == ST.FLOW_EXECUTING
    # sweep 判 stale → interrupted(粘滞)
    row = store.ConversationsStore.get(cid)
    flow.set_flow_state(row, ST.FLOW_INTERRUPTED, trigger="stale")
    assert flow.recompute(cid)["flowState"] == ST.FLOW_INTERRUPTED
    # 无关事件不洗白; 恢复(force)解除
    assert flow.recompute(cid, trigger="noise")["flowState"] == ST.FLOW_INTERRUPTED
    assert flow.recompute(cid, trigger="recover", force=True)["flowState"] \
        == ST.FLOW_EXECUTING


def test_dismiss_consumes_reviewing(arch_env):
    from topoone_app_architect.agent.execution.dispatch import dismiss_task
    from topoone_app_architect.arch_routes import store
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    cid = conv["id"]
    task = store.TasksStore.create({"conversationId": cid, "title": "T",
                                    "instruction": "I", "status": "saved"})
    store.TasksStore.finish(task["id"], "done", "ok")
    assert flow.recompute(cid)["flowState"] == ST.FLOW_REVIEWING
    res = dismiss_task(task["id"])
    assert res["ok"] and res["task"]["dismissedAt"] > 0
    assert flow.recompute(cid, force=True)["flowState"] == ST.FLOW_FREE
    # 幂等: 重复已阅无副作用(ok, 不再变更)
    res2 = dismiss_task(task["id"])
    assert res2["ok"] and res2["task"]["dismissedAt"] == res["task"]["dismissedAt"]
    # 状态闸: 非 done 卡拒绝已阅
    task2 = store.TasksStore.create({"conversationId": cid, "title": "T2",
                                     "instruction": "I", "status": "saved"})
    assert not dismiss_task(task2["id"])["ok"]


def test_safety_class_roundtrip(arch_env):
    from topoone_app_architect.agent.execution.dispatch import propose_task
    from topoone_app_architect.arch_routes import store
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    task = propose_task(conv, "只读分析", "分析架构，不要修改任何文件",
                        safety_class="readonly",
                        work_tags=["analysis", "docs"])
    assert task.get("ok") and task["safetyClass"] == "readonly"
    row = store.TasksStore.get(task["id"])
    assert row["safetyClass"] == "readonly"
    assert row["workTags"] == ["analysis", "docs"]
    # 非法值回落 mutating
    task2 = propose_task(conv, "改代码", "修改文件",
                         safety_class="bogus")
    assert store.TasksStore.get(task2["id"])["safetyClass"] == "mutating"


def test_archive_freezes_phase(arch_env):
    from topoone_app_architect.arch_routes import store
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    cid = conv["id"]
    flow.set_flow_state(store.ConversationsStore.get(cid), ST.FLOW_ARMED,
                        trigger="test")
    store.ConversationsStore.update(cid, {"status": "archived"})
    store.TasksStore.create({"conversationId": cid, "title": "T",
                             "instruction": "I", "status": "saved"})
    r = flow.recompute(cid, trigger="test")
    assert r["flowState"] == ST.FLOW_ARMED and r.get("frozen")
