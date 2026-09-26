"""问询纪律哨兵(重定位 P1 判据, 定位裁决 2026-09-26)。

三挡 architect_note 必须携带问询纪律行——「问什么答什么, 不扩大化」是
治理词汇单源(gears)注入提示面, 本测试防其回潮缺失。
"""
from __future__ import annotations

import pytest

from topoone_app_architect.agent.governance.gears import resolve_gear


@pytest.mark.parametrize("tier", ["T0", "T1", "T2"])
def test_all_gears_carry_inquiry_discipline(tier):
    p = resolve_gear(tier)
    assert "问什么答什么" in p.architect_note, f"{tier} 缺问询纪律行"
    assert "req.propose" in p.architect_note, f"{tier} 纪律行须点名规约工具"
