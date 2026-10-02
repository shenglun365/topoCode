"""错误提炼(P1) — 会话错误历史 → error_pattern 知识单元(项目级)。

设计裁决(2026-09-17):
- **手动触发**: 用户按需调用(REST POST /sessions/{id}/distill-errors), 无自动钩子;
  前端触发位后续再定(先做后端)。
- **提炼即沉淀**: build 与 land 分离(扩展点=函数边界, 未来可插确认环节),
  本期直连——提炼产出直接落库, 不设中间确认。
- **归因来源**: coding agent 执行回执(execution_report failed 单元)——排除故障后
  的归因分析以执行器产出为准; 纯 chat 错误(error 单元)如实标注「无执行回执材料」。
- **签名=粗类别**: 不做细分指纹; 同 (projectId, signature) 已存在 → 追加场景
  计数, 不增行。会话 id 记入 refs 溯源。

分层: 本模块为编排层(读 units + 调轻任务 + 写 units), 依赖注入与
memory.units 同款(_store 惰性解析防循环导入)。轻任务模型经
resolve_light_task_model("distill", cfg) 注入(护栏 R3)。
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 提炼输出 schema(粗类别签名 + 详细归因 + 修正过程)
DISTILL_SCHEMA = {
    "type": "object",
    "properties": {
        "patterns": {
            "type": "array", "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "signature": {"type": "string",
                                  "description": "粗类别签名, 如: 构建失败/依赖缺失/工具调用失败/LLM 空返回"},
                    "cause": {"type": "string",
                              "description": "排除故障后的归因分析(依据执行回执; 详细、具体)"},
                    "fix": {"type": "string",
                            "description": "修正过程/修复方式(已验证或建议)"},
                },
                "required": ["signature", "cause", "fix"],
            },
        },
    },
    "required": ["patterns"],
}

_SYSTEM = (
    "你是错误提炼器。输入是一次会话中的错误记录(回合错误 + 任务失败回执)。"
    "把它们归纳为至多 5 条可复用的错误模式: signature=粗类别(短语); "
    "cause=排除故障后的归因分析(优先依据任务失败回执——那是编码执行器的产出; "
    "没有回执材料时如实写「无执行回执材料, 依据错误文本推断」); "
    "fix=修正过程或修复建议。只输出结构化 JSON。"
)


def _store():
    from ... import store
    return store


def collect_error_material(conv_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """错误材料收集: error 单元 + failed 回执单元(新→旧), 排除已提炼过的。"""
    store = _store()
    units = store.ContextUnitsStore.all(conversation_id=conv_id, limit=200)
    # 已提炼源 id(项目级 error_pattern 的 refs.sourceIds)——不重复提炼
    pid = ""
    conv = store.ConversationsStore.get(conv_id) or {}
    pid = conv.get("projectId") or ""
    distilled: set = set()
    for p in store.ContextUnitsStore.all(project_id=pid, type_="error_pattern",
                                         limit=200):
        for sid in ((p.get("refs") or {}).get("sourceIds") or []):
            distilled.add(str(sid))
    out: List[Dict[str, Any]] = []
    for u in units:
        if u.get("type") not in ("error", "execution_report"):
            continue
        if u.get("id") in distilled:
            continue
        is_receipt = u.get("type") == "execution_report"
        if is_receipt and "failed" not in (u.get("title") or ""):
            continue  # 回执只取失败(归因材料); 成功回执非错误
        out.append({"id": u.get("id") or "", "kind": u.get("type") or "",
                    "title": u.get("title") or "",
                    "body": (u.get("content") or "")[:1500]})
        if len(out) >= max(1, int(limit)):
            break
    return out


def build_error_patterns(material: List[Dict[str, Any]],
                         cfg: Any = None) -> List[Dict[str, Any]]:
    """轻任务提炼(提炼即沉淀的 build 半程)。失败返回 [](调用方如实回执)。"""
    if not material:
        return []
    from ..reflection.repair import summarize_task
    from ...arch_routes.agent_roles import load_light_tasks_cfg
    from ..governance.light_tasks import resolve_light_task_model
    lines = []
    for m in material:
        tag = "失败回执(编码执行器产出)" if m["kind"] == "execution_report" else "回合错误"
        lines.append(f"### [{tag}] {m['title']}\n{m['body']}")
    out = summarize_task(
        task_id="error_distill",
        system=_SYSTEM,
        material=f"错误记录:\n\n" + "\n\n".join(lines)[:12000],
        mode="structured", output_schema=DISTILL_SCHEMA,
        model_id=resolve_light_task_model("distill", cfg if cfg is not None
                                          else load_light_tasks_cfg()),
        parse=lambda r: r.get("output") if isinstance(r.get("output"), dict) else None)
    if not out["ok"] or not isinstance(out["output"], dict):
        return []
    rows = out["output"].get("patterns") or []
    return [p for p in rows
            if isinstance(p, dict) and (p.get("signature") or "").strip()]


def land_error_pattern(project_id: str, pattern: Dict[str, Any],
                       conv_id: str, source_ids: List[str]) -> Dict[str, Any]:
    """落库(land 半程): 同签名(项目级)追加场景不增行。返回单元行。"""
    store = _store()
    sig = str(pattern.get("signature") or "").strip()[:60]
    cause = str(pattern.get("cause") or "").strip()
    fix = str(pattern.get("fix") or "").strip()
    existing = [u for u in store.ContextUnitsStore.all(
        project_id=project_id, type_="error_pattern", limit=200)
        if (u.get("title") or "") == f"错误模式: {sig}"]
    stamp = time.strftime("%m-%d %H:%M")
    if existing:
        u = existing[0]
        refs = dict(u.get("refs") or {})
        occ = int(refs.get("occurrences") or 1) + 1
        sids = [str(x) for x in (refs.get("sourceIds") or [])]
        sids += [str(x) for x in source_ids if str(x) not in sids]
        convs = [str(x) for x in (refs.get("convs") or [])]
        if conv_id and conv_id not in convs:
            convs.append(conv_id)
        refs.update({"occurrences": occ, "sourceIds": sids[:50],
                     "convs": convs[:20], "lastSeenAt": int(time.time() * 1000)})
        content = (f"**归因**: {cause}\n\n**修正**: {fix}\n\n"
                   f"场景 ×{occ} · 最近 {stamp} · 来源会话 {', '.join(convs[:5]) or '-'}")
        row = store.ContextUnitsStore.update(
            u["id"], {"content": content, "refs": refs})
        return row or u
    row = store.ContextUnitsStore.create({
        "conversationId": conv_id, "projectId": project_id,
        "type": "error_pattern",
        "title": f"错误模式: {sig}",
        "content": (f"**归因**: {cause}\n\n**修正**: {fix}\n\n"
                    f"场景 ×1 · 最近 {stamp} · 来源会话 {conv_id or '-'}"),
        "refs": {"occurrences": 1, "sourceIds": [str(x) for x in source_ids][:50],
                 "convs": [conv_id] if conv_id else [],
                 "lastSeenAt": int(time.time() * 1000)},
        "importance": 2})
    # 需求跟踪台账: 新模式挂「异常」条目(同签名追加不重复挂), 失败不阻断
    try:
        from ...store.tracking import emit as _tr_emit
        from ...store.states import TRACK_DONE
        _tr_emit(category="异常", title=f"错误模式: {sig}",
                 content=f"**归因**: {cause}\n**修正**: {fix}"[:1000],
                 action_type="分析", creator_role="architect",
                 state=TRACK_DONE, result="已提炼为错误模式(项目级)",
                 result_state="ok",
                 ref_type="unit", ref_id=row.get("id") or "",
                 conversation_id=conv_id, project_id=project_id)
    except Exception:  # noqa: BLE001
        pass
    return row


def distill_errors(conv_id: str, limit: int = 20,
                   cfg: Any = None) -> Dict[str, Any]:
    """入口: 收集→提炼→落库。返回回执(材料数/模式数/明细), 失败如实。"""
    store = _store()
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return {"ok": False, "error": "conversation-not-found"}
    material = collect_error_material(conv_id, limit=limit)
    if not material:
        return {"ok": True, "materialCount": 0, "patterns": [],
                "note": "无未提炼的错误记录"}
    patterns = build_error_patterns(material, cfg=cfg)
    if not patterns:
        return {"ok": False, "error": "distill-failed",
                "materialCount": len(material)}
    pid = conv.get("projectId") or ""
    landed = []
    for p in patterns:
        try:
            row = land_error_pattern(pid, p, conv_id,
                                     [m["id"] for m in material])
            landed.append({"id": (row or {}).get("id") or "",
                           "signature": str(p.get("signature") or "")})
        except Exception as e:  # noqa: BLE001 — 单条落库失败不阻断其余
            logger.warning("[distill] error_pattern 落库失败: %s", e)
    return {"ok": True, "materialCount": len(material),
            "count": len(landed), "patterns": landed}
