"""语义资产/代码读取工具域(asset.semantic.* + code.read_symbols) — M3 自 req_agent 机械迁出(逐字保真, 注册随定义点)。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..registry import register_architect_tool

logger = logging.getLogger("arch_routes.req_agent")


@register_architect_tool(
    "asset.semantic.stats",
    "语义资产统计：总量/按六类(kind)/按粒度(level)/状态(active/stale/deleted/needsUpdate)。"
    "「有多少资产」「各类数量」等统计类提问用",
)
def tool_semantic_stats(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from ....arch_routes.sem.engine import (SEMANTIC_KINDS, SEMANTIC_LEVELS, _lazy_reconcile,
                                            project_id_for)
    from ....arch_routes import store
    try:
        _lazy_reconcile(root, project)
        pid = project_id_for(root, project)
        by_kind = {k: store.SemanticAssetsStore.count(pid, kind=k) for k in SEMANTIC_KINDS}
        by_level = {lv: store.SemanticAssetsStore.count(pid, level=lv) for lv in SEMANTIC_LEVELS}
        rows = store.SemanticAssetsStore.all_status(pid, limit=4000)
        status: Dict[str, int] = {"active": 0, "stale": 0, "deleted": 0, "needsUpdate": 0}
        for a in rows:
            status[a.get("status") or "active"] = status.get(a.get("status") or "active", 0) + 1
            if a.get("needsUpdate"):
                status["needsUpdate"] += 1
        return {"total": sum(by_kind.values()), "byKind": by_kind,
                "byLevel": by_level, "status": status}
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.stats failed: %s", e)
        return {"error": str(e)}


# ── 语义数据资产工具 ─────────────────────────────────────────────

@register_architect_tool(
    "asset.semantic.search",
    "检索当前项目已提取的语义数据资产(六类 entity/contract/state/rule/process/decision)，"
    "支持 kind 类别 + level 粒度(business/implementation/logic) + scopes 组件范围过滤与关键词命中。"
    "返回资产(含 AST 锚点)。",
)
def tool_semantic_search(root: Optional[str], project: Optional[str],
                         text: str = "", kind: str = "", level: str = "",
                         limit: int = 20, offset: int = 0,
                         scopes: Optional[List[str]] = None,
                         includeGlobal: bool = False) -> List[Dict[str, Any]]:
    from ....arch_routes import semantic_assets as S
    try:
        rows = S.search(root, project, text, kind, limit, offset,
                        scopes=scopes, level=level)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.search failed: %s", e)
        rows = []
    # WS8-S4: includeGlobal 时合并主库全局桶(按需开关, R7 禁全量注入)
    if includeGlobal and text.strip():
        try:
            from ....arch_routes.store.base import GLOBAL_PID, _db, _row_to_api
            like = f"%{text.strip()}%"
            grows = _db().fetchall(
                "SELECT * FROM arch_semantic_assets WHERE project_id = ? "
                "AND status = 'active' AND (name LIKE ? OR desc LIKE ?) LIMIT ?",
                (GLOBAL_PID, like, like, max(3, int(limit) // 4)))
            have = {r.get("id") for r in rows}
            for g in grows:
                d = _row_to_api(g)
                if d.get("id") in have:
                    continue
                d["scopeGlobal"] = True
                rows.append(d)
        except Exception as e:
            logger.debug("[req_agent] global layer merge skipped: %s", e)
    return rows


@register_architect_tool(
    "asset.semantic.extract",
    "按指令从最新代码提取语义数据资产(六类: entity/contract/state/rule/process/decision，实现层)并落库。"
    "指令化提取的唯一执行入口：规则定死类别+tAgent 定向+锚定代码段+语义解释。"
    "参数 scope={type: comm|files|symbols|project, key?, files?, symbols?}，"
    "comm 时 key 为**组件ID**(comm-…，权威范围)；kinds 可选[六类]。"
    "返回紧凑摘要 {count, byKind, degraded, source[, error, candidates, reason]}。",
)
def tool_semantic_extract(root: Optional[str], project: Optional[str],
                          scope: Dict[str, Any] = None,
                          kinds: Optional[List[str]] = None) -> Dict[str, Any]:
    from ....arch_routes import semantic_assets as S
    scope = scope or {}
    try:
        res = S.extract_scope(root, project,
                              scope.get("type") or "project",
                              scope.get("key") or "",
                              scope.get("files") or [],
                              scope.get("symbols") or [],
                              kinds=kinds)
    except Exception as e:
        logger.warning("[req_agent] asset.semantic.extract failed: %s", e)
        return {"count": 0, "degraded": True, "error": str(e)}
    # 紧凑摘要(供 agent 如实汇报；不回传全量资产对象，省对话上下文)
    from collections import Counter
    assets = res.get("assets") or []
    summary: Dict[str, Any] = {
        "count": res.get("count", len(assets)),
        "byKind": dict(Counter(a.get("kind") for a in assets)),
        "degraded": res.get("degraded", False),
        "source": res.get("source"),
    }
    if res.get("error"):
        summary["error"] = res["error"]
    if res.get("candidates"):
        summary["candidates"] = res["candidates"]
    if res.get("reason"):
        summary["reason"] = res["reason"]
    return summary


@register_architect_tool(
    "asset.semantic.detail",
    "读取单个语义数据资产的完整信息(描述/结构化细节/AST 锚点)，供需求/设计引用确认。",
)
def tool_semantic_detail(asset_id: str, root: Optional[str] = None,
                         project: Optional[str] = None) -> Optional[Dict[str, Any]]:
    from ....arch_routes import semantic_assets as S
    return S.detail(asset_id)


@register_architect_tool(
    "asset.semantic.mappings",
    "查询语义数据资产对应的代码映射(文件/行号/符号)，锁定「改哪里」的精确位置。",
)
def tool_semantic_mappings(asset_ids: List[str], root: Optional[str] = None,
                           project: Optional[str] = None) -> List[Dict[str, Any]]:
    from ....arch_routes import semantic_assets as S
    out = []
    for i in (asset_ids or []):
        out += S.mappings(i, root, project)
    return out[:12]


@register_architect_tool(
    "asset.semantic.reconcile",
    "校验语义数据资产新鲜度(git/文件哈希比对)：标记因文件变更或新增文件影响而过期的资产为「需更新后使用」。返回失效清单。",
)
def tool_semantic_reconcile(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from ....arch_routes import semantic_assets as S
    return S.reconcile_semantic(root, project, force=True)


@register_architect_tool(
    "asset.semantic.refresh",
    "更新单个过期(需更新)的语义数据资产：增量重提其所属范围；失败则软删并离线重新生成。返回新状态。",
)
def tool_semantic_refresh(asset_id: str, root: Optional[str] = None,
                          project: Optional[str] = None) -> Dict[str, Any]:
    from ....arch_routes import semantic_assets as S
    return S.handle_stale_asset(asset_id, root, project)


# ── 对话式提取工具（plan-C §4.1 skills+tools calling；M0 §8 工具清单） ──

@register_architect_tool(
    "code.read_symbols",
    "读取项目源码片段(按文件/符号/行号)，对话式提取前先看真实代码。"
    '参数 {"file": "相对路径", "symbol"?: "符号名", "startLine"?: 行, "endLine"?: 行}。',
)
def tool_code_read_symbols(root: Optional[str] = None, project: Optional[str] = None,
                           file: str = "", symbol: str = "",
                           startLine: int = 0, endLine: int = 0) -> Dict[str, Any]:
    import os
    from ....arch_routes.semantic_assets import resolve_root, project_id_for
    from ....arch_routes import store as _store
    rpath = resolve_root(root, project)
    if not rpath or not file:
        return {"error": "缺少项目根或文件路径"}
    full = os.path.realpath(os.path.join(rpath, file))
    base = os.path.realpath(rpath)
    if not full.startswith(base + os.sep):
        return {"error": f"路径越界: {file}"}
    if not os.path.isfile(full):
        return {"error": f"文件不存在: {file}"}
    try:
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            lines = f.read().splitlines()
    except Exception as e:
        return {"error": f"读取失败: {e}"}
    s, e = int(startLine or 0), int(endLine or 0)
    sym_info: Optional[Dict[str, Any]] = None
    if symbol and not (s and e):
        pid = project_id_for(root, project)
        cached = _store.AstCacheStore.get(pid, file.replace("\\", "/"))
        for n in (cached or {}).get("symbols") or []:
            if (n.get("name") or "") == symbol:
                s, e = int(n.get("startLine") or 0), int(n.get("endLine") or 0)
                sym_info = {"kind": n.get("kind") or "", "signature": n.get("signature") or ""}
                break
        if not (s and e):
            return {"error": f"符号未找到且未给行号: {symbol}",
                    "hint": "可改传 startLine/endLine 直接读行段"}
    if not s:
        s, e = 1, min(len(lines), 200)
    e = min(e or len(lines), len(lines))
    truncated = False
    if e - s + 1 > 240:
        e = s + 239
        truncated = True
    snippet = "\n".join(f"{i:4d}| {lines[i - 1]}" for i in range(s, e + 1))
    if len(snippet) > 12000:
        snippet = snippet[:12000] + "\n…(截断)"
        truncated = True
    return {"file": file, "symbol": symbol or None, "range": [s, e],
            "totalLines": len(lines), "truncated": truncated,
            "signature": (sym_info or {}).get("signature") or None,
            "code": snippet}
