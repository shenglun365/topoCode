"""模型能力探测——主 agent 职能域用例(定位裁决 2026-09-26)特征测试。

背景: architect 重定位后主 agent 核心职能=资产问询应答/规约生成/路由决策,
探测套件必须覆盖「问询纪律」(问什么答什么, 不扩大化——cv-257 教训)与
「路由决策」(chat/transfer/assign 三向分发)。本文件守护:
- WEIGHTS 归一不变量(新维度加入后总权重恒 1.0);
- 两组新 graders 的判分契约;
- _build_cases 装配完整性(新维度进套件)。
"""
from __future__ import annotations

from topoone_app_architect.agent.cognition import probe_suite as ps


def test_weights_still_normalized():
    assert abs(sum(ps.WEIGHTS.values()) - 1.0) < 1e-9
    for key in ("inquiry", "routing"):
        assert key in ps.WEIGHTS, f"主 agent 职能维度 {key} 必须参与加权"


def test_inquiry_facts_only_scores_full():
    cases = ps.build_inquiry_cases(count=1)
    raw = ("当前项目 7 个任务中已完成 5 个、1 个进行中; 代码已解析出 187 个"
           "上下文单元。建议建立 KB 关联以获得语义级完成度分析。")
    assert ps.grade_case(cases[0], raw) == 1.0


def test_inquiry_action_declaration_penalized():
    """行动扩大化宣告(已创建需求卡/已启动) → 0.5(事实对但越界)。"""
    cases = ps.build_inquiry_cases(count=1)
    raw = ("当前项目 7 个任务已完成 5 个, 代码解析出 187 个单元。"
           "已为你创建需求卡「项目资产重建」并启动执行。")
    assert ps.grade_case(cases[0], raw) == 0.5


def test_inquiry_tool_call_fails():
    """问询回合输出工具调用块 → 0 分(纪律红线)。"""
    cases = ps.build_inquiry_cases(count=1)
    raw = ('[TOOL_CALL] {"tool": "req.propose", "arguments": {}}[/TOOL_CALL] '
           "项目共 7 个任务、187 个单元。")
    assert ps.grade_case(cases[0], raw) == 0.0


def test_inquiry_missing_facts_half():
    cases = ps.build_inquiry_cases(count=1)
    raw = "项目整体进展顺利, 部分任务仍在进行。"
    assert ps.grade_case(cases[0], raw) == 0.5


def test_routing_action_exact_match():
    cases = ps.build_routing_cases(count=3)
    for case, want in zip(cases, ("transfer", "assign", "chat")):
        good = f'```json\n{{"action": "{want}"}}\n```'
        assert ps.grade_case(case, good) == 1.0
        wrong = f'```json\n{{"action": "{ {"transfer": "assign", "assign": "chat", "chat": "transfer"}[want] }"}}\n```'
        assert ps.grade_case(case, wrong) == 0.0


def test_routing_truncated_fence_half():
    cases = ps.build_routing_cases(count=1)
    assert ps.grade_case(cases[0], '```json\n{"action": "trans') == 0.5


def test_new_dims_in_suite_assembly():
    from topoone_app_architect.agent.cognition.model_profile import _build_cases
    cases = _build_cases()
    assert cases["inquiry"], "问询纪律用例必须进探测套件"
    assert cases["routing"], "路由决策用例必须进探测套件"
