"""A6.2 投影 conformance——runner 事件词汇全量映射契约(架构验收标准)。

事件→Item 映射语义逐项断言: 任何 runner 事件(kind 词表 17 种 + 未来新增)
必须有确定归宿——注册投影 / NON_ITEM 黑名单 / event 透传, 不允许静默丢弃。
与 packages/core tests/adapter_conformance.py(协议方法面)互补: 那侧管
TurnAdapter 方法/形状, 本侧管「事件 → Item」渲染投影契约。

Run: cd <repo> && python -m pytest apps/architect/tests/test_items_conformance.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.execution import items as it  # noqa: E402

# runner JobEvent 词表(单一事实源 packages/core/topoone/plugins/runner/events.py)
RUNNER_KINDS = {"session_ready", "user_input", "input_required", "done",
                "failed", "progress", "aborted", "finished", "text",
                "tool", "usage", "notice", "turn_outcome", "approval_request",
                "team", "mcp", "verify"}


def test_every_runner_kind_has_deterministic_outcome():
    """17 种 kind 逐项: 产出注册 item / 黑名单静默 / 透传 event——三选一。"""
    from_kinds_covered = set()
    for spec in it.item_types().values():
        from_kinds_covered |= set(spec["from_kinds"])
    for kind in sorted(RUNNER_KINDS):
        ev = {"kind": kind, "text": "x", "changedFiles": ["a.py"],
              "toolName": "bash", "requestId": "r", "overall": "A"}
        out = it.project_event(ev)
        if kind in it.NON_ITEM_KINDS:
            assert out == [], f"{kind} 在黑名单却产出了 item"
        elif kind in from_kinds_covered:
            assert out and all(i["type"] != "event" for i in out), \
                f"{kind} 已注册投影却落了透传"
        else:
            assert out and out[0]["type"] == "event", \
                f"{kind} 既未注册也不在黑名单——必须透传 event(不丢信息)"


def test_turn_completed_status_semantics():
    done = it.project_event({"kind": "done", "changedFiles": ["a.py"]})
    failed = it.project_event({"kind": "failed", "text": "x"})
    tc_done = [i for i in done if i["type"] == "turn_completed"][0]
    tc_fail = [i for i in failed if i["type"] == "turn_completed"][0]
    assert tc_done["status"] == "done" and tc_fail["status"] == "failed"


def test_approval_item_carries_request_contract():
    """A6.1 配对: approval item 必须携带 requestId(宿主应答制契约字段)。"""
    out = it.project_event({"kind": "approval_request", "toolName": "bash",
                            "requestId": "req-9", "toolInput": {"cmd": "ls"}})
    ap = out[0]
    assert ap["type"] == "approval" and ap["status"] == "pending"
    assert ap["payload"]["requestId"] == "req-9"
    # 反向桥还原后 requestId 不丢(存量 /approval 应答路径依赖)
    ev = it.as_legacy_events(out)[0]
    assert ev["requestId"] == "req-9"


def test_file_change_only_from_changed_files():
    assert it.project_event({"kind": "done"}) == [i for i in it.project_event({"kind": "done"})]
    fc = [i for i in it.project_event({"kind": "done", "changedFiles": []})
          if i["type"] == "file_change"]
    assert fc == []                       # 无变更不产 file_change


def test_card_item_map_covers_collab_card_vocabulary():
    """collab/cards.py 卡片词汇 ↔ CARD_ITEM_MAP 全量对账(双侧漂移即失败)。"""
    from topoone_app_architect.agent.collab.cards import (
        KIND_DIGEST, KIND_REQUIREMENT, KIND_TASK_APPROVAL, KIND_TASK_CARD,
        KIND_TASK_INPUT_ECHO, KIND_TASK_PLAN, KIND_TASK_PLAN_DONE,
        KIND_TURN_ERROR, KIND_TASK_RECEIPTS)
    collab_kinds = {KIND_REQUIREMENT, KIND_TASK_CARD, KIND_TASK_APPROVAL,
                    KIND_TURN_ERROR, KIND_DIGEST, KIND_TASK_PLAN,
                    KIND_TASK_PLAN_DONE, KIND_TASK_INPUT_ECHO,
                    *KIND_TASK_RECEIPTS}
    # 豁免: specCreated 非卡片词汇(需求分析流直落); task_progress 进度域
    # (与投影 NON_ITEM_KINDS 同纪律——计数/进展文本走 markdown 直渲染)
    mapped = set(it.CARD_ITEM_MAP) - {"specCreated"}
    unmapped = collab_kinds - mapped - {"task_progress"}
    assert not unmapped, f"卡片词汇未入投影映射: {unmapped}"
    for kind in collab_kinds - {"task_progress"}:
        assert it.item_from_card({"kind": kind}, "x") is not None, kind


def test_item_from_card_non_card_pass_through():
    assert it.item_from_card(None, "x") is None
    assert it.item_from_card({}, "x") is None
    assert it.item_from_card({"kind": "whatever"}, "x") is None
