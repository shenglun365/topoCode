#!/usr/bin/env python3
"""
KB 组件统一方案 Phase 0 验证脚本（独立，仅 stdlib，不改生产代码）
按 docs/kb-unified-components-plan.md 表 A–E 实现对齐合并，输出 §6 全指标报告。

用法:
  python3 scripts/unified_merge_eval.py --db <project.db> [--task <task_id>]
      [--tau 0.9] [--tau-lo 0.6] [--order A_first] [--min-node 6]
      [--sweep] [--out <report.json>]

--sweep: 运行 τ 扫描 {0.8,0.85,0.9,0.95} × τ_lo 扫描 {0.5,0.6,0.7} × 顺序对照
"""

import argparse
import json
import sqlite3
import sys
from collections import defaultdict

TAU = 0.9
TAU_LO = 0.6
MIN_NODE = 6
DEEPEST_LEVELS = 6


# ==================== 数据加载 ====================

def load_edges(db, kind):
    """graph_edge(kind) → 文件对集合（同文件剔除，二值化）"""
    rows = db.execute(
        """SELECT gn_s.file_path AS sf, gn_t.file_path AS tf
           FROM graph_edge ge
           JOIN graph_node gn_s ON gn_s.id = ge.source_id
           JOIN graph_node gn_t ON gn_t.id = ge.target_id
           WHERE ge.kind = ?""", (kind,)).fetchall()
    pairs = set()
    skipped = 0
    for sf, tf in rows:
        if not sf or not tf or sf == tf:
            skipped += 1
            continue
        pairs.add((sf, tf) if sf < tf else (tf, sf))
    return pairs, skipped


def load_communities(db, task_id):
    """graph_doc → {line: {level: {comm_id: set(files)}}}（L* 层级）"""
    out = {"INCLUDE": defaultdict(dict), "CALL": defaultdict(dict)}
    rows = db.execute(
        """SELECT edge_type, comm_lv, comm_id, node_list
           FROM graph_doc WHERE task_id = ? AND comm_lv LIKE 'L%'""",
        (task_id,)).fetchall()
    for et, lv, cid, nlist in rows:
        files = set(json.loads(nlist)) if isinstance(nlist, str) else set(nlist)
        if files:
            out[et][lv][cid] = files
    return out


def load_quality(db, task_id):
    rows = db.execute(
        """SELECT edge_type, MIN(quality_score), COUNT(*)
           FROM graph_doc WHERE task_id=? AND comm_lv='L0' GROUP BY edge_type""",
        (task_id,)).fetchall()
    return {et: {"min_q0": q, "n_l0": n} for et, q, n in rows}


# ==================== 表 A：区域判定 ====================

def classify(rI, rC, tau, tau_lo):
    if rI >= tau and rC >= tau:
        return "A"
    if rC >= tau and rI < tau:
        return "B"
    if rI >= tau and rC < tau:
        return "C"
    return "D1" if min(rI, rC) >= tau_lo else "D2"


# ==================== 表 B：逐层消费 ====================

