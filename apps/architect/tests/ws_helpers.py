"""WS 收发助手(规范化环节六) — 会话流测试公共收发序列单源。"""
from __future__ import annotations


def recv_until(ws, *types):
    """收帧直到命中给定类型之一; 返回 (事件, 已见类型序列)。"""
    seen = []
    while True:
        ev = ws.receive_json()
        seen.append(ev["type"])
        if ev["type"] in types:
            return ev, seen


def chat(ws, content, conv_id=None, *, messages=None, **extra):
    """发送 chat 消息。messages=完整消息数组(新契约) 或 缺省 content 快捷式。"""
    payload = {"type": "chat", "content": content, **extra}
    if messages is not None:
        payload["messages"] = messages
    if conv_id:
        payload["conversationId"] = conv_id
    ws.send_json(payload)
    return payload
