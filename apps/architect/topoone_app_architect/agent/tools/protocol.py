"""工具调用文本协议(工具层) — 模型输出 [TOOL_CALL] 块 → 解析/剥离。

标准形: [TOOL_CALL]{"tool":"x","arguments":{...}}[/TOOL_CALL]
模型变体(均容忍)：```json 围栏、丢前导 '['、闭合标签写成 [/TOOL_CALL> 等。
⚠️ 未闭合块(部分模型省略 [/TOOL_CALL]，裸开标签后直接跟 JSON)：必须支持——
否则整轮 0 解析、[TOOL_CALL] 裸文本透传到对话且工具不执行(生产实测回归)。
策略：闭合标签存在时以其定界；缺失时按「下一开标签/文末」切段 + 花括号
配对(字符串/转义感知)抽取 JSON，保证连续多个未闭合块逐块解析。
⚠️ lookbehind (?<![/\w])：排除闭合标签 [/TOOL_CALL] 内部的 "TOOL_CALL]" 子串被
二次认作开标签(曾导致 seg_end 被切短、闭合定界失效、strip 残留闭合标签)。

P1 自 req_agent.py 迁入(纯函数, 零外部依赖)。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

# M4-A 受限生成(单调用/轮): structured 模式的输出 schema——约束解码层保证
# 输出是合法 JSON, 文本协议解析层退化为 json.loads 单一路径。
# 语义: 每轮至多一个工具调用; 无工具可调时不使用本 schema(终稿轮走普通文本)。
TOOL_CALL_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "tool": {
            "type": "string",
            "description": "要调用的工具名(必须来自可用工具清单; 空串=本轮不调用工具)",
        },
        "arguments": {
            "type": "object",
            "description": "工具参数对象(键名与工具定义一致)",
        },
    },
    "required": ["tool"],
}

_TOOL_CALL_OPEN = re.compile(r'(?:```(?:json)?\s*)?\[?\s*(?<![/\w])TOOL_CALL\]',
                             re.DOTALL)
_TOOL_CALL_CLOSE = re.compile(r'\[/TOOL_CALL[>\]]+\]?\s*(?:```)?')
_TOOL_CALL_BLOCK = re.compile(
    r'(?:```(?:json)?\s*)?\[?\s*TOOL_CALL\](.*?)\[/TOOL_CALL[>\]]+\]?\s*(?:```)?',
    re.DOTALL)
_FENCE = re.compile(r'^\s*```(?:json)?\s*|\s*```\s*$')


def _clean_block(raw: str) -> str:
    raw = _FENCE.sub("", raw or "").strip()
    if raw.startswith("{"):
        return raw
    first = raw.find("{")
    last = raw.rfind("}")
    return raw[first:last + 1] if first >= 0 and last > first else raw


def _json_object_spans(text: str) -> List[tuple]:
    """花括号配对(字符串/转义感知)返回顶层 {…} 的 (start, end_exclusive) 段列表。"""
    spans: List[tuple] = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text or ""):
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == '{':
            if depth == 0:
                start = i
            depth += 1
        elif ch == '}':
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, i + 1))
                    start = -1
    return spans


def _parse_tool_payload(raw: str) -> Optional[Dict[str, Any]]:
    """块内容 → {tool, arguments}；非法 JSON/缺 tool 字段返回 None。

    先整体直解(_clean_block 快路径)；失败再按花括号配对逐段兜底
    (块内含前后杂文/多对象时仍可解析)。
    """
    data: Any = None
    try:
        data = json.loads(_clean_block(raw))
    except Exception:
        data = None
    if not (isinstance(data, dict) and isinstance(data.get("tool"), str)):
        for s, e in _json_object_spans(raw or ""):
            try:
                cand = json.loads(raw[s:e])
            except Exception:
                continue
            if isinstance(cand, dict) and isinstance(cand.get("tool"), str):
                data = cand
                break
    if not isinstance(data, dict) or not isinstance(data.get("tool"), str):
        return None
    args = data.get("arguments")
    if not isinstance(args, dict):
        args = {}
    return {"tool": data["tool"], "arguments": args}


def _tool_call_regions(text: str) -> List[tuple]:
    """定位全部工具块区域 [(start, end_exclusive, content)]。

    闭合块 = 开标签..闭合标签尾；未闭合块 = 开标签..首个配对 JSON 尾。
    无合法 JSON 的裸 "TOOL_CALL]" 提及不当块处理(避免误删正文)。
    """
    regions: List[tuple] = []
    opens = list(_TOOL_CALL_OPEN.finditer(text or ""))
    for idx, m in enumerate(opens):
        seg_end = opens[idx + 1].start() if idx + 1 < len(opens) else len(text)
        close = _TOOL_CALL_CLOSE.search(text, m.end(), seg_end)
        if close:
            regions.append((m.start(), close.end(), text[m.end():close.start()]))
            continue
        spans = _json_object_spans(text[m.end():seg_end])
        if spans:
            s, e = spans[0]
            regions.append((m.start(), m.end() + e, text[m.end():m.end() + e]))
    return regions


def extract_tool_calls(text: str) -> List[Dict[str, Any]]:
    """从模型输出中解析工具调用块(闭合/未闭合均支持)。返回 [{tool, arguments}]；异常/缺失字段自动跳过。"""
    calls: List[Dict[str, Any]] = []
    if not text:
        return calls
    for _s, _e, content in _tool_call_regions(text):
        payload = _parse_tool_payload(content)
        if payload:
            calls.append(payload)
    return calls


def strip_tool_blocks(text: str) -> str:
    """移除全部工具调用块(含未闭合块)，返回纯文本。"""
    if not text:
        return ""
    regions = _tool_call_regions(text)
    if not regions:
        return text.strip()
    out: List[str] = []
    pos = 0
    for start, end, _content in regions:
        out.append(text[pos:start])
        pos = end
    out.append(text[pos:])
    return "".join(out).strip()


def tool_parse_audit(text: str) -> Dict[str, int]:
    """解析审计(纯函数, 零 IO): 工具块区域数 vs 有效调用数。

    C 失败样例回流的判据源: regions>0 且 valid<regions = 存在格式损坏
    (未闭合/JSON 破损/字段缺失)——调用方负责落 llm_dataset(本层不做 IO)。
    """
    if not text:
        return {"regions": 0, "valid": 0}
    regions = _tool_call_regions(text)
    valid = sum(1 for _s, _e, content in regions if _parse_tool_payload(content))
    return {"regions": len(regions), "valid": valid}
