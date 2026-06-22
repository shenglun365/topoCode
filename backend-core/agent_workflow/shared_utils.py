"""
shared_utils — 工作流间公用的结构化响应解析和 Markdown 摘要构建。
"""

import json as _json
import re as _re
import logging

logger = logging.getLogger(__name__)


def _extract_json_from_text(text: str) -> dict | None:
    """从可能包含推理文本的 LLM 输出中尝试提取 JSON 对象/数组。"""
    # 优先尝试从 { 到 } 提取最外层对象
    for pattern in [r'(\{.*\})', r'(\[.*\])']:
        match = _re.search(pattern, text, _re.DOTALL)
        if match:
            candidate = match.group(1)
            try:
                return _json.loads(candidate)
            except (_json.JSONDecodeError, ValueError):
                continue
    return None


def parse_structured_response(text: str, fallback_name: str = "") -> dict:
    """从 LLM 响应中提取 JSON，出错时尝试从纯文本恢复或正则提取。返回 dict 含 parsed 和 _parse_error 字段。"""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        parsed = _json.loads(text)
        parsed["_parse_error"] = False
        return parsed
    except (_json.JSONDecodeError, ValueError):
        # 直接解析失败 → 尝试从推理文本中正则提取 JSON
        extracted = _extract_json_from_text(text)
        if extracted is not None:
            extracted["_parse_error"] = False
            return extracted
    lines = text.strip().split("\n")
    name = lines[0].strip()[:60] if lines else fallback_name[:60]
    summary = "\n".join(lines[1:]) if len(lines) > 1 else text
    is_bad = not summary.strip() or name == fallback_name
    return {
        "name": name, "summary": summary, "role": "", "key_files": [], "depends_on": [],
        "_parse_error": is_bad,
        "_error_reason": "LLM 返回格式错误，无法解析结构化 JSON" if is_bad else "",
    }


def build_markdown_summary(name: str, summary: str, role: str,
                             key_files: list, depends_on: list) -> str:
    """将结构化分析结果拼接为增强 Markdown summary。

    key_files 可以是 str 列表（旧格式）或 dict 列表（含 path/summary 字段）。
    """
    parts = []
    parts.append(f"## 功能概要\n{summary}")
    if role:
        parts.append(f"\n**架构角色**: {role}")
    if key_files:
        files_lines = []
        for kf in key_files[:10]:
            if isinstance(kf, dict):
                fp = kf.get("path", kf.get("file", ""))
                fs = kf.get("summary", "")
                if fp and fs:
                    files_lines.append(f"- `{fp}` — {fs}")
                elif fp:
                    files_lines.append(f"- `{fp}`")
            else:
                files_lines.append(f"- `{kf}`")
        if files_lines:
            parts.append(f"\n**关键文件**:\n" + "\n".join(files_lines))
    if depends_on:
        deps_md = ", ".join(depends_on[:10])
        parts.append(f"\n**依赖组件**: {deps_md}")
    return "\n".join(parts)