def merge_layer(i_cands, c_cands, inc_pairs, call_pairs, tau, tau_lo, order, min_node,
                s_inc=1.0, s_call=1.0, residual=True):
    """单层合并。i_cands/c_cands: {comm_id: set(files)}
    返回 (new_comps, pool, stats)
      new_comps: [{members:set, evidence, kind:'base'|'protected'|'normal'}]
      pool: 仲裁池文件列表
      stats: 区域计数等
    """
    # --- 配对判定 ---
    pairs = {}
    for iid, I in i_cands.items():
        for cid, C in c_cands.items():
            inter = I & C
            if not inter:
                continue
            rI = len(inter) / len(I)
            rC = len(inter) / len(C)
            pairs[(iid, cid)] = (classify(rI, rC, tau, tau_lo), rI, rC)

    def pair_key(item):
        (iid, cid), (rg, rI, rC) = item
        return (-min(rI, rC), -min(len(i_cands[iid]), len(c_cands[cid])), iid, cid)

    a_list = sorted(((k, v) for k, v in pairs.items() if v[0] == "A"), key=pair_key)
    bc_list = sorted(((k, v) for k, v in pairs.items() if v[0] in ("B", "C")), key=pair_key)
    d1_list = sorted(((k, v) for k, v in pairs.items() if v[0] == "D1"), key=pair_key)

    consumed = set()
    # container_id -> [base_id,...]（B/C 区域登记）
    bases_of = defaultdict(list)
    base_line = {}          # base_id -> 所属线
    protected = set()       # R-void：保留资格的作废基础件
    new_comps = []
    pool = []
    stats = {"A": 0, "B": 0, "C": 0, "D1": 0, "D2": 0,
             "pairs_total": len(i_cands) * len(c_cands)}
    for (iid, cid), (rg, _, _) in pairs.items():
        stats[rg] += 1

    # R-void 预计算：每个社区作为容器的全部基础件（基于全量配对，与消费顺序无关）
    all_bases_of = defaultdict(list)
    for (iid, cid), (rg, _, _) in pairs.items():
        if rg == "B":
            all_bases_of[iid].append(cid)     # C 为 I 的基础件
        elif rg == "C":
            all_bases_of[cid].append(iid)     # I 为 C 的基础件

    def consume_a(iid, cid):
        members = set(i_cands[iid]) | set(c_cands[cid])
        new_comps.append({"members": members, "evidence": "BOTH", "kind": "normal"})
        # R-void：双方容器的全部基础件保留资格（含尚未登记到的）
        for container in (iid, cid):
            for b in all_bases_of.get(container, []):
                if b not in consumed:
                    protected.add(b)
        consumed.add(iid)
        consumed.add(cid)

    def consume_bc(container, base):
        bases_of[container].append(base)
        base_line[base] = "CALL" if base in c_cands else "INCLUDE"

    phases = [bc_list, a_list] if order == "BC_first" else [a_list, bc_list]
    for phase in phases:
        for (iid, cid), (rg, _, _) in phase:
            if iid in consumed or cid in consumed:
                continue
            if rg == "A":
                consume_a(iid, cid)
            elif rg == "B":      # C 为 I 的基础件
                consume_bc(iid, cid)
            else:                # C 为 I 的基础件对称（I 含于 C）
                consume_bc(cid, iid)

    # 池/残余判定用全量邻接（双线合并视界）
    nbr_all = defaultdict(set)
    for a, b in inc_pairs:
        nbr_all[a].add(b)
        nbr_all[b].add(a)
    for a, b in call_pairs:
        nbr_all[a].add(b)
        nbr_all[b].add(a)

    # --- P2：容器拆解 ---
    for container in sorted(bases_of):
        if container in consumed:
            continue  # 已被 A-对消费 → 基础件走 R-void 保护
        bases = sorted(set(bases_of[container]))
        covered = set()
        for b in bases:
            if b in consumed:
                continue
            consumed.add(b)
            covered |= c_cands.get(b) or i_cands[b]
            new_comps.append({"members": set(i_cands.get(b) or c_cands[b]),
                              "evidence": base_line[b], "kind": "base"})
        container_files = (i_cands.get(container) or c_cands[container])
        container_line = "INCLUDE" if container in i_cands else "CALL"
        leftover = [cand for cand in container_files if cand not in covered]
        # R-resid 条件版：仅当残余多数文件与已形成组件零邻接（仲裁池无法安放）时成组
        if residual and len(leftover) >= min_node:
            # 判定视野 = 全部潜在组件成员（已形成 + 未消耗候选），排除残余自身
            cand_files_all = set()
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

    # --- P2 补漏：被 A 消费容器的潜在基础件 → R-void 保护 ---
    for container, blist in all_bases_of.items():
        if container in consumed:
            for b in blist:
                if b not in consumed:
                    protected.add(b)

    # --- P2.5：D1 弱并 ---
    for (iid, cid), _ in d1_list:
        if iid in consumed or cid in consumed:
            continue
        new_comps.append({"members": set(i_cands[iid]) | set(c_cands[cid]),
                          "evidence": "WEAK", "kind": "normal"})
        consumed.update([iid, cid])

    # --- P3：独立候选 + E4 ---
    for line, cands in (("INCLUDE", i_cands), ("CALL", c_cands)):
        for cid in sorted(cands):
            if cid in consumed:
                continue
            members = cands[cid]
            if len(members) >= min_node:
                kind = "protected" if cid in protected else "normal"
                new_comps.append({"members": set(members), "evidence": line, "kind": kind})
            else:
                pool.extend(members)
            consumed.add(cid)

    stats["new_comps"] = len(new_comps)
    stats["pool"] = len(pool)
    stats["protected"] = len(protected)
    # 出身映射：file -> [来源社区成员集]（强制归入级联用）
    prov = defaultdict(list)
    for line, cands in (("INCLUDE", i_cands), ("CALL", c_cands)):
        for cid, files in cands.items():
            prov_members = frozenset(files)
            for f in files:
                prov[f].append(prov_members)
    return new_comps, pool, stats, prov


