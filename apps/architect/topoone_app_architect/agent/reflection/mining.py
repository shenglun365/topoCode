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

from ...arch_routes.common import err, ok
from ...arch_routes.store.base import _row_to_api

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
    from ...arch_routes import store
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
    from ...arch_routes import store
    from ...arch_routes.semantic_assets import project_id_for
    from ...arch_routes.req_agent import llm_sync
    from ...arch_routes.agent_roles import resolve_role_model

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
        from ...arch_routes.store import NamingConventionStore
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
    from ...arch_routes import store
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
            from ...arch_routes.store import NamingConventionStore
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
    from ...arch_routes.req_agent import register_architect_tool

    @register_architect_tool(
        "capability.mine",
        "能力提炼: 扫描指定会话(消息+方案/回执单元)提炼 规约/流程/技巧/skill 提案, "
        "落入待审队列(pending), 设计者采纳后生效(规约入规约库/skill 文档注入能力文档)。"
        "会话出现可复用模式(有效做法/踩坑经验/命名规律)时主动提议",
    )
    def _capability_mine(conversation: str = "", project: Optional[str] = None,
                         root: Optional[str] = None) -> dict:
        from ...arch_routes import ctx as _ctx
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
    # 统一时间线: 提炼报告沉淀为关联会话消息(复用/分析/总结可见)
    try:
        conv_id = str(body.get("conversationId") or "")
        from ...arch_routes import store
        if conv_id and store.ConversationsStore.get(conv_id):
            store.ConversationsStore.append_message({
                "id": store.next_id("m"), "conversationId": conv_id,
                "role": "assistant", "time": int(_time.time() * 1000),
                "content": "🧠 **能力提炼完成**，新增提案 "
                           + str(len(result.get("proposals") or [])) + " 条（待审）\n\n"
                           + str(result.get("markdown") or "")[:2000],
            })
            store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
    except Exception:  # noqa: BLE001
        pass
    return ok({"count": len(result.get("proposals") or []),
               "markdown": result.get("markdown"),
               "proposals": result.get("proposals") or []})


@router.get("/capabilities/proposals")
async def api_proposals(project: str = "", status: str = "pending"):
    from ...arch_routes import store
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


# ── WS8-S2 认知产出→主库全局桶提升(冲突预检+origin 留痕) ────────────────

def _norm_text(s: str) -> str:
    """语义指纹归一: 去空白/标点、小写(冲突比对用)。"""
    import re as _re
    return _re.sub(r"[\s\W_]+", "", (s or "").lower())


def _unique_global_id(table: str, base_id: str) -> str:
    """全局桶 id 去重(force 并存时 g-<id> 可能已存在)。"""
    from ...arch_routes.store.base import _db
    gid = f"g-{base_id}"
    if _db().fetchone(f"SELECT id FROM {table} WHERE id = ?", (gid,)) is None:
        return gid
    import time as _t
    return f"g-{base_id}-{int(_t.time() * 1000) % 10 ** 8}"


def _global_rows(table: str, status_cond: str = "") -> List[Dict[str, Any]]:
    from ...arch_routes.store.base import GLOBAL_PID, _db
    sql = f"SELECT * FROM {table} WHERE project_id = ?"
    if status_cond:
        sql += f" AND {status_cond}"
    return [_row for _row in _db().fetchall(sql, (GLOBAL_PID,))]


