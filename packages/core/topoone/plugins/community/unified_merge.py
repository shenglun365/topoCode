"""UNIFIED 对齐合并引擎 —— KB 组件体系统一（方案 E：五张封闭表）

INCLUDE/CALL 两线社区划分结果 → 逐层双向对齐合并 → UNIFIED 组件树落库。
规则出处：docs/kb-unified-components-plan.md §3（表 A–E + R-void/R-resid/F3-bis）。

- 全流程确定性（排序遍历 + 平局链），同输入双跑结果逐字节一致；
- 两线划分数据只读，不修改；UNIFIED 仅写入划分结果层（graph_doc/community_hierarchy）；
- 覆盖率保证：F3-bis 强制归入级联使两线并集 100% 进入组件。
"""

import hashlib
import json
import logging
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

from topoone.config import (
    COMMUNITY_UNIFIED_TAU,
    COMMUNITY_UNIFIED_TAU_LO,
    COMMUNITY_UNIFIED_SCORE_INC,
    COMMUNITY_UNIFIED_SCORE_CALL,
    COMMUNITY_UNIFIED_FORCE_ASSIGN,
    COMMUNITY_MIN_NODE_UNIFIED,
)

logger = logging.getLogger(__name__)

TAU = COMMUNITY_UNIFIED_TAU
TAU_LO = COMMUNITY_UNIFIED_TAU_LO
S_INC = COMMUNITY_UNIFIED_SCORE_INC
S_CALL = COMMUNITY_UNIFIED_SCORE_CALL
MIN_NODE = COMMUNITY_MIN_NODE_UNIFIED
FORCE_ASSIGN = COMMUNITY_UNIFIED_FORCE_ASSIGN
MAX_DEPTH = 5          # L0~L5


# ==================== 主入口 ====================

def analyze_unified(task_id: str, analysis_store) -> Dict:
    """INCLUDE/CALL 两线划分结果 → 对齐合并 → UNIFIED 树落库。

    Returns:
        {"community_count": int, "levels": int}
    """
    logger.info(f"[UNIFIED] analyze_unified 入口: task_id={task_id}")
    analysis_store.clear_communities_for_task(task_id, "UNIFIED")

    inc_pairs, call_pairs = _load_file_pairs(analysis_store, task_id)
    comms = _load_communities(analysis_store, task_id)
    has_any = any(comms[line].get(f"L{d}") for line in ("INCLUDE", "CALL")
                  for d in range(MAX_DEPTH + 1))
    if not has_any:
        logger.info(f"[UNIFIED] {task_id}: 两线均无社区数据，跳过")
        return {"community_count": 0, "levels": 0}

    tree, universe = merge_all(comms, inc_pairs, call_pairs,
                               TAU, TAU_LO, "A_first", MIN_NODE,
                               S_INC, S_CALL, True)
    levels = _save_unified(task_id, analysis_store, tree,
                           inc_pairs, call_pairs, universe)

    total = sum(len(tree.get(f"L{d}", [])) for d in range(MAX_DEPTH + 1))
    logger.info(f"[UNIFIED] {task_id}: 合并完成，共 {total} 个组件，{levels} 层，"
                f"universe={len(universe)}")
    return {"community_count": total, "levels": levels}


# ==================== 数据加载 ====================

def _load_file_pairs(analysis_store, task_id: str) -> Tuple[Set, Set]:
    """graph_edge → 文件对集合（同文件剔除、二值化）。返回 (inc_pairs, call_pairs)。"""
    lookup = {}
    try:
        for n in analysis_store.get_graph_nodes(task_id):
            nid = n.get("id", "")
            fp = n.get("file_path", "")
            if nid and fp:
                lookup[nid] = fp
    except Exception:
        pass

    def _pairs(edges):
        out = set()
        for e in edges:
            sf = lookup.get(e.get("source_id", ""), e.get("source_id", ""))
            tf = lookup.get(e.get("target_id", ""), e.get("target_id", ""))
            if not sf or not tf or sf == tf:
                continue
            out.add((sf, tf) if sf < tf else (tf, sf))
        return out

    return _pairs(analysis_store.get_dep_edges(task_id)), \
        _pairs(analysis_store.get_call_edges(task_id))


