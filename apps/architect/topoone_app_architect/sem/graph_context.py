"""W2 图邻域上下文供给（2610-B1）——把自管图数据变成 agent 上下文的一等供给。

graph_neighborhood(): 按符号/模块焦点取 N 跳子图 → 压缩大纲（节点=签名行、
边=调用/包含摘要），字符预算钳制；数量上限三件套（截断 + truncated 透出，
学 comp-graph 先例 6eb00dfc）；freshness 带 baseline 锚。

数据：GraphStore（arch_graph_node/edge，数据主权自管面 1004）。
消费：context_pack 注入段（开关 graph_context_injection）/ mandate 锚定勾稽
（P2-T4）/ W5 test_reach 图加权。纯读、无副作用。
"""
from __future__ import annotations

import subprocess
from typing import Any, Dict, List, Optional

MAX_NODES = 200          # 上限三件套（comp-graph 先例）
MAX_EDGES = 400
DEFAULT_BUDGET = 1600    # outline 字符预算（ctx_budget 之外的第一道钳制）


from ..store.graph import GraphStore
from .. import store as _store_mod


def baseline_rev(project_id: str) -> Dict[str, str]:
    """基线锚 → {rev, baseline_commit}; 无基线 rev=""。"""
    row = _store_mod.ProjectsStore.get(project_id) or {}
    commit = str(row.get("baselineCommit") or "")
    return {"rev": f"baseline:{commit}" if commit else "",
            "baseline_commit": commit}


def _head_commit(root: str) -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root or None,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


def _seed_nodes(project_id: str, rev: str, focus: str) -> List[dict]:
    """焦点种子: 符号名/限定名/文件路径 前缀命中（大小写不敏感）。"""
    nodes = GraphStore.nodes(project_id, rev, limit=5000)
    f = (focus or "").strip().lower()
    if not f:
        return []
    out = []
    for n in nodes:
        hay = " ".join([str(n.get("name") or ""),
                        str(n.get("qualified_name") or ""),
                        str(n.get("file_path") or "")]).lower()
        if f in hay:
            out.append(n)
    return out


def graph_neighborhood(project_id: str, focus: str, depth: int = 2,
                       budget: int = DEFAULT_BUDGET,
                       root: str = "") -> Dict[str, Any]:
    """焦点符号/模块的 N 跳邻域 → 压缩大纲。

    返回 {outline, seed_count, node_count, edge_count, truncated,
    baseline_commit, baseline_stale, reason?}；无基线/无命中时 outline=""。
    """
    info = baseline_rev(project_id)
    rev = info["rev"]
    if not rev:
        return {"outline": "", "reason": "no_baseline",
                "baseline_commit": "", "baseline_stale": False}
    seeds = _seed_nodes(project_id, rev, focus)
    if not seeds:
        return {"outline": "", "reason": "no_focus_hit",
                "baseline_commit": info["baseline_commit"],
                "baseline_stale": False}
    edges = GraphStore.edges(project_id, rev, limit=50000)
    adj: Dict[str, List[tuple]] = {}
    for e in edges:
        adj.setdefault(e["source"], []).append((e["target"], e["kind"]))
        adj.setdefault(e["target"], []).append((e["source"], e["kind"]))
    by_id = {n["id"]: n for n in GraphStore.nodes(project_id, rev, limit=10000)}

    visited = {s["id"]: 0 for s in seeds}
    frontier = list(visited.keys())
    truncated = False
    for d in range(1, max(1, int(depth)) + 1):   # depth 轮扩展 = depth 跳
        nxt = []
        for nid in frontier:
            for tgt, _kind in adj.get(nid, []):
                if tgt in visited or tgt not in by_id:
                    continue
                if len(visited) >= MAX_NODES:
                    truncated = True
                    break
                visited[tgt] = d
                nxt.append(tgt)
            if truncated:
                break
        frontier = nxt
        if not frontier:
            break

    picked = [by_id[i] for i in visited if i in by_id]
    picked.sort(key=lambda n: (str(n.get("file_path") or ""), int(n.get("start_line") or 0)))
    picked = picked[:MAX_NODES]
    ids = {n["id"] for n in picked}
    sel_edges = [e for e in edges
                 if e["source"] in ids and e["target"] in ids][:MAX_EDGES]
    if len(sel_edges) >= MAX_EDGES:
        truncated = True

    lines: List[str] = []
    cur_file = ""
    for n in picked:
        fp = str(n.get("file_path") or "?")
        if fp != cur_file:
            cur_file = fp
            lines.append(f"## {fp}")
        qn = str(n.get("qualified_name") or n.get("name") or n["id"])
        lines.append(f"- [{n.get('kind') or '?'}] {qn}"
                     f" (:{int(n.get('start_line') or 0)})")
    calls = [e for e in sel_edges if str(e.get("kind") or "").lower()
             not in ("contains", "imports")]
    if calls:
        kinds: Dict[str, int] = {}
        for e in calls:
            kinds[str(e["kind"])] = kinds.get(str(e["kind"]), 0) + 1
        lines.append("## 关系摘要")
        lines.append(", ".join(f"{k}×{v}" for k, v in sorted(kinds.items())))
        for e in calls[:8]:
            lines.append(f"- {e['source']} → {e['target']} ({e['kind']})")

    outline = "\n".join(lines)
    if len(outline) > budget:
        outline = outline[:max(0, budget - 1)] + "…"
        truncated = True

    head = _head_commit(root)
    return {
        "outline": outline,
        "seed_count": len(seeds),
        "node_count": len(picked),
        "edge_count": len(sel_edges),
        "truncated": truncated,
        "baseline_commit": info["baseline_commit"],
        "baseline_stale": bool(head and head != info["baseline_commit"]),
    }
