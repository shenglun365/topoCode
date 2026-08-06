"""Coding-agent session REST routes (sqlite-backed).

契约见 docs/architect/api-execution.md §5(WS) 与 execution.md §4.4。
REST 只做查询与会话持久化读取；执行/对话走 WS(/ws/coding-agent)。

适配器清单与联通性**对接真实 agent 接口**：复用 `plugins.installer.targets`
(AgentTarget 注册表)逐一 `detect()`，已安装(=检测到配置)即为连通，不再返回模拟数据。
"""
from fastapi import APIRouter
from .common import ok, err
from . import store

router = APIRouter()


def _targets():
    """懒加载 installer targets 注册表；不可导入时回退到内置清单(避免拖垮 /overview)。"""
    try:
        from plugins.installer.targets import TARGETS
        return TARGETS
    except Exception:
        return {}


_FALLBACK_ADAPTERS = [
    {"id": "claude", "name": "Claude Code", "desc": "Claude Code CLI"},
    {"id": "opencode", "name": "OpenCode", "desc": "OpenCode CLI"},
    {"id": "codex", "name": "OpenAI Codex", "desc": "OpenAI Codex CLI"},
    {"id": "cursor", "name": "Cursor", "desc": "Cursor"},
    {"id": "copilot", "name": "GitHub Copilot", "desc": "GitHub Copilot CLI"},
    {"id": "gemini", "name": "Gemini CLI", "desc": "Gemini CLI"},
    {"id": "windsurf", "name": "Windsurf", "desc": "Windsurf"},
]

_DESC = {
    "claude": "Claude Code CLI",
    "opencode": "OpenCode CLI",
    "codex": "OpenAI Codex CLI",
    "cursor": "Cursor",
    "copilot": "GitHub Copilot CLI",
    "gemini": "Gemini CLI",
    "windsurf": "Windsurf",
}


def list_adapter_adapters() -> list:
    """全部已知 coding agent 适配器(真实来源: installer targets 注册表；回退内置清单)。"""
    targets = _targets()
    if targets:
        return [
            {"id": tid, "name": t.name, "desc": _DESC.get(tid, t.name)}
            for tid, t in targets.items()
        ]
    return [dict(a) for a in _FALLBACK_ADAPTERS]


def adapter_connectivity(adapter_id: str) -> str:
    """真实探测：目标已检测到配置(已安装) → ok；否则 fail。"""
    t = _targets().get(adapter_id)
    if t is None:
        return "fail"
    return "ok" if t.detect() else "fail"


def list_adapter_connectivity() -> list:
    """每个适配器附连通性状态的完整列表(overview 聚合用，真实探测)。"""
    return [{**a, "conn": adapter_connectivity(a["id"])} for a in list_adapter_adapters()]


def _with_messages(session_id: str):
    session = store.AgentSessionsStore.get(session_id)
    if not session:
        return None
    session["messages"] = store.AgentSessionsStore.messages(session_id)
    return session


@router.get("/agent/adapters")
async def list_adapters():
    """全部已知 coding agent 适配器(真实来源: installer targets 注册表)。"""
    return ok(list_adapter_adapters())


@router.get("/agent/adapters/{adapter_id}/connectivity")
async def check_adapter_connectivity(adapter_id: str):
    """真实连通性探测：目标 detect()(检测到配置=已安装)。"""
    return ok({"adapter": adapter_id, "status": adapter_connectivity(adapter_id)})


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
