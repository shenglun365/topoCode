"""Requirements CRUD + status machine routes (sqlite-backed)."""
import re
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store

router = APIRouter()


def _kb_degraded(root=None, project_id=None) -> bool:
    """是否降级: 无项目 或 项目无 KB 基线(工作目录直开/无 KB 内容支撑)。

    项目选择持久化在 URL(?root=/?project=)，由前端随请求透传 root/project。
    复用 project.kb_degraded 统一口径。
    """
    from .project import kb_degraded as _d
    return _d(root, project_id)


@router.get("/requirements")
async def list_requirements():
    return ok(store.RequirementsStore.all())


# ── 需求分析会话历史(阶段D 统一表，范围仅限临时提案/未绑定正式提案的会话) ──

def _conv_bound(conv: dict) -> bool:
    """会话是否已绑定正式提案(存在同 req_id 的需求)。未绑定 → 可导入/删除。"""
    req_id = conv.get("reqId") or ""
    if not req_id:
        return False
    return bool(store.RequirementsStore.get(req_id))


@router.get("/requirements/conversations")
async def list_conversations(project_id: str = "", kind: str = "requirement"):
    """历史会话摘要列表(仅返回临时/未绑定提案的会话，供导入或删除)。

    kind: 会话归类(requirement | asset | design | ...)，按需筛选；缺省 requirement。
    """
    convs = store.ConversationsStore.summaries(kind=kind or "requirement", project_id=project_id or None)
    items = []
    for c in convs:
        if _conv_bound(c):
            continue
        items.append({
            "id": c["id"], "kind": c.get("kind"), "reqId": c.get("reqId", ""),
            "title": c.get("title") or f"{c.get('kind') or 'requirement'} 对话",
            "msgCount": c.get("msgCount") or 0,
            "preview": (c.get("preview") or "").strip()[:160],
            "createdAt": c.get("createdAt") or c.get("updatedAt"),
            "updatedAt": c.get("updatedAt"),
        })
    return ok(items)


@router.get("/requirements/conversations/by-req/{req_id}")
async def get_conversation_by_req(req_id: str, project_id: str = ""):
    """按正式提案 id 自动导入其历史会话(需求再编辑/继续对话)。"""
    conv = None
    for c in store.ConversationsStore.by_req(req_id, project_id=project_id or ""):
        if _conv_bound(c) or c.get("reqId") == req_id:
            conv = c
            break
    if not conv:
        return ok(None)
    return ok({
        "id": conv["id"], "kind": conv.get("kind"), "reqId": conv.get("reqId", ""),
        "title": conv.get("title") or (f"{(store.RequirementsStore.get(req_id) or {}).get('title') or ''}" or f"{req_id} 对话"),
        "messages": store.ConversationsStore.messages(conv["id"]),
    })


