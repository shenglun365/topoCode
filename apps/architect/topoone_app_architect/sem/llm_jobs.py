"""轻解析类 LLM 作业（B3：资产解析统一入任务中心排队）。

资产卡/逻辑卡的即时与手动解析（节点简介/关系描述/逐行解读/伪码解释/功能
摘要/逻辑讲解）原为 HTTP 端点内嵌 llm_sync 直调——连点多资产并发拥堵且
任务中心不可见。现统一 job 化：llm=True 过全局串行闸门 + 任务中心浮窗
可见排队/运行 + 同资产幂等(job_runner scope 摘要键)。

端点侧（engine.py / arch_routes/logic_views.py）改为「提交作业 + 等待
完成 + 透传 result」——HTTP 响应与原直调同构，FE 调用零改动。
"""
from __future__ import annotations

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


def _sc(ctx) -> dict:
    return ctx.scope or {}


def _job_node_brief(ctx) -> dict:
    from .engine import generate_node_brief
    from ..store import SemanticAssetsStore
    sc = _sc(ctx)
    a = SemanticAssetsStore.get(sc.get("assetId") or "")
    if not a:
        return {"brief": "", "cached": False, "degraded": True, "error": "资产不存在"}
    return generate_node_brief(a, sc.get("root"), sc.get("project"),
                               sc.get("modelId") or None, bool(sc.get("force")))


def _job_edge_notes(ctx) -> dict:
    from .engine import generate_edge_notes
    sc = _sc(ctx)
    return generate_edge_notes(sc.get("assetId") or "", sc.get("root"), sc.get("project"),
                               sc.get("modelId") or None, bool(sc.get("force")))


def _job_line_notes(ctx) -> dict:
    from .engine import generate_line_notes
    sc = _sc(ctx)
    return generate_line_notes(sc.get("assetId") or "", sc.get("file") or "",
                               int(sc.get("start") or 0), int(sc.get("end") or 0),
                               sc.get("root"), sc.get("project"),
                               sc.get("modelId") or None, bool(sc.get("force")))


def _job_pseudo(ctx) -> dict:
    from .engine import generate_pseudo
    sc = _sc(ctx)
    return generate_pseudo(sc.get("assetId") or "", sc.get("root"), sc.get("project"),
                           sc.get("modelId") or None, bool(sc.get("force")))


def _job_asset_desc(ctx) -> dict:
    from .engine import generate_desc
    sc = _sc(ctx)
    return generate_desc(sc.get("assetId") or "", sc.get("root"), sc.get("project"),
                         sc.get("modelId") or None)


def _job_explain_logic(ctx) -> dict:
    """逻辑视图 AI 讲解(原 logic_views.py 端点内联逻辑迁此，job 化)。"""
    from ..store import LogicViewsStore, SemanticAssetsStore
    from ..store.logic_views import detail_fingerprint_of
    from .logic_induce import explain_view
    sc = _sc(ctx)
    view_id = sc.get("viewId") or ""
    view = LogicViewsStore.get(view_id)
    if not view:
        return {"error": "视图不存在", "summary": "视图不存在"}
    members: list = json.loads(view.get("memberIds") or "[]")
    rows = [SemanticAssetsStore.get(m) for m in members]
    fp = detail_fingerprint_of([(r or {}).get("srcHash") or "∅" for r in rows])
    cached = (view.get("detail") or "") and (view.get("detailFp") or "") == fp
    if cached and not sc.get("force"):
        return {"viewId": view_id, "detail": view.get("detail"),
                "cached": True, "stale": False, "fingerprint": fp}
    assets = [r for r in rows if r]
    if not assets:
        return {"error": "视图无可解析成员资产", "summary": "成员缺失"}
    detail = explain_view(view, assets, sc.get("modelId") or None)
    if not detail:
        return {"error": "LLM 未返回内容", "summary": "讲解生成失败"}
    LogicViewsStore.update(view_id, {"detail": detail, "detailFp": fp})
    return {"viewId": view_id, "detail": detail,
            "cached": False, "stale": False, "fingerprint": fp}


