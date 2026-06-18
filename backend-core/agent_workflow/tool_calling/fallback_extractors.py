"""
fallback_extractors — 多格式文本工具调用提取器。

当模型的 API response 未包含原生 tool_calls 时，
尝试从 content / reasoning_content 中识别已知的文本格式工具调用。

注册式设计：新增格式只需实现一个 parser 函数并追加到 _PARSERS 列表。
"""

import json
import logging
import re
from typing import Callable, Optional

from . import ToolCall

logger = logging.getLogger(__name__)


# ─── 格式 1: Qwen3.5 XML 格式 ───
#   <tool_call>
#   <function=tool_name>
#   <parameter=param_name>value</parameter>
#   </function>
#   </tool_call>
_RE_QWEN_TOOL_CALL = re.compile(
    r'<tool_call>\s*<function=(\w+)>(.*?)</function>\s*</tool_call>', re.DOTALL
)
_RE_PARAMETER_TAG = re.compile(
    r'<parameter=(\w+)>\s*(.*?)\s*</parameter>', re.DOTALL
)


def parse_qwen_xml(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in _RE_QWEN_TOOL_CALL.finditer(text):
        name = match.group(1).strip()
        body = match.group(2).strip()
        args: dict[str, str] = {}
        for p in _RE_PARAMETER_TAG.finditer(body):
            args[p.group(1)] = p.group(2).strip()
        if name:
            calls.append(ToolCall(
                name=name, arguments=args,
                id=f"qxml_{name}_{hash(text)}",
            ))
    return calls


# ─── 格式 2: [TOOL_CALL:] 标记格式 ───
#   [TOOL_CALL: tool_name]
#   {"arg1": "val1"}
#   [/TOOL_CALL]
_RE_TOOL_CALL_MARKER = re.compile(
    r'\[TOOL_CALL:\s*(\w+)\](.*?)\[/TOOL_CALL\]', re.DOTALL
)


def parse_tool_call_marker(text: str) -> list[ToolCall]:
    calls: list[ToolCall] = []
    for match in _RE_TOOL_CALL_MARKER.finditer(text):
        name = match.group(1).strip()
        args_text = match.group(2).strip()
        args = {}
        try:
            args = json.loads(args_text) if args_text else {}
        except json.JSONDecodeError:
            args = {"_raw": args_text}
        calls.append(ToolCall(
            name=name, arguments=args,
            id=f"tc_{hash(text)}",
        ))
    return calls


# ─── 解析器注册表（按优先级排序） ───
_PARSERS: list[Callable[[str], list[ToolCall]]] = [
    parse_qwen_xml,           # 1. Qwen3.5 reasoning_content XML
    parse_tool_call_marker,   # 2. [TOOL_CALL:] 标记
]


def extract_fallback_tool_calls(text: str) -> list[ToolCall]:
    """对文本尝试所有已知的文本工具调用格式，返回首个匹配结果。

    Args:
        text: 可能包含文本格式工具调用的字符串（content 或 reasoning_content）

    Returns:
        匹配到的 ToolCall 列表；无匹配时返回空列表
    """
    if not text:
        return []
    for parser in _PARSERS:
        calls = parser(text)
        if calls:
            logger.debug(f"[fallback_extractors] {parser.__name__} 匹配到 {len(calls)} 个工具调用")
            return calls
    return []


# ─── 文本清洗 ───

# 所有已知标记的正则（用于 extract_fallback_content 去除标记后保留纯净文本）
_RE_ALL_MARKERS = re.compile(
    r'<tool_call>.*?</tool_call>|'
    r'\[TOOL_CALL:.*?\[/TOOL_CALL\]',
    re.DOTALL,
)


def extract_fallback_content(text: str) -> str:
    """去除文本中所有工具调用标记，返回纯净文本。

    适用于：model 返回的 content 或 reasoning_content 中混合了
    文本格式工具调用，需要提取纯文本部分作为最终答案。
    """
    if not text:
        return ""
    return _RE_ALL_MARKERS.sub('', text).strip()
