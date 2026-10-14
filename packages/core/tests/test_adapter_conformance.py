"""conformance kit 执行（A6.1/批次 3）——参考实现跑套件 + 三真适配器静态面断言。

Run: cd <repo> && python -m pytest packages/core/tests/test_adapter_conformance.py -q
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))

from adapter_conformance import (  # noqa: E402
    EXPECTED_ADAPTER_CAPABILITIES, ReferenceAdapter,
    assert_capability_parity, assert_method_surface, assert_reference_behavior,
    overrides)
from topoone.plugins.runner.implement import ImplementJob  # noqa: E402
from topoone.plugins.runner.turn_adapter import (  # noqa: E402
    build_adapter, TurnAdapter)


def test_reference_adapter_passes_suite():
    """参考实现过全契约（套件可执行的自证）。"""
    adapter = ReferenceAdapter()
    adapter.replies = ["先说方案 [[NEED_INPUT]]"]        # 首轮非终态 → 走完整往返
    assert_method_surface(adapter, "reference")
    job = ImplementJob("j-ref", root="/tmp/x", wt="/tmp/x-wt", base="HEAD",
                       branch="exec/t", instruction="do", adapter=adapter,
                       auto_start=False)
    assert_reference_behavior(adapter, job)


def _real_adapters():
    return {
        "opencode": build_adapter("opencode", "opencode", {}),
        "cline": build_adapter("cline-sdk", "cline", {}),
        "codex": build_adapter("codex-server", "codex", {}),
    }


def test_real_adapter_method_surface():
    """三真适配器过方法面契约（不启 sidecar/进程）。"""
    for etype, adapter in _real_adapters().items():
        assert_method_surface(adapter, etype)


def test_real_adapter_capability_parity():
    """三真适配器能力覆写面 ↔ EXPECTED_ADAPTER_CAPABILITIES。

    跨层契约: architect 侧 test_executor_capabilities.py 有 capabilities.py
    的镜像断言——两侧任一漂移即被捕获。
    """
    for etype, adapter in _real_adapters().items():
        assert_capability_parity(adapter, etype)


def test_base_steer_is_default_not_override():
    """base.steer 为默认实现（非覆写）——OpenCode/Codex 不覆写 → 能力 False。"""
    assert not overrides(_real_adapters()["opencode"], "steer")
    assert overrides(_real_adapters()["cline"], "steer")
    assert issubclass(ReferenceAdapter, TurnAdapter)