def _load_communities(analysis_store, task_id: str) -> Dict:
    """graph_doc → {line: {level: {comm_id: set(files)}}}（仅 L* 层级）"""
    out = {"INCLUDE": defaultdict(dict), "CALL": defaultdict(dict)}
    for line in ("INCLUDE", "CALL"):
        try:
            rows = analysis_store.get_communities(task_id, line)
        except Exception:
            rows = []
        for c in rows:
            lv = c.get("comm_lv", "")
            if not lv.startswith("L"):
                continue
            nl = c.get("node_list", [])
            files = set(json.loads(nl)) if isinstance(nl, str) else set(nl)
            if files:
                out[line][lv][c["comm_id"]] = files
    return out


def _load_special(analysis_store, task_id: str):
    """HUB/ORPHAN 落库行 → (hub_files, orphan_files) 并集"""
    hub, orphan = set(), set()
    for line in ("INCLUDE", "CALL"):
        try:
            rows = analysis_store.get_communities(task_id, line)
        except Exception:
            continue
        for c in rows:
            nl = c.get("node_list", [])
            files = set(json.loads(nl)) if isinstance(nl, str) else set(nl)
            if c.get("comm_lv") == "HUB":
                hub |= files
            elif c.get("comm_lv") == "ORPHAN":
                orphan |= files
    return hub, orphan


# ==================== 表 A：区域判定 ====================

def _classify(rI: float, rC: float, tau: float, tau_lo: float) -> str:
    if rI >= tau and rC >= tau:
        return "A"
    if rC >= tau and rI < tau:
        return "B"
    if rI >= tau and rC < tau:
        return "C"
    return "D1" if min(rI, rC) >= tau_lo else "D2"


# ==================== 表 B：逐层消费 ====================

