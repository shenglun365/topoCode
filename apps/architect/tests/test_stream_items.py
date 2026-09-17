"""A6.2 Item 投影回归——注册制/多 item/透传拓展/反向桥/conformance 语义。

Run: cd <repo> && python -m pytest apps/architect/tests/test_stream_items.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.execution import items as it  # noqa: E402


# ── 内置投影 ────────────────────────────────────────────────────────

def test_tool_call_projection_status_parse():
    run = it.project_event({"kind": "tool", "text": "▶ bash", "toolName": "bash", "seq": 1})
    ok = it.project_event({"kind": "tool", "text": "✓ bash", "toolName": "bash", "seq": 2})
    err = it.project_event({"kind": "tool", "text": "✗ bash", "toolName": "bash", "seq": 3})
    assert run[0]["type"] == "tool_call" and run[0]["status"] == "running"
    assert ok[0]["status"] == "ok" and err[0]["status"] == "error"
    assert run[0]["tool"] == "bash" and not run[0]["text"].startswith("▶")


def test_done_yields_file_change_and_turn_completed():
    out = it.project_event({"kind": "done", "text": "[[IMPLEMENT_DONE]] 完",
                            "changedFiles": ["a.py", "b.py"], "ts": 111})
    types = [i["type"] for i in out]
    assert types == ["file_change", "turn_completed"]
    assert out[0]["payload"]["files"] == ["a.py", "b.py"]
    assert out[1]["status"] == "done"


def test_failed_yields_turn_completed_error_only():
    out = it.project_event({"kind": "failed", "text": "构建失败", "ts": 222})
    assert [i["type"] for i in out] == ["turn_completed"]
    assert out[0]["status"] == "failed" and "构建失败" in out[0]["text"]


def test_approval_verify_input_notice():
    ap = it.project_event({"kind": "approval_request", "toolName": "bash",
                           "requestId": "r1", "toolInput": {"cmd": "ls"}})
    assert ap[0]["type"] == "approval" and ap[0]["status"] == "pending"
    assert ap[0]["payload"]["requestId"] == "r1"
    vf = it.project_event({"kind": "verify", "overall": "A",
                           "build": {"verdict": "PASS"}, "text": "t"})
    assert vf[0]["type"] == "verify" and vf[0]["status"] == "A"
    assert vf[0]["payload"]["stages"]["build"]["verdict"] == "PASS"
    ti = it.project_event({"kind": "input_required", "text": "[[NEED_INPUT]] 等"})
    assert ti[0]["type"] == "task_input" and "等" in ti[0]["text"]
    assert "[[NEED_INPUT]]" not in ti[0]["text"]
    no = it.project_event({"kind": "notice", "text": "压缩", "reason": "compact"})
    assert no[0]["type"] == "notice" and no[0]["payload"]["reason"] == "compact"


def test_non_item_kinds_silent():
    for kind in it.NON_ITEM_KINDS:
        assert it.project_event({"kind": kind, "text": "x"}) == []


# ── 开放拓展(不局限于四类) ──────────────────────────────────────────

def test_unknown_kind_passthrough_event_item():
    out = it.project_event({"kind": "custom_future", "text": "新执行器事件",
                            "customField": 7})
    assert len(out) == 1
    assert out[0]["type"] == "event" and out[0]["kind"] == "custom_future"
    assert out[0]["payload"]["customField"] == 7
    # 反向桥还原
    ev = it.as_legacy_events(out)[0]
    assert ev["kind"] == "custom_future" and ev["customField"] == 7


def test_register_new_type_extends_vocabulary():
    it.register_item_type("checkpoint", ("done",),
                          lambda ev: [it._base("checkpoint", ev, status="ok")])
    try:
        out = it.project_event({"kind": "done", "changedFiles": ["x.py"], "ts": 9})
        types = [i["type"] for i in out]
        assert "checkpoint" in types           # 新类型按注册即生效
        try:
            it.register_item_type("checkpoint", ("done",), lambda e: [])
        except RuntimeError as exc:
            assert "重复注册" in str(exc)
        else:
            raise AssertionError("重复注册未拒绝")
    finally:
        it._REGISTRY.pop("checkpoint", None)


def test_duplicate_builtin_rejected():
    try:
        it.register_item_type("tool_call", ("tool",), lambda e: [])
    except RuntimeError as exc:
        assert "重复注册" in str(exc)
    else:
        raise AssertionError("内置类型重复注册未拒绝")


# ── 流 fold + 反向桥 ────────────────────────────────────────────────

def test_project_stream_preserves_order_and_drops_empty():
    events = [{"kind": "progress", "toolCount": 1},
              {"kind": "tool", "text": "▶ bash", "toolName": "bash", "seq": 1},
              {"kind": "done", "changedFiles": ["a.py"], "seq": 2}]
    out = it.project_stream(events)
    assert [i["type"] for i in out] == ["tool_call", "file_change", "turn_completed"]


def test_as_legacy_bridge_roundtrip_core_types():
    items = it.project_stream([
        {"kind": "tool", "text": "✓ bash", "toolName": "bash"},
        {"kind": "done", "changedFiles": ["a.py"]},
        {"kind": "failed", "text": "boom"}])
    evs = it.as_legacy_events(items)
    kinds = [e["kind"] for e in evs]
    # done 产出 file_change+turn_completed 两个 item, 反向桥各还原一条 done 事件
    assert kinds == ["tool", "done", "done", "failed"]
    assert evs[0]["toolName"] == "bash"
    assert evs[1]["changedFiles"] == ["a.py"]


# ── conformance: 注册表覆盖声明(与 adapter_conformance 同源纪律) ────

def test_registry_from_kinds_declared_and_within_runner_vocabulary():
    runner_kinds = {"session_ready", "user_input", "input_required", "done",
                    "failed", "progress", "aborted", "finished", "text",
                    "tool", "usage", "notice", "turn_outcome",
                    "approval_request", "team", "mcp", "verify",
                        # architect 合成事件(非 runner 词汇, 显式允许)
                        "reasoning", "plan",
                        # 卡片域合成(item_from_card 读侧投影词汇)
                        "task_status", "turn_error", "digest", "spec"}
    for t, spec in it.item_types().items():
        assert spec["from_kinds"], f"{t} 未声明 from_kinds"
        unknown = set(spec["from_kinds"]) - runner_kinds
        assert not unknown, f"{t} 声明了词汇表外 kind: {unknown}"
    # 非词表/非黑名单 kind 必走透传(开放拓展兜底)
    assert it.project_event({"kind": "totally_new"})[0]["type"] == "event"
