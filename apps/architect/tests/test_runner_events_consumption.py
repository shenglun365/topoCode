"""architect 侧 runner 事件消费面守护（R2; 与 core 基线同源对账）。

单源 = packages/core/topoone/plugins/runner/events.py；基线 =
packages/core/runner-events-baseline.json。本测试锁定:

  - runner_client 走「活导入」而非降级桩（_SCHEMA=True）
  - 消费的 parse_event/is_valid_kind 与 core 单源是同一函数对象（无 vendored 副本）
  - schema 全部 kind 流经 parse_event/is_valid_kind 无一拒绝
  - 未知 kind 向后兼容（老 runner 新 kind 不拒）
  - architect 运行环境安装的 core schema 与仓内基线一致（跨侧漂移守卫）

Run: cd <repo> && python -m pytest apps/architect/tests/test_runner_events_consumption.py -q
"""
import json
from pathlib import Path

from topoone.plugins.runner import events as core_events
from topoone_app_architect.agent.execution import runner_client

BASELINE_PATH = Path(__file__).resolve().parents[3] / "packages" / "core" / "runner-events-baseline.json"


def test_schema_live_import_not_stub():
    """core 事件模块必须活导入（降级桩 = 静默失去契约守护，属环境错误）。"""
    assert runner_client._SCHEMA is True, (
        "runner_client 事件 schema 走了降级桩——检查 topoone editable 安装")


def test_single_source_identity():
    """消费的就是 core 单源函数对象：杜绝 architect 侧出现 vendored schema 副本。"""
    assert runner_client.parse_event is core_events.parse_event
    assert runner_client.is_valid_kind is core_events.is_valid_kind


def test_all_schema_kinds_flow_through():
    """schema 全部 kind：is_valid_kind 全真，make→parse 往返无损。"""
    for kind in core_events.EventKind.all():
        assert runner_client.is_valid_kind(kind), kind
        made = core_events.make_event(1, kind, "x", toolName="t")
        parsed = runner_client.parse_event(made)
        assert parsed["kind"] == kind and parsed["text"] == "x"


def test_unknown_kind_backward_compat():
    """未知 kind 放行（老 runner 新 kind 向后兼容）；但 is_valid_kind 不收录。"""
    future = runner_client.parse_event({"seq": 9, "kind": "__future_kind__", "text": ""})
    assert future["seq"] == 9
    assert not runner_client.is_valid_kind("__future_kind__")


def test_installed_core_matches_baseline():
    """architect 运行环境安装的 core schema = 仓内基线（跨侧漂移守卫）。"""
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    actual = core_events.schema_snapshot()
    assert actual == baseline["schema"], (
        "architect 环境的 core 事件 schema 与 runner-events-baseline.json 不一致——"
        "pip editable 安装未同步或基线未重生成")