def merge_layer(i_cands: Dict, c_cands: Dict, inc_pairs: Set, call_pairs: Set,
                tau: float, tau_lo: float, order: str, min_node: int,
                s_inc: float = 1.0, s_call: float = 1.0,
                residual: bool = True):
    """单层合并 → (new_comps, pool, stats, prov)"""
    pairs = {}
    for iid, I in i_cands.items():
        for cid, C in c_cands.items():
            inter = I & C
            if not inter:
                continue
            rI = len(inter) / len(I)
            rC = len(inter) / len(C)
            pairs[(iid, cid)] = (_classify(rI, rC, tau, tau_lo), rI, rC)

    def pair_key(item):
        (iid, cid), (rg, rI, rC) = item
        return (-min(rI, rC), -min(len(i_cands[iid]), len(c_cands[cid])), iid, cid)

    a_list = sorted((kv for kv in pairs.items() if kv[1][0] == "A"), key=pair_key)
    bc_list = sorted((kv for kv in pairs.items() if kv[1][0] in ("B", "C")), key=pair_key)
    d1_list = sorted((kv for kv in pairs.items() if kv[1][0] == "D1"), key=pair_key)

    consumed: Set[str] = set()
    bases_of = defaultdict(list)          # container_id -> [base_id]
    base_line = {}
    protected: Set[str] = set()           # R-void 保留资格
    new_comps = []
    pool: List[str] = []
    stats = {"A": 0, "B": 0, "C": 0, "D1": 0, "D2": 0,
             "pairs_total": len(i_cands) * len(c_cands)}
    for (iid, cid), (rg, _, _) in pairs.items():
        stats[rg] += 1

    # R-void 预计算：容器 → 全部基础件（与消费顺序无关）
    all_bases_of = defaultdict(list)
    for (iid, cid), (rg, _, _) in pairs.items():
        if rg == "B":
            all_bases_of[iid].append(cid)
        elif rg == "C":
            all_bases_of[cid].append(iid)

    def consume_a(iid, cid):
        members = set(i_cands[iid]) | set(c_cands[cid])
        new_comps.append({"members": members, "evidence": "BOTH", "kind": "normal"})
        for container in (iid, cid):
            for b in all_bases_of.get(container, []):
                if b not in consumed:
                    protected.add(b)
        consumed.add(iid)
        consumed.add(cid)

    def register_bc(container, base):
        bases_of[container].append(base)
        base_line[base] = "CALL" if base in c_cands else "INCLUDE"

    for phase in ([bc_list, a_list] if order == "BC_first" else [a_list, bc_list]):
        for (iid, cid), (rg, _, _) in phase:
            if iid in consumed or cid in consumed:
                continue
            if rg == "A":
                consume_a(iid, cid)
            elif rg == "B":
                register_bc(iid, cid)
            else:
                register_bc(cid, iid)

    # P2 补漏：被 A 消费容器的潜在基础件 → R-void 保护
    for container, blist in all_bases_of.items():
        if container in consumed:
            for b in blist:
                if b not in consumed:
                    protected.add(b)

    # 池/残余判定用全量邻接（双线合并视界）
    nbr_all = defaultdict(set)
    for a, b in inc_pairs:
        nbr_all[a].add(b)
        nbr_all[b].add(a)
    for a, b in call_pairs:
        nbr_all[a].add(b)
        nbr_all[b].add(a)

    # P2：容器拆解
    for container in sorted(bases_of):
        if container in consumed:
            continue
        bases = sorted(set(bases_of[container]))
        covered: Set[str] = set()
        for b in bases:
            if b in consumed:
                continue
            consumed.add(b)
            members = set(c_cands.get(b) or i_cands[b])
            covered |= members
            new_comps.append({"members": members,
                              "evidence": base_line[b], "kind": "base"})
        container_files = set(i_cands.get(container) or c_cands[container])
        container_line = "INCLUDE" if container in i_cands else "CALL"
        leftover = [f for f in container_files if f not in covered]
        # R-resid 条件残余：池崩溃预防（Phase 0 实验采纳）
        if residual and len(leftover) >= min_node:
            cand_files_all: Set[str] = set()
            for s in i_cands.values():
                cand_files_all |= s
            for s in c_cands.values():
                cand_files_all |= s
            formed = cand_files_all - set(leftover)
            attached = sum(1 for f in leftover
                           if any(k in formed for k in nbr_all.get(f, ())))
            if attached < 0.5 * len(leftover):
                new_comps.append({"members": set(leftover), "evidence": container_line,
                                  "kind": "normal"})
                consumed.add(container)
                continue
        pool.extend(leftover)
        consumed.add(container)

    # P2.5：D1 弱并
    for (iid, cid), _ in d1_list:
        if iid in consumed or cid in consumed:
            continue
        new_comps.append({"members": set(i_cands[iid]) | set(c_cands[cid]),
                          "evidence": "WEAK", "kind": "normal"})
        consumed.update([iid, cid])

    # P3：独立候选 + E4
    for line, cands in (("INCLUDE", i_cands), ("CALL", c_cands)):
        for cid in sorted(cands):
            if cid in consumed:
                continue
            members = cands[cid]
            if len(members) >= min_node:
                kind = "protected" if cid in protected else "normal"
                new_comps.append({"members": set(members), "evidence": line,
                                  "kind": kind})
            else:
                pool.extend(members)
            consumed.add(cid)

    stats["new_comps"] = len(new_comps)
    stats["pool"] = len(pool)
    stats["protected"] = len(protected)

    # 出身映射：file -> [来源社区成员集]（F3-bis 出身多数用）
    prov = defaultdict(list)
    for cands in (i_cands, c_cands):
        for files in cands.values():
            om = tuple(sorted(files))
            for f in files:
                prov[f].append(om)

    return new_comps, pool, stats, dict(prov)


# ==================== 表 C：文件归属仲裁 ====================

