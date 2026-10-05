"""链路跟踪(深度探索)：符号级 DFS 沿调用链追踪单个资产的上/下游处理链条。

与邻域聚焦(graph focus+hops, BFS 广度圈定)互补不交叉：聚焦=结构视角(谁连
着谁)，跟踪=行为视角(一件事怎么流经系统)。数据源=符号库完整调用图
(native∪codegraph 合并)，途经未提取符号照常入链(标注所属文件)，已锚定
资产聚合显示——突破资产 relations 稀疏断链(实测链常断在未提取符号处)。

预算三闸：每层分支 branch_limit(默认 3, confidence/目标度数排序)、限深
max_depth(默认 6)、总节点 max_nodes(默认 400)。环检测：链上重复即截断
标 cycle。符号库缺失 → 降级资产 relations 图 DFS(链在未提取处断, 标 degraded)。
"""
from __future__ import annotations

import json
import time
from collections import OrderedDict
from typing import Dict, List, Optional, Set, Tuple

from .paths import project_id_for, resolve_root
from .relation_index import relation_target_index, resolve_relation_target
from .symbols import close_symbol_conn, open_symbol_conn
from ..store import SemanticAssetsStore

TRACE_KINDS = ("calls", "instantiates")   # 链路边语义(强关联; references 弱默认不入链)
MAX_DEPTH = 6
BRANCH_LIMIT = 3
MAX_NODES = 400

_cache: "OrderedDict[str, dict]" = OrderedDict()
_CACHE_MAX = 64


def _cache_get(key: str) -> Optional[dict]:
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    return None


def _cache_put(key: str, val: dict) -> None:
    _cache[key] = val
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def _now() -> int:
    return int(time.time() * 1000)


def _node_index(conn) -> Dict[str, dict]:
    """node id → {name, qualifiedName, file, kind, startLine, endLine}。"""
    out: Dict[str, dict] = {}
    try:
        for nid, nm, qn, fp, k, sl, el in conn.execute(
                "SELECT id, name, qualified_name, file_path, kind, "
                "start_line, end_line FROM nodes"):
            out[nid] = {"name": nm or nid,
                        "qualifiedName": qn or nm or nid,
                        "file": fp or "", "kind": k or "",
                        "startLine": int(sl or 0), "endLine": int(el or 0)}
    except Exception:
        pass
    return out


def _sym_to_node(conn) -> Dict[str, str]:
    """符号(qualified_name 优先) → node id。"""
    m: Dict[str, str] = {}
    try:
        for nid, qn, nm in conn.execute("SELECT id, qualified_name, name FROM nodes"):
            if qn:
                m.setdefault(qn, nid)
            if nm:
                m.setdefault(nm, nid)
    except Exception:
        pass
    return m


def _degree_index(conn) -> Dict[str, int]:
    """node id → 总度数(分支排序用: 被依赖多的优先)。"""
    deg: Dict[str, int] = {}
    try:
        for n, c in conn.execute(
                "SELECT target, COUNT(*) FROM edges GROUP BY target"):
            deg[n] = deg.get(n, 0) + int(c)
        for n, c in conn.execute(
                "SELECT source, COUNT(*) FROM edges GROUP BY source"):
            deg[n] = deg.get(n, 0) + int(c)
    except Exception:
        pass
    return deg


def _edge_conf(meta: Optional[str]) -> float:
    if not meta:
        return 0.0
    try:
        m = json.loads(meta)
        if isinstance(m, dict) and m.get("confidence") is not None:
            return float(m["confidence"])
    except Exception:  # noqa: BLE001
        pass
    return 0.7   # 缺省视为达标(_derive_indirect_edges 同口径)


def _anchor_ids(conn, assets: List[dict]) -> Dict[str, str]:
    """全项目资产锚点 → node id → assetId(单资产优先)。"""
    sym = _sym_to_node(conn)
    out: Dict[str, str] = {}
    for a in assets:
        aid = a.get("id") or ""
        if not aid:
            continue
        for r in (a.get("astRefs") or []):
            nid = sym.get((r.get("symbol") or "").strip())
            if nid:
                out.setdefault(nid, aid)
    return out


def _adjacent(conn, frontier: Set[str], direction: str,
              kinds: Tuple[str, ...]) -> List[dict]:
    """frontier 节点的一跳邻接边(down=出边 / up=入边)。"""
    if not frontier:
        return []
    ids = list(frontier)
    ph = ",".join("?" * len(ids))
    col, other = ("source", "target") if direction == "down" else ("target", "source")
    kh = ",".join("?" * len(kinds)) if kinds else "''"
    try:
        rows = conn.execute(
            f"SELECT e.{col}, e.{other}, e.kind, e.line, e.metadata "
            f"FROM edges e WHERE e.{col} IN ({ph}) "
            f"AND e.kind IN ({kh})",
            tuple(ids + list(kinds))).fetchall()
    except Exception:
        return []
    col_i, other_i = (0, 1) if direction == "down" else (1, 0)
    return [{"src": r[col_i], "tgt": r[other_i], "kind": r[2] or "",
             "line": int(r[3] or 0), "conf": _edge_conf(r[4])} for r in rows]


