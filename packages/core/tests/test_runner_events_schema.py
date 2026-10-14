"""runner 事件 schema 契约守护（R2; codex schema-fixtures 同模式）。

单源 = packages/core/topoone/plugins/runner/events.py:schema_snapshot()，
基线 = packages/core/runner-events-baseline.json（生成: scripts/runner-events-baseline.py）。

锁定面:
  - 基线比对（kind 集/顺序、EventKind 常量、基础形状、截断、环容量、parse 策略）
  - EventKind 常量 ↔ _KINDS 一致性（杜绝双源漂移）
  - make_event 形状/截断/非法 kind 即抛
  - parse_event 宽容策略（未知 kind 放行=老 runner 新 kind 向后兼容）
  - 快照确定性（两次调用逐字节一致）

契约纪律（只增不改）：既有字段形状冻结；新增 kind/extra 向后兼容。
有意变更 → 重跑 scripts/runner-events-baseline.py 并在 PR 标注 runner 事件破坏面。

Run: cd <repo> && python -m pytest packages/core/tests/test_runner_events_schema.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from topoone.plugins.runner import events as ev  # noqa: E402

BASELINE_PATH = os.path.join(os.path.dirname(__file__), "..", "runner-events-baseline.json")


def _baseline() -> dict:
    with open(BASELINE_PATH, encoding="utf-8") as f:
        return json.load(f)


def test_baseline_matches_schema():
    """基线漂移守卫：schema_snapshot() 必须与基线逐字段一致。"""
    expected = _baseline()["schema"]
    actual = ev.schema_snapshot()
    assert actual == expected, (
        "runner 事件 schema 与基线不一致（基线 {} vs 实际 {}）。\n"
        "若为有意的契约变更：1) 运行 python3 scripts/runner-events-baseline.py 重生成；"
        "2) PR 描述标注 runner 事件破坏面（turn_adapter 协议/事件 schema/续跑格式）；"
        "3) 同步评估 architect 泵消费面。"
    ).format(
        json.dumps(expected, sort_keys=True, ensure_ascii=False),
        json.dumps(actual, sort_keys=True, ensure_ascii=False))


def test_event_kind_constants_consistent():
    """EventKind 常量 ↔ _KINDS 双源一致性：值集相等、无重复、all() 即 _KINDS。"""
    constants = {v for k, v in vars(ev.EventKind).items()
                 if not k.startswith("_") and isinstance(v, str)}
    kinds = ev.EventKind.all()
    assert set(kinds) == constants, f"EventKind 常量与 _KINDS 漂移: {set(kinds) ^ constants}"
    assert len(kinds) == len(set(kinds)), "kind 存在重复定义"
    assert ev.EventKind.all() is ev._KINDS
    assert all(ev.is_valid_kind(k) for k in kinds)
    assert not ev.is_valid_kind("__nope__")


def test_make_event_shape_truncation_unknown_kind():
    """make_event 形状单源：基础四键 + extra 合并 + 文本截断 + 非法 kind 即抛。"""
    e = ev.make_event(7, ev.EventKind.DONE, "ok", changedFiles=["a.py"])
    assert set(e.keys()) == {"seq", "ts", "kind", "text", "changedFiles"}
    assert e["seq"] == 7 and isinstance(e["ts"], int)
    long = "x" * (ev._TEXT_LIMIT + 100)
    assert len(ev.make_event(1, "text", long)["text"]) == ev._TEXT_LIMIT
    try:
        ev.make_event(1, "__nope__")
    except ValueError as exc:
        assert "__nope__" in str(exc)
    else:
        raise AssertionError("非法 kind 未抛 ValueError")


def test_parse_event_tolerance_policy():
    """parse_event 宽容策略锁定：非 dict 拒；seq 须可整型化；未知 kind 放行。"""
    good = ev.parse_event({"seq": 3, "kind": "done", "text": ""})
    assert good["seq"] == 3
    future = ev.parse_event({"seq": 4, "kind": "__future_kind__", "text": ""})
    assert future["kind"] == "__future_kind__"          # 老 runner 新 kind 向后兼容
    for bad in ("string", 42, None, ["seq"]):
        try:
            ev.parse_event(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"非 dict 输入未拒: {bad!r}")
    try:
        ev.parse_event({"seq": "not-int", "kind": "done"})
    except ValueError:
        pass
    else:
        raise AssertionError("不可整型化 seq 未拒")


def test_schema_snapshot_deterministic():
    """快照确定性：两次调用相等且 JSON 序列化稳定（基线 diff 无噪音）。"""
    a, b = ev.schema_snapshot(), ev.schema_snapshot()
    assert a == b
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
