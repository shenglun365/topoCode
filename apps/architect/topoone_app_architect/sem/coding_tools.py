"""主 agent 子会话通讯工具(内部接口注册面)——coding.sessions / coding.feed。

定位(2610 子会话模型裁决): 主会话→多子会话(独立上下文), 每个子会话各绑
执行器。主 agent 在对话中可查询/投递执行器子会话——
- coding.sessions  列主会话的子会话池(活跃标记/执行器/消息数/运行态);
- coding.feed      向活跃子会话投递文本(内部复用 /feed 链路: 落活跃任务
  task_input 或排队 + 落子会话消息流审计)。

均为内部函数调用(不暴露 MCP)——消费方=主 agent 工具循环。
"""
from __future__ import annotations

from typing import Optional


def _conv_of(conv_id: str) -> dict:
    from ..store.conv import ConversationsStore
    return ConversationsStore.get(conv_id) or {}


def _meta_of(conv: dict) -> dict:
    import json
    raw = conv.get("meta") or ""
    try:
        m = json.loads(raw) if isinstance(raw, str) else (raw or {})
        return m if isinstance(m, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def tool_coding_sessions(conv_id: str = "") -> dict:
    """列主会话的 coding 子会话池。conv_id 空=当前活跃会话。"""
    from ..store.conv import ConversationsStore
    conv = _conv_of(conv_id) if conv_id else {}
    if not conv:
        return {"ok": False, "error": "会话不存在或未指定 conversation"}
    subs = ConversationsStore.by_parent(conv["id"])
    active = (_meta_of(conv).get("activeCodingSession") or "")
    out = [{"id": s["id"], "title": s.get("title") or "",
            "executorId": s.get("executorId") or "",
            "active": s["id"] == active,
            "status": s.get("status") or "active",
            "msgCount": s.get("msgCount") or 0,
            "sessionRef": bool(s.get("sessionRef")),
            "updatedAt": s.get("updatedAt")}
           for s in subs]
    return {"ok": True, "conversationId": conv["id"],
            "activeSub": active, "sessions": out}


def tool_coding_feed(conv_id: str = "", text: str = "") -> dict:
    """向活跃 coding 子会话投递文本(内部转发 /feed 链路)。"""
    if not (text or "").strip():
        return {"ok": False, "error": "text 必填"}
    conv = _conv_of(conv_id) if conv_id else {}
    if not conv:
        return {"ok": False, "error": "会话不存在或未指定 conversation"}
    # 复用 REST 投喂门逻辑(async): 事件循环内直接 await 不可行(工具同步调用)
    # → 独立事件循环执行 handler
    import asyncio
    from ..arch_routes.sessions import feed_to_coding

    class _Req:
        async def json(self):
            return {"text": text}

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            res = ex.submit(asyncio.run,
                            feed_to_coding(conv["id"], _Req())).result(timeout=60)
    else:
        res = asyncio.run(feed_to_coding(conv["id"], _Req()))
    data = res.get("data") if isinstance(res, dict) else None
    return {"ok": True, "result": data}


def run_coding_tool(name: str, args: dict) -> str:
    import json
    if name == "coding.sessions":
        out = tool_coding_sessions(str(args.get("conversation") or ""))
    elif name == "coding.feed":
        out = tool_coding_feed(str(args.get("conversation") or ""),
                               str(args.get("text") or ""))
    else:
        out = {"ok": False, "error": f"未知工具: {name}"}
    return json.dumps(out, ensure_ascii=False)
