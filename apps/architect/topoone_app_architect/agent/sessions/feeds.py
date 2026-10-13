"""会话投喂域(2610 统一模型)——主会话 feed / 子会话 feed-up 共用交付核心。

交付语义: 文本 → 活跃 v2 任务转达(running/waiting_input) + 活跃 coding
子会话审计落流(feedFrom 溯源)。消息流=上下文真相源, 与执行器无关。

R1 合规: 不引 arch_routes——错误经 FeedError 上抛, 路由层转 err()。
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from ... import store
from ...store import states as ST


class FeedError(Exception):
    """投递失败(路由层转 4xx)。"""


def _ts() -> int:
    return int(time.time() * 1000)


def _meta_of(conv: dict) -> dict:
    meta = conv.get("meta")
    if isinstance(meta, str):
        import json
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            meta = {}
    return meta or {}


def resolve_source_text(conv_id: str, body: dict) -> tuple[str, str]:
    """投喂载荷解析: {messageId} 定向转发 | {text} 直发 → (text, src_msg_id)。

    hint 本地提示不可转发; 空文本拒绝。"""
    text, src_msg_id = "", ""
    if body.get("messageId"):
        m = next((x for x in store.ConversationsStore.messages(conv_id, limit=200)
                  if x.get("id") == body["messageId"]), None)
        if not m:
            raise FeedError("消息不存在")
        if (m.get("meta") or {}).get("kind") == "hint":
            raise FeedError("本地提示消息不可转发")
        text = (m.get("content") or "").strip()
        src_msg_id = m.get("id") or ""
    else:
        text = str(body.get("text") or "").strip()
    if not text:
        raise FeedError("转发内容为空")
    return text, src_msg_id


async def deliver_feed(main_conv: dict, text: str, *, src_conv_id: str,
                       src_msg_id: str, summarized: bool = False) -> dict:
    """投喂交付核心(feed / feed-up 共用): 活跃任务转达 + 活跃子会话审计落流。

    返回 ok() 载荷 dict(delivered/queued/summarized/activeSub/summary)。"""
    from ..execution import exec_bridge
    conv_id = main_conv["id"]
    active_sub = _meta_of(main_conv).get("activeCodingSession") or ""
    delivered, queued, feed_note = False, False, ""
    # P3: 投喂目标 = 活跃 v2 任务(running/waiting_input → task_input 转达/排队)
    task = exec_bridge.active_task_of(conv_id)
    if task and (task.get("status") or "") in ("running", ST.TASK_WAITING_INPUT):
        # 投喂路径自带子会话审计落流 → echo=False 防主流双写(R4 回声)
        res = await asyncio.to_thread(exec_bridge.task_input, task["id"], text,
                                      echo=False)
        if res.get("ok"):
            delivered, queued = True, bool(res.get("queued"))
        else:
            e = str(res.get("error") or "")
            if e not in ("task-not-active", "runner 不可达"):
                raise FeedError(f"投递失败: {e}")

    # 落子会话消息流(审计: 哪些信息进入了 coding 上下文)
    if active_sub:
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": active_sub,
            "role": "user", "time": _ts(), "content": text[:12000],
            "projectId": (main_conv.get("projectId") or ""),
            "meta": {"kind": "feed", "feedFrom": {"convId": src_conv_id,
                                                  "messageId": src_msg_id,
                                                  "at": _ts(),
                                                  "summarized": summarized,
                                                  "delivered": delivered,
                                                  "queued": queued}},
        })
        feed_note = f"；已记录到子会话 {active_sub}"
    else:
        feed_note = "；(无活跃子会话——仅投递作业)"
    summary = ("📥 已排队转达(回合结束自动续跑)" if queued
               else "➡️ 已转达作业" if delivered
               else "已记录(当前无活跃作业——下次 /执行 后生效于新上下文)")
    if summarized:
        summary = "🧠 (摘要) " + summary
    return {"delivered": delivered, "queued": queued, "summarized": summarized,
            "activeSub": active_sub, "summary": summary + feed_note}


async def summarize_if_asked(body: dict, text: str) -> tuple[str, bool]:
    """语境摘要(body.summarize 且有文本)——LLM 压缩(best-effort)。"""
    if body.get("summarize") and text:
        from .coding import _summarize_for_coding
        return await _summarize_for_coding(text)
    return text, False


def feed_up_target(sub_id: str) -> tuple[dict, dict]:
    """feed-up 目标解析: 子会话 → (子会话行, 主会话行); 非子会话/主缺失拒绝。"""
    sub = store.ConversationsStore.get(sub_id)
    if not sub:
        raise FeedError("会话不存在")
    parent_id = (sub.get("parentConvId") or "").strip()
    if not parent_id:
        raise FeedError("非子会话——上投仅限主会话的子会话消息")
    main_conv = store.ConversationsStore.get(parent_id)
    if not main_conv:
        raise FeedError("主会话不存在(可能已删除)")
    return sub, main_conv
