"""Coding-agent session REST routes (sqlite-backed).

契约见 docs/architect/api-execution.md §5(WS) 与 execution.md §4.4。
REST 只做查询与会话持久化读取；执行/对话走 WS(/ws/coding-agent)。

适配器清单来自 `agent_adapters` 注册表(当前仅 opencode)。opencode 的「已安装/适配」
验证为**本机真实探测**：可执行文件存在 + `opencode --version` 可运行 + 全局配置文件存在。
"""
from fastapi import APIRouter
from .common import ok, err
from . import store
from . import agent_adapters

router = APIRouter()

OPENCODE_ID = "opencode"

# 适配器清单由注册表提供(当前仅 opencode)。
_DESC = {"opencode": "OpenCode CLI(server 模式)"}


# ── 适配器清单/连通性(注册表驱动) ──────────────────────────────

def list_adapter_adapters() -> list:
    """当前注册的 coding agent 适配器(经 AgentAdapter 注册表)。"""
    return [dict(a) for a in agent_adapters.list_adapters()]


def adapter_connectivity(adapter_id: str) -> str:
    """adapter 真实安装/适配验证 → ok|partial|fail。未知 adapter 一律 fail。"""
    impl = agent_adapters.get_agent(adapter_id)
    if impl is None:
        return "fail"
    return impl.env_check()["status"]


def list_adapter_connectivity() -> list:
    """每个注册适配器附连通性状态的完整列表(overview 聚合用，真实探测)。"""
    out = []
    for a in list_adapter_adapters():
        item = dict(a)
        item["conn"] = adapter_connectivity(item["id"])
        impl = agent_adapters.get_agent(item["id"])
        if impl is not None:
            item["env"] = impl.env_check()
        out.append(item)
    return out


def _with_messages(session_id: str):
    session = store.AgentSessionsStore.get(session_id)
    if not session:
        return None
    session["messages"] = store.AgentSessionsStore.messages(session_id)
    return session


@router.get("/agent/adapters")
async def list_adapters():
    """当前已适配的 coding agent 适配器(当前仅 opencode)。"""
    return ok(list_adapter_adapters())


@router.get("/agent/opencode/env")
async def get_opencode_env():
    """opencode 本机安装/适配验证(可执行 + 版本 + 配置)。"""
    impl = agent_adapters.get_agent("opencode")
    return ok(impl.env_check() if impl else {"status": "fail", "detail": "opencode adapter 未注册"})


@router.get("/agent/adapters/{adapter_id}/connectivity")
async def check_adapter_connectivity(adapter_id: str):
    """真实连通性探测：opencode 的安装/适配验证；其余适配器 fail。"""
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
