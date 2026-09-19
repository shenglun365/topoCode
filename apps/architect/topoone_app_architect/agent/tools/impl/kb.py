"""KB/项目上下文工具域(kb.* + project.ctx + 模型助手单源) — M3 自 req_agent 机械迁出(逐字保真, 注册随定义点)。"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from ..registry import register_architect_tool

logger = logging.getLogger("arch_routes.req_agent")

def _model(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from ....arch_routes.common import build_architecture_model
    return build_architecture_model(root, project)


def _model_assets(root: Optional[str], project: Optional[str]) -> List[Dict[str, Any]]:
    return _model(root, project).get("components") or []


def _model_code_mappings(root: Optional[str], project: Optional[str]) -> List[Dict[str, Any]]:
    from ....arch_routes.common import build_architecture_model
    model = build_architecture_model(root, project, include_code_mappings=True)
    real = model.get("codeMappings") or []
    if real:
        return real[:80]
    return [{
        "id": f"cm-{c.get('id')}", "targetType": "component", "targetId": c.get("id"),
        "targetName": c.get("name"), "file": f"{'/'.join((c.get('owns') or [])[:1]) or 'app/' + str(c.get('name'))}",
        "line": "L1", "level": "logical", "note": c.get("desc"),
    } for c in model.get("components") or []][:40]


def _project_degraded(root: Optional[str], project: Optional[str]) -> bool:
    try:
        from ....arch_routes.project import kb_degraded as _d
        return _d(root, project)
    except Exception:
        return True


# ── Tools 实现 ─────────────────────────────────────────────────────────

@register_architect_tool(
    "kb.asset.search",
    "全文检索知识库架构资产(组件/ER/实体/流程)，按关键词命中并按相关度排序",
)
def tool_kb_asset_search(root: Optional[str], project: Optional[str],
                         text: str, preferred: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    if _project_degraded(root, project):
        return []
    assets = _model_assets(root, project)
    pre = set(preferred or [])
    if pre:
        hits = [a for a in assets if a.get("id") in pre]
        if hits:
            return hits[:6]
    lowered = (text or "").lower()
    tokens = [t for t in lowered.split() if len(t) >= 2]
    scored = []
    if tokens:
        for a in assets:
            hay = f"{a.get('id', '')} {a.get('name', '')} {a.get('desc', '')}".lower()
            score = sum(3 for tk in tokens if tk in hay.split())
            if score == 0:
                score = sum(1 for tk in tokens if tk in hay)
            if pre and a.get("id") in pre:
                score += 10
            if score > 0:
                scored.append((score, a))
        scored.sort(key=lambda x: x[0], reverse=True)
    # 无关键词命中(如「当前系统有哪些组件」等穷举型提问)时回退返回资产清单，
    # 避免 LLM 误判「未检索到任何架构资产」
    if not scored:
        return assets[:6]
    return [a for _, a in scored[:6]]


@register_architect_tool(
    "kb.code_mappings",
    "查询资产对应的代码映射(文件/行号)，锁定「改哪里」的精确位置",
)
def tool_kb_code_mappings(asset_ids: List[str],
                          root: Optional[str] = None, project: Optional[str] = None) -> List[Dict[str, Any]]:
    ids = set(asset_ids or [])
    return [m for m in _model_code_mappings(root, project) if m.get("targetId") in ids][:12]


@register_architect_tool(
    "kb.baseline",
    "读取当前项目 KB 基线信息(git 表示：分支/提交/基线版本)，用于需求影响范围判断",
)
def tool_kb_baseline(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    if _project_degraded(root, project):
        return {}
    from ....arch_routes.project import _resolve_project as _rp
    try:
        proj = _rp(root, project)
    except Exception:
        proj = None
    return {
        "name": (proj or {}).get("name", ""),
        "baselineId": (proj or {}).get("baselineId", ""),
        "branch": (proj or {}).get("branch", "main"),
    }


@register_architect_tool(
    "kb.graph",
    "遍历组件依赖图(依赖/被调用)，判断需求改动的影响链路(基于 KB 真实架构模型的组件 dependsOn 与跨社区边)",
)
def tool_kb_graph(root: Optional[str], project: Optional[str],
                  comp_ids: List[str]) -> List[Dict[str, Any]]:
    """返回组件级依赖链：基于 KB 真实架构模型(kb.asset.search 同源)计算
    每个组件的下游依赖(dependsOn)与上游被依赖方，并附文件/调用关系。

    returns [{componentId, name, kind, downstream:[name], upstream:[name], files:[...], relMd}]
    """
    if not comp_ids:
        return []
    if _project_degraded(root, project):
        raise ValueError("KB 能力不足：项目未绑定 KB 基线，无法读取依赖图。请在项目概览中关联知识库。")
    assets = _model_assets(root, project)
    by_id = {a.get("id"): a for a in assets}
    id_to_name = {a.get("id"): (a.get("name") or a.get("id")) for a in assets}
    # 上游映射：扫描全部组件的 dependsOn，收集指向每个 comp 的调用方
    upstream_map: Dict[str, List[str]] = {}
    for a in assets:
        for dep in (a.get("dependsOn") or []):
            upstream_map.setdefault(dep, []).append(a.get("id"))

    results: List[Dict[str, Any]] = []
    for cid in comp_ids:
        comp = by_id.get(cid)
        if not comp:
            results.append({
                "componentId": cid, "name": cid, "kind": "service",
                "downstream": [], "upstream": [], "files": [],
                "relMd": f"## 依赖分析\n\nKB 中未命中组件 {cid}，请核对组件 ID。",
            })
            continue
        downstream = [id_to_name.get(d, d) for d in (comp.get("dependsOn") or [])]
        upstream = [id_to_name.get(u, u) for u in (upstream_map.get(cid) or [])]
        name = comp.get("name") or cid
        lines = [f"## 组件 {name} 依赖链\n",
                 f"- **下游依赖**(本组件依赖)：{('、'.join(downstream)) if downstream else '无'}\n",
                 f"- **上游调用方**(依赖本组件)：{('、'.join(upstream)) if upstream else '无'}\n",
                 f"- **包含文件**：{(', '.join((comp.get('owns') or [])[:8])) or '—'}\n",
                 f"- **变更状态**：{comp.get('change') or 'same'}",
                 ""]
        results.append({
            "componentId": cid, "name": name, "kind": comp.get("kind") or "service",
            "downstream": downstream, "upstream": upstream,
            "files": (comp.get("owns") or [])[:8],
            "change": comp.get("change") or "same",
            "relMd": "\n".join(lines),
        })
    return results


@register_architect_tool(
    "project.ctx",
    "读取当前项目上下文(项目名/分支/基线 id/降级状态)，LLM 用于判断模式(greenfield/existing)",
)
def tool_project_ctx(root: Optional[str], project: Optional[str]) -> Dict[str, Any]:
    from ....arch_routes.project import _resolve_project as _rp
    try:
        proj = _rp(root, project)
    except Exception:
        proj = None
    return {
        "root": root, "project": project,
        "bound": bool(proj),
        "degraded": _project_degraded(root, project),
        "name": (proj or {}).get("name", ""),
        "baselineId": (proj or {}).get("baselineId", ""),
    }
