"""Coding-agent session REST routes (sqlite-backed)。

契约见 docs/architect/api-execution.md §5(WS) 与 execution.md §4.4。
REST 只做会话查询与持久化读取；对话走 WS(/ws/coding-agent, A7 起经 tAgent)。

注：coding agent 适配器清单/连通性(原 /agent/adapters 等)已随 A7 移除——
执行走 runner、对话走 tAgent，不再需要三方 agent 连接池(agent_server/agent_adapters)。
"""
from fastapi import APIRouter
from .common import ok, err
from . import store

router = APIRouter()


def _with_messages(session_id: str):
    session = store.AgentSessionsStore.get(session_id)
    if not session:
        return None
    session["messages"] = store.AgentSessionsStore.messages(session_id)
    return session


@router.get("/agent/sessions")
async def list_sessions():
    return ok(store.AgentSessionsStore.all())


@router.get("/agent/sessions/{session_id}")
async def get_session(session_id: str):
    session = _with_messages(session_id)
    if not session:
        return err(404, "Session not found")
    return ok(session)


@router.delete("/agent/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话(含消息)。"""
    deleted = store.AgentSessionsStore.delete(session_id)
    if not deleted:
        return err(404, "Session not found")
    return ok({"deleted": session_id})


@router.get("/agent/sessions/{session_id}/messages")
async def get_session_messages(session_id: str):
    msgs = store.AgentSessionsStore.messages(session_id)
    return ok(msgs)


@router.get("/agent/tool-audit")
async def tool_audit(project: str = "", tool: str = "", failed: int = -1,
                     limit: int = 200):
    """工具调用审计流水(WS6-E 落库查询面)。"""
    from .store.base import _db
    conds, params = ["1=1"], []
    if project:
        conds.append("project_id = ?")
        params.append(project)
    if tool:
        conds.append("tool = ?")
        params.append(tool)
    if failed == 1:
        conds.append("ok = 0")
    elif failed == 0:
        conds.append("ok = 1")
    rows = _db().fetchall(
        f"SELECT * FROM arch_tool_audit WHERE {' AND '.join(conds)} "
        f"ORDER BY ts DESC LIMIT ?",
        tuple(params + [max(1, min(int(limit), 1000))]))
    return {"code": 0, "message": "ok", "data": [
        {"ts": r["ts"], "tool": r["tool"], "ok": bool(r["ok"]),
         "argsDigest": r["args_digest"], "resultDigest": r["result_digest"],
         "conversationId": r["conversation_id"], "reqId": r["req_id"],
         "projectId": r["project_id"], "modelId": r["model_id"],
         "latencyMs": r["latency_ms"]} for r in rows]}