def _mk_node(node_id: str, ninfo: dict, edge: Optional[dict],
             aid: str, aname_by: Dict[str, str], depth: int) -> dict:
    n = {"id": node_id, "symbol": ninfo.get("qualifiedName") or node_id,
         "name": ninfo.get("name") or node_id, "file": ninfo.get("file") or "",
         "nodeKind": ninfo.get("kind") or "", "depth": depth,
         "startLine": ninfo.get("startLine") or 0,
         "endLine": ninfo.get("endLine") or 0}
    if edge:
        n["edgeKind"] = edge["kind"]
        n["line"] = edge["line"] or None
        n["confidence"] = round(edge["conf"], 2)
    if aid:
        n["assetId"] = aid
        n["assetName"] = aname_by.get(aid, aid)
    return n


def _trace_symbol_graph(conn, roots: List[str], assets: List[dict], *,
                        direction: str, max_depth: int, branch_limit: int,
                        max_nodes: int) -> dict:
    """符号库受限 DFS(单节点递归)：返回链树 + 根到叶完整路径 + stats。"""
    ninfo = _node_index(conn)
    anchor = _anchor_ids(conn, assets)
    aname_by = {a.get("id"): (a.get("name") or a.get("id")) for a in assets}
    deg = _degree_index(conn)
    budget = {"n": 0}
    cut = {"depth": False, "nodes": False}
    seen_global: Set[str] = set()

    def expand(nid: str, depth: int, stack: Set[str], edge: Optional[dict]) -> dict:
        node = _mk_node(nid, ninfo.get(nid) or {}, edge,
                        anchor.get(nid, ""), aname_by, depth)
        budget["n"] += 1
        if nid in stack:
            node["cycle"] = True          # 环: 标记不展开
            return node
        if nid in seen_global:
            node["seenElsewhere"] = True  # 其他分支已展开过: 不重复建子树
            return node
        seen_global.add(nid)
        if depth >= max_depth:
            cut["depth"] = True
            return node
        if budget["n"] >= max_nodes:
            cut["nodes"] = True
            return node
        cand = _adjacent(conn, {nid}, direction, TRACE_KINDS)
        cand.sort(key=lambda e: (-e["conf"], -deg.get(
            e["tgt"] if direction == "down" else e["src"], 0)))
        node["branchTotal"] = len(cand)
        kids: List[dict] = []
        for e in cand[:branch_limit]:
            if budget["n"] >= max_nodes:
                cut["nodes"] = True
                break
            kids.append(expand(e["tgt"] if direction == "down" else e["src"],
                               depth + 1, stack | {nid}, e))
        node["truncated"] = max(0, len(cand) - branch_limit)
        node["children"] = kids
        return node

    root_ids = [r for r in roots if r]
    if not root_ids:
        return {"error": "asset anchor not found in symbol graph", "degraded": False}
    root = expand(root_ids[0], 0, set(), None)
    extra_roots = [expand(r, 0, {root_ids[0]}, None) for r in root_ids[1:]
                   if budget["n"] < max_nodes]
    paths: List[List[dict]] = []

    def collect(node: dict, acc: List[dict]) -> None:
        acc.append(node)
        children = node.get("children") or []
        if not children or node.get("cycle"):
            paths.append(list(acc))
        for c in children:
            collect(c, acc)
        acc.pop()

    collect(root, [])
    return {"root": root, "paths": paths, "extraRoots": extra_roots,
            "stats": {"nodes": budget["n"],
                      "depthCut": cut["depth"], "nodeCut": cut["nodes"],
                      "degraded": False}}


