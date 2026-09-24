"""备案文档(会话派生总结性文档, M2 自 sessions.py 机械迁出, 行为等价)。

路由/URL 不变(/sessions/{id}/outline, /session-docs*)——独立 APIRouter,
由 arch_routes/__init__ 与 sessions.router 一并挂载。
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from ..common import ok, err
from .. import store

router = APIRouter()


@router.get("/sessions/{conv_id}/outline")
async def session_outline(conv_id: str):
    """会话大纲(K3, 拍板: 回合对颗粒度): user/assistant 回合对 fold + 回执卡单独标注。

    dsh session-turn-outline 同构: prompt 预览 50 字/response 预览 120 字,
    锚点=回合首条消息 id(前端滚动定位)。纯只读投影, 零协议变更。
    """
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    msgs = store.ConversationsStore.messages(conv_id, limit=1000)
    turns: list = []
    cards: list = []
    cur: dict | None = None
    for m in msgs:
        meta = m.get("meta") or {}
        kind = meta.get("kind")
        if kind:
            cards.append({"id": m.get("id") or "", "kind": kind,
                          "ts": m.get("time") or 0,
                          "preview": (m.get("content") or "").strip().replace("\n", " ")[:60]})
            if cur:
                cur["msgCount"] += 1
            continue
        role = m.get("role")
        content = (m.get("content") or "").strip().replace("\n", " ")
        if role == "user":
            cur = {"id": m.get("id") or "", "ts": m.get("time") or 0,
                   "prompt": content[:50], "response": "", "msgCount": 1}
            turns.append(cur)
        elif role == "assistant":
            if cur is None:
                cur = {"id": m.get("id") or "", "ts": m.get("time") or 0,
                       "prompt": "(无提示)", "response": "", "msgCount": 0}
                turns.append(cur)
            if not cur["response"]:
                cur["response"] = content[:120]
            cur["msgCount"] += 1
    return ok({"turns": turns, "cards": cards, "count": len(turns)})


@router.post("/sessions/outline/abbreviate")
async def outline_abbreviate(request: Request):
    """会话大纲条目标题语义缩略(K3 浮窗): 批量用户输入 → ≤16 字语义短标题。

    纯按需计算不落库——缩略结果由前端 LS 缓存(随会话/消息删除清理)。
    LLM 未配置/失败 → 降级为截断(short=text[:16]), 条目标注 degraded=true,
    响应级 degraded=任一条降级。
    """
    data = await request.json()
    items = data.get("items")
    if not isinstance(items, list):
        return err(400, "items 非法")
    items = items[:20]
    out: list = []
    degraded_any = False
    for it in items:
        if not isinstance(it, dict):
            continue
        iid = str(it.get("id") or "")
        text = str(it.get("text") or "").strip().replace("\n", " ")
        short, deg = text[:16], True
        if text:
            try:
                from ..agent.reflection.repair import summarize_task
                from .agent_roles import load_light_tasks_cfg
                from ..agent.governance.light_tasks import resolve_light_task_model
                r = summarize_task(
                    task_id="outline_abbrev",
                    system="你是会话大纲助手。把用户输入缩略为不超过16字的语义短标题，"
                           "保留关键名词与意图，只输出短标题本身。",
                    material=text[:160],
                    max_tokens=64,
                    model_id=resolve_light_task_model("summary", load_light_tasks_cfg()),
                )
                s = ""
                if r.get("ok") and r.get("output"):
                    s = str(r["output"]).strip().splitlines()[0] if str(r["output"]).strip() else ""
                if s:
                    short, deg = s[:24], False
            except Exception:  # noqa: BLE001 —— 模型未配置/网络失败等一律截断降级
                pass
        degraded_any = degraded_any or deg
        out.append({"id": iid, "short": short, "degraded": deg})
    return ok({"items": out, "degraded": degraded_any})


def _doc_outline(md: str, limit: int = 20) -> list:
    """文档 H2 大纲(C 顺带): fence 感知(代码块内 ## 不计)。"""
    out: list = []
    in_fence = False
    for ln in (md or "").splitlines():
        s = ln.strip()
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or not s.startswith("## "):
            continue
        text = s[3:].strip()
        if text:
            out.append({"text": text[:40]})
            if len(out) >= limit:
                break
    return out


@router.get("/session-docs")
async def list_docs(conversation_id: str = "", type: str = "", limit: int = 200):
    docs = store.DocsStore.all(
        conversation_id=conversation_id or None, type_=type or None, limit=limit)
    # K3-C 顺带: 文档内 H2 大纲(目录树)
    for d in docs:
        d["outline"] = _doc_outline(d.get("contentMd") or "")
    return ok(docs)


@router.post("/session-docs")
async def create_doc(request: Request):
    data = await request.json()
    conv_id = (data.get("conversationId") or "").strip()
    if conv_id and not store.ConversationsStore.get(conv_id):
        return err(404, "来源会话不存在")
    doc = store.DocsStore.create({
        "projectId": data.get("projectId") or "",
        "conversationId": conv_id,
        "type": data.get("type") or "requirement_summary",
        "title": data.get("title") or "",
        "contentMd": data.get("contentMd") or "",
        "refs": data.get("refs") or {},
    })
    return ok(doc)


@router.get("/session-docs/{doc_id}")
async def get_doc(doc_id: str):
    doc = store.DocsStore.get(doc_id)
    if not doc:
        return err(404, "文档不存在")
    return ok(doc)


@router.patch("/session-docs/{doc_id}")
async def update_doc(doc_id: str, request: Request):
    doc = store.DocsStore.get(doc_id)
    if not doc:
        return err(404, "文档不存在")
    data = await request.json()
    patch = {}
    if "title" in data:
        patch["title"] = str(data.get("title") or "").strip()
    if "contentMd" in data:
        patch["contentMd"] = str(data.get("contentMd") or "")
    if "refs" in data and isinstance(data.get("refs"), dict):
        patch["refs"] = data["refs"]
    if not patch:
        return err(400, "无可更新字段")
    return ok(store.DocsStore.update(doc_id, patch))


@router.delete("/session-docs/{doc_id}")
async def delete_doc(doc_id: str):
    if not store.DocsStore.get(doc_id):
        return err(404, "文档不存在")
    store.DocsStore.delete(doc_id)
    return ok({"deleted": True, "id": doc_id})


_DOC_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "contentMd": {"type": "string", "description": "Markdown 格式的需求/方案总结文档"},
    },
    "required": ["title", "contentMd"],
}