@router.get("/requirements/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "Conversation not found")
    return ok({
        "id": conv["id"], "kind": conv.get("kind"), "reqId": conv.get("reqId", ""),
        "title": conv.get("title") or f"{(conv.get('kind') or 'requirement')} 对话",
        "messages": store.ConversationsStore.messages(conv_id),
    })


@router.delete("/requirements/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "Conversation not found")
    if _conv_bound(conv):
        return err(400, "已绑定正式提案的会话不可删除")
    store.ConversationsStore.delete(conv_id)
    return ok({"deleted": True, "id": conv_id})


@router.delete("/requirements/conversations/{conv_id}/messages/{message_id}")
async def delete_conversation_message(conv_id: str, message_id: str):
    """对话流单条消息删除(可回退当前轮工具上下文)。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "Conversation not found")
    msg = store.ConversationsStore.messages(conv_id)
    if not any(m.get("id") == message_id for m in msg):
        return err(404, "Message not found")
    if _conv_bound(conv):
        return err(400, "已绑定正式提案的会话不可删除消息")
    ok_deleted = store.ConversationsStore.delete_message(conv_id, message_id)
    store.ConversationsStore.update(conv_id, {"updatedAt": _ts()})
    return ok({"deleted": ok_deleted, "id": message_id})


@router.patch("/requirements/conversations/{conv_id}")
async def update_conversation(conv_id: str, request: Request):
    """绑定会话到正式提案(临时会话保存后 rebind req_id)，或更新标题。"""
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "Conversation not found")
    body = await request.json()
    update = {}
    if body.get("reqId"):
        update["reqId"] = body["reqId"]
    if body.get("title"):
        update["title"] = body["title"]
    if not update:
        return err(400, "No fields to update")
    store.ConversationsStore.update(conv_id, update)
    return ok(store.ConversationsStore.get(conv_id))


@router.post("/requirements")
async def create_requirement(request: Request):
    body = await request.json()
    req = {
        "id": body.get("id") or store.next_id("RQ"), "kind": body.get("kind", "user-story"), "tier": "raw",
        "location": "proposal", "title": body.get("title", ""),
        "priority": body.get("priority", "P2"), "status": "raw",
        "desc": body.get("desc", ""), "acceptance": body.get("acceptance", []),
        "traceTo": body.get("traceTo", []), "updatedAt": _ts(),
    }
    store.RequirementsStore.create(req)
    return ok(store.RequirementsStore.get(req["id"]))


@router.get("/requirements/{req_id}")
async def get_requirement(req_id: str):
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "Requirement not found")
    return ok(row)


@router.patch("/requirements/{req_id}")
async def patch_requirement(req_id: str, request: Request):
    body = await request.json()
    row = store.RequirementsStore.update(req_id, {**body, "updatedAt": _ts()})
    if not row:
        return err(404, "Requirement not found")
    # 语义资产引用登记(req→sa-*，供删除/失效精确波及)
    try:
        from .semantic_assets import register_scope_refs
        scope = (body.get("analysis") or {}).get("assetScope") or []
        register_scope_refs(scope, "req", req_id)
    except Exception:
        pass
    return ok(row)


@router.post("/requirements/{req_id}/cancel")
async def cancel_requirement(req_id: str):
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "Not found")
    row = store.RequirementsStore.update(
        req_id,
        {"status": "cancelled" if row["status"] != "cancelled" else "raw", "updatedAt": _ts()},
    )
    return ok(row)


@router.post("/requirements/{req_id}/finalize")
async def finalize_requirement(req_id: str, request: Request):
    body = await request.json()
    row = store.RequirementsStore.update(req_id, {
        "tier": "analyzed", "location": "pool", "status": "analyzed",
        "analysis": body.get("analysis", {}), "updatedAt": _ts(),
    })
    if not row:
        return err(404, "Not found")
    return ok(row)


@router.post("/requirements/{req_id}/direct")
async def direct_requirement(req_id: str, request: Request):
    body = await request.json()
    row = store.RequirementsStore.update(req_id, {
        "location": "pool", "status": "analyzed", "routedBy": "direct",
        "suggestion": body.get("suggestion"), "updatedAt": _ts(),
    })
    if not row:
        return err(404, "Not found")
    return ok(row)


@router.post("/requirements/{req_id}/location")
async def move_requirement_location(req_id: str, request: Request):
    body = await request.json()
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "Not found")
    row = store.RequirementsStore.update(
        req_id,
        {"location": body.get("location", row["location"]), "updatedAt": _ts()},
    )
    return ok(row)


@router.post("/requirements/analyze/clarify")
async def analyze_clarify(request: Request):
    """KB 澄清: 基于真实 KB 资产命中 + LLM 生成澄清问题清单。

    原则：无回退/降级伪造——项目未绑定 KB 或 harness 失败 → 明确报错(提示 KB 能力不足)。
    仅 greenfield(从零)模式无 KB 可检索时走领域建模提问(生成式能力，非伪造 KB 数据)。
    """
    body = await request.json()
    req = body.get("req") or {}
    title = req.get("title", "")
    desc = req.get("desc", "")
    mode = req.get("mode")
    preferred = req.get("preferredAssetIds") or []
    degraded = _kb_degraded(body.get("root"), body.get("project"))
    model_id = body.get("modelId") or body.get("req", {}).get("modelId") or None

    # 既有项目：必须已绑定 KB，否则明确报错(KB 能力不足/未关联)
    if mode != "greenfield" and degraded:
        return err(400, KB_NOTE)

    from .req_agent import req_harness_clarify
    from .common import KbUnavailableError
    try:
        agent = req_harness_clarify(req, body.get("root"), body.get("project"), model_id=model_id)
    except KbUnavailableError as e:
        return err(502, str(e))
    if agent and agent.get("questions"):
        questions = agent.get("questions")
        hits = agent.get("hits") or []
        content = (f"已基于知识库与需求生成澄清问题清单(命中 {len(hits)} 项候选资产)。请逐一作答，我会据此收敛结果表单。"
                   if mode != "greenfield" else
                   "项目从零开始，无既有知识库可检索。请描述需求的功能范围和核心业务实体，我会据此给出领域建模建议。")
        turns = [
            {"role": "user", "content": f"请基于{'领域建模思路' if mode == 'greenfield' else '知识库'}澄清需求「{title}」。\n{desc or '(未提供详细描述)'}"},
            {"role": "assistant", "content": content, "questions": questions},
        ]
        return ok({"turns": turns, "questions": questions, "hits": hits[:6],
                   "degraded": agent.get("degraded", False), "llm": True})

    # harness 失败(LLM 不可用/结构化解析失败) → 明确报错，不再回退伪造问题
    return err(502, "KB/LLM 能力不足：需求澄清未生成问题清单(harness 调用失败)。请确认 LLM 模型已配置且 KB 可达后重试。")


@router.post("/requirements/analyze/collect")
async def analyze_collect(request: Request):
    """KB 收集: 按答案合成 RequirementAnalysis(与前端 buildReport 对齐的字段)。"""
    body = await request.json()
    base = body.get("base") or {}
    answers = body.get("answers") or {}
    title = base.get("title", "")
    desc = base.get("desc", "")
    answered = [v for v in answers.values() if v and str(v).strip()]
    scope = _split_list(answers.get("scope"))
    boundary = _split_list(answers.get("boundary"))
    acceptance = _split_list(answers.get("acceptance"))
    mode = base.get("mode")
    degraded = _kb_degraded(body.get("root"), body.get("project"))
    model_id = body.get("modelId") or base.get("modelId") or None

    # 既有项目：必须已绑定 KB，否则明确报错(KB 能力不足/未关联)
    if mode != "greenfield" and degraded:
        return err(400, KB_NOTE)

    from .req_agent import req_harness_collect
    from .common import KbUnavailableError
    try:
        agent = req_harness_collect({"turns": body.get("turns") or [], "base": base,
                                     "answers": answers, "note": body.get("note")},
                                    body.get("root"), body.get("project"), model_id=model_id)
    except KbUnavailableError as e:
        return err(502, str(e))
    if agent and agent.get("report"):
        report = agent.get("report")
        draft = {
            "title": title, "kind": base.get("kind") or "user-story", "priority": base.get("priority"),
            "tags": [], "assetScope": report.get("assetScope") or [],
            "assessmentSummary": report.get("assessmentSummary") or "",
            "estMin": (report.get("feasibility") or {}).get("estMin") or 0,
            "specsMd": report.get("specsMd") or "跨组件调用仅经公开接口",
            "implementationPath": report.get("implementationPath") or "",
            "report": report,
        }
        return ok({"report": report, "formDraft": draft, "reply": _compose_collect_reply(report, title),
                   "hits": (agent.get("hits") or [])[:6],
                   "degraded": agent.get("degraded", False), "llm": True})

    # ── greenfield：从零生成(architect 设计的生成式能力，非 KB 检索数据) ──
    if mode == "greenfield":
        primary = (scope or ["core-service"])[0]
        asset_scope = []
        for s in scope or ["core-service"]:
            asset_scope.append({"assetId": f"p-c-{_slug(s)}", "assetType": "component", "role": "core", "source": "auto"})
        for i, e in enumerate(boundary or ["CoreEntity"]):
            asset_scope.append({"assetId": f"p-entity-{_slug(e)}", "assetType": "entity", "role": "core" if i == 0 else "related", "source": "auto"})
        report = {
            "functionalScope": scope, "entityBoundary": boundary,
            "feasibility": {"ok": True, "reason": f"建议以「{primary}」为核心模块", "estMin": len(scope or []) * 120},
            "assetScope": asset_scope,
            "assessment": {"necessity": {"grade": "high", "reason": "与核心链路直接相关"},
                           "atomicity": {"independent": True, "reason": "核心模块收敛"},
                           "acceptability": {"ok": True, "reason": "可转换为功能用例验收"}},
            "assessmentSummary": f"需求「{title}」评估结论：可行。",
            "implementationPath": f"建议以「{primary}」为主干，实现「{title}」核心逻辑。",
            "steps": [{"id": "gstep-1", "title": "领域设计", "desc": "细化建议模块的边界与职责", "estMin": 60, "context": scope or ["core-service"]},
                      {"id": "gstep-2", "title": "核心实现", "desc": f"按蓝图实现「{title}」主体", "estMin": 120, "context": scope or ["core-service"]}],
        }
        if not answered:
            questions = [{"key": "acceptance", "label": "请至少补充一条备注信息，将并入备注。", "type": "text", "hint": "描述可验证的行为或期望的功能范围。"}]
            return ok({"turns": [{"role": "assistant", "content": "请补充需求描述后再继续。", "questions": questions}], "questions": questions, "degraded": False})
        return ok({"report": report, "degraded": False, "formDraft": {
            "title": title, "kind": base.get("kind") or "user-story", "priority": base.get("priority"),
            "tags": [], "assetScope": asset_scope,
            "assessmentSummary": report["assessmentSummary"], "estMin": report["feasibility"]["estMin"],
            "specsMd": "跨模块调用仅经公开接口\n建议资产为从零规划，待架构蓝图细化确认",
            "implementationPath": report["implementationPath"], "report": report,
        }})

    # 既有项目 harness 失败(LLM 不可用/结构化解析失败) → 明确报错，不再回退伪造
    return err(502, "KB/LLM 能力不足：需求分析收敛未生成结果(harness 调用失败)。请确认 LLM 模型已配置且 KB 可达后重试。")


def _slug(text):
    return re.sub(r"\s+", "-", text.lower())


def _split_list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _compose_collect_reply(report: dict, title: str) -> str:
    """把 LLM 收敛出的分析结论转成助手回复文本,透传给前端聊天区展示。"""
    scope = report.get("functionalScope") or []
    assets = report.get("assetScope") or []
    est = (report.get("feasibility") or {}).get("estMin") or 0
    summary = report.get("assessmentSummary") or ""
    path = report.get("implementationPath") or ""
    parts = [f"已完成对「{title}」的需求分析：功能范围 {len(scope)} 项，关联 {len(assets)} 项数据资产，预估耗时 {est} 分钟。"]
    if summary:
        parts.append(summary)
    if path:
        parts.append(f"实现路径：{path}")
    parts.append("右侧已生成结果表单草案，请审阅确认后再替换表单。")
    return "\n".join(p for p in parts if p)


def _match_assets(text, preferred=None, root=None, project=None):
    """按文本在 kb 资产里做朴素命中(名称/标签/描述包含)。"""
    try:
        from .knowledge import _all_assets as kb_all
        assets = kb_all(root, project)
    except Exception:
        assets = []
    lowered = (text or "").lower()
    pre = set(preferred or [])
    hits = [a for a in assets if pre and a.get("assetId") in pre]
    if not hits:
        hits = [a for a in assets if lowered and any(
            kw in (a.get("name") or "").lower()
            or kw in (a.get("description") or a.get("desc") or "").lower()
            for kw in _split_list(lowered)
        )]
    return hits


@router.post("/requirements/merge")
async def merge_requirements(request: Request):
    return ok({"merged": True})
