"""策略字段消费门禁(R1.2, 整体设计 §7-2) — GearPolicy 字段必须有注册消费者。

机制: 补偿注册表自省(consumption_map)——每个必检字段须有 ≥1 个 Provider
声明消费(consumes)。M0 骨架期 REQUIRED_FIELDS 为空; M1/M2 收编时逐批填充
(§5.1 七字段), 填充即门禁生效。行数基线门禁见 test_file_size_gate。

Run: cd <repo> && python -m pytest apps/architect/tests/test_policy_consumption_gate.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.compensation import (
    Axis, CompensationCtx, GLOBAL_REGISTRY, PromptPiece, Purpose, RunParams,
    Verdict, ProviderRegistry, assemble, conclude, TurnOutput)

# ── 棘轮清单 ──
# M1 五 Provider 收编 + M2 门禁全量(R1.2): §5.1 七字段全部接线。
# D11: reasoning_effort 已迁出 GearPolicy, 永不入列。
REQUIRED_FIELDS: tuple = (
    "architect_note", "element_hints", "cap_note", "ctx_budget", "agent_note",
    "tool_surface", "prompt_style", "structured_output", "logic_diagram",
    "cadence", "schedule_discipline",
)

# 基线(棘轮只增不减): 全局注册表内置 Provider 数(M1 五 + M2 四)。
EXPECTED_GLOBAL_COUNT = 9


class _Probe:
    """协议探针(仅用于自省机制测试)。"""

    name = "probe"
    purposes = frozenset({Purpose.EXTRACTION})
    consumes = frozenset({"tool_surface"})

    def assemble(self, ctx, prompt) -> None:
        prompt.pieces.append(_mk_piece())

    def conclude(self, ctx, output):
        return None


def _mk_piece():
    return PromptPiece(placement="system", key="probe", text="x")


def _ctx(purpose: Purpose = Purpose.EXTRACTION) -> CompensationCtx:
    from topoone_app_architect.agent.governance.gears import default_policy
    return CompensationCtx(gear=default_policy(), axis=Axis.S, purpose=purpose)


def test_registry_introspection_machinery():
    """消费清单自省机制(门禁的依据)可用且语义正确。"""
    reg = ProviderRegistry()
    reg.register(_Probe(), priority=10)
    mapping = reg.consumption_map()
    assert mapping == {"tool_surface": ["probe"]}
    assert [p.name for p in reg.providers(Purpose.EXTRACTION)] == ["probe"]
    assert reg.providers(Purpose.SPLIT) == []          # purposes 过滤
    try:
        reg.register(_Probe())
        raise AssertionError("重复登记应报错")
    except ValueError:
        pass


def test_assemble_collects_pieces_and_params():
    reg = ProviderRegistry()

    class _P:
        name, purposes, consumes = "p", frozenset(), frozenset()

        def assemble(self, ctx, prompt):
            prompt.pieces.append(_mk_piece())
            prompt.params = prompt.params.merge_first_wins(
                RunParams(ctx_budget=0.5, cadence="key_step"))

        def conclude(self, ctx, output):
            return Verdict(ok=True, gate_notes=["g1"])

    reg.register(_P(), priority=1)
    prompt = assemble(_ctx(), reg, "BASE")
    assert prompt.base == "BASE"
    assert [p.key for p in prompt.pieces] == ["probe"]
    assert prompt.params.ctx_budget == 0.5 and prompt.params.cadence == "key_step"
    assert prompt.system_notes() == ["x"]
    v = conclude(_ctx(), reg, TurnOutput(text="out"))
    assert v.ok and v.gate_notes == ["g1"]


def test_required_fields_have_consumers():
    """必检字段 → ≥1 消费者(棘轮: REQUIRED_FIELDS 随 M1/M2 收编逐批填充)。"""
    mapping = GLOBAL_REGISTRY.consumption_map()
    missing = [f for f in REQUIRED_FIELDS if not mapping.get(f)]
    assert not missing, f"策略字段缺消费者: {missing}"


def test_reasoning_effort_not_in_strategy_code():
    """D11: reasoning_effort 已迁出 GearPolicy, agent 策略代码禁再现。"""
    import os
    import re
    pkg = os.path.join(os.path.dirname(__file__), "..", "..",
                       "topoone_app_architect")
    hits = []
    for sub in ("agent", "arch_routes"):
        root = os.path.join(pkg, sub)
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d != "__pycache__"]
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                full = os.path.join(dirpath, fn)
                with open(full, encoding="utf-8") as f:
                    if re.search(r"\breasoning_effort\b", f.read()):
                        hits.append(os.path.relpath(full, pkg))
    assert not hits, f"reasoning_effort 应只存在于模型配置域(D11), 策略代码残留: {hits}"


def test_global_registry_baseline():
    """全局注册表基线(棘轮): M1 五内置 Provider 登记; M2 增量更新本断言。"""
    from topoone_app_architect.agent.compensation import providers  # 触发登记
    assert len(GLOBAL_REGISTRY) == EXPECTED_GLOBAL_COUNT
    mapping = GLOBAL_REGISTRY.consumption_map()
    assert set(mapping) >= set(REQUIRED_FIELDS)
