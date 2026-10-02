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


def register_all() -> None:
    from . import job_runner
    job_runner.register("node_brief", _job_node_brief)
    job_runner.register("edge_notes", _job_edge_notes)
    job_runner.register("line_notes", _job_line_notes)
    job_runner.register("pseudo", _job_pseudo)
    job_runner.register("asset_desc", _job_asset_desc)
    job_runner.register("explain_logic", _job_explain_logic)
