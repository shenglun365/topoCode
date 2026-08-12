"""设计方案 + 范围圈定 + 修改前后对比(方向1/2/3)。

方向1  交互式数据资产范围圈定: req_harness_scope —— 基于需求 + 数据资产目录(组件/ER/实体/
       流程/数据流/语义资产) 提议 core/related 范围(结构化，含业务理由)。
方向2  设计方案: req_harness_design —— 结构化 DesignDraft(dataChanges/interfaceChanges/
       semanticChanges/steps/landingNote) + 确定性 after-model 合成(纯函数，不依赖 LLM 排版)。
方向3  修改前后对比: planned = 当前基线 vs 应用方案后的合成 after；actual = 实施后回读
       实际模型/语义资产，逐项比对计划 vs 实际偏差。

全部数据来自 KB 真实模型 + architect 语义资产；LLM 仅产出「变更意图」，落库/差异计算均为
确定性逻辑，杜绝 LLM 结构化漂移导致图表错位。
"""
from __future__ import annotations

import copy
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Request

from .common import _ts, ok, err, build_architecture_model
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()


# ── 数据资产目录 ──────────────────────────────────────────────

_ER_TABLE_KEYS = ("id", "name", "level", "change", "desc",
                  "columns", "relations", "invariants", "ast")


def _norm_table(t: Dict[str, Any]) -> Dict[str, Any]:
    """把 KB erTables 归一化为前端 ErTable 形状(缺字段补默认)。"""
    cols = []
    for c in t.get("columns") or []:
        cols.append({
            "name": c.get("name") or "", "type": c.get("type") or "string",
            "nullable": bool(c.get("nullable")), "pk": bool(c.get("pk")),
            "fk": c.get("fk") or "", "desc": c.get("desc") or "",
            "ast": c.get("ast") or {},
        })
    rels = []
    for r in t.get("relations") or []:
        rels.append({
            "from": r.get("from") or "", "to": r.get("to") or "",
            "type": r.get("type") or "1:N", "key": r.get("key") or "",
            "desc": r.get("desc") or "",
        })
    return {
        "id": t.get("id") or t.get("tableId") or "", "name": t.get("name") or "",
        "level": t.get("level") or "logical", "change": t.get("change") or "same",
        "desc": t.get("desc") or "", "columns": cols, "relations": rels,
        "invariants": t.get("invariants") or [], "ast": t.get("ast") or {},
    }


def data_asset_catalog(root: Optional[str], project: Optional[str],
                       max_items: int = 60) -> Dict[str, Any]:
    """数据资产目录：组件 + ER/实体/流程/数据流 + 语义资产(范围圈定/设计候选来源)。"""
    model = build_architecture_model(root, project)
    items: List[Dict[str, Any]] = []
    for c in model.get("components") or []:
        items.append({"assetId": c.get("id") or "", "name": c.get("name") or "",
                      "assetType": "component", "desc": c.get("desc") or "",
                      "kind": c.get("kind") or "service"})
    for t in model.get("erTables") or []:
        items.append({"assetId": t.get("id") or t.get("tableId") or "",
                      "name": t.get("name") or "", "assetType": "er",
                      "desc": t.get("desc") or "", "kind": "table"})
    for e in model.get("entityClasses") or []:
        items.append({"assetId": e.get("id") or "", "name": e.get("name") or "",
                      "assetType": "entity", "desc": e.get("desc") or "",
                      "kind": e.get("kind") or "class"})
    for f in model.get("executionFlows") or []:
        items.append({"assetId": f.get("id") or "", "name": f.get("name") or "",
                      "assetType": "flow", "desc": f.get("desc") or "",
                      "kind": "flow"})
    for d in model.get("dataFlows") or []:
        items.append({"assetId": d.get("id") or "", "name": d.get("name") or "",
                      "assetType": "dataflow", "desc": d.get("desc") or "",
                      "kind": "dataflow"})
    try:
        from . import semantic_assets as S
        for a in (S.search(root, project, "") or []):
            items.append({"assetId": a.get("id") or "", "name": a.get("name") or "",
                          "assetType": a.get("kind") or "structure",
                          "level": a.get("level") or "medium",
                          "desc": a.get("desc") or "", "kind": "semantic"})
    except Exception:
        pass
    return {"items": items[:max_items], "model": model}