def assign_files(new_comps: List[Dict], pool: List[str], inc_pairs: Set,
                 call_pairs: Set, s_inc: float = 1.0, s_call: float = 1.0,
                 prov: Optional[Dict] = None, force: bool = True,
                 min_node: int = 6):
    """F1/F2 定属 + F3 池仲裁 + F3-bis 强制归入级联。→ (assignment, unassigned)"""
    nbr_inc = defaultdict(set)
    nbr_call = defaultdict(set)
    for a, b in inc_pairs:
        nbr_inc[a].add(b)
        nbr_inc[b].add(a)
    for a, b in call_pairs:
        nbr_call[a].add(b)
        nbr_call[b].add(a)

    members_list = [c["members"] for c in new_comps]
    claims = defaultdict(list)
    for idx, c in enumerate(new_comps):
        for f in c["members"]:
            claims[f].append(idx)

    ev_rank = {"base": 3, "protected": 3, "BOTH": 2, "WEAK": 1,
               "INCLUDE": 0, "CALL": 0}

    def comp_score(f, idx):
        m = members_list[idx]
        if f not in nbr_inc and f not in nbr_call:
            return 0.0
        return (s_inc * sum(1 for k in m if k in nbr_inc.get(f, ()))
                + s_call * sum(1 for k in m if k in nbr_call.get(f, ())))

    assignment: Dict[str, int] = {}
    unassigned: List[str] = []
    for f in sorted(claims):
        cs = claims[f]
        if len(cs) == 1:
            assignment[f] = cs[0]
            continue
        base_cs = [i for i in cs if new_comps[i]["kind"] in ("base", "protected")]
        if base_cs:
            base_cs.sort(key=lambda i: (-ev_rank[new_comps[i]["evidence"]],
                                        -len(members_list[i]), i))
            assignment[f] = base_cs[0]
            continue
        best = sorted(cs, key=lambda i: (-comp_score(f, i),
                                         -ev_rank[new_comps[i]["evidence"]],
                                         -len(members_list[i]), i))[0]
        top = comp_score(f, best)
        tied = [i for i in cs if comp_score(f, i) == top]
        if len(tied) > 1:
            tied.sort(key=lambda i: (-ev_rank[new_comps[i]["evidence"]],
                                     -len(members_list[i]), i))
            best = tied[0]
        assignment[f] = best

    # F3 仲裁池
    for f in sorted(set(pool)):
        if f in assignment:
            continue
        scored = [(comp_score(f, i), i) for i in range(len(new_comps))]
        scored.sort(key=lambda t: (-t[0], -ev_rank[new_comps[t[1]]["evidence"]],
                                   -len(members_list[t[1]]), t[1]))
        if scored and scored[0][0] > 0:
            assignment[f] = scored[0][1]
        else:
            unassigned.append(f)

    # ===== F3-bis 强制归入级联 =====
    if force:
        nbr_all = defaultdict(set)
        for a, b in inc_pairs:
            nbr_all[a].add(b)
            nbr_all[b].add(a)
        for a, b in call_pairs:
            nbr_all[a].add(b)
            nbr_all[b].add(a)
        unplaced = sorted(set(unassigned))

        def best_of(counter):
            if not counter:
                return None
            return sorted(counter.items(),
                          key=lambda t: (-t[1], -len(members_list[t[0]]), t[0]))[0][0]

        def wave_origin():
            placed = 0
            for f in list(unplaced):
                cnt = defaultdict(int)
                for om in (prov or {}).get(f, ()):
                    for m in om:
                        if m != f and m in assignment:
                            cnt[assignment[m]] += 1
                dest = best_of(cnt)
                if dest is not None:
                    assignment[f] = dest
                    unplaced.remove(f)
                    placed += 1
            return placed

        def wave_neighbor():
            placed = 0
            for f in list(unplaced):
                cnt = defaultdict(int)
                for nb in nbr_all.get(f, ()):
                    if nb in assignment:
                        cnt[assignment[nb]] += 1
                dest = best_of(cnt)
                if dest is not None:
                    assignment[f] = dest
                    unplaced.remove(f)
                    placed += 1
            return placed

        for _ in range(4):
            if not unplaced:
                break
            if wave_origin() + wave_neighbor() == 0:
                break

        if unplaced:                            # 池级残余成组
            by_origin = defaultdict(list)
            for f in unplaced:
                oms = (prov or {}).get(f, ())
                key = min(oms) if oms else ()
                by_origin[key].append(f)
            for key, group in sorted(by_origin.items(), key=lambda t: -len(t[1])):
                gset = set(group)
                if len(gset) >= min_node and any(
                        any(nb in gset for nb in nbr_all.get(f, ())) for f in gset):
                    new_comps.append({"members": gset, "evidence": "FORCED",
                                      "kind": "normal"})
                    members_list.append(gset)
                    for f in group:
                        assignment[f] = len(members_list) - 1
                    unplaced = [f for f in unplaced if f not in gset]
            for _ in range(2):
                if not unplaced:
                    break
                if wave_origin() + wave_neighbor() == 0:
                    break

        if unplaced:                            # 终极兜底：目录多数 → 最大组件
            def dirname(p):
                return p.rsplit("/", 1)[0] if "/" in p else ""
            dir_votes = defaultdict(lambda: defaultdict(int))
            for f in unplaced:
                d = dirname(f)
                for m, idx in assignment.items():
                    if dirname(m) == d:
                        dir_votes[f][idx] += 1
            largest = (max(range(len(members_list)), key=lambda i: len(members_list[i]))
                       if members_list else None)
            for f in sorted(unplaced):
                dest = best_of(dir_votes[f]) or largest
                if dest is not None:
                    assignment[f] = dest
                    unplaced.remove(f)
        unassigned = list(unplaced)

    return assignment, unassigned


