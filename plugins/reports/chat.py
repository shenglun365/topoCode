"""Chat module — /chat + session/LLM/notes/documents/models/skills API"""

import asyncio
import json
import logging
import os
import queue as _queue
import re as _re
import threading
import uuid

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

import common
import common

router = APIRouter()

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# ── Activity tracking ──
_active_streams: dict = {}
_active_streams_lock = threading.Lock()


# ── Static page ──

@router.get("/chat", response_class=HTMLResponse)
async def view_chat():
    legacy_path = os.path.join(STATIC_DIR, "legacy-chat.html")
    chat_path = os.path.join(STATIC_DIR, "chat.html")
    if os.path.isfile(legacy_path):
        return FileResponse(legacy_path)
    if os.path.isfile(chat_path):
        return FileResponse(chat_path)
    return HTMLResponse("chat.html not found.")


# ── Helpers ──

def _require_chat_ready():
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    if not common.web_tool_executor:
        raise HTTPException(503, "Chat tools not initialized")


def _sdb():
    return common.multi_db.sessions_db


def _make_session_id():
    return f"chat_{uuid.uuid4().hex[:12]}"


def _make_message_id():
    return f"msg_{uuid.uuid4().hex[:12]}"


def _make_note_id():
    return f"note_{uuid.uuid4().hex[:12]}"


def _create_chat_session(title: str, project_id: str = "") -> str:
    sid = _make_session_id()
    now = __import__("datetime").datetime.now().isoformat()
    metadata = json.dumps({"module": "web_chat", "model_id": ""}, ensure_ascii=False)
    _sdb().execute(
        "INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at) "
        "VALUES (?, 'ai_assistant', ?, ?, ?, ?, ?)",
        (sid, project_id or None, title, metadata, now, now),
    )
    sys_content = "你是 TopoCode 架构分析助手，帮助用户理解和分析项目代码架构。"
    _sdb().execute(
        "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
        "VALUES (?, ?, 'system', ?, '{}', ?)",
        (_make_message_id(), sid, sys_content, now),
    )
    return sid


def _resolve_default_model_id() -> str:
    try:
        row = common.multi_db.main_db.fetchone(
            "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected' LIMIT 1"
        )
        if row:
            return row["id"]
    except Exception:
        pass
    return ""


def _parse_tool_calls_simple(raw_parts: list) -> list:
    try:
        raw = "".join(raw_parts)
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            result = []
            for tc in parsed:
                func = tc.get("function", {})
                args_raw = func.get("arguments", "{}")
                args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                result.append({"id": tc.get("id", ""), "name": func.get("name", ""), "arguments": args})
            return result
        elif isinstance(parsed, dict):
            func = parsed.get("function", {})
            args_raw = func.get("arguments", "{}")
            args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
            return [{"id": parsed.get("id", ""), "name": func.get("name", ""), "arguments": args}]
    except (json.JSONDecodeError, AttributeError):
        pass
    return []


def _extract_title_from_llm_output(raw: str) -> str:
    if not raw:
        return ""
    lines = [l.strip().strip('"').strip("'").strip() for l in raw.split('\n') if l.strip()]
    for l in reversed(lines):
        if 2 <= len(l) <= 20 and not l.startswith('-') and not l.startswith('*') and not l.startswith('#'):
            return l
    if lines:
        last = lines[-1]
        if 2 <= len(last) <= 30:
            return last
    return ""


def _fallback_title(session_id: str, llm_hint: str) -> str:
    try:
        row = _sdb().fetchone(
            "SELECT content FROM llm_messages WHERE session_id = ? AND role = 'user' ORDER BY created_at LIMIT 1",
            (session_id,),
        )
        if row and row["content"]:
            text = row["content"].strip()
            if len(text) <= 16:
                return text
            return text[:16] + "…"
    except Exception:
        pass
    return ""


def _do_auto_title(session_id: str, context: str):
    try:
        model_id = ""
        default_row = common.multi_db.main_db.fetchone(
            "SELECT value FROM app_config WHERE key='web_chat_default_model_id'"
        )
        if default_row and default_row["value"]:
            model_id = default_row["value"]
        if not model_id:
            default_model = common.multi_db.main_db.fetchone(
                "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected' LIMIT 1"
            )
            if default_model:
                model_id = default_model["id"]
        if not model_id:
            logger.warning(f"[auto-title] _do: no default model found for session {session_id[:16]}")
            return
        model_cfg = common.multi_db.main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))
        if not model_cfg:
            logger.warning(f"[auto-title] _do: model {model_id[:16]} not found in configs")
            return
        md = dict(model_cfg)
        base_url = md.get("url", "").rstrip("/")
        if base_url.endswith("/v1"):
            base_url = base_url[:-3]
        import requests as _req
        payload = {}
        extra_raw = md.get('extra_config')
        if extra_raw and isinstance(extra_raw, str):
            try:
                extra = json.loads(extra_raw)
                if isinstance(extra, dict):
                    payload.update(extra)
            except (json.JSONDecodeError, TypeError):
                pass
        payload["model"] = md.get("model", "")
        payload["messages"] = [
            {"role": "system", "content": "为对话生成一个简短标题。列出3个候选，直接选一个输出。"},
            {"role": "user", "content": f"对话内容：{context}"},
        ]
        payload["stream"] = False
        payload["max_tokens"] = md.get('max_tokens', 16384)
        payload["temperature"] = 0.1
        if md.get('frequency_penalty') is not None:
            payload['frequency_penalty'] = md['frequency_penalty']
        if md.get('presence_penalty') is not None:
            payload['presence_penalty'] = md['presence_penalty']
        _headers = {"Content-Type": "application/json"}
        api_key = md.get("api_key", "")
        if api_key:
            _headers["Authorization"] = f"Bearer {api_key}"
        resp = _req.post(f"{base_url}/v1/chat/completions", json=payload, headers=_headers, timeout=30)
        if resp.status_code != 200:
            return
        data = resp.json()
        choices = data.get("choices", [])
        raw = ""
        if choices:
            msg = choices[0].get("message", {})
            raw = (msg.get("content", "") or msg.get("reasoning_content", "") or "").strip()
        title = _extract_title_from_llm_output(raw)
        if title and 2 <= len(title) <= 16:
            from datetime import datetime as _dt
            now = _dt.now().isoformat()
            _sdb().execute("UPDATE llm_sessions SET title = ?, updated_at = ? WHERE id = ?", (title, now, session_id))
        else:
            fallback = _fallback_title(session_id, raw[:80])
            if fallback:
                from datetime import datetime as _dt
                now = _dt.now().isoformat()
                _sdb().execute("UPDATE llm_sessions SET title = ?, updated_at = ? WHERE id = ?", (fallback, now, session_id))
    except Exception as e:
        logger.warning(f"[auto-title] _do_auto_title error: {e}")


def _check_auto_title(session_id: str):
    try:
        row = _sdb().fetchone("SELECT title FROM llm_sessions WHERE id = ?", (session_id,))
        if not row:
            return
        title = row["title"] or ""
        if title and not title.startswith("新对话") and not title.startswith("便签分析"):
            return
        msgs = _sdb().fetchall(
            "SELECT role, content FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY created_at",
            (session_id,),
        )
        if len(msgs) < 2:
            return
        context = "\n".join([f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:500]}" for m in msgs[-4:]])
        _do_auto_title(session_id, context)
    except Exception as e:
        logger.warning(f"[auto-title] _check_auto_title error: {e}")


# ── Models / Skills ──

@router.get("/api/template-locale")
async def get_template_locale():
    if not common.multi_db:
        return {"locale": "zh-CN"}
    try:
        row = common.multi_db.main_db.fetchone("SELECT value FROM context_store WHERE key='default_template_locale'")
        return {"locale": row["value"] if row else "zh-CN"}
    except Exception:
        return {"locale": "zh-CN"}