def _catalog_text(items: List[Dict[str, Any]]) -> str:
    lines = []
    for it in items:
        lines.append(f"- {it['assetId']} | {it['assetType']} | {it['name']}"
                     f"{(' — ' + it['desc']) if it.get('desc') else ''}")
    return "\n".join(lines)


# ── 方向1: 范围圈定 ───────────────────────────────────────────

_SCOPE_SCHEMA = {
    "type": "object",
    "required": ["scope", "coverage", "missing"],
    "properties": {
        "scope": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["assetId", "assetType", "role", "businessReason"],
                "properties": {
                    "assetId": {"type": "string"},
                    "assetType": {"type": "string"},
                    "role": {"enum": ["core", "related"]},
                    "businessReason": {"type": "string"},
                },
            },
        },
        "coverage": {"type": "array", "items": {"type": "string"}},
        "missing": {"type": "array", "items": {"type": "string"}},
    },
}


def req_harness_scope(req: Dict[str, Any], root: Optional[str], project: Optional[str],
                      model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """方向1: 按业务需求圈定需要迭代的数据资产范围(核心/相关 + 业务理由)。"""
    from .req_agent import llm_sync
    _aggregate_high_best_effort(root, project, model_id)
    catalog = data_asset_catalog(root, project)
    items = catalog["items"]
    title = req.get("title", "")
    desc = req.get("desc", "")
    mode = req.get("mode") or ("greenfield" if not project else "existing")
    sys_prompt = (
        "你是资深架构师。根据业务需求，从候选数据资产中圈定本次迭代需要改动/联动的范围。\n"
        "规则：core=直接增删改查的资产；related=被牵连需要联动调整的资产；只从候选列表中选择，"
        "不要臆造不存在的资产 id；若需求需要新建资产，missing 里用『业务语义名(建议类型)』描述。\n"
        '只输出 JSON 对象(不要代码块)：{"scope":[{"assetId","assetType","role","businessReason"}],'
        '"coverage":[str], "missing":[str]}。'
    )
    user_prompt = (
        f"需求标题：{title}\n需求描述：{desc or '(未提供)'}\n模式：{mode}\n\n"
        f"候选数据资产目录({len(items)} 项)：\n{_catalog_text(items)}\n\n请圈定本次迭代的数据资产范围。"
    )
    res = llm_sync([{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}],
                   mode="structured", output_schema=_SCOPE_SCHEMA,
                   max_tokens=1800, model_id=model_id)
    if not res:
        return None
    output = res.get("output")
    if not isinstance(output, dict):
        return None
    proposal = output.get("scope") or []
    valid = [s for s in proposal if s.get("assetId") and s.get("assetType")]
    return {"proposal": valid, "coverage": output.get("coverage") or [],
            "missing": output.get("missing") or [], "catalog": items,
            "degraded": False}


def scope_diff(prev: List[Dict[str, Any]], proposal: List[Dict[str, Any]]) -> Dict[str, Any]:
    """方向1 迭代 diff：对比上版范围与本次圈定，输出增删/升降级。"""
    def key(a): return (a.get("assetId") or "", a.get("assetType") or "")
    prev_map = {key(a): a for a in prev or []}
    prop_map = {key(a): a for a in proposal or []}
    added, removed, promoted, demoted = [], [], [], []
    for k, a in prop_map.items():
        old = prev_map.get(k)
        if not old:
            added.append(a)
        elif (old.get("role"), a.get("role")) == ("related", "core"):
            promoted.append(a)
        elif (old.get("role"), a.get("role")) == ("core", "related"):
            demoted.append(a)
    for k, a in prev_map.items():
        if k not in prop_map:
            removed.append(a)
    return {"added": added, "removed": removed,
            "promoted": promoted, "demoted": demoted}


# ── 方向2: 设计方案 ───────────────────────────────────────────

_DESIGN_SCHEMA = {
    "type": "object",
    "required": ["dataChanges", "interfaceChanges", "semanticChanges", "steps", "landingNote"],
    "properties": {
        "dataChanges": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["action", "detail"],
                "properties": {
                    "assetId": {"type": "string"},
                    "assetType": {"type": "string"},
                    "action": {"enum": ["create", "alter", "drop", "extend"]},
                    "name": {"type": "string"},
                    "detail": {
                        "type": "object",
                        "properties": {
                            "desc": {"type": "string"},
                            "columns": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string"}, "type": {"type": "string"},
                                        "pk": {"type": "boolean"}, "fk": {"type": "string"},
                                    },
                                },
                            },
                            "relations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "from": {"type": "string"}, "to": {"type": "string"},
                                        "type": {"type": "string"}, "key": {"type": "string"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "interfaceChanges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assetId": {"type": "string"}, "assetType": {"type": "string"},
                    "action": {"type": "string"}, "name": {"type": "string"},
                    "detail": {
                        "type": "object",
                        "properties": {
                            "before": {"type": "string"}, "after": {"type": "string"},
                            "endpoints": {"type": "array", "items": {"type": "string"}},
                            "flows": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "reason": {"type": "string"},
                },
            },
        },
        "semanticChanges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "assetId": {"type": "string"}, "name": {"type": "string"},
                    "action": {"enum": ["create", "modify", "drop"]},
                    "reason": {"type": "string"},
                },
            },
        },
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"}, "desc": {"type": "string"},
                    "estMin": {"type": "integer"},
                    "context": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "landingNote": {"type": "string"},
    },
}