# ==================== 全量合并（逐层递归） ====================

def merge_all(comms: Dict, inc_pairs: Set, call_pairs: Set, tau: float,
              tau_lo: float, order: str, min_node: int,
              s_inc: float = 1.0, s_call: float = 1.0, residual: bool = True):
    """→ (tree, universe)；tree: {level: [node]}，node 含 members/evidence/children/unassigned"""
    i_levels = comms["INCLUDE"]
    c_levels = comms["CALL"]
    universe: Set[str] = set()
    for s in i_levels.get("L0", {}).values():
        universe |= s
    for s in c_levels.get("L0", {}).values():
        universe |= s

    depths = [int(lv[1:]) for lv in list(i_levels) + list(c_levels)
              if lv.startswith("L") and lv[1:].isdigit()]
    max_depth = max([1] + depths)

    def recurse(parent_members: Set[str], level: int):
        if level == 0:
            i_cands = dict(i_levels.get("L0", {}))     # L0 不做 min_node 预筛
            c_cands = dict(c_levels.get("L0", {}))
        else:
            i_cands, c_cands = {}, {}
            for cid, files in i_levels.get(f"L{level}", {}).items():
                clipped = files & parent_members
                if len(clipped) >= min_node:
                    i_cands[cid] = clipped
            for cid, files in c_levels.get(f"L{level}", {}).items():
                clipped = files & parent_members
                if len(clipped) >= min_node:
                    c_cands[cid] = clipped
        new_comps, pool, stats, prov = merge_layer(
            i_cands, c_cands, inc_pairs, call_pairs,
            tau, tau_lo, order, min_node, s_inc, s_call, residual)
        assignment, unassigned = assign_files(new_comps, pool, inc_pairs,
                                              call_pairs, s_inc, s_call,
                                              prov, True, min_node)
        groups = defaultdict(set)
        for f, idx in assignment.items():
            groups[idx].add(f)
        out = []
        for idx, c in enumerate(new_comps):
            members = groups.get(idx, set())
            node = {"members": members, "evidence": c["evidence"],
                    "kind": c["kind"], "unassigned": [], "children": []}
            if level < max_depth and members:
                children, sub_unassigned, _ = recurse(members, level + 1)
                node["children"] = children
                node["unassigned"] = sorted(set(sub_unassigned) & members)
            out.append(node)
        layer_unassigned = sorted(set(unassigned) & parent_members)
        return out, layer_unassigned, stats

    root, _, l0_stats = recurse(universe, 0)
    tree = {"L0": root, "_stats_L0": l0_stats}
    return tree, universe


# ==================== 保存 ====================

def _stable_key(members: Set[str]) -> str:
    return hashlib.sha1("\n".join(sorted(members)).encode("utf-8")).hexdigest()[:16]


def _modularity_of(members: Set[str], pairs: Set) -> float:
    """单社区内聚度近似：内部边占比 × 社区模块度项（简化，仅作质量展示）"""
    inner = sum(1 for a, b in pairs if a in members and b in members)
    return round(inner / max(len(members), 1), 6)


