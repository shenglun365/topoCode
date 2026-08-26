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
