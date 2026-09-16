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
from topoone_app_architect.arch_routes import req_agent  # noqa: E402


def test_protocol_doc_composed_from_constants():
    """chat 面 _PROTOCOL_DOC 必须由常量拼接(常量改动自动生效, 无第二份手写)。"""
    expected = (disc.TOOL_PROTOCOL_HEAD + disc.ANTI_FABRICATION
                + disc.REQ_CARD_DISCIPLINE + disc.DIRECT_CMD_SYMBOLS
                + disc.TOOL_TAIL)
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
