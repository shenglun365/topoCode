"""会话闸门(感知层) — WS 对话回合的会话绑定/校验/自愈。

P2 自 websocket._handle_kb_chat 前段迁入:
  - 请求级上下文绑定(项目库路由/需求/会话)
  - 会话存在性: 无 conv_id → 新建; 陈旧 conv_id(库漂移) → 自愈新建零丢失
  - 归档只读闸(拒绝并给出 error 事件载荷)
  - 会话↔需求绑定回填 + 兜底(刷新后前端 reqId 丢失仍可 NL 确认)

降级纪律: 自愈路径绝不报 "conversation not found" 后中断——历史消息全量在
payload.messages, 新建会话零丢失, done 事件回传新 id 前端自动跟进。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SessionBinding:
    """一次对话回合的会话绑定结果。"""
    conv_id: str
    conv: dict
    user_message_id: str = ""
    created: bool = False                    # 本回合新建(含自愈)
    error_event: Optional[dict] = field(default=None)  # 非空=闸门拒绝(归档), 回合终止


def bind_session(data: dict, store, ctx, next_id) -> SessionBinding:
    """解析/创建会话并绑定请求级上下文。error_event 非空时调用方直接回错误。

    store/ctx: arch_routes.store / arch_routes.ctx (参数注入避免包级循环)。
    """
    conv_id = data.get("conversationId") or ""
    conv = None
    created = False
    if not conv_id:
        conv = store.ConversationsStore.create({
            "kind": data.get("kind") or "chat",
            "projectId": data.get("project") or "",
            "reqId": data.get("reqId") or "",
            "title": data.get("title") or "",
            "status": "active", "meta": {"title": data.get("title") or ""},
        })
        conv_id = conv["id"]
        created = True
    else:
        conv = store.ConversationsStore.get(conv_id)
        if conv and (conv.get("status") or "active") == "archived":
            # PR1: 归档会话只读——拒绝继续对话(读取/复制/提炼经 REST 与只读工具仍开放)
            return SessionBinding(
                conv_id=conv_id, conv=conv,
                error_event={"type": "error", "requestId": data.get("requestId") or "",
                             "message": "会话已归档(只读)：不可继续对话。可复制到新会话或提炼引用。"})
        # 会话↔需求绑定回填：提案卡产生后前端 send 会带 reqId——补写进会话记录,
        # 刷新/重开会话后 openConversation 携带 meta.reqId, 自然语言确认仍可用
        if conv and (data.get("reqId") or "") and not (conv.get("reqId") or ""):
            try:
                conv = store.ConversationsStore.update(conv_id, {"reqId": data["reqId"]})
            except Exception:  # noqa: BLE001
                pass
        if not conv:
            # 自愈降级：浏览器 tab 内存里保留的 chatConvId 可能指向已不存在的会话
            # (服务重启/数据目录迁移/多实例并存导致库漂移)。历史消息全量在
            # payload.messages, 新建会话零丢失; done 事件回传新 conv_id 前端自动跟进。
            conv = store.ConversationsStore.create({
                "kind": data.get("kind") or "chat",
                "projectId": data.get("project") or "",
                "reqId": data.get("reqId") or "",
                "title": data.get("title") or "",
                "status": "active", "meta": {"title": data.get("title") or ""},
            })
            conv_id = conv["id"]
            created = True
    # 请求级上下文(项目库路由/需求定位/证据链回填)
    try:
        ctx.set_conv(conv_id)
    except Exception:  # noqa: BLE001
        pass
    # 需求绑定兜底: 载荷未带 reqId 时回退会话记录的既有绑定
    try:
        if not (data.get("reqId") or "") and conv and (conv.get("reqId") or ""):
            ctx.set_req(conv["reqId"])
    except Exception:  # noqa: BLE001
        pass
    user_message_id = next_id("m")
    return SessionBinding(conv_id=conv_id, conv=conv,
                          user_message_id=user_message_id, created=created)