def _evidence_metrics(members: Set[str], evidence: str, inc_pairs: Set,
                      call_pairs: Set, inc_parts: Dict, call_parts: Dict) -> Dict:
    m = max(len(members), 1)
    inc_d = sum(1 for a, b in inc_pairs if a in members and b in members) / m
    call_d = sum(1 for a, b in call_pairs if a in members and b in members) / m
    agree = both = 0
    ms = sorted(members)
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            if a in inc_parts and b in inc_parts and a in call_parts and b in call_parts:
                both += 1
                if (inc_parts[a] == inc_parts[b]) and (call_parts[a] == call_parts[b]):
                    agree += 1
    return {
        "incDensity": round(inc_d, 4),
        "callDensity": round(call_d, 4),
        "agreeRatio": round(agree / both, 4) if both else None,
        "evidence": evidence,
        "stableKey": _stable_key(members),
    }


def _save_unified(task_id: str, analysis_store, tree: Dict, inc_pairs: Set,
                  call_pairs: Set, universe: Set[str]) -> int:
    """UNIFIED 树 → graph_doc + community_hierarchy。返回最大层数。"""
    inc_parts: Dict[str, str] = {}
    call_parts: Dict[str, str] = {}
    # 最深层级身份（agree_ratio 口径）
    db_inc = analysis_store.get_communities(task_id, "INCLUDE")
    db_call = analysis_store.get_communities(task_id, "CALL")

    def deepest(rows, out):
        for c in sorted(rows, key=lambda r: -(int(str(r.get("comm_lv", "L0"))[1:])
                                               if str(r.get("comm_lv", "L0"))[1:].isdigit()
                                               else 0)):
            nl = c.get("node_list", [])
            files = json.loads(nl) if isinstance(nl, str) else nl
            for f in files:
                if f not in out:
                    out[f] = c.get("comm_id", "")
    deepest(db_inc, inc_parts)
    deepest(db_call, call_parts)

    max_depth = 0
    counts: Dict[int, int] = defaultdict(int)

    def walk(nodes, level, parent_comm_id):
        nonlocal max_depth
        max_depth = max(max_depth, level)
        nodes = sorted(nodes, key=lambda x: sorted(x["members"]))
        for i, n in enumerate(nodes):
            cid = f"comm-{task_id[:8]}-uni-L{level}-{i:04d}"
            counts[level] += 1
            members = n["members"]
            meta = _evidence_metrics(members, n["evidence"], inc_pairs,
                                     call_pairs, inc_parts, call_parts)
            edge_list = []
            for a, b in sorted(inc_pairs):
                if a in members and b in members:
                    edge_list.append({"source": a, "target": b, "direction": "imports"})
            for a, b in sorted(call_pairs):
                if a in members and b in members:
                    edge_list.append({"source": a, "target": b, "direction": "calls"})
            comm_docs = [{
                "task_id": task_id,
                "edge_type": "UNIFIED",
                "comm_lv": f"L{level}",
                "parent_comm_id": parent_comm_id,
                "comm_id": cid,
                "node_list": sorted(members),
                "node_count": len(members),
                "file_count": len(members),
                "edge_list": edge_list,
                "edge_count": len(edge_list),
                "quality_score": _modularity_of(members, inc_pairs | call_pairs),
                "description": f"UNIFIED community at L{level}, {len(members)} nodes, "
                               f"{len(edge_list)} edges, evidence={n['evidence']}",
                "metadata": json.dumps(meta, ensure_ascii=False),
            }]
            hierarchies = [{
                "task_id": task_id,
                "edge_type": "UNIFIED",
                "comm_lv": f"L{level}",
                "comm_id": cid,
                "parent_comm_id": parent_comm_id,
                "node_count": len(members),
                "file_count": len(members),
                "edge_count": len(edge_list),
                "quality_score": comm_docs[0]["quality_score"],
            }]
            analysis_store.bulk_insert_communities(comm_docs)
            analysis_store.bulk_insert_hierarchy(hierarchies)
            if n["children"]:
                walk(n["children"], level + 1, cid)

    walk(tree.get("L0", []), 0, None)
    return max_depth + 1 if any(tree.get("L0", [])) else 0
