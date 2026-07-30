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
    try:
        from diagram import rebuild_mermaid
        result = rebuild_mermaid(code, "auto")
        if result and "code" in result and result["code"].strip():
            return {"valid": True, "errors": [], "warnings": []}
        return {"valid": False, "errors": ["Rebuild returned empty code"]}
    except ValueError as e:
        return {"valid": False, "errors": [str(e)]}
    except ImportError:
        pass
    except Exception:
        pass

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
    try:
        from diagram import rebuild_plantuml
        result = rebuild_plantuml(code, None)
        if result and "code" in result and result["code"].strip():
            return {"valid": True, "errors": []}
        return {"valid": False, "errors": ["Rebuild returned empty code"]}
    except ValueError as e:
        return {"valid": False, "errors": [str(e)]}
    except Exception as e:
        return {"valid": False, "errors": [f"Validation error: {e}"]}