# ==================== 表 C：文件归属仲裁 ====================

def assign_files(new_comps, pool, inc_pairs, call_pairs, s_inc=1.0, s_call=1.0,
                 prov=None, force=True, min_node=6):
    """F1/F2 定属 + F3 仲裁池。返回 (assignment, unassigned)
    assignment: file -> comp_idx；unassigned: [file]"""
    # 双线邻接表（分别计权）
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

    ev_rank = {"base": 3, "protected": 3, "BOTH": 2, "WEAK": 1, "INCLUDE": 0, "CALL": 0}

    def comp_score(f, idx):
        m = members_list[idx]
        if f not in nbr_inc and f not in nbr_call:
            return 0
        return (s_inc * sum(1 for k in m if k in nbr_inc.get(f, ()))
                + s_call * sum(1 for k in m if k in nbr_call.get(f, ())))

    assignment = {}
    unassigned = []
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

    # ===== F3-bis 强制归入级联（消除合并覆盖率损失） =====
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
            """出身多数：来源社区中其他已分配成员的多数归属"""
            placed = 0
            for f in list(unplaced):
                cnt = defaultdict(int)
                for om in prov.get(f, ()):
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
            """邻居跟随：双线图邻接中已分配成员的多数归属（一跳）"""
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

        for _ in range(4):                      # 传播至不动点（池簇逐波吸附）
            if not unplaced:
                break
            n = wave_origin() + wave_neighbor()
            if n == 0:
                break

        if unplaced:                            # 池级残余成组（≥min_node 且内部连通）
            by_origin = defaultdict(list)
            for f in unplaced:
                key = min((id(om) for om in prov.get(f, ())), default=id(None))
                by_origin[key].append(f)
            for key, group in sorted(by_origin.items(), key=lambda t: -len(t[1])):
                gset = set(group)
                if len(gset) >= min_node and any(
                        any(nb in gset for nb in nbr_all.get(f, ())) for f in gset):
                    new_comps.append({"members": gset, "evidence": "FORCED", "kind": "normal"})
                    members_list.append(gset)
                    for f in group:
                        assignment[f] = len(members_list) - 1
                    unplaced = [f for f in unplaced if f not in gset]
            for _ in range(2):                  # 新组件出现后再传播一轮
                if not unplaced:
                    break
                if wave_origin() + wave_neighbor() == 0:
                    break

        if unplaced:                            # 终极兜底：目录多数 → 最大组件（保证 100%）
            def dirname(fpath):
                return fpath.rsplit("/", 1)[0] if "/" in fpath else ""
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
        # 级联后统一同步：unplaced 即真残余（正常应为空）
        unassigned = list(unplaced)

    return assignment, unassigned


# ==================== 全量合并（逐层递归） ====================

def merge_all(comms, inc_pairs, call_pairs, tau, tau_lo, order, min_node,
              s_inc=1.0, s_call=1.0, residual=True):
    """返回统一树 {level: [comp...]}，comp 含 members/evidence/children"""
    i_levels = comms["INCLUDE"]
    c_levels = comms["CALL"]
    universe = set()
    for lv in i_levels:
        for s in i_levels[lv].values():
            if lv == "L0":
                universe |= s
    for lv in c_levels:
        for s in c_levels[lv].values():
            if lv == "L0":
                universe |= s

    max_depth = max([1] + [int(lv[1:]) for lv in list(i_levels) + list(c_levels)])
    tree = {}

    def recurse(parent_members, level):
        if level == 0:
            # L0 不做 min_node 预筛（小社区应走 P3/E4 解散入池，而非剔除）
            i_cands = dict(i_levels.get("L0", {}))
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
        new_comps, pool, stats, prov = merge_layer(i_cands, c_cands, inc_pairs,
                                             call_pairs, tau, tau_lo, order, min_node,
                                             s_inc, s_call, residual)
        assignment, unassigned = assign_files(new_comps, pool, inc_pairs, call_pairs,
                                              s_inc, s_call, prov, True, min_node)
        groups = defaultdict(set)
        for f, idx in assignment.items():
            groups[idx].add(f)
        out = []
        for idx, c in enumerate(new_comps):
            members = groups.get(idx, set())
            node = {"members": members, "evidence": c["evidence"], "kind": c["kind"],
                    "unassigned": [], "children": []}
            if level < max_depth and members:
                children, sub_unassigned, _ = recurse(members, level + 1)
                node["children"] = children
                node["unassigned"] = sorted(set(sub_unassigned) & members)
            out.append(node)
        # 本层未分配（限父范围）
        layer_unassigned = sorted(set(unassigned) & parent_members)
        return out, layer_unassigned, stats

    root, _, l0_stats = recurse(universe, 0)
    tree["L0"] = root
    tree["_stats_L0"] = l0_stats
    return tree, universe


