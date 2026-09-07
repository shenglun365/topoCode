"""上下文注册表(P2) —— 会话派生单元的写入/检索/提取。

设计对齐(裁决3): 上下文统一 = 每个任务会话执行前可「拉取」关联内容构造完整上下文；
不是把所有内容塞进一个会话。本模块提供:

  写入侧(自动 hook):
    - 对话工具轨迹(tool_call) → 单元(含 req.propose 等产物 artifact 单元)
    - 会话摘要(session_summary) → 单元(POST /sessions/{id}/summarize 时)
    - 执行回执(execution_report) → 单元(执行终态: done/failed/stopped)
    消息本体不复制(存 arch_conversation_messages)，检索时联查——注册表保持轻。

  读取侧(拉取式):
    - ctx.search(query, types, conversation_id) → 跨会话检索单元+消息+备案文档(MD)
    - ctx.get(conversation_id) → 会话上下文包(摘要+单元+文档清单, MD)
    - ctx.summarize(conversation_id) → 生成/刷新会话摘要并返回
  三面暴露: 会话 agent 工具(register_architect_tool) / MCP(map.* 同款 run_tool) / REST。
"""
import json
import logging
from typing import Any, Dict, List, Optional

from . import store
from .common import _ts

logger = logging.getLogger(__name__)

# 会话 agent 可见的能力文档段落(注入 req_agent._CAPABILITY_DOC)
CTX_CAPABILITY_LINES = (
    "- ctx.search：跨会话检索历史上下文(工具轨迹/产物/决策/摘要/执行回执/消息)，"
    "构造答复或任务上下文前先检索关联结论，避免重复讨论\n"
    "- ctx.get：读取指定会话的上下文包(摘要+关键单元+备案文档清单)\n"
    "- ctx.summarize：生成/刷新会话摘要(标题+结论/决策/待办)\n"
)

# MCP 工具描述(asset_map_tools.TOOLS 同形)
TOOLS = [
    {"name": "ctx.search", "desc": "跨会话检索历史上下文(单元+消息+备案文档；返回 Markdown 命中列表)",
     "args": {"query": "关键词", "type": "单元类型(tool_call/artifact/decision/session_summary/execution_report)",
              "conversation": "限定会话 id", "limit": "条数", "project": "项目 id"}},
    {"name": "ctx.get", "desc": "会话上下文包：摘要+关键单元+备案文档(MD)",
     "args": {"conversation": "会话 id", "project": "项目 id"}},
    {"name": "ctx.summarize", "desc": "生成/刷新会话摘要(标题+结论/决策/待办)",
     "args": {"conversation": "会话 id"}},
]

_ARTIFACT_TOOLS = {"req.propose", "contract.propose", "convention.propose"}


# ── 写入侧 ────────────────────────────────────────────────

def _project_of(conv_id: str) -> str:
    conv = store.ConversationsStore.get(conv_id) or {}
    return conv.get("projectId") or ""


def _conv_tags(conv: dict) -> dict:
    tags = conv.get("tags")
    if isinstance(tags, str):
        try:
            tags = json.loads(tags)
        except (TypeError, ValueError):
            tags = None
    if not isinstance(tags, dict):
        tags = {}
    return {"modules": tags.get("modules") or [], "groups": tags.get("groups") or []}


