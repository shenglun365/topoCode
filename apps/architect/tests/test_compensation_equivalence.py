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
from topoone_app_architect.agent.governance.gears import _TIERS, resolve_gear
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
    assert resolve_gear("quick").tier == "T0"
    assert resolve_gear("auto", {"tierProbed": "T2"}).tier == "T2"
    assert resolve_gear("auto", {"capability": "T0"}).tier == "T0"
    assert resolve_gear("unknown-mode").tier == "T1"


# ── 任务指令组装 golden(收编迁往 DispatchTurn + MilestoneProvider 前冻结) ──

def test_instruction_golden_t0():
    out = assemble_task_instruction(_TASK, policy=_TIERS["T0"])
    assert out == _golden("task_instruction_T0.txt")


def test_instruction_golden_t1():
    out = assemble_task_instruction(_TASK, prior_brief="", policy=_TIERS["T1"])
    assert out == _golden("task_instruction_T1.txt")


def test_instruction_golden_t2_cap_runtime():
    policy = dataclasses.replace(
        _TIERS["T2"], cap_note="指令跟随探针未过——封顶 T2(结构化 probeFlags)")
    out = assemble_task_instruction(
        _TASK, prior_brief="前情：已完成基础骨架搭建。", policy=policy,
        runtime={"branch": "task/demo-1", "root": "/home/u/proj-main"})
    assert out == _golden("task_instruction_T2.txt")


# ── task 围栏提取 golden(弱模型围栏协议, cv-150 教训) ──

def test_task_fence_explicit_block():
    text = '前言\n```task\n{"title": "任务A", "instruction": "做事"}\n```\n后记'
    d = extract_task_fence(text)
    assert d and d["title"] == "任务A" and d["instruction"] == "做事"


def test_task_fence_json_candidate_and_diagram_excluded():
    # json 候选围栏: 需实质任务字段(instruction/requirementMd ≥10 字, 防误判)
    d = extract_task_fence(
        '```json\n{"title": "任务B", "requirementMd": "为导出模块补充批量导出能力"}\n```')
    assert d and d["title"] == "任务B" and "批量导出" in d["instruction"]
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
    assert ctx.tier == "T2"
    assert ctx.purpose_score() == 0.42          # R2.4 分目的消费口
