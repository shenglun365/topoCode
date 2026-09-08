"""WS7 能力提炼闭环: 历史会话/日志 → 规约/流程/技巧/skill 提案 → 待审 → 采纳生效。

设计(对齐决策):
- capability.mine 工具/REST: 材料=会话消息+高优上下文单元(方案/回执/artifact),
  LLM(role=mine)产出结构化提案; 去重(已 active 规约/已采纳提案按标题);
- 提案落 arch_capability_proposals(pending)——设计者逐条 采纳/忽略;
- 采纳生效: convention → NamingConventionStore(active); process/trick/skill →
  accepted, 由 asset_skill.skill_docs 按场景标签注入(静态注册→可增长);
- 触发: 会话内工具 + 会话中心手动按钮(定时批处理留待后续)。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from .common import err, ok

logger = logging.getLogger(__name__)

router = APIRouter()

_MINE_SCHEMA = {
    "type": "object",
    "properties": {
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "convention|process|trick|skill"},
                    "title": {"type": "string", "description": "一句话标题(≤24字)"},
                    "content": {"type": "string", "description": "条目正文: 规约一句/流程步骤/技巧说明/skill 文档 Markdown"},
                    "scenarios": {"type": "array", "items": {"type": "string"},
                                  "description": "注入场景标签: extract/accept/naming/…(空=不注入, 仅留档)"},
                    "reason": {"type": "string", "description": "提炼依据(引用对话来源)"},
                },
                "required": ["type", "title", "content"],
            },
        }
    },
    "required": ["proposals"],
}


def _mine_material(conv_id: str, budget: int = 12000) -> str:
    """会话材料: 消息(用户问题+助手结论) + 高优上下文单元(方案/回执/artifact 摘要)。"""
    from . import store
    parts: List[str] = []
    msgs = store.ConversationsStore.messages(conv_id, limit=40) or []
    for m in msgs:
        role = "用户" if m.get("role") == "user" else "助手"
        text = " ".join((m.get("content") or "").split())[:600]
        if text:
            parts.append(f"[{role}] {text}")
    units = store.ContextUnitsStore.all(conversation_id=conv_id, limit=60) or []
    picked = [u for u in units if (u.get("importance") or 0) >= 1]
    for u in sorted(picked, key=lambda x: x.get("createdAt") or "")[-12:]:
        body = " ".join((u.get("content") or "").split())[:400]
        if body:
            parts.append(f"[单元:{u.get('type')}] {u.get('title', '')} — {body}")
    out = "\n".join(parts)
    return out[:budget]


def _parse_proposal_array(text: str) -> List[dict]:
    """chat 回退产物中容错抽取 JSON 数组(容忍围栏/前后缀)。"""
    import re as _re
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        raw = raw.rsplit("```", 1)[0]
    m = _re.search(r"\[\s]*\{", raw)
    if not m:
        return []
    depth, in_str, esc, start = 0, False, False, m.start()
    for j in range(start, len(raw)):
        ch = raw[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0 and raw[start] == "[":
                import json as _json
                try:
                    data = _json.loads(raw[start:j + 1])
                    return data if isinstance(data, list) else []
                except Exception:
                    return []
    return []


def run_mine(conversation_id: str, root: Optional[str] = None,
             project: Optional[str] = None, model_id: str = "") -> Dict[str, Any]:
    """提炼入口: 材料 → LLM(role=mine) → 提案(pending)。返回 {proposals, markdown}。"""
    from . import store
    from .semantic_assets import project_id_for
    from .req_agent import llm_sync
    from .agent_roles import resolve_role_model

    pid = project_id_for(root, project)
    if not conversation_id:
        return {"error": "缺少 conversation(会话 id)"}
    material = _mine_material(conversation_id)
    if not material:
        return {"error": "会话无可提炼材料(空会话)"}

    sys_prompt = (
        "你是架构能力提炼器。从对话记录与上下文单元中提炼可复用的能力条目：\n"
        "- convention: 命名/编码规约(一句可执行规则, 如「服务类以 Service 结尾」)\n"
        "- process: 流程经验(某类任务的推进步骤要点)\n"
        "- trick: 技巧(工具/检索/分析的具体窍门)\n"
        "- skill: skill 文档(Markdown, 按场景注入 agent 提示词, 需给 scenarios 标签)\n"
        "只提炼对话中真实体现、可复用的条目(2-6 条); 没有就返回空数组, 严禁编造。"
        "只输出 JSON。"
    )
    usr = {"role": "user", "content": f"会话 {conversation_id} 记录:\n\n{material}"}
    mid = model_id or resolve_role_model("mine") or None
    res = llm_sync(messages=[{"role": "system", "content": sys_prompt}, usr],
                   mode="structured", output_schema=_MINE_SCHEMA, max_tokens=2048,
                   model_id=mid)
    proposals = []
    if res and isinstance(res.get("output"), dict):
        proposals = [p for p in (res["output"].get("proposals") or [])
                     if isinstance(p, dict) and p.get("title") and p.get("content")]
    # structured 空输出(本地模型嵌套 schema 易失败) → chat 模式 + 宽松数组解析回退
    if not proposals:
        hint = ('\n\n只输出 JSON 数组, 形如: '
                '[{"type":"convention","title":"…","content":"…","scenarios":["naming"],"reason":"…"}]')
        chat = llm_sync(
            messages=[{"role": "system", "content": sys_prompt},
                      {"role": "user", "content": usr["content"] + hint}],
            mode="chat", max_tokens=2048, model_id=mid)
        if chat is None and res is None:
            return {"error": "LLM 不可达——提炼失败(可稍后重试)"}
        proposals = [p for p in _parse_proposal_array((chat or {}).get("content", ""))
                     if isinstance(p, dict) and p.get("title") and p.get("content")]

    # 去重: 已 active 规约 + 已采纳提案(标题精确匹配)
    try:
        from .store import NamingConventionStore
        existing = {c.get("ruleText", "").strip() for c in NamingConventionStore.list(pid, status="active")}
    except Exception:
        existing = set()
    accepted_titles = {p.get("title", "").strip()
                       for p in store.CapabilityProposalStore.list(pid, status="accepted", limit=500)}
    created, skipped = [], 0
    for p in proposals:
        title = str(p.get("title")).strip()[:48]
        content = str(p.get("content")).strip()[:4000]
        type_ = p.get("type") if p.get("type") in ("convention", "process", "trick", "skill") else "trick"
        if title in accepted_titles or content in existing:
            skipped += 1
            continue
        row = store.CapabilityProposalStore.create(
            pid, type_, title, content,
            scenarios=[str(x) for x in (p.get("scenarios") or [])][:4],
            reason=str(p.get("reason") or "")[:300],
            source_conversation_id=conversation_id)
        created.append(row)
        if type_ == "convention":
            existing.add(content)
    lines = [f"# 能力提炼(会话 {conversation_id})", "",
             f"- 新提案 {len(created)} 条(待审)" + (f", 去重跳过 {skipped} 条" if skipped else ""), ""]
    for r in created:
        lines.append(f"- **[{r.get('type')}]** {r.get('title')} — {r.get('content', '')[:80]}…"
                     f"(依据: {r.get('reason', '')[:60]})")
    if not created:
        lines.append("(无新提案——对话无足够可复用模式, 或均与已有能力重复)")
    lines += ["", "提案在会话中心「能力提案」待审队列逐条 采纳/忽略; 采纳后: 规约入规约库、"
              "skill/技巧/流程按场景标签注入 agent 能力文档。"]
    return {"proposals": created, "skipped": skipped, "markdown": "\n".join(lines)}


def decide_proposal(project_id: str, proposal_id: str, action: str) -> Dict[str, Any]:
    """采纳/忽略提案。采纳生效: convention→规约库(active); 其余→accepted(skill_docs 注入)。"""
    from . import store
    row = store.CapabilityProposalStore.get(proposal_id, project_id)
    if not row:
        return {"error": f"提案 {proposal_id} 不存在"}
    if row.get("status") != "pending":
        return {"error": f"提案已处理({row.get('status')})"}
    action = (action or "").strip().lower()
    if action not in ("accept", "ignore"):
        return {"error": "action 须为 accept|ignore"}
    applied = ""
    if action == "accept":
        if row.get("type") == "convention":
            from .store import NamingConventionStore
            NamingConventionStore.create(
                project_id, row.get("content", ""),
                scenarios=row.get("scenarios") or ["naming"],
                source="mined", author="capability.mine")
            applied = "已入命名规约库(active)"
        else:
            applied = f"已采纳({row.get('type')})——skill_docs 按场景标签注入"
    store.CapabilityProposalStore.update(proposal_id, {"status": "accept" if action == "accept" else "ignored"})
    return {"ok": True, "id": proposal_id, "action": action, "applied": applied}


def register_mining_tools() -> None:
    """注册 capability.mine 会话 agent 工具(WS7)。"""
    from .req_agent import register_architect_tool

    @register_architect_tool(
        "capability.mine",
        "能力提炼: 扫描指定会话(消息+方案/回执单元)提炼 规约/流程/技巧/skill 提案, "
        "落入待审队列(pending), 设计者采纳后生效(规约入规约库/skill 文档注入能力文档)。"
        "会话出现可复用模式(有效做法/踩坑经验/命名规律)时主动提议",
    )
    def _capability_mine(conversation: str = "", project: Optional[str] = None,
                         root: Optional[str] = None) -> dict:
        from . import ctx as _ctx
        conv_id = (conversation or "").strip() or _ctx.get_conv() or ""
        result = run_mine(conv_id, root=root, project=project)
        if result.get("error"):
            return result
        return {"markdown": result.get("markdown", ""),
                "count": len(result.get("proposals") or []),
                "proposals": [{"id": p.get("id"), "type": p.get("type"), "title": p.get("title")}
                              for p in (result.get("proposals") or [])[:10]]}


# ── REST(会话中心手动按钮/待审队列) ────────────────────────────────────

@router.post("/capabilities/mine")
async def api_mine(request: Request):
    body = await request.json()
    result = run_mine(str(body.get("conversationId") or ""),
                      root=body.get("root"), project=body.get("project"))
    if result.get("error"):
        return err(400, result["error"])
    return ok({"count": len(result.get("proposals") or []),
               "markdown": result.get("markdown"),
               "proposals": result.get("proposals") or []})


@router.get("/capabilities/proposals")
async def api_proposals(project: str = "", status: str = "pending"):
    from . import store
    if not project:
        return err(400, "缺少 project")
    rows = store.CapabilityProposalStore.list(project, status=status or "pending")
    return ok(rows)


@router.post("/capabilities/proposals/{proposal_id}")
async def api_decide(proposal_id: str, request: Request):
    body = await request.json()
    project = str(body.get("project") or "")
    if not project:
        return err(400, "缺少 project")
    result = decide_proposal(project, proposal_id, str(body.get("action") or ""))
    if result.get("error"):
        return err(400, result["error"])
    return ok(result)