def record_tool_call(conv_id: str, name: str, args: Dict[str, Any],
                     ok: bool, summary: str) -> None:
    """对话中的工具轨迹 → 单元；产物类工具另记 artifact 单元(importance=1)。"""
    if not conv_id:
        return
    try:
        project = _project_of(conv_id)
        store.ContextUnitsStore.create({
            "conversationId": conv_id, "projectId": project,
            "type": "tool_call",
            "title": f"{name}({'ok' if ok else 'error'})",
            "content": f"参数: {json.dumps(args, ensure_ascii=False)[:600]}\n\n结果: {summary[:1200]}",
            "refs": {}, "importance": 0,
        })
        if ok and name in _ARTIFACT_TOOLS:
            store.ContextUnitsStore.create({
                "conversationId": conv_id, "projectId": project,
                "type": "artifact",
                "title": f"产物: {name}",
                "content": summary[:2000],
                "refs": {}, "importance": 1,
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx-registry] 工具单元写入失败: %s", e)


def write_exec_report(task_id: str, status: str) -> None:
    """执行终态 → 执行回执单元(简报素材；refs 带 execIds/reqIds/modules)。"""
    try:
        task = store.ExecutionTasksStore.get(task_id) or {}
        conv_id = task.get("conversationId") or ""
        req_ids = task.get("reqIds") or []
        req_titles = []
        for rid in req_ids[:8]:
            r = store.RequirementsStore.get(rid) or {}
            if r.get("title"):
                req_titles.append(r["title"])
        stats = task.get("stats") or {}
        lines = [
            f"# 执行回执 {task_id}",
            f"- 终态: **{status}**",
            f"- 分支: {task.get('taskBranch') or '-'}",
            f"- 落地提交: {task.get('branchCommit') or '-'}",
            f"- 关联需求: {', '.join(req_titles) or '-'}",
            f"- 会话数: {len(task.get('sessionIds') or [])} · 请求数: {stats.get('requests', 0)}",
        ]
        if task.get("error"):
            lines.append(f"- 错误: {task['error'][:500]}")
        refs = {"execIds": [task_id], "reqIds": list(req_ids)}
        if conv_id:
            conv = store.ConversationsStore.get(conv_id) or {}
            refs["modules"] = _conv_tags(conv).get("modules") or []
        store.ContextUnitsStore.create({
            "conversationId": conv_id,
            "projectId": (_project_of(conv_id) if conv_id else ""),
            "type": "execution_report",
            "title": f"执行回执 {task_id} [{status}]",
            "content": "\n".join(lines),
            "refs": refs, "importance": 1,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx-registry] 执行回执写入失败: %s", e)


_TITLE_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string", "description": "不超过 24 字的会话标题"},
        "summary": {"type": "string", "description": "不超过 120 字的会话摘要(结论/决策/待办)"},
    },
    "required": ["title", "summary"],
}