# ==================== 指标 ====================

def modularity(pairs, partition):
    """二值无向图模块度；partition: {file: part_id}（仅限图内节点）"""
    nodes = set()
    for a, b in pairs:
        nodes.add(a)
        nodes.add(b)
    m = len(pairs)
    if m == 0 or not nodes:
        return 0.0
    deg = defaultdict(int)
    for a, b in pairs:
        deg[a] += 1
        deg[b] += 1
    part_of = {n: partition.get(n, f"__iso_{n}") for n in nodes}
    in_sum = defaultdict(int)
    for a, b in pairs:
        if part_of[a] == part_of[b]:
            key = part_of[a]
            in_sum[key] += 1
    q = 0.0
    parts = defaultdict(list)
    for n, p in part_of.items():
        parts[p].append(n)
    for p, ns in parts.items():
        kin = in_sum.get(p, 0)           # 内部边数（每条计 1）
        ktot = sum(deg[n] for n in ns)
        q += kin / m - (ktot / (2 * m)) ** 2   # Q = Σ[ in_c/m − (k_c/2m)² ]
    return q


def line_partition_on(nodes, comms_line):
    """线内最深层级身份映射 file -> comm_id"""
    out = {}
    for lv in sorted(comms_line, key=lambda x: int(x[1:]), reverse=True):
        for cid, files in comms_line[lv].items():
            for f in files:
                if f in nodes and f not in out:
                    out[f] = cid
    return out


def flatten_tree(tree_nodes, acc=None):
    if acc is None:
        acc = []
    for n in tree_nodes:
        acc.append(n)
        flatten_tree(n["children"], acc)
    return acc


def nmi(part_a, part_b):
    """NMI（算术平均归一）；part_*: file -> cluster_id"""
    import math
    from collections import Counter
    common = set(part_a) & set(part_b)
    n = len(common)
    if n == 0:
        return 0.0
    ca = Counter(part_a[f] for f in common)
    cb = Counter(part_b[f] for f in common)
    cont = Counter((part_a[f], part_b[f]) for f in common)
    mi = sum(cab / n * math.log(n * cab / (ca[ka] * cb[kb]))
             for (ka, kb), cab in cont.items())
    ha = -sum(c / n * math.log(c / n) for c in ca.values())
    hb = -sum(c / n * math.log(c / n) for c in cb.values())
    return round(mi / ((ha + hb) / 2), 4) if ha + hb else 1.0


