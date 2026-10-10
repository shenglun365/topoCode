"""提示词纪律单源(环节二) — 工具调用纪律文本唯一源 = cognition.prompt 常量。

cv-177 教训: 同一纪律段在 chat 面(cognition/prompt.py)与工具面
(req_agent.run_tools_loop)各有一份手工拷贝, 三处措辞漂移。
本文件锁定: 单源引用 + 手工副本不复存在。
"""
import inspect
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.agent.cognition import prompt as disc  # noqa: E402
from topoone_app_architect.agent.tools import req_agent


def test_protocol_doc_composed_from_constants():
    """chat 面 _PROTOCOL_DOC 必须由常量拼接(常量改动自动生效, 无第二份手写)。

    W1-2: REQUEST_ENVELOPE_DOC(<request> 信封纪律)入组合——golden 同步锁定。"""
    expected = (disc.TOOL_PROTOCOL_HEAD + disc.ANTI_FABRICATION
                + disc.REQ_CARD_DISCIPLINE + disc.REQUEST_ENVELOPE_DOC
                + disc.DIRECT_CMD_SYMBOLS + disc.TOOL_TAIL)
    assert disc._PROTOCOL_DOC == expected


def test_chat_face_contains_discipline_constants():
    doc = req_agent.chat_system_prompt(None, None)
    for seg in (disc.ANTI_FABRICATION, disc.REQ_CARD_DISCIPLINE,
                disc.DIRECT_CMD_SYMBOLS):
        assert seg in doc


def test_tools_loop_face_references_constants_no_hand_copy():
    """工具面(run_tools_loop)引用常量; 旧手写副本('需求落库纪律'头)必须不存在。"""
    src = inspect.getsource(req_agent)
    assert "_disc.REQ_CARD_DISCIPLINE" in src
    assert "_disc.ANTI_FABRICATION" in src
    assert "需求落库纪律" not in src          # 旧手写段落已删(措辞漂移源头)


def test_discipline_no_stale_finalize_wording():
    """/定稿 已移除——纪律文本不得再引用(漂移检测: 上轮曾漏改 prompt.py 副本)。"""
    for seg in (disc.ANTI_FABRICATION, disc.REQ_CARD_DISCIPLINE,
                disc.DIRECT_CMD_SYMBOLS):
        assert "定稿" not in seg


# ── B4 工具文档单源化(注册表 → 能力文档渲染) ─────────────────────────

def _all_registered_tools():
    return req_agent._ARCH_TOOLS


def test_capability_doc_covers_all_registered_tools():
    """单源渲染覆盖全部注册工具(diagram.build/validate 除外——归 diagram_skill 块)。"""
    doc = disc.capability_doc_from_tools()
    assert doc, "单源渲染不应为空(注册表非空)"
    for name in _all_registered_tools():
        if name in ("diagram.build", "diagram.validate"):
            assert name not in doc
            continue
        assert f"- {name}：" in doc, f"工具 {name} 未出现在单源能力清单"


def test_capability_doc_params_from_registry():
    """参数段来自注册点声明(MS-B3 表退役)——非空且含代表性条目。"""
    doc = disc.capability_doc_from_tools()
    assert "各工具的参数：" in doc
    assert "- kb.asset.search:" in doc
    assert '"text": "检索关键词"' in doc
    # 注册点抽查: brief 与迁移文本逐字落位
    from topoone_app_architect.agent.tools.registry import _ARCH_TOOLS
    assert _ARCH_TOOLS["kb.baseline"]["brief"] in doc
    assert _ARCH_TOOLS["kb.graph"]["params_doc"] in doc


def test_capability_doc_structure_complete():
    """单源文档必须含 纪律段/范围段/层级约定/图表输出 四大段(结构对齐原文)。"""
    doc = disc.capability_doc_from_tools()
    for seg in (disc._TIER_CONVENTION_DOC, disc._SCOPE_DOC,
                disc._DIAGRAM_OUTPUT_DOC, disc.ANTI_FABRICATION,
                disc.REQ_CARD_DISCIPLINE):
        assert seg in doc


def test_capability_default_is_single_source():
    """单源唯一模式(MS-B3): 渲染含注册工具(conv.read); single_source 覆盖键
    已随 legacy 回退通道退役——设置它不再切换渲染源。"""
    doc = req_agent.chat_system_prompt(None, None)
    assert "conv.read：" in doc, "应走单源渲染(含全部注册工具)"
    try:
        disc.set_overrides({"single_source": False})
        still = req_agent.chat_system_prompt(None, None)
        assert "conv.read：" in still, "回退通道已退役, 覆盖键不再切源"
    finally:
        disc.set_overrides({})


def test_registry_entry_prefers_explicit_doc_over_tables():
    """注册点显式传参优先于迁移表(新工具直接传 brief/params_doc)。"""
    from topoone_app_architect.agent.tools.registry import (
        _ARCH_TOOLS, register_architect_tool)

    @register_architect_tool("b4.dummy", "测试工具。",
                             params_doc='{"x": 1}', brief="显式简介")
    def _dummy():
        return {}

    try:
        entry = _ARCH_TOOLS["b4.dummy"]
        assert entry["brief"] == "显式简介"
        assert entry["params_doc"] == '{"x": 1}'
        doc = disc.capability_doc_from_tools()
        assert "- b4.dummy：显式简介" in doc
        assert "- b4.dummy: {\"x\": 1}" in doc
    finally:
        _ARCH_TOOLS.pop("b4.dummy", None)


def test_tool_parse_audit_counts_broken_blocks():
    """M4-C 判据源(纯函数): 区域数 vs 有效调用数。"""
    from topoone_app_architect.agent.tools.protocol import tool_parse_audit
    good = '[TOOL_CALL]{"tool":"kb.baseline","arguments":{}}[/TOOL_CALL]'
    assert tool_parse_audit(good) == {"regions": 1, "valid": 1}
    assert tool_parse_audit("普通文本无工具块") == {"regions": 0, "valid": 0}
    # 区域命中但 JSON 破损(arguments 值缺失)
    bad = '[TOOL_CALL]{"tool": "kb.baseline", "arguments": }[/TOOL_CALL]'
    assert tool_parse_audit(bad) == {"regions": 1, "valid": 0}
    audit = tool_parse_audit(bad + good)
    assert audit["regions"] == 2 and audit["valid"] == 1


def test_record_tool_parse_fail_samples(tmp_path, monkeypatch):
    """损坏样本落 llm_dataset(kind=tool_parse_fail); 正常输出零事件。"""
    import json
    import topoone_app_architect.ctx as C
    data = str(tmp_path / "d")
    C._db = None; C._kb = None; C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None)); C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    from topoone_app_architect.agent.reflection import dataset as ds
    from topoone_app_architect.agent.tools import req_agent
    good = '[TOOL_CALL]{"tool":"kb.baseline","arguments":{}}[/TOOL_CALL]'
    req_agent.record_tool_parse_audit(good, [{"tool": "kb.baseline"}])
    bad = ('前文\n[TOOL_CALL]{"tool": "kb.baseline", "arguments": }'
           "[/TOOL_CALL]")
    req_agent.record_tool_parse_audit(bad, [], surface="chat")
    path = ds._path()
    rows = [json.loads(ln) for ln in open(path, encoding="utf-8")]
    fails = [r for r in rows if r["kind"] == "tool_parse_fail"]
    assert len(fails) == 1
    assert fails[0]["regions"] == 1 and fails[0]["valid"] == 0
    assert fails[0]["surface"] == "chat" and "kb.baseline" in fails[0]["sample"]
