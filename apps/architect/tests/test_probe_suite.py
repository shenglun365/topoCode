"""探针套件纯函数层回归(probe_suite: A/C 两轴统一刻度/准入/structured 判据)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_probe_suite.py -q
"""
from topoone_app_architect.agent.cognition import probe_suite as ps  # noqa: E402


def _noop_parse(raw):
    return []


def test_tool_cases_use_real_tool_names():
    """工具协议用例接真实注册工具(name+参数形状由调用方注入)。"""
    tools = [{"name": "req.propose", "params_hint": '{"title", ...}'},
             {"name": "kb.asset.search", "params_hint": '{"text"}'}]
    cases = ps.build_tool_cases(tools, _noop_parse, count=3)
    assert len(cases) == 3
    assert all(c["dim"] == "tool" for c in cases)
    # 轮转覆盖全部真实工具
    wants = {c["want_tool"] for c in cases}
    assert wants == {"req.propose", "kb.asset.search"}
    # 系统段含真实参数形状与系统基本指令(工具调用协议)
    assert '{"title", ...}' in cases[0]["system"]
    assert "[TOOL_CALL]" in cases[0]["system"]
    assert ps.grade_case(cases[0], "plain text 无协议") == 0.0
    assert ps.grade_case(cases[0], "[TOOL_CALL]{bad json") == 0.5
    from topoone_app_architect.agent.tools.protocol import extract_tool_calls
    real = ps.build_tool_cases(tools, extract_tool_calls, count=1)
    assert ps.grade_case(
        real[0],
        '[TOOL_CALL]{"tool":"req.propose","arguments":{}}[/TOOL_CALL]') == 1.0


def test_json_and_instruction_grades():
    jc = ps.build_json_cases()
    assert ps.grade_case(jc[0], '```json\n{"title": "T"}\n```') == 1.0
    assert ps.grade_case(jc[0], "```json\n{bad}\n```") == 0.5
    assert ps.grade_case(jc[0], "没有围栏") == 0.0
    ic = ps.build_instruction_cases()
    assert ps.grade_case(ic[0], "好的, 我来实现该脚本") == 1.0
    assert ps.grade_case(ic[0], "这超出我的能力范围, 建议您使用其他工具") == 0.0


def test_tier_from_score_monotonic():
    """差分只降不升: 名义强档低分 → 兜底; 高分不升档。"""
    assert ps.tier_from_score(0.95, 0) == 0
    assert ps.tier_from_score(0.60, 0) == 0      # 0.60 ≥ 0.52, base=0 → 保持 0
    assert ps.tier_from_score(0.60, 2) == 2      # base 弱不因分数回升
    assert ps.tier_from_score(0.40, 0) == 1      # <0.52 → 至少 T1
    assert ps.tier_from_score(0.20, 0) == 2      # <0.25 → T2 全面补偿


def test_admission_weak_not_blocking():
    """准入: T2 → weak 提示(不拦截); T0/T1 → pass。"""
    weak = ps.admission(2)
    assert weak["level"] == "weak" and "建议更换" in weak["note"]
    assert ps.admission(1)["level"] == "pass"
    assert ps.admission(0)["level"] == "pass"


def test_structured_bit_threshold():
    assert ps.structured_from(0.7) is True
    assert ps.structured_from(1.0) is True
    assert ps.structured_from(0.69) is False
