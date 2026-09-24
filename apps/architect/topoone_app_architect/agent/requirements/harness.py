"""需求 Harness(澄清/收集) — M3 自 req_agent 机械迁出(逐字保真)。

clarify/collect 两回合的 LLM 编排(R3.1 批次②, M4 迁 CallTurn);
req_agent 经 re-export 保持 requirements REST 与既有引用接缝。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..governance.gears import DEFAULT_TIER_ID as _DEFAULT_TIER

# ── Harness: 需求澄清 / 需求收集 ─────────────────────────────────────

_SYSTEM_PROMPT = (
    "你是 TopoCode 架构需求分析 agent。你拥有知识库 skills/tools 能力：可检索知识库资产"
    "(kb.asset.search)、查代码映射(kb.code_mappings)、读基线(kb.baseline)、遍历依赖图(kb.graph)、"
    "检索/提取语义数据资产(asset.semantic.*，类别 structure/behavior/rule/contract × 粒度 high/medium/low，"
    "锚定 AST 节点)。"
    "你的产出必须直接可被表单消费，不得包含多余解释。"
)


def _names(hits: List[Dict[str, Any]]) -> List[str]:
    return [h.get("name") or h.get("id") for h in hits if h]


def _kb_hits(root: Optional[str], project: Optional[str],
             text: str, preferred: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """组件资产 + 语义数据资产合并命中(需求分析收敛的候选来源)。"""
    from ...agent.tools import req_agent as _ra   # 调用期解析(接缝/避免初始化环)
    hits = _ra.tool_kb_asset_search(root, project, text, preferred)
    try:
        from ...arch_routes import semantic_assets as S
        sem = S.search(root, project, text) or []
        seen = {h.get("id") for h in hits}
        for a in sem:
            if a.get("id") and a.get("id") not in seen:
                hits.append(a)
    except Exception:
        pass
    return hits


def _hint(hits: List[Dict[str, Any]]) -> str:
    names = "、".join(_names(hits))
    if not names:
        return "知识库未命中明显资产，请依据需求描述给出建议资产。"
    return f"知识库命中候选：{names}。请优先据此收敛范围。"


def req_harness_clarify(req: Dict[str, Any], root: Optional[str] = None,
                        project: Optional[str] = None,
                        model_id: Optional[str] = None,
                        tier: str = _DEFAULT_TIER) -> Optional[Dict[str, Any]]:
    """clarify 回合: KB 资产检索 → LLM 生成澄清问题清单。返回 None 表示未生成(调用方明确报 502，不回退伪造)。

    model_id: 本次对话选择的模型(可选)；空则回退全局 llm.modelId → 主后端默认。
    tier: 会话挡位(R3.1 链3② D7-②): 弱挡附问题模板槽位脚手架 + 兜底静态三问。
    """
    from ...agent.tools import req_agent as _ra   # 调用期解析(run_tools_loop/打桩接缝)
    from ..compensation.ctx import Purpose
    from ..turns import call as _call_turn
    title = req.get("title", "")
    desc = req.get("desc", "")
    mode = req.get("mode") or ("greenfield" if not project else "existing")
    preferred = req.get("preferredAssetIds") or []
    text = f"{title} {desc}"
    hits = _kb_hits(root, project, text, preferred)

    sys_prompt = _SYSTEM_PROMPT + (
        "\n\n当前阶段：需求澄清。请根据需求与知识库命中，返回 3-5 个需要用户确认的问题。"
        '只输出 JSON 数组: [{"key": str, "label": str, "type": "text", "hint": str}]。'
        "不要 Markdown 代码块。不要多余文字。"
    )
    user_prompt = (
        f"需求标题：{title}\n需求描述：{desc or '(未提供)'}\n模式：{mode}\n\n"
        f"{_hint(hits)}\n\n请生成澄清问题清单。"
    )

    def _validate(content):
        qs = _parse_json_array(content or "")
        return (bool(qs), "" if qs else "输出不是合法的 JSON 问题数组或为空")

    def _fallback():
        # §5.4 兜底: 静态三问模板(目标/边界/验收缺失各 1 问保底)
        return [{"key": "goal", "label": "目标：这次要达成什么？", "type": "text", "hint": "一句话描述要做成什么"},
                {"key": "scope", "label": "边界：涉及哪些文件/模块？", "type": "text", "hint": "可改动范围与禁止改动"},
                {"key": "acceptance", "label": "验收：如何算完成？", "type": "text", "hint": "可验证的完成标准"}]

    r = _call_turn.call(Purpose.CLARIFY,
                        [{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": user_prompt}],
                        tier=tier, model_id=model_id,
                        max_tokens=_ra.get_max_tokens_preference(),
                        validate=_validate, fallback=_fallback,
                        runner=True, root=root, project=project)
    if r.get("ok") and r.get("degraded"):
        # §5.4 兜底: CallTurn 产出静态三问模板(output 通道)
        return {"questions": r["output"], "hits": hits, "mode": mode,
                "degraded": True}
    content = r.get("content") if r.get("ok") else ""
    questions = _parse_json_array(content) if content else []
    if not questions:
        return None
    return {"questions": questions, "hits": hits, "mode": mode,
            "degraded": False}


def _parse_json_array(text: str) -> List[Dict[str, Any]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def req_harness_collect(ctx: Dict[str, Any], root: Optional[str] = None,
                        project: Optional[str] = None,
                        model_id: Optional[str] = None,
                        tier: str = _DEFAULT_TIER) -> Optional[Dict[str, Any]]:
    """collect 回合: 上下文+答案 → LLM structured 产出 RequirementAnalysis。返回 None 降级。

    model_id: 本次对话选择的模型(可选)；空则回退全局 llm.modelId → 主后端默认。
    tier: 会话挡位(R3.1 链3② D7-②): 弱挡附八字段逐项脚手架; 兜底维持 None(502)。
    """
    from ...agent.tools import req_agent as _ra   # 调用期解析(run_tools_loop/打桩接缝)
    base = ctx.get("base") or {}
    answers = {k: str(v) for k, v in (ctx.get("answers") or {}).items() if v and str(v).strip()}
    note = (ctx.get("note") or "").strip()
    title = base.get("title", "")
    desc = base.get("desc", "")
    mode = base.get("mode") or ("greenfield" if not project else "existing")
    preferred = base.get("preferredAssetIds") or []
    text = f"{title} {desc} {note} {' '.join(answers.values())}"
    hits = _kb_hits(root, project, text, preferred)
    manual = [{"assetId": a, "role": "core", "source": "manual"} for a in (preferred or [])]

    # 完整数据资产目录(组件/ER/实体/流程/数据流/语义资产)作为候选池，覆盖文本命中未及的范围。
    catalog_items: List[Dict[str, Any]] = []
    catalog_text = ""
    try:
        from ...arch_routes.design import data_asset_catalog, _catalog_text
        catalog = data_asset_catalog(root, project)
        catalog_items = catalog.get("items") or []
        catalog_text = _catalog_text(catalog_items)
    except Exception:
        pass

    schema = {
        "type": "object",
        "required": ["functionalScope", "entityBoundary", "assetScope", "estMin",
                      "implementationPath", "assessmentSummary"],
        "properties": {
            "functionalScope": {"type": "array", "items": {"type": "string"}},
            "entityBoundary": {"type": "array", "items": {"type": "string"}},
            "assessmentSummary": {"type": "string"},
            "assetScope": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["assetId", "assetType", "role", "source"],
                    "properties": {
                        "assetId": {"type": "string"},
                        "assetType": {"enum": ["component", "er", "orm", "entity",
                                                "flow", "dataflow",
                                                "entity", "contract", "state", "rule", "process", "decision"]},
                        "level": {"enum": ["business", "logic", "implementation"]},
                        "role": {"enum": ["core", "related"]},
                        "source": {"enum": ["auto", "manual"]},
                        "file": {"type": "string"},
                        "businessReason": {"type": "string"},
                    },
                },
            },
            "estMin": {"type": "integer"},
            "implementationPath": {"type": "string"},
        },
    }

    sys_prompt = _SYSTEM_PROMPT + (
        "\n\n当前阶段：需求分析收敛。请依据作答/候选资产，只输出一个 JSON 对象(不要代码块)，字段："
        '{"functionalScope":[str], "entityBoundary":[str], "assetScope":[{assetId,assetType,role,'
        'source,file?,businessReason?}], "estMin":int(分钟), "implementationPath":str, "assessmentSummary":str}。'
        "assetScope 从下方完整数据资产目录与用户首选资产收敛，core 为直接改动、related 为联动，"
        "businessReason 简述业务理由。"
    )
    convo = "\n".join(
        f"{t.get('role')}: {t.get('content')}" for t in (ctx.get("turns") or [])[-8:]
        if isinstance(t, dict) and t.get("content")
    )
    answered_lines = "\n".join(f"• {k}: {v}" for k, v in answers.items())
    user_prompt = (
        f"需求：{title}\n描述：{desc or '(未提供)'}\n模式：{mode}\n"
        f"候选资产：{'、'.join(_names(hits)) or '—'}\n用户作答：\n{answered_lines or '(无)'}\n"
        f"备注：{note or '(无)'}\n对话摘录：{convo or '(无)'}"
    )
    if catalog_text:
        user_prompt += (
            f"\n\n完整数据资产目录({len(catalog_items)} 项)，assetScope 只从其中选择，不要臆造不存在的资产：\n"
            f"{catalog_text}"
        )
    # R3.1 链3②(D7-②): 经 CallTurn——弱挡八字段逐项脚手架/按挡重试;
    # 兜底维持 None(requirements REST 明确 502, 不回退伪造)
    from ..compensation.ctx import Purpose
    from ..turns import call as _call_turn
    r = _call_turn.call(Purpose.COLLECT,
                        [{"role": "system", "content": sys_prompt},
                         {"role": "user", "content": user_prompt}],
                        tier=tier, model_id=model_id,
                        max_tokens=_ra.get_max_tokens_preference(),
                        schema=schema,
                        validate=lambda p: (isinstance(p, dict)
                                            and bool(p.get("functionalScope") is not None),
                                            "输出非 JSON 对象"),
                        fallback=lambda: None,
                        runner=True, root=root, project=project)
    output = r.get("output") if r.get("ok") else None
    if not output:
        return None

    report = {
        "functionalScope": output.get("functionalScope") or [],
        "entityBoundary": output.get("entityBoundary") or [],
        "feasibility": {"ok": True, "reason": "经知识库与 LLM 收敛，路径清晰",
                        "estMin": int(output.get("estMin") or 0)},
        "assetScope": _merge_assets(output.get("assetScope") or [], manual, hits, root, project),
        "assessment": _build_assessment(hits),
        "assessmentSummary": output.get("assessmentSummary")
            or f"需求「{title}」评估结论：可行。{_assessment_summary(hits)}",
        "implementationPath": output.get("implementationPath") or "",
        "changes": _build_changes(hits),
        "steps": _build_steps(hits, output.get("estMin") or 90),
    }
    return {"report": report, "hits": hits[:6], "degraded": False}


def _assessment_summary(hits: List[Dict[str, Any]]) -> str:
    if not hits:
        return "可行但需补充上下文。"
    return f"知识库命中 {len(hits)} 项资产，核心改动收敛。"


def _build_assessment(hits: List[Dict[str, Any]]):
    if hits:
        return {"necessity": {"grade": "high", "reason": f"命中 {len(hits)} 项资产"},
                "atomicity": {"independent": len(hits) <= 3,
                              "reason": "核心收敛" if len(hits) <= 3 else "跨资产较多"},
                "acceptability": {"ok": True, "reason": "可转化为功能用例验收"}}
    return {"necessity": {"grade": "medium", "reason": "命中不足"},
            "atomicity": {"independent": True, "reason": "领域建模建议"},
            "acceptability": {"ok": True, "reason": "可转换为功能用例验收"}}


def _merge_assets(llm_assets: List[Dict[str, Any]], manual: List[Dict[str, Any]],
                  hits: List[Dict[str, Any]],
                  root: Optional[str] = None, project: Optional[str] = None) -> List[Dict[str, Any]]:
    from ...agent.tools import req_agent as _ra   # 调用期解析
    merged: Dict[str, Dict[str, Any]] = {}
    for m in manual:
        merged[m["assetId"]] = dict(m)
    for a in llm_assets:
        aid = a.get("assetId")
        if aid in merged:
            merged[aid].update({k: v for k, v in a.items() if k not in ("role", "source")})
        else:
            merged[aid] = dict(a)
    cm_by = {c.get("targetId"): c for c in _ra._model_code_mappings(root, project)}
    for aid in list(merged.keys()):
        cm = cm_by.get(aid)
        if cm and not merged[aid].get("file"):
            merged[aid]["file"] = cm.get("file")
    return list(merged.values())


def _build_changes(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [{"resource": h.get("name") or h.get("id"), "kind": "modified",
             "before": f"当前 {h.get('name')} 基线实现", "after": "扩展以覆盖需求变更"}
            for h in hits[:4]]


def _build_steps(hits: List[Dict[str, Any]], est_min: int) -> List[Dict[str, Any]]:
    names = [h.get("name") or h.get("id") for h in hits[:3]]
    primary = "、".join(names) or "核心资产"
    # 语义资产 id(sa-*)并入步骤 context，供任务树携带并在 coding-agent 上下文展开锚点。
    sem_ids = [h.get("id") for h in hits if h.get("id") and str(h.get("id")).startswith("sa-")][:6]
    ctx1 = list(dict.fromkeys(names + sem_ids))
    return [
        {"id": "step-1", "title": "梳理现状与边界",
         "desc": f"检索知识库中 {primary} 的现状，锁定逻辑边界与不变量", "estMin": 30,
         "context": ctx1},
        {"id": "step-2", "title": "实现需求变更",
         "desc": f"按需求落地变更，覆盖 {primary} 的扩展点", "estMin": int(est_min),
         "context": ctx1},
        {"id": "step-3", "title": "测试与验收",
         "desc": "补充单测与集成用例，覆盖幂等/回滚/边界行为", "estMin": 60,
         "context": ["验收标准"] + sem_ids},
    ]
