"""Lightweight code-syntax validator (legacy agent-tool contract).

Used by /api/diagram/validate + /api/diagram/build's post-check + the chat
web_diagram_validate skill tool: returns {valid, errors, warnings}.

- mermaid: line-scan against known mermaid directives (the legacy
  ``diagram.rebuild_*`` probe is unavailable outside the docs app and always
  fell through to this path anyway).
- plantuml: structural check (@startuml/@enduml + non-empty + sane body).
"""

import re
from typing import Any


def validate_diagram_syntax(code: str, lang: str) -> dict[str, Any]:
    if lang == "mermaid":
        return _validate_mermaid(code)
    elif lang == "plantuml":
        return _validate_plantuml(code)
    else:
        return {"valid": False, "errors": [f"Unknown language: {lang}"]}


def _validate_mermaid(code: str) -> dict[str, Any]:
    direct_errors: list[str] = []
    lines = code.split("\n")
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        if re.match(r"^\s*graph\s+(TB|TD|LR|RL|BT)\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*sequenceDiagram\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*classDiagram\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*stateDiagram-v2\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*erDiagram\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*gantt\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*pie\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*journey\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*subgraph\b", stripped, re.IGNORECASE):
            continue
        if stripped in ("end",):
            continue
        if re.match(r"^\s*%%\{init:", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*\}\s*%%\s*$", stripped):
            continue
        if re.match(r"^\s*---+\s*$", stripped):
            continue
        if re.match(r"^\s*title\s+", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*style\s+", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*classDef\s+", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*class\s+\w[\w\d_]*\s", stripped, re.IGNORECASE):
            continue
        node_edge = re.match(
            r"^\s*(\w[\w\d_]*)\s*(-->|==>|-\.->|---?)\s*(?:\(\(|\(|\[\(|\{|\[)?"
            r"[^\]\)\}]*[\]\)\}]?\s*(?:\|([^|]*)\|)?\s*(\w[\w\d_]*)",
            stripped,
        )
        if node_edge:
            continue
        inline_node = re.match(
            r"^\s*(\w[\w\d_]*)\s*(?:\(\([^)]*\)\)|\([^)]+\)|\(\[[^\]]*\]\)|\{[^}]*\}|\[[^\]]*\])",
            stripped,
        )
        if inline_node:
            continue
        if re.match(r"^\s*participant\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*actor\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*Note\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*activate\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*deactivate\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*loop\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*alt\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*else\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*opt\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*rect\b", stripped, re.IGNORECASE):
            continue
        if re.match(r"^\s*namespace\b", stripped, re.IGNORECASE):
            continue

        exists_in_known = False
        for kw in ["participant", "actor", "Note", "activate", "deactivate",
                    "loop", "alt", "else", "opt", "rect", "end",
                    "namespace"]:
            if stripped.lower().startswith(kw.lower()):
                exists_in_known = True
                break
        if not exists_in_known:
            direct_errors.append(f"Line {i+1}: unrecognized syntax '{stripped[:60]}'")

    if direct_errors:
        return {"valid": False, "errors": direct_errors}
    return {"valid": True, "errors": [], "warnings": []}


def _validate_plantuml(code: str) -> dict[str, Any]:
    if not code or not code.strip():
        return {"valid": False, "errors": ["empty plantuml code"]}
    if "@startuml" not in code:
        return {"valid": False, "errors": ["missing '@startuml' directive"]}
    if "@enduml" not in code:
        return {"valid": False, "errors": ["missing '@enduml' directive"]}
    start = code.find("@startuml")
    end = code.find("@enduml")
    body = code[start + len("@startuml"):end]
    if not body.strip():
        return {"valid": False, "errors": ["empty plantuml body"]}
    if _unbalanced_quotes(code):
        return {"valid": False, "errors": ["unterminated quote in plantuml source"]}
    return {"valid": True, "errors": [], "warnings": []}


def _unbalanced_quotes(code: str) -> bool:
    in_quote = False
    for i, ch in enumerate(code):
        if ch == "'" and not in_quote:
            # `'` starts a comment unless inside a double-quoted string or
            # within an identifier like don't; PlantUML comments are line-based
            # so a single quote on a line just comments it out.
            continue
        if ch == '"':
            if in_quote:
                # escaped quote
                in_quote = code[i - 1] != "\\"
            else:
                in_quote = True
    return in_quote