def promote_to_global(project: str, kind: str, ref_id: str,
                      decision: str = "") -> Dict[str, Any]:
    """项目认知产出提升到主库全局桶(WS8 设计稿 §4/§5)。

    kind: asset(语义资产, 剥锚点只留语义) | convention(命名规约) | capability(已采纳提案)。
    decision: ""(预检, 无冲突即提升) | force(冲突并存, 资产名加后缀) | merge(并入既有全局条目)。
    冲突三选一: duplicate(重复, 提示跳过) / conflict(同语义, 报告双方) / promoted。
    """
    import time as _time
    from ...arch_routes.store import base as _sbase
    from ...arch_routes.store import NamingConventionStore, SemanticAssetsStore, CapabilityProposalStore
    now = int(_time.time() * 1000)
    decision = (decision or "").strip().lower()

    if kind == "convention":
        src = NamingConventionStore.get(ref_id, project)
        if not src:
            return {"error": f"规约 {ref_id} 不存在"}
        norm = _norm_text(src.get("ruleText", ""))
        for g in _global_rows("arch_naming_conventions", "status = 'active'"):
            if _norm_text(g["rule_text"] or "") == norm:
                if decision == "force":
                    break
                return {"status": "duplicate",
                        "markdown": f"全局层已有等价规约（{g['id']}），无需提升"}
        gid = _unique_global_id("arch_naming_conventions", ref_id)
        _sbase._insert_global("arch_naming_conventions", {
            "id": gid, "scope": "global", "ruleText": src.get("ruleText", ""),
            "appliesKinds": src.get("appliesKinds") or [],
            "scenarios": src.get("scenarios") or ["general"],
            "source": "promoted", "author": src.get("author") or "",
            "originProjectId": project, "status": "active",
            "createdAt": now, "updatedAt": now})
        return {"status": "promoted", "globalId": gid,
                "markdown": f"规约已提升到主库全局桶（{gid}）"}

    if kind == "capability":
        src = CapabilityProposalStore.get(ref_id, project)
        if not src:
            return {"error": f"能力提案 {ref_id} 不存在"}
        if (src.get("status") or "") != "accepted":
            return {"error": "仅已采纳(accepted)的提案可提升——先在提案队列采纳"}
        for g in _global_rows("arch_capability_proposals", "status = 'promoted'"):
            if (g["title"] or "").strip() == (src.get("title") or "").strip():
                if decision != "force":
                    return {"status": "duplicate",
                            "markdown": f"全局层已有同名能力（{g['id']}），无需提升"}
                break
        gid = _unique_global_id("arch_capability_proposals", ref_id)
        _sbase._insert_global("arch_capability_proposals", {
            "id": gid, "type": src.get("type", "trick"),
            "title": src.get("title", ""), "content": src.get("content", ""),
            "scenarios": src.get("scenarios") or [],
            "reason": (src.get("reason") or "") + f" [promoted from {project}]",
            "sourceConversationId": src.get("sourceConversationId") or "",
            "status": "promoted", "createdAt": now, "updatedAt": now})
        return {"status": "promoted", "globalId": gid,
                "markdown": f"能力已提升到主库全局桶（{gid}）"}

    if kind == "asset":
        src = SemanticAssetsStore.get(ref_id)
        if not src:
            return {"error": f"语义资产 {ref_id} 不存在"}
        norm_name = _norm_text(src.get("name", ""))
        canon = (src.get("canonicalKey") or "").strip().lower()
        hit = None
        for g in _global_rows("arch_semantic_assets", "status = 'active'"):
            g_canon = (g["canonical_key"] or "").strip().lower() if g["canonical_key"] else ""
            if (canon and g_canon and canon == g_canon) or \
               (_norm_text(g["name"] or "") == norm_name):
                hit = g
                break
        if hit is not None and decision not in ("force", "merge"):
            return {"status": "conflict", "globalId": hit["id"],
                    "markdown": (f"全局层已有同语义资产 {hit['name']}（{hit['id']}）\n"
                                 f"- 全局: {hit['id']} {(hit['desc'] or '')[:80]}\n"
                                 f"- 本项目: {src.get('id')} {(src.get('desc') or '')[:80]}\n"
                                 "decision=merge(并入全局, 补充描述) / force(并存, 名称加后缀)"),
                    "conflict": {"global": {"id": hit["id"], "desc": hit["desc"] or ""},
                                 "local": {"id": src.get("id"), "desc": src.get("desc") or ""}}}
        gid = _unique_global_id("arch_semantic_assets", ref_id)
        if hit is not None and decision == "merge":
            _sbase._update("arch_semantic_assets", hit["id"],
                           {"desc": hit["desc"] or src.get("desc", ""), "updatedAt": now})
            return {"status": "merged", "globalId": hit["id"],
                    "markdown": f"描述已并入全局资产 {hit['id']}"}
        name = src.get("name", "")
        if hit is not None and decision == "force":
            name = f"{name}.{project[-6:]}"
        meta = src.get("meta") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        meta["originProjectId"] = project
        meta["originAssetId"] = src.get("id")
        meta["promotedAt"] = now
        _sbase._insert_global("arch_semantic_assets", {
            "id": gid, "kind": src.get("kind", "entity"),
            "level": src.get("level", "business"), "name": name,
            "desc": src.get("desc", ""), "scopeType": src.get("scopeType") or "global",
            "scopeKey": src.get("scopeKey") or "", "source": "promoted",
            "originProjectId": project,
            "status": "active", "meta": meta,
            "astRefs": [], "anchorHashes": [],   # 剥锚点: 跨项目无意义, 只留语义
            "canonicalKey": src.get("canonicalKey") or "",
            "createdAt": now, "updatedAt": now})
        return {"status": "promoted", "globalId": gid,
                "markdown": f"语义资产已提升到主库全局桶（{gid}, 锚点已剥离）"}

    return {"error": f"未知提升类型 kind={kind}(asset|convention|capability)"}


