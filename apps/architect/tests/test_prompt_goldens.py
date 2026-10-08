"""W1-1 prompt 分型金样(golden)测试 — 漂移即红。

断言三维: ① 全文快照相等(主断言, 最强) ② 结构锚按序(诊断信息) ③ 关键契约句
存在 + 字数预算上限。golden 变更必须对应模板/契约版本变更(成对版本化纪律,
roadmap §6.5)且走 --regen-goldens 显式再生、人工过目 diff。

分型(以 render_system 实际 ctx 维度为准): default_t1 / full_t0 / slim_t2 /
t1_diagram。arch_env 隔离下无项目绑定 → 各块渲染确定(header=未绑定+greenfield,
mcp/skill_docs 空块剔除, capability 由 _ARCH_TOOLS 静态注册表渲染)。

Run: python -m pytest apps/architect/tests/test_prompt_goldens.py -q
再生: python -m pytest apps/architect/tests/test_prompt_goldens.py --regen-goldens
"""
from __future__ import annotations

import json
import os

import pytest

from topoone_app_architect.agent.cognition import prompt as P

GOLDEN_DIR = os.path.join(os.path.dirname(__file__), "goldens", "prompt")

BASE_CTX = {"root": "", "project": None, "model_id": ""}


@pytest.fixture(autouse=True)
def _prod_tool_registry():
    """对齐生产工具注册态: ctx.*/probe/评估/提炼 工具由 orchestrator 幂等注册
    (orchestrator.py:36 register_session_tools)——golden 必须在**生产形态**
    下渲染, 否则快照随测试导入顺序漂移(全量套件下其它用例先行触发注册)。"""
    from topoone_app_architect.agent.orchestrator import register_session_tools
    register_session_tools()

VARIANTS = {
    "default_t1": {"tier": 1},                       # 缺省档
    "full_t0": {"tier": 0},                          # 宽预算档
    "slim_t2": {"tier": 2, "prompt_slim": True},     # 简挡(系统面说明省略)
    "t1_diagram": {"tier": 1, "diagram_skill": True},  # 绘图技能块
}

# 结构锚(按渲染顺序; 子集断言——条件块按预算可裁, 恒置块必在)
ANCHORS = ["你是 TopoCode", "## 职责边界", "## 对话路线", "你可以使用以下能力"]
# 关键契约句(恒置语义, 任何分型不得缺失)
KEY_PHRASES = [
    "[TOOL_CALL]",            # 工具调用协议
    "硬性规则(防编造)",        # 防编造纪律
    "req.amend",              # 需求卡纪律
    "<request>",              # W1-2 信封语义
]


def _render(extra: dict) -> str:
    ctx = dict(BASE_CTX)
    ctx.update(extra)
    return P.render_system(ctx)


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_prompt_golden(name, arch_env, request):
    system_md = _render(VARIANTS[name])
    assert system_md.strip(), "system 不应为空"

    # ② 结构锚按序(恒置块)
    pos = [system_md.find(a) for a in ANCHORS]
    assert all(p >= 0 for p in pos), f"结构锚缺失: {[(a, p) for a, p in zip(ANCHORS, pos) if p < 0]}"
    assert pos == sorted(pos), f"结构锚乱序: {pos}"

    # ③ 关键契约句 + 字数预算(裁剪后不得超预算)
    for ph in KEY_PHRASES:
        assert ph in system_md, f"契约句缺失: {ph}"
    budget = P.budget_for(VARIANTS[name]["tier"])
    assert len(system_md) <= budget, f"超预算: {len(system_md)} > {budget}"

    # ① 全文快照(主断言)
    path = os.path.join(GOLDEN_DIR, f"{name}.json")
    if request.config.getoption("--regen-goldens"):
        os.makedirs(GOLDEN_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"system_md": system_md, "char_count": len(system_md),
                       "tier": VARIANTS[name]["tier"]},
                      f, ensure_ascii=False, indent=1)
        return
    with open(path, encoding="utf-8") as f:
        golden = json.load(f)
    assert system_md == golden["system_md"], (
        f"prompt 漂移: {name} 与 golden 不一致 (golden={golden['char_count']}字, "
        f"now={len(system_md)}字)。意图变更 → --regen-goldens 再生并过目 diff, "
        "且必须对应模板/契约版本变更; 非意图变更 → 修复回归")


def test_slim_omits_scope_doc(arch_env):
    """slim 分型省略系统面说明段(可处理范围), 但信封纪律恒在。"""
    full = _render({"tier": 1})
    slim = _render({"tier": 1, "prompt_slim": True})
    assert "可处理范围" in full and "可处理范围" not in slim
    assert "<request>" in slim
