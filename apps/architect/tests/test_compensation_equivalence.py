"""收编等价基线(M0, 整体设计 §7-1) — 补偿收编前的行为基线冻结。

覆盖: gear 解析冒烟(深覆盖见 test_gears/test_gear_policy_matrix) +
任务指令组装 golden(挡位分叉/cap_note/运行时身份) + task 围栏提取 golden +
purpose 词表冻结校验。收编(补偿/回合引擎迁移)前后本文件必须全绿(D3)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_compensation_equivalence.py -q
"""
import dataclasses
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.compensation import (Axis, CompensationCtx,
                                                      CapabilityScores, Purpose)
from topoone_app_architect.agent.governance.gears import resolve_gear
from topoone_app_architect.agent.planning.task_plan import (
    assemble_task_instruction, extract_task_fence)

GOLDENS = os.path.join(os.path.dirname(__file__), "goldens")

_TASK = {"title": "示例任务",
         "instruction": "实现示例功能：在模块 A 中增加导出函数。"}


def _golden(name: str) -> str:
    with open(os.path.join(GOLDENS, name), encoding="utf-8") as f:
        return f.read()


# ── gear 解析冒烟(深覆盖: test_gears.py / test_gear_policy_matrix.py) ──

def test_gear_chain_smoke():
    """2610 挡位退役: 解析恒统一策略行(T1)。"""
    assert resolve_gear("quick").tier == "T1"
    assert resolve_gear("auto", {"tierProbed": "T2"}).tier == "T1"
    assert resolve_gear("auto", {"capability": "T0"}).tier == "T1"
    assert resolve_gear("unknown-mode").tier == "T1"


# ── 任务指令组装 golden(收编迁往 DispatchTurn + MilestoneProvider 前冻结) ──
# 2610 挡位退役: 组装器字段覆盖仍受支持(手构策略行保覆盖; 生产恒统一策略)

def _tier_policy_like(**fields):
    """手构旧挡位形态策略行(仅测试: 组装器按字段分叉的覆盖面)。"""
    import dataclasses
    from topoone_app_architect.agent.governance.gears import UNIFIED_POLICY
    return dataclasses.replace(UNIFIED_POLICY, **fields)


def test_instruction_golden_t0():
    p = _tier_policy_like(
        tier="T0", label="强模型直通车·直出任务卡", kb=False, pre_split="none",
        max_iterations=2000,
        architect_note=("快捷挡(T0 直通车)：不做需求分析(不调用 req.propose 与资产检索类工具)。"
                        "信息问询(状态/进度/资产检索类提问)直接作答, 不建任何卡——问什么答什么, 不扩大化。"
                        "依据用户请求直接整理实质任务(目标/方案要点/边界/验收)调用 task.propose "
                        "创建任务卡供用户确认执行；请求过于模糊时先集中提问。"
                        "内联 @执行器 前缀(如 @cline)直接按指定执行器建卡。"),
        agent_note="执行器自主推进, 减少不必要暂停；里程碑协议照常(计划确认+每里程碑报告)。",
        ctx_budget=1.0, prompt_style="standard", structured_output=False)
    out = assemble_task_instruction(_TASK, policy=p)
    assert out == _golden("task_instruction_T0.txt")


def test_instruction_golden_t1():
    from topoone_app_architect.agent.governance.gears import UNIFIED_POLICY
    out = assemble_task_instruction(_TASK, prior_brief="", policy=UNIFIED_POLICY)
    assert out == _golden("task_instruction_T1.txt")


def test_instruction_golden_t2_cap_runtime():
    policy = dataclasses.replace(
        _tier_policy_like(
            tier="T2", label="弱模型全面补偿·步骤级编排", pre_split="steps",
            cadence="key_step", max_iterations=300,
            tool_surface="reduced", ctx_budget=0.35,
            depends_source="linear", logic_diagram="uml",
            agent_note="按任务上下文中的步骤序列逐步执行；关键步骤(编译前/破坏性操作/方案分叉)完成后简短报告再继续；里程碑协议照常。"),
        cap_note="指令跟随探针未过——封顶 T2(结构化 probeFlags)")
    out = assemble_task_instruction(
        _TASK, prior_brief="前情：已完成基础骨架搭建。", policy=policy,
        runtime={"branch": "task/demo-1", "root": "/home/u/proj-main",
                 "workspace": "worktree"})
    assert out == _golden("task_instruction_T2.txt")


# ── task 围栏提取 golden(弱模型围栏协议, cv-150 教训) ──

def test_task_fence_explicit_block():
    text = '前言\n```task\n{"title": "任务A", "instruction": "做事"}\n```\n后记'
    d = extract_task_fence(text)
    assert d and d["title"] == "任务A" and d["instruction"] == "做事"


def test_task_fence_json_candidate_and_diagram_excluded():
    # 归属排斥(cv-246 架构裁决): 规约 schema 载荷归 req.propose 域——
    # 任务域不再把 requirementMd 折叠成 instruction 误落任务卡
    assert extract_task_fence(
        '```json\n{"title": "任务B", "requirementMd": "为导出模块补充批量导出能力"}\n```'
    ) is None
    # 纯任务形态 json(instruction)仍认领
    d = extract_task_fence(
        '```json\n{"title": "任务C", "instruction": "统计各目录文件数量并输出清单"}\n```')
    assert d and d["title"] == "任务C" and "文件数量" in d["instruction"]
    # 图 IR 不认领(diagram.build 产物形态)
    assert extract_task_fence(
        '```json\n{"type": "flow", "version": 1, "nodes": [], "edges": []}\n```'
    ) is None
    assert extract_task_fence("无围栏文本") is None


# ── purpose 词表冻结(D10) ──

def test_purpose_vocabulary_frozen():
    assert len(Purpose) == 19
    assert {p.value for p in Purpose} == {
        "requirement", "architecture", "module",
        "extraction", "clarify", "collect", "split", "probe",
        "summary", "distill", "design", "se", "ut",
        "role:extract", "role:verify", "role:induce", "role:pseudo",
        "role:evaluate", "role:mine",
    }


def test_compensation_ctx_dimensions():
    ctx = CompensationCtx(
        gear=resolve_gear("auto", {"tierProbed": "T2"}), axis=Axis.S,
        purpose=Purpose.EXTRACTION,
        scores=CapabilityScores(requirement=0.42, arch=0.7, module=0.55))
    assert ctx.tier == "T1"                     # 2610 挡位退役: 恒统一策略行
    assert ctx.purpose_score() == 0.42          # R2.4 分目的消费口
