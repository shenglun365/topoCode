import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

_SUBAGENT_SESSIONS: dict[str, dict[str, Any]] = {}


def create_subagent_session(
    main_session_id: str,
    msg_id: str,
    diag_id: str,
    original_code: str,
    lang: str,
    instruction: str = "",
) -> dict[str, Any]:
    session_id = f"diagram_sub_{main_session_id}_{msg_id}_{int(time.time() * 1000)}"
    session = {
        "id": session_id,
        "main_session_id": main_session_id,
        "msg_id": msg_id,
        "diag_id": diag_id,
        "original_code": original_code,
        "current_code": original_code,
        "lang": lang,
        "instruction": instruction,
        "created_at": time.time(),
        "history": [],
        "status": "active",
    }
    _SUBAGENT_SESSIONS[session_id] = session
    return {
        "session_id": session_id,
        "char_count": len(original_code),
        "lang": lang,
        **_summarize_size(original_code),
    }


def get_subagent_session(session_id: str) -> dict[str, Any] | None:
    return _SUBAGENT_SESSIONS.get(session_id)


def apply_change(session_id: str, new_code: str) -> dict[str, Any]:
    session = _SUBAGENT_SESSIONS.get(session_id)
    if not session:
        return {"error": "Session not found"}

    from ._validator import validate_diagram_syntax
    validation = validate_diagram_syntax(new_code, session["lang"])

    old_code = session["current_code"]
    session["current_code"] = new_code
    session["history"].append({
        "timestamp": time.time(),
        "old_code": old_code,
        "new_code": new_code,
        "validation": validation,
    })

    result: dict[str, Any] = {
        "valid": validation["valid"],
        "char_count": len(new_code),
        "history_count": len(session["history"]),
    }
    if validation.get("errors"):
        result["errors"] = validation["errors"]
    result.update(_summarize_size(new_code))
    return result


def commit_to_main(session_id: str) -> dict[str, Any]:
    session = _SUBAGENT_SESSIONS.get(session_id)
    if not session:
        return {"error": "Session not found"}

    session["status"] = "committed"

    return {
        "code": session["current_code"],
        "msg_id": session["msg_id"],
        "diag_id": session["diag_id"],
        "lang": session["lang"],
        "original_code": session["original_code"],
        "modified": session["current_code"] != session["original_code"],
    }


def discard_subagent_session(session_id: str) -> None:
    _SUBAGENT_SESSIONS.pop(session_id, None)


def _summarize_size(code: str) -> dict[str, Any]:
    lines = code.split("\n")
    return {
        "line_count": len(lines),
        "char_count": len(code),
        "is_large": len(code) > 8000,
        "suggestion": "图较大，建议分区域修改" if len(code) > 8000 else "",
    }
