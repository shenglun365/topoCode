"""Requirements CRUD + status machine routes (sqlite-backed)."""
import re
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store

router = APIRouter()


def _kb_degraded(root=None, project_id=None) -> bool:
    """是否降级: 无项目 或 项目无 KB 基线(工作目录直开/无 KB 内容支撑)。

    项目选择持久化在 URL(?root=/?project=)，由前端随请求透传 root/project。
    """
    try:
        from .project import _resolve_project
        proj = _resolve_project(root, project_id)
    except Exception:
        return True
    return not (proj and proj.get("baselineId"))


@router.get("/requirements")
async def list_requirements():
    return ok(store.RequirementsStore.all())


@router.post("/requirements")
async def create_requirement(request: Request):
    body = await request.json()
    req = {
        "id": store.next_id("RQ"), "kind": body.get("kind", "user-story"), "tier": "raw",
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
    """KB 澄清: 返回候选资产命中 + 澄清问题清单(同步完整, 不必走 /ws/kb-analysis)。"""
    body = await request.json()
    req = body.get("req") or {}
    title = req.get("title", "")
    desc = req.get("desc", "")
    mode = req.get("mode")
    preferred = req.get("preferredAssetIds") or []
    degraded = _kb_degraded(body.get("root"), body.get("project"))
    # 简单命中: 按 traceTo/关键词在 kb 资产名里匹配；未绑定项目时降级为无命中
    hits = [] if degraded else _match_assets(f"{title} {desc}", preferred)
    options = [h["name"] for h in hits[:6]]
    if mode == "greenfield":
        questions = [
            {"key": "scope", "label": "需求的功能范围包含哪些？建议的模块/服务划分？", "type": "text", "hint": "如：订单管理、支付、库存…一行一条。"},
            {"key": "boundary", "label": "核心业务实体有哪些？", "type": "text", "hint": "如 Order、Payment、Product 等业务抽象。"},
            {"key": "flows", "label": "核心业务流？", "type": "text", "hint": "如：下单流程、支付回调流程、超时关单…"},
            {"key": "acceptance", "label": "可验收标准？(至少一条可测试的行为)", "type": "text", "hint": "描述可验证的输入/输出与边界行为。"},
        ]
        content = ("项目从零开始，没有既有知识库可以检索。请描述需求的功能范围和核心业务实体，我会据此给出领域建模建议。"
                   if not degraded else
                   "未绑定项目，KB 能力降级：无既有资产检索。请描述需求的功能范围和核心业务实体，我会基于领域建模给出建议资产。")
    else:
        questions = [
            {"key": "scope", "label": "需求的功能范围包含哪些？", "type": "text", "hint": f"命中候选：{('、'.join(options)) or '无'}。一行一条或逗号分隔。"},
            {"key": "boundary", "label": "涉及的核心业务实体与逻辑边界？", "type": "text", "hint": "如 Order、OutboxEvent 等业务抽象(非详细代码)。"},
            {"key": "acceptance", "label": "可验收标准？(至少一条可测试的行为)", "type": "text", "hint": "描述可验证的输入/输出与边界行为。"},
        ]
        content = (f"已检索知识库(命中 {len(hits)} 项资产：{('、'.join(options)) or '—'})。先回答下面几个问题，我会据此生成结果表单草案。"
                   if not degraded else
                   "未绑定项目，KB 能力降级：无资产检索/无社区摘要。先回答下面几个问题，我会基于需求描述生成结果表单草案。")
    turns = [
        {"role": "user", "content": f"请基于{'领域建模思路' if mode == 'greenfield' else '知识库'}澄清需求「{title}」。\n{desc or '(未提供详细描述)'}"},
        {"role": "assistant", "content": content, "questions": questions},
    ]
    return ok({"turns": turns, "questions": questions, "hits": hits[:6], "degraded": degraded})


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
    degraded_note = "（未绑定项目，KB 能力降级：无既有资产检索/社区摘要，以下为基于需求描述的规划建议）" if degraded else ""

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
            "assessmentSummary": f"需求「{title}」评估结论：可行。{degraded_note}".rstrip(),
            "implementationPath": f"建议以「{primary}」为主干，实现「{title}」核心逻辑。",
            "steps": [{"id": "gstep-1", "title": "领域设计", "desc": "细化建议模块的边界与职责", "estMin": 60, "context": scope or ["core-service"]},
                      {"id": "gstep-2", "title": "核心实现", "desc": f"按蓝图实现「{title}」主体", "estMin": 120, "context": scope or ["core-service"]}],
        }
        if not answered:
            questions = [{"key": "acceptance", "label": "请至少补充一条备注信息，将并入备注。", "type": "text", "hint": "描述可验证的行为或期望的功能范围。"}]
            return ok({"turns": [{"role": "assistant", "content": "请补充需求描述后再继续。", "questions": questions}], "questions": questions, "degraded": degraded})
        return ok({"report": report, "degraded": degraded, "formDraft": {
            "title": title, "kind": base.get("kind") or "user-story", "priority": base.get("priority"),
            "tags": [], "assetScope": asset_scope,
            "assessmentSummary": report["assessmentSummary"], "estMin": report["feasibility"]["estMin"],
            "specsMd": "跨模块调用仅经公开接口\n建议资产为从零规划，待架构蓝图细化确认",
            "implementationPath": report["implementationPath"], "report": report,
        }})

    hits = [] if degraded else _match_assets(f"{title} {desc} {' '.join(answered)}", base.get("preferredAssetIds") or [])
    asset_scope = [{"assetId": h["assetId"], "assetType": "component", "role": "core" if i == 0 else "related", "source": "auto"}
                   for i, h in enumerate(hits[:5])]
    report = {
        "functionalScope": scope, "entityBoundary": boundary,
        "feasibility": {"ok": True, "reason": "已核对需求边界，可按步骤落地", "estMin": 30 + len(hits) * 60},
        "assetScope": asset_scope,
        "assessment": {"necessity": {"grade": "high", "reason": "直接关联核心链路"},
                       "atomicity": {"independent": True, "reason": "边界清晰"},
                       "acceptability": {"ok": True, "reason": "可转换为验收用例"}},
        "assessmentSummary": f"需求「{title}」评估结论：可行。涉及 {len(hits)} 项资产。{degraded_note}".rstrip(),
        "implementationPath": f"按「{title}」需求实现，覆盖涉及资产。",
        "steps": [{"id": f"step-{i}", "title": f"实现 {h['name']}", "desc": f"围绕 {h['name']} 落地需求变更", "estMin": 90, "context": [h["name"]]} for i, h in enumerate(hits[:4])] or
                 [{"id": "step-1", "title": "实现需求主体", "desc": "按需求描述实现", "estMin": 90, "context": []}],
    }
    return ok({"report": report, "hits": hits[:6], "degraded": degraded})


def _slug(text):
    return re.sub(r"\s+", "-", text.lower())


def _split_list(value):
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    if not value:
        return []
    return [v.strip() for v in str(value).split(",") if v.strip()]


def _match_assets(text, preferred=None):
    """按文本在 kb 资产里做朴素命中(名称/标签/描述包含)。"""
    try:
        from .knowledge import _all_assets as kb_all
        assets = kb_all()
    except Exception:
        assets = []
    lowered = (text or "").lower()
    pre = set(preferred or [])
    hits = [a for a in assets if pre and a.get("assetId") in pre]
    if not hits:
        hits = [a for a in assets if lowered and any(
            kw in (a.get("name") or "").lower() or kw in (a.get("description") or "").lower()
            for kw in _split_list(lowered)
        )]
    return hits


@router.post("/requirements/merge")
async def merge_requirements(request: Request):
    return ok({"merged": True})
