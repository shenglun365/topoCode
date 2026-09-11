"""agent-bus 桥接路由(P3.3)：architect 侧与 broker 的交互入口。

- `POST /bus/publish`：向 broker 发布消息(前端 / coding subagent 经 SE context 指引调用)；
- `GET  /bus/needs-input`：「需要你输入(N)」汇总——blocked/accepting 执行任务 +
  未回复的 interaction.clarify(经主库 arch_bus_messages 直读，broker 共享同库)；
- `POST /requirements/{req_id}/injection`：把 subagent/用户消息注入需求会话
  (plan agent 下一回合可见)；broker 将 dst=plan 的消息路由到此。
"""
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store

router = APIRouter()


@router.post("/bus/publish")
async def bus_publish(request: Request):
    """代理发布到 broker。body: {src, dst, topic, payload}。broker 不可达 → code 503。"""
    from .bus_client import get_bus
    body = await request.json()
    topic = (body.get("topic") or "").strip()
    if not topic:
        return err(400, "topic required")
    data = get_bus().publish(
        body.get("src") or "", body.get("dst") or "", topic,
        body.get("payload") or {})
    if data is None:
        return err(503, "agent-bus broker 不可达")
    return ok(data)


@router.get("/bus/needs-input")
async def bus_needs_input():
    """需要你输入(N)：未回复的 clarify 提问。"""
    clarifies = store.AgentBusStore.list(topic="interaction.clarify",
                                         status="delivered", limit=200)
    answers = store.AgentBusStore.list(topic="interaction.answer",
                                       status="delivered", limit=200)
    answered = {(a.get("payload") or {}).get("replyTo")
                for a in answers if (a.get("payload") or {}).get("replyTo")}
    pending = [c for c in clarifies if c.get("id") not in answered]
    items = [
        {
            "type": "clarify", "id": c["id"],
            "reqId": (c.get("payload") or {}).get("reqId") or "",
            "src": c.get("src") or "",
            "label": ((c.get("payload") or {}).get("message") or "")[:120],
            "status": "clarify",
        } for c in pending
    ]
    return ok({"count": len(items), "items": items})


@router.post("/requirements/{req_id}/injection")
async def requirement_injection(req_id: str, request: Request):
    """把消息注入需求最新会话(role=assistant，带来源前缀)。

    plan agent 下一回合随历史可见；前端重载会话时渲染。
    body: {message, src?, topic?}。
    """
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "需求不存在")
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        return err(400, "message required")
    src = (body.get("src") or "").strip()
    topic = (body.get("topic") or "").strip()
    tag = {"coding": "执行 subagent", "runner": "执行 subagent",
           "plan": "plan agent", "user": "用户", "mcp": "外部 subagent"}.get(src, src or "subagent")
    convs = store.ConversationsStore.by_req(req_id)
    # PR 复查: 归档会话只读——subagent 消息注入优先非归档会话
    conv = next((c for c in convs if (c.get("status") or "active") != "archived"), None)
    conv_id = conv["id"] if conv else ""
    if not conv_id:
        conv = store.ConversationsStore.create({
            "kind": "requirement", "projectId": "", "reqId": req_id,
            "title": row.get("title") or req_id, "status": "active",
            "meta": {"title": row.get("title") or req_id},
        })
        conv_id = conv["id"]
    msg_id = store.next_id("m")
    store.ConversationsStore.append_message({
        "id": msg_id, "conversationId": conv_id,
        "role": "assistant", "time": _ts(),
        "content": f"[{tag}]" + (f" · {topic}" if topic else "") + f"\n{message}",
    })
    return ok({"conversationId": conv_id, "messageId": msg_id})