def summarize_conversation(conv_id: str) -> Optional[dict]:
    """生成/刷新会话标题与摘要 → 落库 + session_summary 单元。返回更新后会话。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return None
    msgs = store.ConversationsStore.messages(conv_id, limit=30)
    transcript = "\n".join(
        f"[{'用户' if m.get('role') == 'user' else '助手'}] {(m.get('content') or '').strip()[:400]}"
        for m in msgs if (m.get("content") or "").strip()
    )
    title, summary = "", ""
    if transcript:
        from . import req_agent
        res = req_agent.llm_sync(
            messages=[
                {"role": "system", "content": "你是会话归档助手。根据对话记录生成简短标题与摘要，只输出结构化结果。"},
                {"role": "user", "content": f"对话记录:\n{transcript[:6000]}"},
            ],
            mode="structured",
            output_schema=_TITLE_SCHEMA,
            max_tokens=512,
        )
        if res and isinstance(res.get("output"), dict):
            title = str(res["output"].get("title") or "").strip()[:48]
            summary = str(res["output"].get("summary") or "").strip()[:400]
    if not title:
        first_user = next((m.get("content") or "" for m in msgs if m.get("role") == "user"), "")
        title = first_user.strip().replace("\n", " ")[:24] or (conv.get("title") or "会话")
    if not summary:
        summary = (conv.get("summary") or "").strip()
    updated = store.ConversationsStore.update(conv_id, {"title": title, "summary": summary})
    # 摘要单元(高优先级；refs 继承会话 tags)
    try:
        tags = _conv_tags(conv)
        store.ContextUnitsStore.create({
            "conversationId": conv_id, "projectId": conv.get("projectId") or "",
            "type": "session_summary",
            "title": f"会话摘要: {title}",
            "content": summary or "(空摘要)",
            "refs": {"modules": tags.get("modules") or []},
            "importance": 1,
        })
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx-registry] 摘要单元写入失败: %s", e)
    return updated or conv


# ── 读取侧(ctx.* → Markdown) ──────────────────────────────

def _fmt_ts(ts) -> str:
    try:
        import time as _t
        return _t.strftime("%m-%d %H:%M", _t.localtime((int(ts) or 0) / 1000))
    except Exception:  # noqa: BLE001
        return "-"


def ctx_search(query: str, type_: str = "", conversation_id: str = "",
               project_id: str = "", limit: int = 20) -> str:
    """跨会话检索单元+消息+备案文档 → Markdown 命中列表(带溯源)。"""
    if not (query or "").strip():
        return "# ctx.search\n\nquery 为空。用法: ctx.search(query=\"支付\")"
    like = f"%{query.strip()}%"
    hits: List[dict] = []

    # 1) 上下文单元
    try:
        for u in store.ContextUnitsStore.search(query.strip(), type_=type_ or None,
                                                conversation_id=conversation_id or None,
                                                project_id=project_id or None,
                                                limit=limit):
            hits.append({"src": "unit", "type": u.get("type"), "title": u.get("title") or "-",
                         "excerpt": (u.get("content") or "")[:200], "conv": u.get("conversationId") or "",
                         "ts": u.get("createdAt"), "importance": u.get("importance") or 0})
    except Exception as e:  # noqa: BLE001
        logger.warning("[ctx.search] units: %s", e)

    # 2) 会话消息(不限定类型；按内容命中)
    if not type_:
        try:
            rows = store.ConversationsStore.summaries(limit=200)
        except Exception:
            rows = []
        for c in rows:
            if conversation_id and c.get("id") != conversation_id:
                continue
            for m in store.ConversationsStore.messages(c.get("id") or "", limit=50):
                content = (m.get("content") or "")
                if query.strip().lower() in content.lower():
                    hits.append({"src": "message", "type": f"消息/{c.get('kind')}",
                                 "title": c.get("title") or "-",
                                 "excerpt": content[:200], "conv": c.get("id"),
                                 "ts": m.get("time"), "importance": 0})
                    if len(hits) >= limit * 2:
                        break
            if len(hits) >= limit * 2:
                break

    # 3) 备案文档
    if not type_:
        try:
            for d in store.DocsStore.all(project_id=project_id or None, limit=100):
                blob = f"{d.get('title') or ''}\n{d.get('contentMd') or ''}"
                if query.strip().lower() in blob.lower():
                    hits.append({"src": "doc", "type": f"备案/{d.get('type')}",
                                 "title": d.get("title") or "-",
                                 "excerpt": (d.get("contentMd") or "")[:200],
                                 "conv": d.get("conversationId") or "",
                                 "ts": d.get("updatedAt"), "importance": 1})
        except Exception as e:  # noqa: BLE001
            logger.warning("[ctx.search] docs: %s", e)

    hits.sort(key=lambda h: (-(h.get("importance") or 0), -(int(h.get("ts") or 0))))
    hits = hits[:limit]
    out = [f"# ctx.search「{query.strip()}」({len(hits)} 命中)", ""]
    if not hits:
        out.append("无命中。")
    for h in hits:
        out.append(f"## [{h['type']}] {h['title']}")
        out.append(f"会话 `{h['conv'] or '-'}` · {_fmt_ts(h.get('ts'))} · 来源 {h['src']}")
        out.append("")
        out.append((h["excerpt"] or "").strip().replace("\n", " ")[:180])
        out.append("")
    return "\n".join(out)


def ctx_get(conversation_id: str) -> str:
    """会话上下文包：基础信息+摘要+关键单元(高优先级在前)+备案文档。"""
    conv = store.ConversationsStore.get(conversation_id)
    if not conv:
        return f"# ctx.get\n\n会话 `{conversation_id}` 不存在。"
    tags = _conv_tags(conv)
    units = store.ContextUnitsStore.all(conversation_id=conversation_id, limit=50)
    units.sort(key=lambda u: (-(u.get("importance") or 0), -(u.get("createdAt") or 0)))
    docs = store.DocsStore.all(conversation_id=conversation_id, limit=20)
    out = [
        f"# 会话上下文包 `{conversation_id}`",
        f"- 标题: {conv.get('title') or '-'} · 类型: {conv.get('kind')} · 状态: {conv.get('status')}",
        f"- 模块: {', '.join(tags['modules']) or '-'} · 分组: {', '.join(tags['groups']) or '-'}",
        "",
        "## 摘要",
        (conv.get("summary") or "(未生成——可 ctx.summarize)").strip(),
        "",
        f"## 关键单元({len(units)})",
    ]
    if not units:
        out.append("(无)")
    for u in units[:15]:
        out.append(f"- **[{u.get('type')}] {u.get('title') or '-'}** · {_fmt_ts(u.get('createdAt'))}")
        body = (u.get("content") or "").strip()
        if body:
            out.append(f"  > {body[:160].replace(chr(10), ' ')}")
    out.append("")
    out.append(f"## 备案文档({len(docs)})")
    if not docs:
        out.append("(无)")
    for d in docs:
        out.append(f"- [{d.get('type')}] {d.get('title') or '-'} · {_fmt_ts(d.get('updatedAt'))}")
    return "\n".join(out)


def ctx_summarize(conversation_id: str) -> str:
    conv = summarize_conversation(conversation_id)
    if not conv:
        return f"# ctx.summarize\n\n会话 `{conversation_id}` 不存在。"
    return f"# ctx.summarize\n\n- 标题: {conv.get('title')}\n- 摘要: {conv.get('summary') or '(空)'}"


def run_tool(name: str, args: dict) -> str:
    """MCP 统一入口(map.* 同款)。"""
    handlers = {
        "ctx.search": lambda: ctx_search(args.get("query") or "",
                                         type_=args.get("type") or "",
                                         conversation_id=args.get("conversation") or "",
                                         project_id=args.get("project") or "",
                                         limit=int(args.get("limit") or 20)),
        "ctx.get": lambda: ctx_get(args.get("conversation") or ""),
        "ctx.summarize": lambda: ctx_summarize(args.get("conversation") or ""),
    }
    fn = handlers.get(name)
    if not fn:
        return f"未知工具: {name}（可用: {', '.join(handlers)}）"
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"工具执行失败: {e}"


# ── 会话 agent 工具面(register_architect_tool) ────────────

def register_chat_tools() -> None:
    """注册 ctx.* 为会话 agent 工具(幂等)。"""
    from .req_agent import register_architect_tool

    @register_architect_tool("ctx.search", "跨会话检索历史上下文(单元/消息/备案文档)")
    def _ctx_search(query: str, type: str = "", conversation: str = "",  # noqa: A002
                    limit: int = 20, project: Optional[str] = None, root: Optional[str] = None) -> dict:
        return {"markdown": ctx_search(query, type_=type, conversation_id=conversation,
                                       project_id=project or "", limit=limit)}

    @register_architect_tool("ctx.get", "读取会话上下文包(摘要+关键单元+备案文档)")
    def _ctx_get(conversation: str, project: Optional[str] = None,
                 root: Optional[str] = None) -> dict:
        return {"markdown": ctx_get(conversation)}

    @register_architect_tool("ctx.summarize", "生成/刷新会话摘要")
    def _ctx_summarize(conversation: str, project: Optional[str] = None,
                       root: Optional[str] = None) -> dict:
        return {"markdown": ctx_summarize(conversation)}
