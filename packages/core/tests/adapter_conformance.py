"""TurnAdapter 协议一致性套件（conformance kit; A6.1/批次 3）。

伪适配器升格参考实现——任何 TurnAdapter（测试桩与新执行器接入自证）过同一套
协议契约；真实执行器（opencode/cline/codex）做静态面断言（不启 sidecar）。

契约面:
  A 方法面: start_session/run_turn/probe/abort/dispose 必备（base 声明）;
           steer/respond_approval 为可选能力（覆写探测）
  B 形状面: TurnOutcome(output, changed_files) / TurnProbe(status, last_activity_ts, error)
  C 能力对账: EXPECTED_ADAPTER_CAPABILITIES ↔ architect
             agent/execution/capabilities.py（那侧有镜像测试，双护栏）
"""
from __future__ import annotations

from typing import Any, Dict, List

from topoone.plugins.runner.turn_adapter import (
    TurnAdapter, TurnOutcome, TurnProbe)

# 与 architect agent/execution/capabilities.py 的 approval/steer 列对账
# （跨层契约：此表漂移或彼侧漂移都会被双侧测试捕获）
EXPECTED_ADAPTER_CAPABILITIES: Dict[str, Dict[str, bool]] = {
    "opencode": {"steer": False, "approval": False},
    "cline": {"steer": True, "approval": True},
    "codex": {"steer": False, "approval": False},
}


class ReferenceAdapter(TurnAdapter):
    """参考实现（合同教科书）：echo 回合 + 可编程结局; steer 默认支持。"""

    executor_id = "reference"

    def __init__(self):
        self.seen: List[str] = []
        self.replies: List[str] = []
        self.steer_enabled = True

    async def start_session(self, job) -> None:
        job.session_id = job.session_id or "ref-session"

    async def run_turn(self, job, text: str) -> TurnOutcome:
        self.seen.append(text)
        if self.replies:
            return TurnOutcome(output=self.replies.pop(0), changed_files=[])
        return TurnOutcome(output=f"{text}\n[[IMPLEMENT_DONE]]", changed_files=[])

    async def probe(self, job) -> TurnProbe:
        return TurnProbe("idle", job.last_activity_ts, "")

    async def steer(self, job, text: str) -> bool:
        return bool(self.steer_enabled)


def overrides(adapter: TurnAdapter, method: str) -> bool:
    """可选能力探测：子类是否覆写了 base 方法（base 实现视为「不支持」）。"""
    return getattr(type(adapter), method, None) is not getattr(TurnAdapter, method, None)


def assert_method_surface(adapter: TurnAdapter, executor_type: str) -> None:
    """契约 A/B: 必备方法 + TurnOutcome/TurnProbe 形状字段。"""
    for m in ("start_session", "run_turn", "probe", "abort", "dispose"):
        fn = getattr(adapter, m, None)
        assert callable(fn), f"{executor_type} 缺必备方法 {m}"
    outcome_fields = {f for f in TurnOutcome._dataclass_fields_} \
        if hasattr(TurnOutcome, "_dataclass_fields_") else {"output", "changed_files"}
    assert {"output", "changed_files"} <= outcome_fields
    probe_fields = {f for f in TurnProbe._dataclass_fields_} \
        if hasattr(TurnProbe, "_dataclass_fields_") else set()
    if probe_fields:
        assert {"status", "last_activity_ts"} <= probe_fields


def assert_capability_parity(adapter: TurnAdapter, executor_type: str) -> None:
    """契约 C: 适配器覆写面 ↔ 能力期望表（↔ architect capabilities.py）。"""
    expect = EXPECTED_ADAPTER_CAPABILITIES.get(executor_type)
    assert expect is not None, f"未登记的执行器类型: {executor_type}"
    assert overrides(adapter, "steer") == expect["steer"], \
        f"{executor_type} steer 覆写面与能力表不符"
    assert (callable(getattr(adapter, "respond_approval", None))) == expect["approval"], \
        f"{executor_type} respond_approval 与能力表不符"


def assert_reference_behavior(adapter: ReferenceAdapter, job) -> None:
    """参考实现行为脚本（可执行文档）：start→首轮 NEED_INPUT→user_input 续跑→done。"""
    import asyncio

    async def _flow():
        await job.start()
        assert job.status == "running"
        assert job.session_id == "ref-session"
        await job.turn_task                              # 回合 1(指令)
        assert job.status == "waiting_input"
        r = await job.user_input("第二轮")
        assert r["ok"] and r["queued"] is False
        await job.turn_task                              # 回合 2(用户回复)
        assert job.status == "done"

    asyncio.run(_flow())
    kinds = [e["kind"] for e in job.bus.events]
    assert kinds[0] == "session_ready"
    assert "input_required" in kinds and "user_input" in kinds and "done" in kinds
    assert adapter.seen == [job.instruction, "第二轮"]
