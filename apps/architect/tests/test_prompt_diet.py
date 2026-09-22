"""批丁特征测试: 提示词减载三件套(A 测量面 / B 工具按需注入 / C 静态面瘦身)。

背景体检: 静态 system ~9.6K 字 + 工具文档 5K 全量注入, 结构化轮 msgs 实测
10-12.4K 字符, 约束词 20+ 处且落卡纪律四处重复——中小模型遵从率劣化
(cv-222/224 实证)。本批: 提示分层遥测 + GU 路线工具子集 + 协议段去重压缩。

Run: cd <repo> && python -m pytest apps/architect/tests/test_prompt_diet.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.cognition import prompt as pr
from topoone_app_architect.agent.governance import flow_policy as fp
from topoone_app_architect.agent.turns import goal as gu


@pytest.fixture()
def pol():
    import copy
    return copy.deepcopy(fp.DEFAULT_FLOW_POLICY)


# ── B: 决策表 tools 字段 + allowed 解析 ───────────────────────────────

def test_decision_rules_carry_tools_defaults(pol):
    """缺省决策表: 落卡类动作带写工具限定, 菜单/先问类显式只读([])。"""
    rules = {r["then"]: r.get("tools", "__none__")
             for r in pol["goal"]["decision"]}
    assert rules["clarify-first"] == ["req.amend"]      # 澄清轮禁落新卡
    assert rules["propose-requirement"] == ["req.propose", "req.amend"]
    assert rules["propose-task"] == ["task.propose"]
    assert rules["present-options"] == []
    assert rules["passthrough"] == "__none__"           # 指令直通不限面


def test_tools_validation():
    ok, errs = fp.validate_flow_policy({"goal": {"decision": [
        {"when": {"kind": "operation"}, "then": "propose-task",
         "tools": ["task.propose"]}]}})
    assert ok and not errs
    ok, errs = fp.validate_flow_policy({"goal": {"decision": [
        {"when": {"kind": "operation"}, "then": "propose-task",
         "tools": [""]}]}})
    assert not ok and any(".tools" in e for e in errs)


def test_resolve_gu_allowed_none_vs_empty(arch_env, monkeypatch):
    """tools=None(未配置)→不限面; tools=[](显式只读)→仅读类面——语义分界。"""
    from topoone_app_architect.agent.orchestrator import _resolve_gu_allowed
    assert _resolve_gu_allowed(None) is None
    assert _resolve_gu_allowed({"tools": None}) is None
    ro = _resolve_gu_allowed({"tools": []})
    assert ro and "kb.asset.search" in ro and "req.propose" not in ro \
        and "task.propose" not in ro
    wr = _resolve_gu_allowed({"tools": ["req.propose"]})
    assert "req.propose" in wr and "kb.asset.search" in wr \
        and "task.propose" not in wr          # 未点名写工具不可用
    assert "convention.propose" not in wr     # 注册表交集(其它写工具仍排除)


def test_capability_doc_subset_by_allowed():
    """能力文档按 allowed 收敛: 写面 5.5K → 子集 ~1.7K, 名单外工具不可见。"""
    full = pr.capability_doc_from_tools()
    sub = pr.capability_doc_from_tools(
        allowed={"req.propose", "req.amend", "kb.asset.search", "map.overview"})
    assert len(sub) < len(full) * 0.5
    assert "req.propose" in sub and "task.propose" not in sub
    assert "各工具的参数" in sub               # 参数表同裁


def test_chat_loop_refuses_out_of_list(arch_env, monkeypatch):
    """执行面执法: allowed 名单外工具拒绝回喂(不派发), 名单内正常。"""
    import asyncio
    import topoone_app_architect.agent.turns.chat as ch
    from topoone_app_architect.arch_routes import req_agent as ra

    executed = []

    def _fake_exec(name, args, root, project, model_id=""):
        executed.append(name)
        return {"ok": True}
    monkeypatch.setattr(ra, "execute_tool_with_repair", _fake_exec)
    monkeypatch.setattr(ra, "structured_model_enabled", lambda m: True)
    seq = [{"tool": "task.propose", "arguments": {}},          # 名单外 → 拒绝
           {"tool": "kb.asset.search", "arguments": {"text": "x"}},
           {"calls": None}]                                    # 无调用 → 收
    budgets = [1, 1, 1, 0]     # 四轮预算(拒绝轮不推进 executed, 按调用序推进)
    sres_holder = {}
    idx = {"i": 0}

    def _fake_structured(*a, **kw):
        sres_holder["schema"] = kw.get("schema")
        item = seq[min(idx["i"], len(seq) - 1)]
        idx["i"] += 1
        if item.get("calls") is None and "tool" not in item:
            return {"calls": [], "content": "done", "error": ""}
        return {"calls": [item], "content": "", "error": ""}

    monkeypatch.setattr(ra, "structured_tool_round", _fake_structured)

    class _IO:
        t0 = 0.0
        chat_start_sent = True
        last_user_msg_id = ""

        def budget_left(self):
            return budgets[min(idx["i"], len(budgets) - 1)]

        async def ensure_chat_start(self):
            pass

        async def send(self, ev):
            return True

        async def send_ev(self, ev):
            return True

    allowed = {"kb.asset.search", "req.amend"}
    loop = asyncio.get_event_loop_policy().new_event_loop()
    try:
        res = loop.run_until_complete(ch._run_llm_tool_loop(
            _IO(), "cv-x", [{"role": "user", "content": "q"}], "", "",
            None, "", set(), {}, max_tool_rounds=3, allowed_tools=allowed))
    finally:
        loop.close()
    assert executed == ["kb.asset.search"]            # task.propose 被拒
    assert res["tool_round"] >= 1


def test_gu_structured_schema_enum():
    schema = ch_gu_schema({"kb.asset.search", "req.amend"})
    assert schema["properties"]["tool"]["enum"] == ["kb.asset.search", "req.amend"]
    assert ch_gu_schema(None) is None


def ch_gu_schema(allowed):
    from topoone_app_architect.agent.turns.chat import _gu_structured_schema
    return _gu_structured_schema(allowed)


# ── A: prompt_sections 遥测 ──────────────────────────────────────────

def test_prompt_sections_recorded(arch_env):
    """每回合提示分层字数落 llm_dataset(system/注入/历史/tier/GU 面)。"""
    import asyncio
    from topoone_app_architect.agent.orchestrator import _record_prompt_sections
    from topoone_app_architect.agent.reflection import dataset as ds

    class _Gear:
        tier = 2
        tool_surface = "reduced"

    msgs = [{"role": "system", "content": "S" * 100},
            {"role": "system", "content": "I" * 30},
            {"role": "user", "content": "U" * 50}]
    _record_prompt_sections(msgs, _Gear(), {"action": "propose-task"},
                            {"kb.asset.search"})
    rows = [json.loads(x) for x in open(ds._path(), encoding="utf-8")]
    ev = [r for r in rows if r.get("kind") == "prompt_sections"][-1]
    assert ev["systemBase"] == 100 and ev["systemInjections"] == 30
    assert ev["history"] == 50 and ev["tier"] == 2
    assert ev["guAction"] == "propose-task" and ev["guTools"] == 1


# ── C: 静态面瘦身 + 去重 ─────────────────────────────────────────────

def test_discipline_dedup_single_source():
    """落卡纪律去重: 与 posture 三问重复的「按需产卡」条退役, 纪律单源工具面。"""
    assert "分析/问答/检索类请求直接回答" not in pr.REQ_CARD_DISCIPLINE
    assert "req.amend" in pr.REQ_CARD_DISCIPLINE           # 工具面规则保留
    assert "严禁自造" in pr.REQ_CARD_DISCIPLINE
    # posture 保留人格级三问定性(产卡判据唯一源)
    assert "先按三问定性" in pr.posture_text()


def test_slim_protocol_drops_system_face():
    """简挡协议: 省略指令符号段(系统确定性处理), 保留防编造/纪律/收尾。"""
    slim = pr.protocol_doc(slim=True)
    assert "会话指令符号" not in slim
    assert "防编造" in slim and "需求卡纪律" in slim
    assert len(slim) < len(pr._PROTOCOL_DOC)


def test_slim_capability_drops_scope():
    full = pr.capability_doc_from_tools()
    slim = pr.capability_doc_from_tools(slim=True)
    assert "可处理范围" in full and "可处理范围" not in slim
    assert len(slim) < len(full)


def test_static_diet_actual_savings():
    """体检对账: 压缩后协议段较原 731 字显著下降; 工具子集降幅 ≥60%。"""
    assert len(pr._PROTOCOL_DOC) < 520            # 原 731
    full = pr.capability_doc_from_tools()
    sub = pr.capability_doc_from_tools(allowed={"req.propose", "kb.asset.search"})
    assert len(sub) <= len(full) * 0.4