@router.get("/api/models")
async def list_models():
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        rows = common.multi_db.main_db.fetchall(
            "SELECT id, name, provider, model, is_default, type FROM model_configs ORDER BY is_default DESC, name"
        )
        result = []
        for r in rows:
            badge = "本地" if r["type"] == "local" else "API"
            result.append({"id": r["id"], "name": r["name"] or r["model"], "provider": r["provider"],
                           "model": r["model"], "isDefault": bool(r["is_default"]), "badge": badge})
        default_row = common.multi_db.main_db.fetchone("SELECT value FROM app_config WHERE key='web_chat_default_model_id'")
        default_model = default_row["value"] if default_row else None
        return {"models": result, "webChatDefaultModelId": default_model}
    except Exception as e:
        return {"models": [], "webChatDefaultModelId": None}


@router.put("/api/models/{model_id}")
async def update_model_config(model_id: str, body: dict):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    extra = body.get("extraConfig") or body.get("extra_config")
    if extra is not None:
        common.multi_db.main_db.execute(
            "UPDATE model_configs SET extra_config = ? WHERE id = ?",
            (json.dumps(extra) if isinstance(extra, dict) else str(extra), model_id)
        )
    return {"ok": True}


@router.get("/api/skills")
async def list_skills():
    from skills import get_skill_registry
    registry = get_skill_registry()
    return {"skills": registry.to_frontend_list(), "defaults": registry.list_defaults()}


# ── Session CRUD ──

@router.post("/api/chat/sessions")
async def create_chat_session(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        title = body.get("title", "新对话")
        project_id = body.get("projectId") or body.get("project_id", "")
        model_id = body.get("modelId") or body.get("model_id", "")
        active_skills = body.get("skills") or body.get("active_skills", [])
        refs = body.get("refs", [])

        if not model_id:
            default_row = common.multi_db.main_db.fetchone("SELECT value FROM app_config WHERE key='web_chat_default_model_id'")
            if default_row and default_row["value"]:
                model_id = default_row["value"]
            else:
                default_model = common.multi_db.main_db.fetchone(
                    "SELECT id FROM model_configs WHERE is_default = 1 AND status = 'connected'"
                )
                if default_model:
                    model_id = default_model["id"]

        from skills import get_skill_registry
        registry = get_skill_registry()
        if not active_skills:
            active_skills = registry.list_defaults()

        sid = _make_session_id()
        metadata = json.dumps({"module": "web_chat", "model_id": model_id,
                                "active_skills": active_skills, "refs": refs}, ensure_ascii=False)
        now = __import__("datetime").datetime.now().isoformat()
        _sdb().execute(
            "INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at) "
            "VALUES (?, 'ai_assistant', ?, ?, ?, ?, ?)",
            (sid, project_id or None, title, metadata, now, now),
        )

        from web_tools import resolve_refs_to_context
        system_parts = [
            "你是 TopoCode 架构分析助手，帮助用户理解和分析项目代码架构。",
            "你可以使用工具查询项目数据，回答用户关于架构、代码、设计的问题。",
            "可用命令: /overview (生成架构概览), /analyze_components (组件分析), "
            "/presummary (文件预摘要), /pipeline (完整流水线). 支持参数: "
            "--force (重新生成), -L zh/en (输出语言), "
            "-j N (并发数, 1-5, 默认1, 如 /pipeline -j 2). "
            "overview 命令不支持 -j 参数, 只有一个并发.",
            "注意：每次消息最多可以进行 50 次工具调用。请在此限制内规划分析路径。"
            "工具的调用必须使用可用工具列表中提供的精确名称，禁止猜测或编造工具名。"
            "如果无合适工具可用，直接告知用户无法处理，不要循环尝试不存在的工具。"
            "如果某个工具返回空结果或无有效数据，说明该路径不可行，请跳过并尝试其他方法。"
            "不要重复调用返回相同结果的工具。如果已获取足够信息，直接输出结论。"
            "如果多次尝试后仍无法获取需要的信息，直接告知用户当前的能力限制。",
        ]
        if refs:
            ref_context = resolve_refs_to_context(refs, common.multi_db)
            if ref_context:
                system_parts.append(ref_context)
        skill_context = registry.collect_context(active_skills)
        if skill_context:
            system_parts.append(skill_context)

        system_content = "\n\n".join(system_parts)
        if system_content.strip():
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, '{}', ?)",
                (_make_message_id(), sid, system_content, now),
            )

        return {"id": sid, "title": title, "projectId": project_id,
                "modelId": model_id, "activeSkills": active_skills, "createdAt": now}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/chat/sessions")