def _trace_relations_graph(assets: List[dict], asset_id: str, *,
                           direction: str, max_depth: int,
                           branch_limit: int, max_nodes: int = MAX_NODES) -> dict:
    """降级：资产 relations 图 DFS(链在未提取处断)。"""
    idx = relation_target_index(assets)
    by_id = {a.get("id"): a for a in assets if a.get("id")}
    fwd: Dict[str, List[Tuple[str, str]]] = {}
    bwd: Dict[str, List[Tuple[str, str]]] = {}
    for a in assets:
        aid = a.get("id") or ""
        for rel in (a.get("detail") or {}).get("relations") or []:
            tid, _ok = resolve_relation_target(str(rel.get("target") or ""), idx)
            if not tid or tid == aid:
                continue
            fwd.setdefault(aid, []).append((tid, rel.get("type") or "calls"))
            bwd.setdefault(tid, []).append((aid, rel.get("type") or "calls"))
    budget = {"n": 1}

    def build(cur: str, depth: int, stack: Set[str]) -> List[dict]:
        if depth >= max_depth or budget["n"] >= max_nodes:
            return []
        table = fwd if direction == "down" else bwd
        cand = table.get(cur, [])
        out: List[dict] = []
        for tid, k in cand[:branch_limit]:
            if budget["n"] >= max_nodes:
                break
            a = by_id.get(tid) or {}
            node = {"id": tid, "symbol": a.get("name") or tid,
                    "name": a.get("name") or tid, "file": "", "nodeKind": "asset",
                    "assetId": tid, "assetName": a.get("name") or tid,
                    "edgeKind": k, "depth": depth, "children": []}
            budget["n"] += 1
            if tid in stack:
                node["cycle"] = True
                out.append(node)
                continue
            node["children"] = build(tid, depth + 1, stack | {tid})
            out.append(node)
        return out

    a0 = by_id.get(asset_id) or {}
    root = {"id": asset_id, "symbol": a0.get("name") or asset_id,
            "name": a0.get("name") or asset_id, "file": "", "nodeKind": "asset",
            "assetId": asset_id, "assetName": a0.get("name") or asset_id,
            "depth": 0}
    root["children"] = build(asset_id, 1, {asset_id})
    paths: List[List[dict]] = []

    def collect(node: dict, acc: List[dict]) -> None:
        acc.append(node)
        children = node.get("children") or []
        if not children or node.get("cycle"):
            paths.append(list(acc))
        for c in children:
            collect(c, acc)
        acc.pop()

    collect(root, [])
    return {"root": root, "paths": paths, "extraRoots": [],
            "stats": {"nodes": budget["n"], "depthReached": max_depth,
                      "degraded": True}}


def _load_assets(pid: str) -> List[dict]:
    return [r for r in SemanticAssetsStore.all_status(pid, limit=8000)
            if r.get("status") == "active"]


def trace(root: Optional[str], project: Optional[str], asset_id: str, *,
          direction: str = "down", max_depth: int = MAX_DEPTH,
          branch_limit: int = BRANCH_LIMIT, max_nodes: int = MAX_NODES) -> dict:
    """资产链路跟踪入口：asset → 符号库锚定 → 受限 DFS。"""
    pid = project_id_for(root, project)
    if not pid:
        return {"error": "缺少项目"}
    direction = direction if direction in ("down", "up") else "down"
    key = f"{pid}|{asset_id}|{direction}|{max_depth}|{branch_limit}|{max_nodes}"
    hit = _cache_get(key)
    if hit:
        return hit
    assets = _load_assets(pid)
    asset = next((a for a in assets if a.get("id") == asset_id), None)
    if not asset:
        return {"error": "资产不存在"}
    conn, _src = open_symbol_conn(resolve_root(root, project), project)
    try:
        if conn is None:
            res = _trace_relations_graph(assets, asset_id, direction=direction,
                                         max_depth=max_depth,
                                         branch_limit=branch_limit,
                                         max_nodes=max_nodes)
        else:
            sym = _sym_to_node(conn)
            anchors = []
            for r in (asset.get("astRefs") or []):
                nid = sym.get((r.get("symbol") or "").strip())
                if nid and nid not in anchors:
                    anchors.append(nid)
            if not anchors:
                res = _trace_relations_graph(assets, asset_id, direction=direction,
                                             max_depth=max_depth,
                                             branch_limit=branch_limit,
                                             max_nodes=max_nodes)
            else:
                res = _trace_symbol_graph(conn, anchors, assets,
                                          direction=direction,
                                          max_depth=max_depth,
                                          branch_limit=branch_limit,
                                          max_nodes=max_nodes)
    finally:
        if conn is not None:
            close_symbol_conn(conn)   # 缓存(native)连接不关，勿直接 conn.close()
    res = {"trace": res, "assetId": asset_id, "direction": direction,
           "generatedAt": _now()}
    _cache_put(key, res)
    return res


def trace_expand(root: Optional[str], project: Optional[str], symbol: str, *,
                 direction: str = "down", max_depth: int = MAX_DEPTH,
                 branch_limit: int = BRANCH_LIMIT,
                 max_nodes: int = MAX_NODES) -> dict:
    """侧栏懒加载：以任意中途符号为根继续 DFS(与 trace 同预算语义)。"""
    pid = project_id_for(root, project)
    if not pid:
        return {"error": "缺少项目"}
    direction = direction if direction in ("down", "up") else "down"
    conn, _src = open_symbol_conn(resolve_root(root, project), project)
    try:
        if conn is None:
            return {"error": "符号库不可用(无展开能力, 仅整链降级跟踪)"}
        sym = _sym_to_node(conn)
        nid = sym.get((symbol or "").strip())
        if not nid:
            return {"error": "符号未在符号图谱中找到"}
        assets = _load_assets(pid)
        res = _trace_symbol_graph(conn, [nid], assets, direction=direction,
                                  max_depth=max_depth, branch_limit=branch_limit,
                                  max_nodes=max_nodes)
    finally:
        if conn is not None:
            close_symbol_conn(conn)
    return {"trace": res, "symbol": symbol, "direction": direction,
            "generatedAt": _now()}