def _job_induce_scope(ctx) -> dict:
    """图谱范围逻辑解析(B3+跳数可控)：每组(核心+跳数邻域)→逻辑视图(source=graph)
    + LLM 概括 + 讲解指纹(成员变化自动失效)。"""
    import time as _time
    from ..store import LogicViewsStore, SemanticAssetsStore
    from ..store.logic_views import detail_fingerprint_of
    from .logic_extract import summarize_members
    from .paths import project_id_for, resolve_root
    sc = _sc(ctx)
    groups = sc.get("groups") or []
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败", "summary": "失败：root 解析失败"}
    pid = project_id_for(rid, sc.get("project"))
    view_ids: list = []
    model_id = sc.get("modelId") or None
    for g in groups:
        core_id = g.get("coreId") or ""
        members = [m for m in (g.get("memberIds") or []) if m]
        if not members:
            continue
        rows = [SemanticAssetsStore.get(m) for m in members]
        assets = [r for r in rows if r]
        if not assets:
            continue
        core_name = (SemanticAssetsStore.get(core_id) or {}).get("name") or core_id
        name = f"{core_name}·{g.get('hops') or 1}跳逻辑"[:80]
        summary = summarize_members(assets, model_id)
        view = LogicViewsStore.create(
            pid, name, [core_id] if core_id else members[:1], members,
            summary=summary, source="graph")
        fp = detail_fingerprint_of([(r or {}).get("srcHash") or "∅" for r in rows])
        LogicViewsStore.update(view["id"], {"detailFp": fp})
        view_ids.append(view["id"])
        _time.sleep(0)
    return {"viewIds": view_ids[:20], "count": len(view_ids),
            "summary": f"图谱范围解析 {len(view_ids)} 条逻辑视图"}


# ── 缓存预检(wait_llm_job 提交作业前快查：命中直接返回，不建作业行) ──
# 资产卡高频点击(切换选中/多轮重复)时，已生成结果不再重复提交作业——
# 任务中心不再堆积「已完成」记录、作业线程不再空转(实测 2026-10-03)。

def _pre_node_brief(sc: dict) -> Optional[dict]:
    from ..store import SemanticAssetsStore
    a = SemanticAssetsStore.get(sc.get("assetId") or "")
    if not a:
        return None
    fresh = (a.get("status") == "active") and not a.get("needsUpdate")
    existing = (a.get("nodeBrief") or "").strip()
    if fresh and existing and not sc.get("force"):
        return {"brief": existing, "cached": True, "degraded": False}
    return None


def _pre_edge_notes(sc: dict) -> Optional[dict]:
    """复刻 generate_edge_notes 缓存判定(纯内存：fresh + 全 key 覆盖)。"""
    from ..store import SemanticAssetsStore
    from .engine import project_id_for
    from .relation_index import relation_target_index as _relation_target_index, resolve_relation_target as _resolve_relation_target
    a = SemanticAssetsStore.get(sc.get("assetId") or "")
    if not a:
        return None
    pid = project_id_for(sc.get("root"), sc.get("project"))
    if not pid:
        return None
    fresh = (a.get("status") == "active") and not a.get("needsUpdate")
    if not fresh or sc.get("force"):
        return None
    try:
        old = json.loads((a.get("edgeNotes") or "") or "{}")
    except Exception:
        return None
    idx = _relation_target_index([x for x in SemanticAssetsStore.all_status(pid, limit=4000)
                                  if x.get("status") != "deleted"])
    keys = []
    for rel in (a.get("detail") or {}).get("relations") or []:
        tgt, resolved = _resolve_relation_target((rel.get("target") or "").strip(), idx)
        if tgt and resolved:
            keys.append(f"{a['id']}|{tgt}")
    if not keys:
        return None
    if all(k in old and isinstance(old.get(k), dict) and (old[k] or {}).get("desc") for k in keys):
        return {"notes": {k.split("|", 1)[1]: (old[k] or {}).get("desc") or "" for k in keys},
                "cached": True, "degraded": False}
    return None


def _pre_explain_logic(sc: dict) -> Optional[dict]:
    from ..store import LogicViewsStore, SemanticAssetsStore
    from ..store.logic_views import detail_fingerprint_of
    view = LogicViewsStore.get(sc.get("viewId") or "")
    if not view or sc.get("force"):
        return None
    rows = [SemanticAssetsStore.get(m) for m in json.loads(view.get("memberIds") or "[]")]
    fp = detail_fingerprint_of([(r or {}).get("srcHash") or "∅" for r in rows])
    if (view.get("detail") or "") and (view.get("detailFp") or "") == fp:
        return {"viewId": view.get("id"), "detail": view.get("detail"),
                "cached": True, "stale": False, "fingerprint": fp}
    return None


_PRECHECKS = {
    "node_brief": _pre_node_brief,
    "edge_notes": _pre_edge_notes,
    "explain_logic": _pre_explain_logic,
}


def precheck_cached(kind: str, scope: dict) -> Optional[dict]:
    """有缓存语义的轻解析作业预检：返回 dict=缓存命中(免作业)；None=需生成。"""
    fn = _PRECHECKS.get(kind)
    return fn(scope or {}) if fn else None


def register_all() -> None:
    from . import job_runner
    job_runner.register("node_brief", _job_node_brief)
    job_runner.register("edge_notes", _job_edge_notes)
    job_runner.register("line_notes", _job_line_notes)
    job_runner.register("pseudo", _job_pseudo)
    job_runner.register("asset_desc", _job_asset_desc)
    job_runner.register("explain_logic", _job_explain_logic)
    job_runner.register("induce_scope", _job_induce_scope)