@router.post("/session-docs/from-conversation/{conv_id}")
async def doc_from_conversation(conv_id: str, request: Request):
    """从会话提取备案文档(裁决2): LLM 总结需求/方案, 降级为对话原文拼接。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    data = {}
    try:
        data = await request.json()
    except Exception:
        data = {}
    title_hint = (data.get("title") or "").strip()
    msgs = store.ConversationsStore.messages(conv_id, limit=200)
    transcript = "\n".join(
        f"[{'用户' if m.get('role') == 'user' else '助手'}] {(m.get('content') or '').strip()[:1200]}"
        for m in msgs if (m.get("content") or "").strip()
    )
    if not transcript:
        return err(400, "会话无消息, 无法提取")
    title, content = "", ""
    from ..agent.reflection.repair import summarize_task
    out = summarize_task(
        task_id="doc_from_conversation",
        system="你是需求归档助手。把对话中的需求与方案讨论整理为一份备案文档"
               "(Markdown: ## 需求 / ## 方案 / ## 待办 三段), 忠实于对话内容, 不新增结论。",
        material=f"对话记录:\n{transcript[:24000]}",
        mode="structured", output_schema=_DOC_SCHEMA, max_tokens=2048,
        parse=lambda r: r.get("output") if isinstance(r.get("output"), dict) else None)
    if out["ok"]:
        title = str((out["output"] or {}).get("title") or "").strip()[:80]
        content = str((out["output"] or {}).get("contentMd") or "").strip()
    if not content:
        title = title_hint or (conv.get("title") or "会话备案")
        content = f"# {title}\n\n(自动提取降级: 对话原文)\n\n{transcript[:12000]}"
    doc = store.DocsStore.create({
        "projectId": conv.get("projectId") or "",
        "conversationId": conv_id,
        "type": data.get("type") or "requirement_summary",
        "title": title_hint or title,
        "contentMd": content,
        "refs": data.get("refs") or {},
    })
    return ok(doc)