def register_promote_tools() -> None:
    """注册 capability.promote 会话 agent 工具(WS8-S2)。"""
    from ...arch_routes.req_agent import register_architect_tool

    @register_architect_tool(
        "capability.promote",
        "提升到主库: 把项目内验证成熟的 认知产出(语义资产/命名规约/已采纳能力提案) "
        "提升到主库全局桶, 供跨项目检索复用。冲突时报告双方差异, 由设计者裁决"
        "(merge 并入/force 并存)。项目产出经反复验证、具跨项目通用性时用",
    )
    def _capability_promote(kind: str, id: str, decision: str = "",
                            project: Optional[str] = None,
                            root: Optional[str] = None) -> dict:
        from ...arch_routes.project import _resolve_project
        try:
            proj = _resolve_project(root, project)
        except Exception:
            proj = None
        pid = (proj or {}).get("id") or project or ""
        if not pid:
            return {"error": "无法解析项目(project)"}
        result = promote_to_global(pid, (kind or "").strip(), (id or "").strip(),
                                   decision)
        if result.get("error"):
            return result
        return {"markdown": result.get("markdown", ""), **{
            k: v for k, v in result.items() if k in ("status", "globalId")}}


register_promote_tools()


@router.post("/capabilities/promote")
async def api_promote(request: Request):
    body = await request.json()
    project = str(body.get("project") or "")
    if not project:
        return err(400, "缺少 project")
    result = promote_to_global(project, str(body.get("kind") or ""),
                               str(body.get("id") or ""),
                               str(body.get("decision") or ""))
    if result.get("error"):
        return err(400, result["error"])
    return ok(result)


# ── P5 定时批量提炼(后台周期扫描, 产出 pending 提案交设计者裁决) ───────

async def periodic_mine_loop(interval_h: float = 6.0, min_idle_h: float = 24.0,
                             min_messages: int = 12) -> None:
    """周期扫描: 各项目库中「静默超 min_idle_h 且消息数达标且尚无本会话提案」的
    会话 → run_mine 落 pending(设计者裁决, 不自动生效)。异常吞掉, 下轮重试。"""
    import asyncio as _aio
    import time as _time
    from ...arch_routes.store import CapabilityProposalStore, ConversationsStore
    from ...arch_routes.store.base import _scan_dbs
    await _aio.sleep(60)  # 启动缓冲
    while True:
        try:
            now = int(_time.time() * 1000)
            for db in _scan_dbs():
                try:
                    rows = db.fetchall(
                        "SELECT id, project_id, updated_at FROM arch_conversations "
                        "WHERE status IN ('active', 'archived') AND updated_at < ? "
                        "ORDER BY updated_at DESC LIMIT 40",
                        (now - int(min_idle_h * 3600 * 1000),))
                except Exception:
                    continue
                for r in rows:
                    conv_id, pid = r["id"], r["project_id"] or ""
                    if not pid:
                        continue
                    try:
                        existing = CapabilityProposalStore.list(pid, status="pending", limit=500) +                             CapabilityProposalStore.list(pid, status="accepted", limit=500)
                        if any(p.get("sourceConversationId") == conv_id for p in existing):
                            continue  # 本会话已提炼过
                        msgs = ConversationsStore.messages(conv_id, limit=200)
                        if len(msgs) < min_messages:
                            continue
                        result = run_mine(conv_id, project=pid)
                        if result.get("proposals"):
                            logger.info("[periodic-mine] %s → %d proposals",
                                        conv_id, len(result["proposals"]))
                    except Exception as e:  # noqa: BLE001
                        logger.debug("[periodic-mine] %s skipped: %s", conv_id, e)
        except Exception as e:  # noqa: BLE001
            logger.warning("[periodic-mine] loop error: %s", e)
        await _aio.sleep(interval_h * 3600)