def eval_metrics(tree, universe, inc_pairs, call_pairs, comms, min_q):
    l0 = tree["L0"]
    stats = tree["_stats_L0"]
    l0_parts = {}
    for i, n in enumerate(sorted(l0, key=lambda x: sorted(x["members"]))):
        for f in n["members"]:
            l0_parts[f] = i

    # Q gate
    q_inc = modularity(inc_pairs, l0_parts)
    q_call = modularity(call_pairs, l0_parts)
    ref_inc = ref_call = 0.0
    for lv in comms["INCLUDE"]:
        p = line_partition_on({f for a, b in inc_pairs for f in (a, b)},
                              {"L0": comms["INCLUDE"][lv]})
        ref_inc = max(ref_inc, modularity(inc_pairs, p))
    for lv in comms["CALL"]:
        p = line_partition_on({f for a, b in call_pairs for f in (a, b)},
                              {"L0": comms["CALL"][lv]})
        ref_call = max(ref_call, modularity(call_pairs, p))

    # 未分配率
    all_nodes = flatten_tree(l0)
    unassigned_total = sum(len(n["unassigned"]) for n in all_nodes)
    l0_unassigned = len(l0_parts)  # 已定属文件数
    orphans = len(universe) - l0_unassigned

    # 证据分布 / 深度
    ev_count = defaultdict(int)
    depth_max = 0

    def walk(nodes, d):
        nonlocal depth_max
        for n in nodes:
            ev_count[n["evidence"]] += 1
            depth_max = max(depth_max, d)
            walk(n["children"], d + 1)
    walk(l0, 0)

    # 小组件存活率（<20 成员的源社区，≥70% 成员落入同一 U 组件）
    l0_group_of = {}
    comp_members = defaultdict(set)
    for i, n in enumerate(sorted(l0, key=lambda x: sorted(x["members"]))):
        for f in n["members"]:
            comp_members[i].add(f)
            l0_group_of[f] = i
    small_total = small_alive = 0
    for line in ("INCLUDE", "CALL"):
        for lv in comms[line]:
            for files in comms[line][lv].values():
                if len(files) >= 20:
                    continue
                small_total += 1
                cnt = defaultdict(int)
                for f in files:
                    cnt[l0_group_of.get(f, "__none__")] += 1
                if cnt and max(cnt.values()) / len(files) >= 0.7 and \
                        max(cnt, key=cnt.get) != "__none__":
                    small_alive += 1

    # 单线独有文件率
    inc_files = set()
    for lv in comms["INCLUDE"]:
        for s in comms["INCLUDE"][lv].values():
            inc_files |= s
    call_files = set()
    for lv in comms["CALL"]:
        for s in comms["CALL"][lv].values():
            call_files |= s
    single_only = len((inc_files - call_files) | (call_files - inc_files))

    n_l0 = len(l0)
    inc_n_l0 = sum(1 for _ in comms["INCLUDE"].get("L0", {}))

    # 线间一致性诊断：交叉模块度天花板 + NMI + 帕累托判定
    inc_l0_part = {f: i for i, (_, s) in enumerate(sorted(comms["INCLUDE"].get("L0", {}).items()))
                   for f in s}
    call_l0_part = {f: i for i, (_, s) in enumerate(sorted(comms["CALL"].get("L0", {}).items()))
                    for f in s}
    ceil_call_side = (modularity(call_pairs, inc_l0_part) / ref_call) if ref_call else None
    ceil_inc_side = (modularity(inc_pairs, call_l0_part) / ref_inc) if ref_inc else None
    deepest_inc = line_partition_on(inc_files, comms["INCLUDE"])
    deepest_call = line_partition_on(call_files, comms["CALL"])
    pareto = (q_inc / ref_inc >= (ceil_inc_side or 0) - 1e-9
              and q_call / ref_call >= (ceil_call_side or 0) - 1e-9) if ref_inc and ref_call else None
    return {
        "ceiling_inc_side": round(ceil_inc_side, 3) if ceil_inc_side is not None else None,
        "ceiling_call_side": round(ceil_call_side, 3) if ceil_call_side is not None else None,
        "pareto_vs_ceilings": pareto,
        "nmi_lines": nmi(deepest_inc, deepest_call),
        "q_inc": round(q_inc, 4), "q_call": round(q_call, 4),
        "ref_inc": round(ref_inc, 4), "ref_call": round(ref_call, 4),
        "gate_q_ratio_inc": round(q_inc / ref_inc, 3) if ref_inc else None,
        "gate_q_ratio_call": round(q_call / ref_call, 3) if ref_call else None,
        "universe": len(universe),
        "assigned_l0": l0_unassigned,
        "orphan_or_unassigned": orphans + unassigned_total,
        "unassigned_rate": round((orphans + unassigned_total) / len(universe), 4),
        "n_unified_l0": n_l0, "n_inc_l0": inc_n_l0,
        "count_ratio": round(n_l0 / inc_n_l0, 2) if inc_n_l0 else None,
        "depth_max": depth_max,
        "evidence": dict(ev_count),
        "region_stats": stats,
        "small_total": small_total, "small_alive": small_alive,
        "small_survival": round(small_alive / small_total, 3) if small_total else None,
        "single_line_only_files": single_only,
        "single_line_rate": round(single_only / len(universe), 4),
        "hub_diff_rate": None,  # 成功路径不落库 HUB → N/A
    }


# ==================== 序列化与确定性 ====================

def tree_to_json(tree_nodes):
    out = []
    for n in tree_nodes:
        out.append({
            "members": sorted(n["members"]),
            "evidence": n["evidence"],
            "kind": n["kind"],
            "unassigned": sorted(n["unassigned"]),
            "children": tree_to_json(n["children"]),
        })
    out.sort(key=lambda x: x["members"])
    return out


# ==================== 主流程 ====================