async def list_chat_sessions(project_id: str = Query(None), status: str = Query(None)):
    _require_chat_ready()
    try:
        wheres = ["json_extract(metadata, '$.module') = 'web_chat'"]
        params = []
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        if status:
            wheres.append("status = ?")
            params.append(status)
        sql = "SELECT id, project_id, title, status, metadata, created_at, updated_at " \
              f"FROM llm_sessions WHERE {' AND '.join(wheres)} ORDER BY updated_at DESC"
        rows = _sdb().fetchall(sql, tuple(params))
        result = []
        for r in rows:
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
            result.append({"id": r["id"], "projectId": r["project_id"], "title": r["title"],
                           "status": r["status"], "modelId": meta.get("model_id", ""),
                           "activeSkills": meta.get("active_skills", []),
                           "messageCount": meta.get("message_count", 0),
                           "createdAt": r["created_at"], "updatedAt": r["updated_at"]})
        return {"sessions": result, "total": len(result)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/chat/sessions/{session_id}")
async def get_chat_session(session_id: str):
    _require_chat_ready()
    try:
        row = _sdb().fetchone(
            "SELECT id, project_id, title, status, metadata, created_at, updated_at FROM llm_sessions WHERE id = ?",
            (session_id,),
        )
        if not row:
            raise HTTPException(404, "Session not found")
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        messages = _sdb().fetchall(
            "SELECT id, role, content, metadata, created_at FROM llm_messages "
            "WHERE session_id = ? ORDER BY created_at", (session_id,),
        )
        return {"id": row["id"], "projectId": row["project_id"], "title": row["title"],
                "status": row["status"], "modelId": meta.get("model_id", ""),
                "activeSkills": meta.get("active_skills", []), "refs": meta.get("refs", []),
                "messages": [{"id": m["id"], "role": m["role"], "content": m["content"],
                               "refs": json.loads(m["metadata"]).get("refs", []) if m["metadata"] else [],
                               "reasoning": json.loads(m["metadata"]).get("reasoning", "") if m["metadata"] else "",
                               "toolCalls": json.loads(m["metadata"]).get("tool_calls", []) if m["metadata"] else [],
                               "createdAt": m["created_at"]} for m in messages],
                "createdAt": row["created_at"], "updatedAt": row["updated_at"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/api/chat/sessions/{session_id}")
async def update_chat_session(session_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        row = _sdb().fetchone("SELECT metadata FROM llm_sessions WHERE id = ?", (session_id,))
        if not row:
            raise HTTPException(404, "Session not found")
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        updates = []
        if "title" in body:
            updates.append(("title", body["title"]))
        if "status" in body:
            updates.append(("status", body["status"]))
        if "modelId" in body or "model_id" in body:
            meta["model_id"] = body.get("modelId") or body.get("model_id", "")
        if "skills" in body:
            meta["active_skills"] = body["skills"]
        if "refs" in body:
            meta["refs"] = body["refs"]
        now = __import__("datetime").datetime.now().isoformat()
        updates.append(("metadata", json.dumps(meta, ensure_ascii=False)))
        updates.append(("updated_at", now))
        set_clause = ", ".join(f"{k} = ?" for k, _ in updates)
        vals = [v for _, v in updates] + [session_id]
        _sdb().execute(f"UPDATE llm_sessions SET {set_clause} WHERE id = ?", tuple(vals))
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/api/chat/sessions/{session_id}")
async def delete_chat_session(session_id: str):
    _require_chat_ready()
    try:
        _sdb().execute("DELETE FROM llm_sessions WHERE id = ?", (session_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/chat/sessions/{session_id}/auto-title")
async def auto_title_session(session_id: str):
    _require_chat_ready()
    try:
        row = _sdb().fetchone("SELECT title FROM llm_sessions WHERE id = ?", (session_id,))
        if not row:
            raise HTTPException(404, "Session not found")
        msgs = _sdb().fetchall(
            "SELECT role, content FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant') ORDER BY created_at",
            (session_id,),
        )
        if len(msgs) < 2:
            return {"title": row["title"] or "新对话", "generated": False}
        context = "\n".join([f"{'用户' if m['role'] == 'user' else '助手'}: {m['content'][:500]}" for m in msgs[-4:]])
        _do_auto_title(session_id, context)
        updated = _sdb().fetchone("SELECT title FROM llm_sessions WHERE id = ?", (session_id,))
        new_title = updated["title"] if updated else (row["title"] or "新对话")
        return {"title": new_title, "generated": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/chat/sessions/{session_id}/stream/abort")
async def abort_chat_stream(session_id: str):
    _require_chat_ready()
    with _active_streams_lock:
        resp = _active_streams.pop(session_id, None)
    if resp:
        resp.close()
    return {"ok": True}


# ── Messages ──

@router.put("/api/chat/sessions/{session_id}/messages/{message_id}")
async def update_chat_message(session_id: str, message_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        content = body.get("content", "")
        _sdb().execute("UPDATE llm_messages SET content = ? WHERE id = ? AND session_id = ?",
                       (content, message_id, session_id))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/chat/sessions/{session_id}/messages")
async def send_chat_message(session_id: str, request: Request):
    """Send message + SSE streaming reply (core endpoint)"""
    _require_chat_ready()
    try:
        body = await request.json()
        content = body.get("content", "")
        refs = body.get("refs", [])
        model_id = body.get("modelId") or body.get("model_id", "")
        streaming = body.get("stream", True)
        context_limit = body.get("contextLimit", 0)

        # ── Phase 0: Command detection ──
        if content.startswith("/compress"):
            compressor = SessionCompressor(_sdb())
            summary = await compressor.execute(content, session_id)
            async def _compress_stream():
                yield f"data: {json.dumps({'type': 'chunk', 'text': summary[:100]})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'content': summary})}\n\n"
            return StreamingResponse(_compress_stream(), media_type="text/event-stream")

        # ── Phase 1: Reference parsing ──
        parsed_refs = ReferenceParser.parse(content, refs)
        session = _sdb().fetchone("SELECT id, project_id, metadata FROM llm_sessions WHERE id = ?", (session_id,))
        if not session:
            raise HTTPException(404, "Session not found")

        meta = json.loads(session["metadata"]) if session["metadata"] else {}
        if not model_id:
            model_id = meta.get("model_id", "")
        if not context_limit:
            context_limit = meta.get("context_limit", 32000)
        active_skills = meta.get("active_skills", [])

        now = __import__("datetime").datetime.now().isoformat()

        from web_tools import resolve_refs_to_context as _resolve_refs_to_context

        if refs:
            ref_context = _resolve_refs_to_context(refs, common.multi_db)
            if ref_context:
                _sdb().execute(
                    "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                    "VALUES (?, ?, 'system', ?, '{}', ?)",
                    (_make_message_id(), session_id, ref_context, now),
                )
            first = refs[0]
            ctx_parts = []
            if first.get("projectName") or first.get("projectId"):
                name = first.get("projectName", "")
                pid = first.get("projectId", "")
                ctx_parts.append(f"项目：{name}" + (f"（ID: {pid}）" if pid else ""))
            else:
                ctx_parts.append(f"项目ID：{session.get('project_id', '')}")
            if first.get("taskId"):
                ctx_parts.append(f"任务ID：{first['taskId']}")
            if first.get("componentId"):
                ctx_parts.append(f"组件ID：{first['componentId']}")
            ctx_parts.append(f"会话ID：{session_id}")
            ctx_parts.append("每轮消息最多 50 次工具调用。工具名必须使用可用工具列表中提供的精确名称，禁止猜测或编造工具名。如果无合适工具可用，直接告知用户无法处理，不要循环尝试不存在的工具。")
            ctx_msg = "；".join(ctx_parts)
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, '{}', ?)",
                (_make_message_id(), session_id, ctx_msg, now),
            )

        if not refs:
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, '{}', ?)",
                (_make_message_id(), session_id,
                 f"会话ID：{session_id}；每轮消息最多 50 次工具调用。工具名必须使用可用工具列表中提供的精确名称，禁止猜测或编造工具名。如果无合适工具可用，直接告知用户无法处理，不要循环尝试不存在的工具。",
                 now),
            )

        msg_meta = json.dumps({"refs": refs} if refs else {})
        _sdb().execute(
            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, 'user', ?, ?, ?)",
            (_make_message_id(), session_id, content, msg_meta, now),
        )

        count_row = _sdb().fetchone(
            "SELECT count(*) AS cnt FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
        )
        count = count_row["cnt"] if count_row else 0
        meta["message_count"] = count // 2
        _sdb().execute("UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                       (json.dumps(meta, ensure_ascii=False), now, session_id))

        if not streaming:
            return {"ok": True, "messageId": _make_message_id()}

        # ── SSE streaming ──
        from skills import get_skill_registry
        registry = get_skill_registry()
        tool_names = registry.collect_tool_names(active_skills)
        has_tools = len(tool_names) > 0

        msgs = _sdb().fetchall(
            "SELECT role, content FROM llm_messages WHERE session_id = ? ORDER BY created_at", (session_id,)
        )
        context_messages = [{"role": m["role"], "content": m["content"]} for m in msgs]

        # ── Phase 2: Context assembly ──
        assembler = ContextAssembler(session_id, _sdb())
        context_messages = assembler.build(context_messages, parsed_refs, context_limit)

        if has_tools:
            tool_descriptions = registry.collect_tool_descriptions(active_skills)
            if tool_descriptions:
                context_messages.append({"role": "system", "content": "可用工具列表：\n" + tool_descriptions})

        # ── Multi-round tool calling ──
        from web_tools import get_web_tool_definitions
        tool_defs = get_web_tool_definitions(tool_names) if has_tools else None
        executor = common.web_tool_executor

        def _llm_round(messages, tools, chunk_q, force_tool_choice=False):
            _log = logger.info
            try:
                model_cfg = common.multi_db.main_db.fetchone("SELECT * FROM model_configs WHERE id = ?", (model_id,))
                if not model_cfg:
                    chunk_q.put({"type": "error", "message": f"Model not found: {model_id}"})
                    chunk_q.put({"type": "done"})
                    return
                md = dict(model_cfg)
                has_t = bool(tools)
                import requests as _req
                base_url = md.get('url', '').rstrip('/')
                if base_url.endswith('/v1'):
                    base_url = base_url[:-3]
                payload = {}
                extra_raw = md.get('extra_config')
                if extra_raw and isinstance(extra_raw, str):
                    try:
                        extra = json.loads(extra_raw)
                        if isinstance(extra, dict):
                            payload.update(extra)
                    except (json.JSONDecodeError, TypeError):
                        pass
                payload['model'] = md.get('model', '')
                payload['messages'] = messages
                payload['stream'] = True
                if tools:
                    payload['tools'] = tools
                    if force_tool_choice:
                        payload['tool_choice'] = 'auto'
                if md.get('temperature') is not None:
                    payload['temperature'] = md['temperature']
                if md.get('frequency_penalty') is not None:
                    payload['frequency_penalty'] = md['frequency_penalty']
                if md.get('presence_penalty') is not None:
                    payload['presence_penalty'] = md['presence_penalty']
                payload['max_tokens'] = md.get('max_tokens', 16384)
                headers = {'Content-Type': 'application/json'}
                api_key = md.get('api_key', '')
                if api_key:
                    headers['Authorization'] = f'Bearer {api_key}'
                timeout = md.get('timeout', 300)
                resp = _req.post(f'{base_url}/v1/chat/completions', json=payload, headers=headers, stream=True, timeout=timeout)
                if resp.status_code != 200:
                    err_body = resp.text[:300]
                    chunk_q.put({'type': 'error', 'message': f'API error {resp.status_code}: {err_body}'})
                    chunk_q.put({'type': 'done'})
                    return
                with _active_streams_lock:
                    _active_streams[session_id] = resp
                line_count = 0
                reasoning_only_count = 0
                MAX_REASONING_LINES = 3000
                try:
                    for line_bytes in resp.iter_lines():
                        if not line_bytes:
                            continue
                        line = line_bytes.decode('utf-8')
                        if not line.startswith('data: '):
                            continue
                        data_str = line[6:].strip()
                        if data_str == '[DONE]':
                            break
                        line_count += 1
                        try:
                            data = json.loads(data_str)
                            delta = data.get('choices', [{}])[0].get('delta', {})
                            chunk = delta.get('content', '')
                            reasoning = delta.get('reasoning_content', '')
                            if reasoning and not chunk:
                                reasoning_only_count += 1
                                if reasoning_only_count > MAX_REASONING_LINES:
                                    break
                            else:
                                reasoning_only_count = 0
                            if reasoning:
                                chunk_q.put({"type": "reasoning", "text": reasoning})
                            if chunk:
                                chunk_q.put(chunk)
                            tc = delta.get('tool_calls')
                            if tc:
                                chunk_q.put({'type': 'tool_calls', 'data': json.dumps(tc)})
                        except Exception:
                            pass
                except Exception as e:
                    with _active_streams_lock:
                        _is_aborted = session_id not in _active_streams
                    if _is_aborted:
                        chunk_q.put({"type": "aborted"})
                    else:
                        chunk_q.put({"type": "error", "message": str(e)})
                finally:
                    with _active_streams_lock:
                        _active_streams.pop(session_id, None)
                    chunk_q.put({'type': 'done'})
            except Exception as e:
                chunk_q.put({"type": "error", "message": str(e)})
                chunk_q.put({"type": "done"})

        async def event_stream():
            queue = asyncio.Queue()
            loop = asyncio.get_event_loop()
            executor._current_session_id = session_id
            TOOL_ROUND_LIMIT = 50

            async def _producer():
                ctx_msgs = list(context_messages)
                _acc_reasoning = ""
                _acc_tool_calls = 0
                for round_idx in range(TOOL_ROUND_LIMIT):
                    force_choice = round_idx == 0 and bool(tool_defs)
                    chunk_q = _queue.Queue()
                    full_content = ""
                    full_reasoning = ""
                    tc_by_idx = {}

                    t = threading.Thread(target=_llm_round, args=(ctx_msgs, tool_defs, chunk_q, force_choice), daemon=True)
                    t.start()

                    while True:
                        try:
                            item = await loop.run_in_executor(None, chunk_q.get, True, 0.15)
                        except _queue.Empty:
                            continue
                        if isinstance(item, dict):
                            if item.get("type") == "done":
                                break
                            if item.get("type") == "error":
                                await queue.put({"type": "error", "message": item.get("message", "")})
                                await queue.put({"type": "done"})
                                return
                            if item.get("type") == "aborted":
                                await queue.put({"type": "done", "content": ""})
                                return
                            if item.get("type") == "tool_calls":
                                tc_delta_list = json.loads(item.get("data", "[]"))
                                for td in tc_delta_list:
                                    idx = td.get("index", 0)
                                    acc = tc_by_idx.setdefault(idx, {})
                                    if "id" in td:
                                        acc["id"] = td["id"]
                                    if "type" in td:
                                        acc["type"] = td["type"]
                                    fn = td.get("function", {})
                                    if fn:
                                        acc.setdefault("function", {})
                                        if "name" in fn:
                                            acc["function"]["name"] = fn["name"]
                                        if "arguments" in fn:
                                            acc["function"]["arguments"] = acc["function"].get("arguments", "") + fn["arguments"]
                            if item.get("type") == "reasoning":
                                full_reasoning += item.get("text", "")
                                await queue.put({"type": "reasoning", "text": item.get("text", "")})
                            if item.get("type") == "chunk" and not force_choice:
                                await queue.put({"type": "chunk", "text": item.get("text", "")})
                        elif isinstance(item, str):
                            full_content += item
                            if not force_choice:
                                await queue.put({"type": "chunk", "text": item})

                    t.join(timeout=5)
                    _acc_reasoning += full_reasoning
                    parsed = []
                    for v in tc_by_idx.values():
                        try:
                            args = json.loads(v.get("function", {}).get("arguments", "{}"))
                        except Exception:
                            args = {}
                        parsed.append({"id": v.get("id", ""), "name": v.get("function", {}).get("name", ""), "arguments": args})
                    _acc_tool_calls += len(parsed)

                    if not parsed:
                        final_content = full_content.strip()
                        _reasoning_len = len(full_reasoning.strip())
                        _acc_reasoning_str = _acc_reasoning.strip()
                        quality = "ok"
                        if not final_content and _acc_reasoning_str:
                            if len(_acc_reasoning_str) >= 500:
                                final_content = _acc_reasoning_str
                            elif _acc_tool_calls >= 2:
                                quality = "low"
                        elif not final_content and not _acc_reasoning_str and _acc_tool_calls >= 2:
                            quality = "low"
                        if final_content:
                            _meta = {}
                            if _reasoning_len:
                                _meta["reasoning"] = full_reasoning.strip()
                            _sdb().execute(
                                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                                "VALUES (?, ?, 'assistant', ?, ?, ?)",
                                (_make_message_id(), session_id, final_content, json.dumps(_meta), now),
                            )
                        if round_idx == 0 and tool_defs and final_content:
                            await queue.put({"type": "chunk", "text": final_content})
                        await queue.put({"type": "done", "content": final_content if quality == "ok" else "",
                                          "quality": quality,
                                          "reasoning": _acc_reasoning_str if quality == "low" else ""})
                        return

                    tool_msgs = []
                    for tc_item in parsed:
                        t_name = tc_item.get("name", "")
                        t_args = tc_item.get("arguments", {})
                        tc_id = tc_item.get("id", "")
                        await queue.put({"type": "tool_call", "id": tc_id, "name": t_name, "arguments": t_args})
                        try:
                            result = executor.execute(t_name, t_args)
                        except Exception as e:
                            result = {"error": str(e)}
                        await queue.put({"type": "tool_result", "id": tc_id, "name": t_name, "result": result})
                        result_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
                        _sdb().execute(
                            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                            "VALUES (?, ?, 'tool', ?, ?, ?)",
                            (_make_message_id(), session_id, result_str, json.dumps({"tool_call_id": tc_id}), now),
                        )
                        tool_msgs.append({"role": "tool", "content": result_str, "tool_call_id": tc_id})

                    asst_tc_payload = [{"id": p.get("id", ""), "type": "function",
                                        "function": {"name": p.get("name", ""), "arguments": json.dumps(p.get("arguments", {}), ensure_ascii=False)}}
                                       for p in parsed]
                    ctx_msgs.append({"role": "assistant", "content": full_content.strip() or "", "tool_calls": asst_tc_payload})
                    ctx_msgs.extend(tool_msgs)
                    asst_id = _make_message_id()
                    tc_meta_dict = {"tool_calls": [{"name": p.get("name", ""), "arguments": p.get("arguments", {})} for p in parsed]}
                    if full_reasoning.strip():
                        tc_meta_dict["reasoning"] = full_reasoning.strip()
                    _sdb().execute(
                        "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                        "VALUES (?, ?, 'assistant', ?, ?, ?)",
                        (asst_id, session_id, full_content.strip() or "", json.dumps(tc_meta_dict), now),
                    )

                await queue.put({"type": "error", "message": "工具调用次数过多，请简化问题"})
                await queue.put({"type": "done"})

            asyncio.create_task(_producer())
            try:
                while True:
                    event = await queue.get()
                    if event["type"] == "done":
                        yield f"event: done\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        break
                    elif event["type"] == "error":
                        yield f"event: error\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                        break
                    elif event["type"] == "chunk":
                        yield f"event: chunk\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event["type"] == "reasoning":
                        yield f"event: reasoning\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event["type"] == "tool_call":
                        yield f"event: tool_call\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    elif event["type"] == "tool_result":
                        yield f"event: tool_result\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
            finally:
                pass

        return StreamingResponse(event_stream(), media_type="text/event-stream")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Chat error: {e}")


@router.get("/api/chat/sessions/{session_id}/messages")
async def get_chat_messages(session_id: str, limit: int = Query(50), offset: int = Query(0)):
    _require_chat_ready()
    try:
        rows = _sdb().fetchall(
            "SELECT id, role, content, metadata, created_at FROM llm_messages "
            "WHERE session_id = ? ORDER BY created_at LIMIT ? OFFSET ?",
            (session_id, limit, offset),
        )
        return {"messages": [{"id": m["id"], "role": m["role"], "content": m["content"],
                               "refs": json.loads(m["metadata"]).get("refs", []) if m["metadata"] else [],
                               "createdAt": m["created_at"]} for m in rows], "total": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/api/chat/sessions/{session_id}/messages")
async def delete_chat_messages(session_id: str, message_id: str = Query(None)):
    _require_chat_ready()
    try:
        ids = [m.strip() for m in (message_id or "").split(",") if m.strip()]
        if not ids:
            raise HTTPException(422, "message_id is required")
        timestamps = []
        for _id in ids:
            row = _sdb().fetchone("SELECT created_at FROM llm_messages WHERE id = ? AND session_id = ?", (_id, session_id))
            if row:
                timestamps.append(row["created_at"])
        placeholders = ",".join("?" * len(ids))
        _sdb().execute(f"DELETE FROM llm_messages WHERE session_id = ? AND id IN ({placeholders})", (session_id, *ids))
        for ts in timestamps:
            next_row = _sdb().fetchone(
                "SELECT MIN(created_at) AS next_ts FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') AND created_at > ?", (session_id, ts)
            )
            next_ts = next_row["next_ts"] if next_row and next_row["next_ts"] else "9999-12-31"
            _sdb().execute("DELETE FROM llm_messages WHERE session_id = ? AND role = 'tool' AND created_at >= ? AND created_at < ?",
                           (session_id, ts, next_ts))
            prev_row = _sdb().fetchone(
                "SELECT MAX(created_at) AS prev_ts FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') AND created_at < ?", (session_id, ts)
            )
            if prev_row and prev_row["prev_ts"]:
                _sdb().execute("DELETE FROM llm_messages WHERE session_id = ? AND role = 'tool' AND created_at > ? AND created_at < ?",
                               (session_id, prev_row["prev_ts"], ts))
        cnt = _sdb().fetchone("SELECT COUNT(*) AS c FROM llm_messages WHERE session_id = ? AND role IN ('user', 'assistant')", (session_id,))
        count = cnt["c"] // 2 if cnt else 0
        row = _sdb().fetchone("SELECT metadata FROM llm_sessions WHERE id = ?", (session_id,))
        if row:
            meta = json.loads(row["metadata"]) if row["metadata"] else {}
            meta["message_count"] = count
            _sdb().execute("UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                           (json.dumps(meta, ensure_ascii=False), __import__("datetime").datetime.now().isoformat(), session_id))
        return {"ok": True, "deleted": len(ids)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Autocomplete ──

@router.get("/api/chat/autocomplete")
async def chat_autocomplete(type: str = Query(...), q: str = Query(...),
                             taskId: str = Query(None), projectId: str = Query(None)):
    _require_chat_ready()
    try:
        results = []
        if type == "community" and q:
            tid = taskId or ""
            rows = _sdb().fetchall(
                "SELECT DISTINCT comm_name, comm_id, comm_lv FROM community_llm_results "
                "WHERE task_id = ? AND comm_name LIKE ? LIMIT 10", (tid, f"%{q}%")
            )
            for r in rows:
                results.append({"label": f"{r['comm_name']} ({r['comm_lv']})", "value": r["comm_id"], "type": "community"})
        elif type == "file" and q:
            pid = projectId or ""
            rows = _sdb().fetchall(
                "SELECT DISTINCT file_path FROM file_summaries WHERE project_id = ? AND file_path LIKE ? LIMIT 10",
                (pid, f"%{q}%")
            )
            for r in rows:
                results.append({"label": r["file_path"], "value": r["file_path"], "type": "file"})
        elif type == "symbol" and q:
            rows = _sdb().fetchall("SELECT name, kind FROM graph_node WHERE name LIKE ? LIMIT 10", (f"%{q}%",))
            seen = set()
            for r in rows:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    results.append({"label": f"{r['name']} ({r['kind'] or 'symbol'})", "value": r["name"], "type": "symbol"})
        elif type == "session" and q:
            rows = _sdb().fetchall(
                "SELECT id, title FROM llm_sessions WHERE id LIKE ? OR title LIKE ? LIMIT 10", (f"%{q}%", f"%{q}%")
            )
            for r in rows:
                results.append({"label": f"{r['title'] or '未命名'} ({r['id'][:12]}...)", "value": r["id"], "type": "session"})
        return {"results": results}
    except Exception as e:
        return {"results": [], "error": str(e)}


# ── Context APIs ──

@router.get("/api/chat/context/project/{project_id}")
async def get_project_context(project_id: str):
    _require_chat_ready()
    try:
        proj = common.multi_db.main_db.fetchone("SELECT id, name, root_path FROM projects WHERE id = ?", (project_id,))
        if not proj:
            raise HTTPException(404, "Project not found")
        tasks = common.multi_db.main_db.fetchall(
            "SELECT id, name, status FROM analysis_tasks WHERE project_id = ? ORDER BY created_at DESC", (project_id,)
        )
        return {"project": {"id": proj["id"], "name": proj["name"], "rootPath": proj["root_path"]},
                "tasks": [{"id": t["id"], "name": t["name"], "status": t["status"]} for t in tasks]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/chat/context/task/{task_id}")
async def get_task_context(task_id: str):
    _require_chat_ready()
    try:
        task = common.multi_db.main_db.fetchone("SELECT id, name, status, project_id FROM analysis_tasks WHERE id = ?", (task_id,))
        if not task:
            raise HTTPException(404, "Task not found")
        pid = task["project_id"]
        pdb = common.multi_db.get_project_db(pid)
        communities = pdb.fetchall(
            "SELECT comm_id, comm_lv, name FROM community_llm_results WHERE task_id = ? LIMIT 20", (task_id,)
        )
        return {"task": {"id": task["id"], "name": task["name"], "status": task["status"], "projectId": task["project_id"]},
                "communities": [{"commId": c["comm_id"], "level": c["comm_lv"], "name": c["name"]} for c in communities]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Archives ──

@router.post("/api/chat/archives")
async def create_archive(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        aid = f"arch_{uuid.uuid4().hex[:12]}"
        session_id = body.get("sessionId") or body.get("session_id", "")
        title = body.get("title", "")
        content = body.get("content", "")
        category = body.get("category", "note")
        tags = body.get("tags", "")
        pid = body.get("projectId") or body.get("project_id", "")
        if not pid and session_id:
            row = _sdb().fetchone("SELECT project_id FROM llm_sessions WHERE id = ?", (session_id,))
            if row:
                pid = row["project_id"]
        common.multi_db.main_db.execute(
            "INSERT INTO chat_archives (id, session_id, project_id, title, content, category, tags, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')",
            (aid, session_id or None, pid or None, title, content, category, tags),
        )
        return {"id": aid, "ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/chat/archives")
async def list_archives(project_id: str = Query(None), category: str = Query(None), tag: str = Query(None)):
    _require_chat_ready()
    try:
        wheres = []
        params = []
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        if category:
            wheres.append("category = ?")
            params.append(category)
        if tag:
            wheres.append("tags LIKE ?")
            params.append(f"%{tag}%")
        where = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        rows = common.multi_db.main_db.fetchall(
            f"SELECT id, title, content, category, tags, source, created_at "
            f"FROM chat_archives {where} ORDER BY created_at DESC LIMIT 50"
        )
        return {"archives": [{"id": r["id"], "title": r["title"], "content": r["content"][:500],
                               "category": r["category"], "tags": r["tags"], "source": r["source"],
                               "createdAt": r["created_at"]} for r in rows], "total": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/api/chat/archives/{archive_id}")
async def delete_archive(archive_id: str):
    _require_chat_ready()
    try:
        common.multi_db.main_db.execute("DELETE FROM chat_archives WHERE id = ?", (archive_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Notes ──

@router.post("/api/notes")
async def create_note(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        nid = _make_note_id()
        title = body.get("title", "")
        content = body.get("content", "")
        refs = json.dumps(body.get("refs", []), ensure_ascii=False)
        project_id = body.get("projectId") or body.get("project_id", "")
        now = __import__("datetime").datetime.now().isoformat()
        common.multi_db.main_db.execute(
            "INSERT INTO chat_notes (id, title, content, refs, status, project_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'draft', ?, ?, ?)",
            (nid, title, content, refs, project_id or None, now, now),
        )
        return {"id": nid, "title": title, "ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/notes")
async def list_notes(status: str = Query(None), project_id: str = Query(None)):
    _require_chat_ready()
    try:
        wheres = []
        params = []
        if status:
            wheres.append("status = ?")
            params.append(status)
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(wheres)}" if wheres else ""
        rows = common.multi_db.main_db.fetchall(
            f"SELECT id, title, content, refs, status, session_id, project_id, created_at, updated_at "
            f"FROM chat_notes {where} ORDER BY updated_at DESC", tuple(params)
        )
        return {"notes": [{"id": r["id"], "title": r["title"], "content": r["content"],
                            "refs": json.loads(r["refs"]) if r["refs"] else [],
                            "status": r["status"], "sessionId": r["session_id"], "projectId": r["project_id"],
                            "createdAt": r["created_at"], "updatedAt": r["updated_at"]} for r in rows], "total": len(rows)}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/notes/{note_id}")
async def get_note(note_id: str):
    _require_chat_ready()
    try:
        row = common.multi_db.main_db.fetchone(
            "SELECT id, title, content, refs, status, session_id, project_id, created_at, updated_at FROM chat_notes WHERE id = ?",
            (note_id,),
        )
        if not row:
            raise HTTPException(404, "Note not found")
        return {"id": row["id"], "title": row["title"], "content": row["content"],
                "refs": json.loads(row["refs"]) if row["refs"] else [],
                "status": row["status"], "sessionId": row["session_id"], "projectId": row["project_id"],
                "createdAt": row["created_at"], "updatedAt": row["updated_at"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/api/notes/{note_id}")
async def update_note(note_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        row = common.multi_db.main_db.fetchone("SELECT id, refs FROM chat_notes WHERE id = ?", (note_id,))
        if not row:
            raise HTTPException(404, "Note not found")
        existing_refs = json.loads(row["refs"]) if row["refs"] else []
        updates = []
        if "title" in body:
            updates.append(("title", body["title"]))
        if "content" in body:
            updates.append(("content", body["content"]))
        if "refs" in body:
            seen = set()
            merged = []
            for r in existing_refs + body["refs"]:
                key = json.dumps(r, sort_keys=True)
                if key not in seen:
                    seen.add(key)
                    merged.append(r)
            updates.append(("refs", json.dumps(merged, ensure_ascii=False)))
        if not updates:
            return {"ok": True}
        now = __import__("datetime").datetime.now().isoformat()
        updates.append(("updated_at", now))
        set_clause = ", ".join(f"{k} = ?" for k, _ in updates)
        vals = [v for _, v in updates] + [note_id]
        common.multi_db.main_db.execute(f"UPDATE chat_notes SET {set_clause} WHERE id = ?", tuple(vals))
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/api/notes/{note_id}")
async def delete_note(note_id: str):
    _require_chat_ready()
    try:
        common.multi_db.main_db.execute("DELETE FROM chat_notes WHERE id = ?", (note_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/notes/{note_id}/send")
async def send_note(note_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        session_id = body.get("sessionId") or body.get("session_id", "")
        row = common.multi_db.main_db.fetchone("SELECT id, title, content, refs, status, project_id FROM chat_notes WHERE id = ?", (note_id,))
        if not row:
            raise HTTPException(404, "Note not found")
        if row["status"] == "sent":
            raise HTTPException(400, "Note already sent")

        refs = json.loads(row["refs"]) if row["refs"] else []
        title = row["title"] or "便签消息"
        note_content = row["content"] or ""
        project_id = row["project_id"]

        from web_tools import resolve_refs_to_context
        ref_context = resolve_refs_to_context(refs, common.multi_db)

        if not session_id:
            from skills import get_skill_registry
            registry = get_skill_registry()
            default_skills = registry.list_defaults()
            sid = _make_session_id()
            now = __import__("datetime").datetime.now().isoformat()
            metadata = json.dumps({"module": "web_chat", "model_id": "",
                                    "active_skills": default_skills, "refs": refs, "note_id": note_id}, ensure_ascii=False)
            _sdb().execute(
                "INSERT INTO llm_sessions (id, module_type, project_id, title, metadata, created_at, updated_at) "
                "VALUES (?, 'ai_assistant', ?, ?, ?, ?, ?)",
                (sid, project_id or None, title, metadata, now, now),
            )
            session_id = sid
        else:
            existing = _sdb().fetchone("SELECT id, metadata FROM llm_sessions WHERE id = ?", (session_id,))
            if not existing:
                raise HTTPException(404, "Session not found")
            meta = json.loads(existing["metadata"]) if existing["metadata"] else {}
            sent_notes = meta.get("sent_note_ids", [])
            if note_id in sent_notes:
                raise HTTPException(400, "Note already sent to this session")
            meta.setdefault("sent_note_ids", []).append(note_id)
            now = __import__("datetime").datetime.now().isoformat()
            _sdb().execute("UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                           (json.dumps(meta, ensure_ascii=False), now, session_id))

        now = __import__("datetime").datetime.now().isoformat()
        sys_msg_id = _make_message_id()
        user_msg_id = _make_message_id()

        if ref_context:
            _sdb().execute(
                "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
                "VALUES (?, ?, 'system', ?, ?, ?)",
                (sys_msg_id, session_id, ref_context, json.dumps({"refs": refs, "note_id": note_id}, ensure_ascii=False), now),
            )

        user_text = note_content or f"分析这些内容：{title}"
        _sdb().execute(
            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, 'user', ?, ?, ?)",
            (user_msg_id, session_id, user_text, json.dumps({"refs": refs, "note_id": note_id}, ensure_ascii=False), now),
        )

        common.multi_db.main_db.execute(
            "UPDATE chat_notes SET status = 'sent', session_id = ?, message_id = ?, updated_at = ? WHERE id = ?",
            (session_id, user_msg_id, now, note_id),
        )

        return {"sessionId": session_id, "messageId": user_msg_id, "ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/notes/batch-send")
async def batch_send_notes(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        note_ids = body.get("noteIds", [])
        if not note_ids:
            raise HTTPException(422, "noteIds is required")
        first = None
        for nid in note_ids:
            try:
                result = await send_note(nid, request)
                if not first:
                    first = result
            except HTTPException as e:
                if e.status_code == 400 and "already sent" in str(e.detail):
                    continue
                raise
        return first or {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/api/notes/execute-draft")
async def execute_draft(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        refs = body.get("refs", [])
        user_text = body.get("userText", "").strip()
        session_id = body.get("sessionId") or body.get("session_id")

        if not refs:
            raise HTTPException(422, "refs is required")

        project_id = refs[0].get("projectId", "")
        task_id = refs[0].get("taskId", "")

        context_parts = []
        for ref in refs:
            label = ref.get("label", "")
            text = ref.get("text", "")
            pid = ref.get("projectId", "")
            tid = ref.get("taskId", "")
            cid = ref.get("componentId", "")
            meta = []
            if pid: meta.append(f"项目:{pid[:12]}")
            if tid: meta.append(f"任务:{tid[:10]}")
            if cid: meta.append(f"组件:{cid[:10]}")
            if label: meta.append(f"来源:{label}")
            s = " | ".join(meta)
            if text: s += "\n" + text
            context_parts.append(s)
        resolved = "\n\n".join(context_parts) if context_parts else "（引用材料为空）"

        if not session_id:
            title = "便签分析"
            if project_id:
                proj = common.multi_db.main_db.fetchone("SELECT name FROM projects WHERE id = ?", (project_id,))
                if proj:
                    title = proj["name"] + " - 便签分析"
            session_id = _create_chat_session(title, task_id or project_id)

        sys_id = uuid.uuid4().hex[:16]
        from datetime import datetime as _dt
        now = _dt.now().isoformat()
        common.multi_db.sessions_db.execute(
            "INSERT INTO llm_messages (id, session_id, role, content, created_at) VALUES (?, ?, 'system', ?, ?)",
            (sys_id, session_id, resolved, now),
        )
        user_msg_id = uuid.uuid4().hex[:16]
        content = user_text or "分析这些内容"
        common.multi_db.sessions_db.execute(
            "INSERT INTO llm_messages (id, session_id, role, content, created_at) VALUES (?, ?, 'user', ?, ?)",
            (user_msg_id, session_id, content, now),
        )
        cnt = common.multi_db.sessions_db.fetchone("SELECT COUNT(*) AS c FROM llm_messages WHERE session_id=?", (session_id,))
        if cnt:
            row = common.multi_db.sessions_db.fetchone("SELECT metadata FROM llm_sessions WHERE id=?", (session_id,))
            if row:
                meta = json.loads(row["metadata"]) if row["metadata"] else {}
                meta["message_count"] = cnt["c"]
                common.multi_db.sessions_db.execute("UPDATE llm_sessions SET metadata=?, updated_at=? WHERE id=?",
                                             (json.dumps(meta, ensure_ascii=False), now, session_id))

        return {"sessionId": session_id, "messageId": user_msg_id, "ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Documents ──

@router.post("/api/documents")
async def create_doc(request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        title = body.get("title", "无标题文档")
        content = body.get("content", "")
        project_id = body.get("projectId") or body.get("project_id", "")
        tags = body.get("tags", "")
        did = f"doc_{uuid.uuid4().hex[:12]}"
        now = __import__("datetime").datetime.now().isoformat()
        common.multi_db.knowledge_db.execute(
            "INSERT INTO knowledge_docs (id, title, content, project_id, tags, status, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, 'draft', ?, ?)",
            (did, title, content, project_id, tags, now, now)
        )
        return {"id": did, "ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/documents")
async def list_docs(search: str = "", status: str = "", project_id: str = "",
                     page: int = 1, page_size: int = 50):
    _require_chat_ready()
    try:
        where = "WHERE 1=1"
        params = []
        if search:
            where += " AND (title LIKE ? OR content LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        if status:
            where += " AND status = ?"
            params.append(status)
        if project_id:
            where += " AND project_id = ?"
            params.append(project_id)
        total = common.multi_db.knowledge_db.fetchone(
            f"SELECT COUNT(*) AS c FROM knowledge_docs {where}", tuple(params)
        )["c"]
        rows = common.multi_db.knowledge_db.fetchall(
            f"SELECT id, title, type, status, project_id, tags, created_at, updated_at "
            f"FROM knowledge_docs {where} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            tuple(params) + (page_size, (page - 1) * page_size)
        )
        return {"documents": rows, "total": total}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.get("/api/documents/{doc_id}")
async def get_doc(doc_id: str):
    _require_chat_ready()
    try:
        row = common.multi_db.knowledge_db.fetchone("SELECT * FROM knowledge_docs WHERE id = ?", (doc_id,))
        if not row:
            raise HTTPException(404, "Document not found")
        return dict(row)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, str(e))


@router.put("/api/documents/{doc_id}")
async def update_doc(doc_id: str, request: Request):
    _require_chat_ready()
    try:
        body = await request.json()
        allowed = {"title", "content", "tags", "status"}
        sets = []
        vals = []
        for k in allowed:
            if k in body:
                sets.append(f"{k} = ?")
                vals.append(body[k])
        if not sets:
            return {"ok": True}
        vals.append(__import__("datetime").datetime.now().isoformat())
        sets.append("updated_at = ?")
        common.multi_db.knowledge_db.execute(f"UPDATE knowledge_docs SET {', '.join(sets)} WHERE id = ?", tuple(vals) + (doc_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.delete("/api/documents/{doc_id}")
async def delete_doc(doc_id: str):
    _require_chat_ready()
    try:
        common.multi_db.knowledge_db.execute("DELETE FROM knowledge_docs WHERE id = ?", (doc_id,))
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, str(e))


# ── Helper classes (kept in same file for simplicity) ──

class ReferenceParser:
    ID_PATTERNS = [
        (r'\b(comm-\w+)\b', 'community'),
        (r'\b(proj-\w+)\b', 'project'),
        (r'\b(task-\w+)\b', 'task'),
        (r'\b(chat_\w+)\b', 'session'),
        (r'\b(arch_\w+)\b', 'archive'),
    ]

    @staticmethod
    def parse(user_content: str, body_refs: list = None) -> list:
        parsed = []
        for match in _re.finditer(r'@(\w+):([^\s,;，。！？\n]+)', user_content):
            parsed.append({"type": match.group(1), "id": match.group(2), "source": "explicit"})
        for pattern, ref_type in ReferenceParser.ID_PATTERNS:
            for match in _re.finditer(pattern, user_content):
                id_val = match.group(1)
                if not any(r.get("type") == ref_type and r.get("id") == id_val for r in parsed):
                    parsed.append({"type": ref_type, "id": id_val, "source": "implicit"})
        if body_refs:
            for br in body_refs:
                pr = ReferenceParser._infer_ref_type(br)
                if pr:
                    key = (pr["type"], pr["id"])
                    if not any((r.get("type"), r.get("id")) == key for r in parsed):
                        parsed.append({**pr, "source": "refs"})
        return parsed

    @staticmethod
    def _infer_ref_type(ref: dict) -> dict | None:
        if ref.get("type"):
            return {"type": ref["type"], "id": ref.get("id", "")}
        if ref.get("componentId"):
            return {"type": "community", "id": ref["componentId"]}
        if ref.get("projectId"):
            return {"type": "project", "id": ref["projectId"]}
        if ref.get("taskId"):
            return {"type": "task", "id": ref["taskId"]}
        return None


class TokenBudget:
    CHARS_PER_TOKEN = 2

    @classmethod
    def estimate(cls, text: str) -> int:
        return max(1, len(text) // cls.CHARS_PER_TOKEN)

    @classmethod
    def estimate_msgs(cls, messages: list[dict]) -> int:
        return sum(cls.estimate(m.get("content", "")) for m in messages)

    @classmethod
    def trim(cls, messages: list[dict], max_context: int = 16000, reserve: int = 4000) -> list[dict]:
        budget = max_context - reserve
        if budget <= 0:
            return messages[-8:] if len(messages) > 8 else messages
        system_msgs = [m for m in messages if m["role"] == "system"]
        dialog_msgs = [m for m in messages if m["role"] != "system"]
        base_tokens = cls.estimate_msgs(system_msgs)
        if base_tokens > budget:
            return system_msgs
        remaining = budget - base_tokens
        keep = []
        for m in reversed(dialog_msgs):
            if remaining <= 0:
                break
            tok = cls.estimate(m.get("content", ""))
            if tok <= remaining:
                keep.insert(0, m)
                remaining -= tok
        return system_msgs + keep


class ContextAssembler:
    def __init__(self, session_id: str, sdb):
        self.session_id = session_id
        self.sdb = sdb

    def build(self, db_messages: list[dict], parsed_refs: list = None, context_limit: int = 32000) -> list[dict]:
        l1 = self._build_l1(parsed_refs)
        merged = self._merge(db_messages, l1)
        return TokenBudget.trim(merged, context_limit)

    def _build_l1(self, parsed_refs: list = None) -> list[dict]:
        msgs = []
        if parsed_refs:
            from web_tools import resolve_refs_to_context
            context = resolve_refs_to_context(parsed_refs, common.multi_db)
            if context:
                msgs.append({"role": "system", "content": context})
        session = self.sdb.fetchone("SELECT metadata FROM llm_sessions WHERE id = ?", (self.session_id,))
        if session:
            meta = json.loads(session["metadata"]) if session["metadata"] else {}
            summary = meta.get("compressed_summary", "")
            if summary:
                msgs.append({"role": "system", "content": f"以下是对本对话早期内容的结构化摘要：\n{summary}"})
        return msgs

    def _merge(self, db_msgs: list[dict], l1_msgs: list[dict]) -> list[dict]:
        if not l1_msgs:
            return db_msgs
        system_msgs = [m for m in db_msgs if m["role"] == "system"]
        dialog_msgs = [m for m in db_msgs if m["role"] != "system"]
        return system_msgs + l1_msgs + dialog_msgs


class SessionCompressor:
    PROMPT_TEMPLATE = """请将以下对话压缩为结构化摘要：

要求：
1. 提取关键信息：涉及的项目/社区/文件/符号，核心结论和分析结果
2. 格式：
## 主题
[一句话概括]
## 关键内容
- 要点1
- 要点2
## 涉及的资源
- 社区: @community:xxx
- 文件: @file:path/to/file

3. 控制在 300 字以内，保留引用标记

== 对话内容 ==
{text}"""

    def __init__(self, sdb, llm_service=None):
        self.sdb = sdb
        self.service = llm_service

    @classmethod
    def parse_args(cls, content: str) -> dict:
        args = {"target_ids": [], "save": False, "category": ""}
        m = _re.search(r'--session\s+(\S+)', content)
        if m:
            args["target_ids"] = [x.strip() for x in m.group(1).split(",")]
        if "--save" in content:
            args["save"] = True
        m = _re.search(r'--category\s+(\S+)', content)
        if m:
            args["category"] = m.group(1).strip()
        return args

    def _load_messages(self, session_ids: list[str]) -> str:
        parts = []
        for sid in session_ids:
            rows = self.sdb.fetchall(
                "SELECT role, content FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "ORDER BY created_at LIMIT 100", (sid,),
            )
            if rows:
                parts.append(f"--- 会话 {sid} ---")
                for r in rows:
                    role_label = "用户" if r["role"] == "user" else "AI"
                    content = (r["content"] or "")[:2000]
                    parts.append(f"[{role_label}] {content}")
        return "\n\n".join(parts) if parts else "（无对话内容）"

    def _save_summary(self, summary_text: str, current_id: str, target_ids: list[str],
                      to_archive: bool, category: str = ""):
        meta_key = "compressed_summary"
        session = self.sdb.fetchone("SELECT metadata FROM llm_sessions WHERE id = ?", (current_id,))
        if session:
            meta = json.loads(session["metadata"]) if session["metadata"] else {}
            meta[meta_key] = summary_text
            now = __import__("datetime").datetime.now().isoformat()
            self.sdb.execute("UPDATE llm_sessions SET metadata = ?, updated_at = ? WHERE id = ?",
                             (json.dumps(meta, ensure_ascii=False), now, current_id))
        if to_archive:
            archive_id = f"arch_{_make_message_id()}"
            project_row = self.sdb.fetchone("SELECT project_id FROM llm_sessions WHERE id = ?",
                                            (target_ids[0] if target_ids else current_id,))
            pid = project_row["project_id"] if project_row else ""
            self.sdb.execute(
                "INSERT INTO chat_archives (id, session_id, project_id, title, content, category, tags, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (archive_id, target_ids[0] if target_ids else current_id, pid, "会话摘要",
                 summary_text, category or "compress", ",".join(target_ids or [current_id]), "auto_compress"),
            )

    async def execute(self, content: str, current_session_id: str) -> str:
        args = self.parse_args(content)
        target_ids = args["target_ids"] or [current_session_id]
        conversation_text = self._load_messages(target_ids)
        summary = await self._llm_compress(conversation_text)
        self._save_summary(summary, current_session_id, target_ids, args["save"], args["category"])
        return summary

    async def _llm_compress(self, text: str) -> str:
        try:
            import aiohttp
            model_id = _resolve_default_model_id()
            configs = _sdb().fetchall("SELECT model_id, api_base, api_key, model_name, extra_config FROM model_configs")
            cfg = next((c for c in configs if c["model_id"] == model_id), None)
            if not cfg:
                cfg = configs[0] if configs else None
            if not cfg:
                return "（无可用模型）"
            base_url = (cfg["api_base"] or "").rstrip("/")
            api_key = cfg.get("api_key") or "sk-no-key"
            model_name = cfg.get("model_name") or model_id
            payload = {"model": model_name,
                       "messages": [{"role": "user", "content": self.PROMPT_TEMPLATE.format(text=text[:40000])}],
                       "stream": False, "max_tokens": 1000}
            extra_raw = cfg.get("extra_config")
            if extra_raw and isinstance(extra_raw, str):
                try:
                    extra = json.loads(extra_raw)
                    if isinstance(extra, dict):
                        payload.update(extra)
                except (json.JSONDecodeError, TypeError):
                    pass
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            async with aiohttp.ClientSession() as sess:
                async with sess.post(f"{base_url}/v1/chat/completions", json=payload, headers=headers, timeout=30) as resp:
                    data = await resp.json()
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")[:2000]
        except Exception as e:
            logger.info(f"[compress] LLM call failed: {e}")
        return "（压缩失败）"