def start_periodic_mine() -> None:
    """应用启动时挂载(app.on_event startup 调用)。"""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(periodic_mine_loop())
        logger.info("[periodic-mine] scheduled (6h)")
    except Exception as e:  # noqa: BLE001
        logger.warning("[periodic-mine] schedule failed: %s", e)


@router.get("/capabilities/global")
async def api_global_layer(project: str = ""):
    """主库全局桶概览(WS8-S3 消费侧): 提案明细 + 规约/资产计数。"""
    from ...arch_routes.store.base import GLOBAL_PID, _db
    props = []
    for r in _db().fetchall(
            "SELECT * FROM arch_capability_proposals WHERE project_id = ? "
            "AND status = 'promoted' ORDER BY created_at DESC LIMIT 100", (GLOBAL_PID,)):
        props.append(_row_to_api(r))
    counts = {}
    for t in ("arch_naming_conventions", "arch_semantic_assets"):
        counts[t] = _db().fetchone(
            f"SELECT count(*) AS c FROM {t} WHERE project_id = ? AND status = 'active'",
            (GLOBAL_PID,))["c"]
    return ok({"proposals": props,
               "conventions": counts["arch_naming_conventions"],
               "assets": counts["arch_semantic_assets"]})


@router.post("/capabilities/global/import")
async def api_global_import(request: Request):
    """冷启动导入(WS8-S4): 全局条目复制为本项目库条目(origin 留痕, 可参与本项目锚定)。"""
    body = await request.json()
    project = str(body.get("project") or "")
    items = body.get("items") or []
    if not project or not items:
        return err(400, "缺少 project/items")
    from ...arch_routes.store.base import GLOBAL_PID, _db, _insert, _update, _now_ms
    imported = []
    for it in items[:50]:
        kind, gid = str(it.get("kind") or ""), str(it.get("id") or "")
        table = {"convention": "arch_naming_conventions",
                 "asset": "arch_semantic_assets",
                 "capability": "arch_capability_proposals"}.get(kind)
        if not table or not gid:
            continue
        g = _db().fetchone(f"SELECT * FROM {table} WHERE id = ? AND project_id = ?",
                           (gid, GLOBAL_PID))
        if g is None:
            continue
        row = _row_to_api(g)
        now = _now_ms()
        row["id"] = f"imp-{gid}"
        row["projectId"] = project
        row["status"] = "accepted" if kind == "capability" else "active"
        if kind == "convention":
            row["source"] = "imported"
        if kind == "asset":
            row["source"] = "imported"
            row["astRefs"] = []
            row["anchorHashes"] = []
            row["needsUpdate"] = 0
        row["originProjectId"] = str(g["origin_project_id"] or "").replace(GLOBAL_PID, "global")
        row["createdAt"] = now
        row["updatedAt"] = now
        _insert(table, row)
        imported.append({"kind": kind, "id": row["id"], "from": gid})
    return ok({"imported": imported, "count": len(imported)})


# ── WS8-S5 KB 通用知识层接口位(预留, 构建时接通) ─────────────────────────

async def promote_to_kb(kind: str, global_id: str) -> Dict[str, Any]:
    """全局桶条目 → KB 通用知识层提升接口位。

    KB 侧当前仅项目关联信息(用户确认), 通用知识层未来构建时在此接通;
    届时仍需独立审批, _check_main_kb_policy 的主 KB 保护不受影响。
    """
    return {"status": "not_implemented",
            "note": "KB 通用知识层未构建——接口位预留(见 docs/architect-reconstruction/global-promotion-design.md §6)"}