def run_once(db_path, task_id, tau, tau_lo, order, min_node, s_inc=1.0, s_call=1.0,
             residual=True):
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    comms = load_communities(db, task_id)
    inc_pairs, _ = load_edges(db, "imports")
    call_pairs, _ = load_edges(db, "calls")
    qual = load_quality(db, task_id)
    db.close()
    tree, universe = merge_all(comms, inc_pairs, call_pairs, tau, tau_lo, order, min_node,
                               s_inc, s_call, residual)
    metrics = eval_metrics(tree, universe, inc_pairs, call_pairs, comms, qual)
    canon = json.dumps(tree_to_json(tree["L0"]), sort_keys=True, ensure_ascii=False)
    return metrics, canon, qual


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--task", default=None)
    ap.add_argument("--tau", type=float, default=TAU)
    ap.add_argument("--tau-lo", type=float, default=TAU_LO)
    ap.add_argument("--order", default="A_first", choices=["A_first", "BC_first"])
    ap.add_argument("--min-node", type=int, default=MIN_NODE)
    ap.add_argument("--s-inc", type=float, default=1.0)
    ap.add_argument("--no-residual", action="store_true")
    ap.add_argument("--s-call", type=float, default=1.0)
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    db = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    if args.task:
        task_id = args.task
    else:
        row = db.execute(
            """SELECT task_id, COUNT(*) c FROM graph_doc
               WHERE comm_lv LIKE 'L%' GROUP BY task_id ORDER BY c DESC LIMIT 1"""
        ).fetchone()
        task_id = row[0]
    db.close()

    print(f"== Phase 0 对齐合并评估 == task={task_id}")
    print(f"   τ={args.tau} τ_lo={args.tau_lo} order={args.order} min_node={args.min_node}")

    metrics, canon, qual = run_once(args.db, task_id, args.tau, args.tau_lo,
                                    args.order, args.min_node, args.s_inc, args.s_call,
                                    not args.no_residual)

    # 双跑确定性
    metrics2, canon2, _ = run_once(args.db, task_id, args.tau, args.tau_lo,
                                   args.order, args.min_node, args.s_inc, args.s_call,
                                    not args.no_residual)
    metrics["deterministic"] = (canon == canon2)

    report = {"task_id": task_id, "params": {
        "tau": args.tau, "tau_lo": args.tau_lo, "order": args.order,
        "min_node": args.min_node}, "metrics": metrics,
        "line_quality_l0": qual}

    print("\n-- 主跑指标 --")
    print(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True))

    gate = []
    r_i, r_c = metrics.get("gate_q_ratio_inc"), metrics.get("gate_q_ratio_call")
    gate.append(("Q_ratio_inc ≥ 0.7", r_i is not None and r_i >= 0.7, r_i))
    gate.append(("Q_ratio_call ≥ 0.7", r_c is not None and r_c >= 0.7, r_c))
    ur = metrics["unassigned_rate"]
    gate.append(("未分配率 ≤ 0.10", ur <= 0.10, ur))
    cr = metrics.get("count_ratio")
    gate.append(("组件数比 ∈ [0.5,1.5]", cr is not None and 0.5 <= cr <= 1.5, cr))
    gate.append(("双跑 diff 为空", metrics["deterministic"], None))
    print("\n-- Gate 判定 --")
    for name, ok, val in gate:
        print(f"   [{'PASS' if ok else 'FAIL'}] {name}" + (f" = {val}" if val is not None else ""))

    if args.sweep:
        print("\n-- 扫描（组件数/未分配率/Q比/存活率） --")
        sweep_rows = []
        for tau in (0.8, 0.85, 0.9, 0.95):
            for tau_lo in (0.5, 0.6, 0.7):
                if tau_lo >= tau:
                    continue
                for order in ("A_first", "BC_first"):
                    m, _, _ = run_once(args.db, task_id, tau, tau_lo, order, args.min_node)
                    row = {
                        "tau": tau, "tau_lo": tau_lo, "order": order,
                        "n_l0": m["n_unified_l0"],
                        "unassigned": m["unassigned_rate"],
                        "q_ratio_inc": m["gate_q_ratio_inc"],
                        "q_ratio_call": m["gate_q_ratio_call"],
                        "survival": m["small_survival"],
                        "evidence": m["evidence"],
                    }
                    sweep_rows.append(row)
                    print(f"   τ={tau} τ_lo={tau_lo} {order:9s} | "
                          f"L0={row['n_l0']:3d} 未分配={row['unassigned']:.3f} "
                          f"Q比=({row['q_ratio_inc']},{row['q_ratio_call']}) "
                          f"存活={row['survival']}")
        report["sweep"] = sweep_rows

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"\n报告已写入 {args.out}")


if __name__ == "__main__":
    sys.exit(main())