def _cols_from_llm(detail: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for c in (detail.get("columns") or []):
        if not c.get("name"):
            continue
        out.append({"name": c["name"], "type": c.get("type") or "string",
                    "nullable": True, "pk": bool(c.get("pk")),
                    "fk": c.get("fk") or "", "desc": "", "ast": {}})
    return out


def _rels_from_llm(detail: Dict[str, Any], tables_by_id: Dict[str, Dict[str, Any]],
                   fallback_id: str) -> List[Dict[str, Any]]:
    out = []
    for r in (detail.get("relations") or []):
        frm = r.get("from") or fallback_id
        to = r.get("to") or ""
        if not to:
            continue
        out.append({"from": frm, "to": to, "type": r.get("type") or "1:N",
                    "key": r.get("key") or "", "desc": ""})
    return out


def synthesize_after_model(before: List[Dict[str, Any]],
                           data_changes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """方向2 确定性 after-model 合成(纯函数)：把 dataChanges 应用到当前 ER 基线。

    返回深拷贝后的表列表：create→added、drop→removed、alter/extend→modified(列级 diff 计算)。
    """
    tables: List[Dict[str, Any]] = copy.deepcopy(before)
    by_id = {t.get("id"): t for t in tables}
    existing_ids = set(by_id)
    new_seq = 0
    for ch in data_changes or []:
        action = ch.get("action") or ""
        detail = ch.get("detail") or {}
        tid = (ch.get("assetId") or "").strip()
        if action == "create":
            new_seq += 1
            tid = tid or (ch.get("name") or "").strip() or f"NEW-{new_seq}"
            name = ch.get("name") or tid
            tables.append({
                "id": tid, "name": name, "level": "logical", "change": "added",
                "desc": detail.get("desc") or "", "columns": _cols_from_llm(detail),
                "relations": _rels_from_llm(detail, by_id, tid),
                "invariants": [], "ast": {},
            })
            by_id[tid] = tables[-1]
            continue
        if action == "drop":
            if tid in by_id:
                by_id[tid]["change"] = "removed"
            continue
        if action in ("alter", "extend"):
            if tid in by_id:
                t = by_id[tid]
                t["change"] = "modified"
                t["desc"] = detail.get("desc") or t.get("desc") or ""
                t["columns"] = _cols_from_llm(detail) or t["columns"]
                rels = _rels_from_llm(detail, by_id, tid)
                if rels:
                    t["relations"] = rels
            else:
                # alter 目标表不在基线 → 按 create 处理(避免丢变更)
                new_seq += 1
                tid2 = tid or (ch.get("name") or "").strip() or f"NEW-{new_seq}"
                tables.append({
                    "id": tid2, "name": ch.get("name") or tid2,
                    "level": "logical", "change": "added",
                    "desc": detail.get("desc") or "", "columns": _cols_from_llm(detail),
                    "relations": _rels_from_llm(detail, by_id, tid2),
                    "invariants": [], "ast": {},
                })
                by_id[tid2] = tables[-1]
    return tables


def _column_diff(before_cols: List[Dict[str, Any]], after_cols: List[Dict[str, Any]]) -> Dict[str, Any]:
    b = {c.get("name"): c for c in before_cols}
    a = {c.get("name"): c for c in after_cols}
    added = [c for c in after_cols if c.get("name") not in b]
    removed = [c for c in before_cols if c.get("name") not in a]
    modified = []
    for name, ac in a.items():
        bc = b.get(name)
        if not bc:
            continue
        if (bc.get("type") != ac.get("type")
                or bool(bc.get("pk")) != bool(ac.get("pk"))
                or (bc.get("fk") or "") != (ac.get("fk") or "")):
            modified.append({"name": name, "before": bc, "after": ac})
    return {"added": added, "removed": removed, "modified": modified}


def diff_models(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> Dict[str, Any]:
    """方向3 计划态对比：计算表级 + 列级差异。返回 after 表(带 change)与逐表列 diff。"""
    b = {t.get("id"): t for t in before}
    a = {t.get("id"): t for t in after}
    summary = {"added": 0, "removed": 0, "modified": 0, "same": 0}
    column_diffs: Dict[str, Any] = {}
    for tid, t in a.items():
        change = t.get("change") or "same"
        summary[change] = summary.get(change, 0) + 1
        if change == "modified" and tid in b:
            column_diffs[tid] = _column_diff(b[tid].get("columns") or [],
                                             t.get("columns") or [])
    return {"summary": summary, "tables": after, "columnDiffs": column_diffs}


def _aggregate_high_best_effort(root: Optional[str], project: Optional[str],
                                model_id: Optional[str] = None) -> None:
    """需求分析/设计前按需聚合 H 级业务概念资产(失败不阻塞，仅记录日志)。"""
    try:
        from .semantic_assets import _aggregate_high
        res = _aggregate_high(root, project, model_id=model_id)
        if res.get("count"):
            logger.info("[design] 按需聚合 H 级资产: %d 个", res.get("count"))
    except Exception as e:
        logger.warning("[design] 按需聚合 H 级资产失败(忽略): %s", e)


def req_harness_design(req: Dict[str, Any], analysis: Dict[str, Any],
                       root: Optional[str], project: Optional[str],
                       model_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """方向2: 基于需求 + 已圈定范围生成设计方案(数据层/接口流程层/语义层)。"""
    from .req_agent import llm_sync
    _aggregate_high_best_effort(root, project, model_id)
    catalog = data_asset_catalog(root, project)
    model = catalog["model"]
    before = [_norm_table(t) for t in (model.get("erTables") or [])]
    scope = (analysis or {}).get("assetScope") or []
    title = req.get("title", "")
    desc = req.get("desc", "")
    sys_prompt = (
        "你是资深架构师。基于业务需求与已圈定数据资产范围，输出详细设计方案。\n"
        "dataChanges 逐条描述数据资产的增删改查：action ∈ create/alter/drop/extend；"
        "detail.columns 为目标最终字段列表(create/alter/extend 都给全量)，"
        "detail.relations 为目标最终表关系；drop 只需 assetId。\n"
        "interfaceChanges 描述接口/流程层变更(服务/API/数据流)。\n"
        "semanticChanges 描述语义资产(数据结构/处理流程/控制逻辑)的创建/修改/删除。\n"
        "steps 为落地方案步骤(标题/说明/预估分钟/上下文)。\n"
        "只输出 JSON 对象(不要代码块)。"
    )
    user_prompt = (
        f"需求：{title}\n描述：{desc or '(未提供)'}\n"
        f"已圈定范围({len(scope)} 项)：\n"
        + "\n".join(f"- {s.get('assetId')} | {s.get('assetType')} | {s.get('role')}"
                    for s in scope) + "\n\n"
        f"当前 ER 基线({len(before)} 表)：\n"
        + "\n".join(f"- {t['id']} ({t['name']}) cols={len(t['columns'])}"
                    for t in before) + "\n\n"
        "请输出详细设计方案。"
    )
    res = llm_sync([{"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt}],
                   mode="structured", output_schema=_DESIGN_SCHEMA,
                   max_tokens=3200, model_id=model_id)
    if not res:
        return None
    output = res.get("output")
    if not isinstance(output, dict):
        return None
    data_changes = output.get("dataChanges") or []
    after = synthesize_after_model(before, data_changes)
    diff = diff_models(before, after)
    design = {
        "dataChanges": data_changes,
        "interfaceChanges": output.get("interfaceChanges") or [],
        "semanticChanges": output.get("semanticChanges") or [],
        "steps": output.get("steps") or [],
        "landingNote": output.get("landingNote") or "",
        "createdAt": _ts(),
    }
    return {"design": design, "beforeTables": before, "afterTables": after,
            "diff": diff}


# ── 方向3: 修改前后对比 ───────────────────────────────────────

def _semantic_diff_planned(design: Dict[str, Any]) -> Dict[str, Any]:
    """方向3 计划态语义资产差异(来自设计方案 semanticChanges)。"""
    summary = {"create": 0, "modify": 0, "drop": 0}
    for c in (design.get("semanticChanges") or []):
        a = c.get("action") or "modify"
        summary[a] = summary.get(a, 0) + 1
    return {"summary": summary, "items": design.get("semanticChanges") or []}


def _compare_actual(model: Dict[str, Any], design: Dict[str, Any]) -> Dict[str, Any]:
    """方向3 实施后实际对比：计划 after vs 实施后实际模型/语义资产。"""
    planned_after = {t.get("id"): t for t in (design.get("afterTables") or [])}
    actual = {t.get("id"): _norm_table(t) for t in (model.get("erTables") or [])}
    deviations: List[Dict[str, Any]] = []
    for tid, t in planned_after.items():
        change = t.get("change") or "same"
        if change == "added":
            if tid not in actual:
                deviations.append({"level": "er", "kind": "未落地(表未创建)",
                                   "planned": f"{tid} ({t.get('name')})", "actual": "—",
                                   "note": "计划新建，实施后未发现"})
        elif change == "removed":
            if tid in actual:
                deviations.append({"level": "er", "kind": "未落地(表未删除)",
                                   "planned": f"{tid} ({t.get('name')})", "actual": "仍存在",
                                   "note": "计划删除，实施后仍存在"})
        elif change == "modified":
            if tid not in actual:
                deviations.append({"level": "er", "kind": "未落地(目标表缺失)",
                                   "planned": f"{tid} ({t.get('name')})", "actual": "—",
                                   "note": "计划修改，实施后目标表不存在"})
            else:
                col = _column_diff(t.get("columns") or [],
                                   actual[tid].get("columns") or [])
                if col["added"] or col["removed"] or col["modified"]:
                    deviations.append({"level": "er", "kind": "列级偏差",
                                       "planned": f"{tid}",
                                       "actual": f"+{len(col['added'])} -{len(col['removed'])} ~{len(col['modified'])}",
                                       "note": "计划列与实施后列不一致"})
    planned_ids = set(planned_after)
    for tid in actual:
        if tid not in planned_ids:
            deviations.append({"level": "er", "kind": "额外变更",
                               "planned": "—", "actual": tid,
                               "note": "实施后出现计划外的新表"})
    return {"deviations": deviations}


def compare_requirement(req: Dict[str, Any], mode: str = "planned",
                        root: Optional[str] = None, project: Optional[str] = None) -> Dict[str, Any]:
    """方向3 对比入口。planned=计划态合成对比；actual=实施后回读实际对比。"""
    design = (req.get("design") or {})
    before = design.get("beforeTables") or []
    after = design.get("afterTables") or []
    if mode == "actual":
        model = build_architecture_model(root, project)
        actual = _compare_actual(model, design)
        return {"mode": "actual", "summary": diff_models(before, after)["summary"],
                "semanticDiff": _semantic_diff_planned(design),
                "deviations": actual["deviations"],
                "beforeTables": before, "afterTables": after}
    diff = diff_models(before, after)
    return {"mode": "planned", "summary": diff["summary"],
            "columnDiffs": diff["columnDiffs"],
            "semanticDiff": _semantic_diff_planned(design),
            "beforeTables": before, "afterTables": after,
            "deviations": []}


# ── REST ──────────────────────────────────────────────────────

@router.post("/requirements/analyze/scope")
async def api_scope(request: Request):
    """方向1: 圈定数据资产范围。body: {req, prevScope?, root?, project?, modelId?}。"""
    body = await request.json()
    req = body.get("req") or {}
    if not req.get("title"):
        return err(400, "需求标题不能为空")
    from .req_agent import llm_sync  # noqa: F401  (确保通道就绪即抛错)
    try:
        res = req_harness_scope(req, body.get("root"), body.get("project"),
                                model_id=body.get("modelId") or req.get("modelId"))
    except Exception as e:
        logger.warning("[design] scope harness failed: %s", e)
        return err(502, f"范围圈定失败：{e}")
    if not res:
        return err(502, "范围圈定未生成结果：请确认 LLM 模型已配置且 KB 可达后重试。")
    diff = scope_diff(body.get("prevScope") or [], res["proposal"])
    return ok({"proposal": res["proposal"], "coverage": res["coverage"],
               "missing": res["missing"], "catalog": res["catalog"], "diff": diff})


@router.post("/requirements/{req_id}/design")
async def api_generate_design(req_id: str, request: Request):
    """方向2: 生成设计方案并持久化到需求.design。body: {analysis?, root?, project?, modelId?}。"""
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "Requirement not found")
    body = await request.json()
    analysis = body.get("analysis") or (row.get("analysis") or {})
    req = {"id": row["id"], "title": row.get("title") or "", "desc": row.get("desc") or ""}
    try:
        res = req_harness_design(req, analysis, body.get("root"), body.get("project"),
                                 model_id=body.get("modelId"))
    except Exception as e:
        logger.warning("[design] design harness failed: %s", e)
        return err(502, f"设计方案生成失败：{e}")
    if not res:
        return err(502, "设计方案未生成：请确认 LLM 模型已配置且 KB 可达后重试。")
    # 连同合成后的 before/after 表一并持久化，供离线对比(计划态/实施后)使用。
    payload = dict(res["design"])
    payload["beforeTables"] = res["beforeTables"]
    payload["afterTables"] = res["afterTables"]
    store.RequirementsStore.update(req_id, {"design": payload, "updatedAt": _ts()})
    return ok({"design": res["design"], "beforeTables": res["beforeTables"],
               "afterTables": res["afterTables"], "diff": res["diff"]})


@router.get("/requirements/{req_id}/design")
async def api_get_design(req_id: str, root: Optional[str] = None, project: Optional[str] = None):
    """读取已生成的设计方案(含对比所需 before/after 表)。"""
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "Requirement not found")
    design = row.get("design") or {}
    if not design:
        return ok({"design": None, "beforeTables": [], "afterTables": [], "diff": None})
    before = design.get("beforeTables") or []
    after = design.get("afterTables") or []
    if not before:
        # 旧数据无持久化 before → 用当前 KB 基线兜底。
        model = build_architecture_model(root, project)
        before = [_norm_table(t) for t in (model.get("erTables") or [])]
    diff = diff_models(before, after)
    return ok({"design": design, "beforeTables": before,
               "afterTables": after, "diff": diff})


@router.post("/requirements/{req_id}/compare")
async def api_compare(req_id: str, request: Request):
    """方向3: 修改前后对比。body: {mode: planned|actual, root?, project?}。"""
    row = store.RequirementsStore.get(req_id)
    if not row:
        return err(404, "Requirement not found")
    body = await request.json()
    mode = body.get("mode") or "planned"
    try:
        res = compare_requirement(row, mode=mode,
                                  root=body.get("root"), project=body.get("project"))
    except Exception as e:
        logger.warning("[design] compare failed: %s", e)
        return err(502, f"对比失败：{e}")
    return ok(res)
