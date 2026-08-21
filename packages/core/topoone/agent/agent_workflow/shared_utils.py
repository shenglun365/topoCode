"""
shared_utils — 工作流间公用的结构化响应解析和 Markdown 摘要构建。
"""

import json as _json
import re as _re
import logging

logger = logging.getLogger(__name__)


def _extract_json_from_text(text: str) -> dict | None:
    """Attempt to extract JSON object/array from LLM output possibly containing reasoning text."""
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
    """Extract JSON from LLM response, fallback to plain text or regex extraction on error. Returns dict with parsed and _parse_error fields."""
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
        "_error_reason": "LLM returned format error, unable to parse structured JSON" if is_bad else "",
    }


def build_markdown_summary(name: str, summary: str, role: str,
                             key_files: list, depends_on: list) -> str:
    """Build enhanced Markdown summary from structured analysis results.

    key_files can be a list of str (old format) or dict (with path/summary fields).
    """
    parts = []
    parts.append(f"## Functional Summary\n{summary}")
    if role:
        parts.append(f"\n**Architecture Role**: {role}")
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
            parts.append(f"\n**Key Files**:\n" + "\n".join(files_lines))
    if depends_on:
        deps_md = ", ".join(depends_on[:10])
        parts.append(f"\n**Dependencies**: {deps_md}")
    return "\n".join(parts)
