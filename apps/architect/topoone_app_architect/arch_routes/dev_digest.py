"""开发简报(P4) —— SE 流程的「汇总面」。

数据流: 会话摘要单元 + 执行回执单元 + 备案文档 + 落地执行(分支/提交)
        → LLM 结构化总结 → dev_digest 备案文档(带 refs 图文深链)。
用途: 项目概览驾驶舱；用户高效全面了解开发走向。

refs.entries 结构: [{type(exec|session|doc), execId, conversationId, title,
                     branch, commit, landedAt}] —— 前端据此渲染深链
(会话→会话中心 select；执行资产变化→基线管理 merge 视图)。
"""
import logging
import time
from typing import Optional

from fastapi import APIRouter, Request

from ..common import _ts, ok, err
from .. import store

logger = logging.getLogger(__name__)

router = APIRouter()

_DIGEST_SCHEMA = {
    "type": "object",
    "properties": {
        "overviewMd": {"type": "string", "description": "3-5 行本期开发走向概览(markdown)"},
        "entriesMd": {"type": "string", "description": "按重要性排列的迭代条目列表(markdown 列表项)"},
        "attentionMd": {"type": "string", "description": "建议关注的风险/待办(无则空串)"},
    },
    "required": ["overviewMd", "entriesMd"],
}


def _collect(project_id: str, since_ms: int) -> dict:
    """采集时间窗内的简报素材(项目库路由按当前项目)。"""
    landed = []

    sessions = []
    for c in store.ConversationsStore.all(limit=200):
        ts = c.get("updatedAt") or 0
        if ts < since_ms:
            continue
        if not ((c.get("summary") or "").strip() or (c.get("reqId") or "")):
            continue
        sessions.append(c)
    sessions.sort(key=lambda c: c.get("updatedAt") or 0, reverse=True)

    docs = [d for d in store.DocsStore.all(limit=100)
            if (d.get("updatedAt") or 0) >= since_ms]
    docs.sort(key=lambda d: d.get("updatedAt") or 0, reverse=True)
    return {"landed": landed, "sessions": sessions, "docs": docs}


def _entries_refs(collected: dict) -> list:
    """结构化条目(refs 图文深链数据源)。"""
    out = []
    for e in collected["landed"][:20]:
        out.append({"type": "exec", "execId": e.get("id") or "",
                    "conversationId": e.get("conversationId") or "",
                    "title": e.get("title") or e.get("id") or "",
                    "branch": e.get("taskBranch") or "",
                    "commit": (e.get("branchCommit") or "")[:12],
                    "landedAt": e.get("branchLandedAt") or 0})
    for c in collected["sessions"][:20]:
        out.append({"type": "session", "conversationId": c.get("id") or "",
                    "title": c.get("title") or "", "summary": (c.get("summary") or "")[:160],
                    "landedAt": c.get("updatedAt") or 0})
    for d in collected["docs"][:10]:
        out.append({"type": "doc", "title": d.get("title") or "",
                    "conversationId": d.get("conversationId") or "",
                    "docId": d.get("id") or "", "landedAt": d.get("updatedAt") or 0})
    return out


def _material_md(collected: dict) -> str:
    lines = []
    for e in collected["landed"][:15]:
        lines.append(f"- [已落地] {e.get('title') or e.get('id')} · 分支 {e.get('taskBranch')} "
                     f"@ {(e.get('branchCommit') or '')[:10]} · 提交于 "
                     f"{time.strftime('%m-%d %H:%M', time.localtime((e.get('branchLandedAt') or 0) / 1000))}")
    for c in collected["sessions"][:15]:
        lines.append(f"- [会话] {c.get('title')}: {(c.get('summary') or '(无摘要)')[:120]}")
    for d in collected["docs"][:8]:
        lines.append(f"- [备案] {d.get('title')} ({d.get('type')})")
    return "\n".join(lines)


@router.post("/digest")
async def generate_digest(request: Request):
    """生成开发简报(时间窗内素材 → LLM 总结 → dev_digest 文档)。降级: 素材直排。"""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}
    project_id = (body.get("projectId") or "").strip()
    since_days = min(max(int(body.get("sinceDays") or 7), 1), 180)
    since_ms = _ts() - since_days * 86400000

    collected = _collect(project_id, since_ms)
    material = _material_md(collected)
    if not material:
        return err(400, f"近 {since_days} 天无可用素材(会话摘要/落地执行/备案文档)")

    overview_md, entries_md, attention_md = "", "", ""
    from ..agent.reflection.repair import summarize_task
    out = summarize_task(
        task_id="dev_digest",
        system="你是项目开发简报助手。基于素材总结本期开发走向：概览 3-5 行；"
               "迭代条目按重要性排列并保留分支/提交信息；指出风险与待办。"
               "忠实素材，不虚构。",
        material=f"时间窗: 近 {since_days} 天\n\n素材:\n{material[:20000]}",
        mode="structured", output_schema=_DIGEST_SCHEMA, max_tokens=2048,
        parse=lambda r: r.get("output") if isinstance(r.get("output"), dict) else None)
    if out["ok"] and isinstance(out["output"], dict):
        o = out["output"]
        overview_md = str(o.get("overviewMd") or "").strip()
        entries_md = str(o.get("entriesMd") or "").strip()
        attention_md = str(o.get("attentionMd") or "").strip()
    if not entries_md:
        overview_md = overview_md or f"近 {since_days} 天开发活动汇总(自动降级直排)。"
        entries_md = material
        attention_md = attention_md or "(LLM 不可达，未生成建议关注)"

    content = "\n\n".join([
        f"# 开发简报 · 近 {since_days} 天",
        overview_md,
        "## 迭代条目",
        entries_md,
        (f"## 建议关注\n{attention_md}" if attention_md else ""),
    ]).strip() + "\n"
    doc = store.DocsStore.create({
        "projectId": project_id,
        "conversationId": "",
        "type": "dev_digest",
        "title": f"开发简报 {time.strftime('%Y-%m-%d')}(近{since_days}天)",
        "contentMd": content,
        "refs": {
            "entries": _entries_refs(collected),
            "sinceDays": since_days,
            "generatedAt": _ts(),
        },
    })
    return ok(doc)


@router.get("/digest")
async def list_digests(limit: int = 10):
    docs = store.DocsStore.all(type_="dev_digest", limit=limit)
    return ok([{
        "id": d["id"], "title": d.get("title") or "",
        "contentMd": d.get("contentMd") or "",
        "refs": d.get("refs") or {},
        "createdAt": d.get("createdAt"), "updatedAt": d.get("updatedAt"),
    } for d in docs])


