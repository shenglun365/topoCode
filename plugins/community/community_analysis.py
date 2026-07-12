"""
Community Analysis — 社区分析（纯内存 + SQLite 写入）

从 SQLite 加载调用/依赖边数据，构建图，执行社区检测（Leiden 首选 / Louvain 回退），
递归分层分析，结果写入 graph_doc + community_hierarchy 表。

改进：
- Leiden 算法（连通性保证、更稳定、更快收敛），Louvain 为回退
- 枢纽节点过滤（degree > total_nodes * 0.3 或 > 50）
- 孤立节点标记（移除枢纽后 degree ≤ 1）
- 质量分使用模块度而非图密度
- 同文件内调用降权而非删除（备选方案）
- CALL min_node_cnt 降低至 12
"""

import json
import logging
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

import networkx as nx
from community import community_louvain

try:
    import leidenalg as la
    import igraph as ig
    _LEIDEN_AVAILABLE = True
except ImportError:
    _LEIDEN_AVAILABLE = False
    la = None
    ig = None

from config import (
    HUB_DEGREE_RATIO, HUB_MIN_DEGREE, ORPHAN_MAX_DEGREE,
    INTRAn_FILE_EDGE_WEIGHT, INTRAn_FILE_EDGE_FALLBACK_WEIGHT,
    LARGE_GRAPH_NODE_THRESHOLD,
)

logger = logging.getLogger(__name__)


# ==================== 主入口 ====================

def analyze_communities(task_id: str, analysis_store, edge_type: str,
                        min_node_cnt: int = 10) -> Dict:
    """
    执行社区分析

    Args:
        task_id: 任务 ID
        analysis_store: AnalysisStore 实例
        edge_type: "INCLUDE" 或 "CALL"
        min_node_cnt: 最小节点数（低于此值的子社区不再递归）

    Returns:
        {"community_count": int, "levels": int, "hub_count": int, "orphan_count": int}
    """
    logger.info(f"[COMMUNITY] analyze_communities 入口: task_id={task_id}, edge_type={edge_type}, min_node_cnt={min_node_cnt}")

    # 0. 清理旧数据，防止多次运行导致重复
    analysis_store.clear_communities_for_task(task_id, edge_type)

    # 1. 从 SQLite 加载边数据
    if edge_type == "INCLUDE":
        edges = analysis_store.get_dep_edges(task_id)
    elif edge_type == "CALL":
        edges = analysis_store.get_call_edges(task_id)
    else:
        logger.warning(f"未知的 edge_type: {edge_type}")
        return {"community_count": 0, "levels": 0, "hub_count": 0, "orphan_count": 0}

    logger.info(f"[COMMUNITY] {edge_type}: 加载边数据完成, count={len(edges)}")
    if edges:
        logger.info(f"[COMMUNITY] {edge_type}: 首条边样例 keys={list(edges[0].keys())}")

    if not edges:
        logger.info(f"[COMMUNITY] {edge_type}: 没有边数据，跳过")
        return {"community_count": 0, "levels": 0, "hub_count": 0, "orphan_count": 0}

    # 2. 构建 node_lookup (v2: source_id/target_id → file_path, name)
    node_lookup = _build_node_lookup(analysis_store, task_id)

    # 3. 构建图 + 枢纽/孤立节点过滤
    graph, edge_directions, hub_nodes, orphan_nodes, node_coreness = _build_graph(
        edges, edge_type, filter_intra_file=False, node_lookup=node_lookup
    )
    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    # 分析过滤后节点格式
    community_ready = all_nodes - hub_nodes - orphan_nodes
    fp_nodes = [n for n in community_ready if '/' in n or '\\' in n]
    id_nodes = [n for n in community_ready if '/' not in n and '\\' not in n]
    bs_nodes = [n for n in community_ready if '\\' in n]
    logger.info(
        f"[COMMUNITY] {edge_type}: 过滤后 {len(all_nodes)} 节点, "
        f"入社区={len(community_ready)}, HUB={len(hub_nodes)}, ORPHAN={len(orphan_nodes)}, "
        f"社区文件路径={len(fp_nodes)}, ID-fallback={len(id_nodes)}, 含反斜杠={len(bs_nodes)}"
    )

    if len(all_nodes) < min_node_cnt:
        logger.info(
            f"[COMMUNITY] {edge_type}: 过滤后节点数 {len(all_nodes)} < {min_node_cnt}"
            f" (枢纽={len(hub_nodes)}, 孤立={len(orphan_nodes)})，跳过"
        )
        _save_special_nodes(task_id, edge_type, hub_nodes, orphan_nodes, graph, edge_directions, analysis_store)
        return {"community_count": 0, "levels": 0,
                "hub_count": len(hub_nodes), "orphan_count": len(orphan_nodes)}

    logger.info(
        f"[COMMUNITY] {edge_type}: 图包含 {len(all_nodes)} 个节点, {len(edges)} 条边"
        f" (枢纽={len(hub_nodes)}, 孤立={len(orphan_nodes)})"
    )

    # 3. 执行社区检测
    communities = _detect_communities(graph, all_nodes)

    if not communities:
        _save_special_nodes(task_id, edge_type, hub_nodes, orphan_nodes, graph, edge_directions, analysis_store)
        return {"community_count": 0, "levels": 0,
                "hub_count": len(hub_nodes), "orphan_count": len(orphan_nodes)}

    # 4. 保存 L0 层级
    level = "L0"
    parent_comm_id = None
    saved, hub_saved, orphan_saved = _save_communities(
        task_id, edge_type, level, parent_comm_id,
        communities, graph, analysis_store, edge_directions,
        node_lookup=node_lookup,
        node_coreness=node_coreness,
    )

    # 5. 检测是否需要备选方案（CALL 图连通性过高）
    use_fallback = False
    if edge_type == "CALL" and len(communities) == 1:
        l0_comms = analysis_store.get_communities(task_id, edge_type, "L0")
        if l0_comms and l0_comms[0].get("quality_score", 1.0) < 0.01:
            use_fallback = True
            logger.info(
                f"[COMMUNITY] CALL: 检测到超级连通分量（1 个社区，质量分={l0_comms[0]['quality_score']:.4f}），"
                f"启用备选方案：同文件内调用降权"
            )

    if use_fallback:
        analysis_store.clear_communities_for_task(task_id, edge_type)
        logger.info(f"[COMMUNITY] CALL: 已清除默认方案的社区数据，重新分析")

        # 重新构建图（同文件内调用降权而非删除）
        graph, edge_directions, hub_nodes, orphan_nodes, node_coreness = _build_graph(
            edges, edge_type, filter_intra_file=False,
            intra_file_weight=INTRAn_FILE_EDGE_FALLBACK_WEIGHT,
            node_lookup=node_lookup,
        )
        graph, edge_directions, hub_nodes, orphan_nodes = _filter_hubs_and_orphans(
            graph, edge_directions
        )
        all_nodes = set(graph.keys())
        for neighbors in graph.values():
            all_nodes.update(neighbors)

        if len(all_nodes) < min_node_cnt:
            logger.info(f"[COMMUNITY] CALL (备选): 节点数 {len(all_nodes)} < {min_node_cnt}，跳过")
            _save_special_nodes(task_id, edge_type, hub_nodes, orphan_nodes, graph, edge_directions, analysis_store)
            return {"community_count": 0, "levels": 0,
                    "hub_count": len(hub_nodes), "orphan_count": len(orphan_nodes)}

        logger.info(f"[COMMUNITY] CALL (备选): 图包含 {len(all_nodes)} 个节点")

        communities = _detect_communities(graph, all_nodes)
        if not communities:
            _save_special_nodes(task_id, edge_type, hub_nodes, orphan_nodes, graph, edge_directions, analysis_store)
            return {"community_count": 0, "levels": 0,
                    "hub_count": len(hub_nodes), "orphan_count": len(orphan_nodes)}

        saved, hub_saved, orphan_saved = _save_communities(
            task_id, edge_type, level, parent_comm_id,
            communities, graph, analysis_store, edge_directions,
            node_lookup=node_lookup,
            node_coreness=node_coreness,
        )
        logger.info(f"[COMMUNITY] CALL (备选): L0 产生 {len(communities)} 个社区")

    # 6. 递归分析子社区
    total_count = saved
    max_depth = 0
    for depth in range(1, 6):  # 最多 6 层
        sub_communities = _get_sub_communities(
            task_id, edge_type, level, graph, min_node_cnt, analysis_store
        )
        if not sub_communities:
            break

        new_level = f"L{depth}"
        new_saved = 0
        for parent_id, nodes in sub_communities.items():
            sub_graph = _build_sub_graph(graph, nodes)
            sub_comms = _detect_communities(sub_graph, set(nodes))
            if sub_comms:
                ns, _, _ = _save_communities(
                    task_id, edge_type, new_level, parent_id,
                    sub_comms, sub_graph, analysis_store, edge_directions,
                    node_lookup=node_lookup,
                    node_coreness=node_coreness,
                )
                new_saved += ns
                total_count += ns

        if new_saved == 0:
            break
        level = new_level
        max_depth = depth

    fallback_tag = " (备选)" if use_fallback else ""
    logger.info(
        f"[COMMUNITY] {edge_type}{fallback_tag}: "
        f"共 {total_count} 个社区, 枢纽 {hub_saved} 个, 孤立 {orphan_saved} 个"
    )

    # 7. 社区去重：父社区只有一个子社区时，对比节点相似度删除冗余子社区
    deleted = _deduplicate_single_child_communities(task_id, edge_type, analysis_store)
    if deleted:
        total_count -= deleted
        logger.info(f"[COMMUNITY] {edge_type}: 社区去重完成，已删除 {deleted} 个冗余子社区")

    return {
        "community_count": total_count,
        "levels": max_depth + 1 if total_count > 0 else 0,
        "hub_count": hub_saved,
        "orphan_count": orphan_saved,
    }


# ==================== 图构建 + 枢纽/孤立过滤 ====================

def _build_node_lookup(analysis_store, task_id: str) -> dict:
    """从 graph_node 表构建 node_id → (file_path, name) 映射 (v2)"""
    lookup = {}
    file_path_count = 0
    empty_path_count = 0
    path_samples = []
    try:
        nodes = analysis_store.get_graph_nodes(task_id)
        for n in nodes:
            nid = n.get("id", "")
            if nid:
                fp = n.get("file_path", "")
                lookup[nid] = (fp, n.get("name", ""))
                if fp:
                    file_path_count += 1
                    if len(path_samples) < 5:
                        path_samples.append((nid[:16], fp))
                else:
                    empty_path_count += 1
    except Exception:
        pass
    logger.info(
        f"[COMMUNITY] _build_node_lookup: total={len(lookup)}, "
        f"with_file_path={file_path_count}, empty_path={empty_path_count}"
    )
    if path_samples:
        logger.info(f"[COMMUNITY] node_lookup 样例: {path_samples}")
    return lookup


def _build_graph(edges: List[Dict], edge_type: str, *,
                 filter_intra_file: bool = False,
                 intra_file_weight: float = 1.0,
                 node_lookup: Dict[str, tuple] = None) -> Tuple[Dict, Dict, Set, Set, Dict]:
    """
    从边数据构建无向图（邻接表），含枢纽/孤立节点预过滤 + k-core 核心度。

    Returns:
        (filtered_graph, edge_directions, hub_nodes, orphan_nodes, node_coreness)
    """
    if filter_intra_file:
        intra_file_weight = 0.0

    # 构建 node_lookup (v2: 从 graph_node 查询)
    if node_lookup is None:
        node_lookup = {}

    graph = defaultdict(set)
    edge_directions = {}
    skipped = 0

    for edge in edges:
        if edge_type == "INCLUDE":
            # ── v2 schema: graph_edge (source_id, target_id) ──
            source_id = edge.get("source_id", "")
            target_id = edge.get("target_id", "")
            if source_id and target_id:
                src_info = node_lookup.get(source_id, ("", source_id))
                tgt_info = node_lookup.get(target_id, ("", target_id))
                # 使用 file_path 而非 name，避免同名文件在不同目录下冲突
                source = src_info[0] if src_info and src_info[0] else source_id
                target = tgt_info[0] if tgt_info and tgt_info[0] else target_id
            else:
                # fallback for old schema
                source = str(edge.get("file_id", ""))
                target = edge.get("include_path", "")
            if not source or not target:
                skipped += 1
                continue
            direction = "INCLUDE"

        elif edge_type == "CALL":
            # ── v2 schema: graph_edge 表 (source_id, target_id) ──
            source_id = edge.get("source_id", "")
            target_id = edge.get("target_id", "")

            if not source_id or not target_id:
                # 无法解析的调用 (metadata.method="unresolved") 直接跳过
                skipped += 1
                continue

            # 映射到文件级：将 source 和 target 都转换为其所在文件路径
            # v2 schema 中 source_id 通常是文件节点、target_id 是符号节点
            # 统一聚合为文件级图，避免符号节点全部沦为孤立节点
            src_info = node_lookup.get(source_id)
            tgt_info = node_lookup.get(target_id)

            src_file = src_info[0] if src_info and src_info[0] else source_id
            tgt_file = tgt_info[0] if tgt_info and tgt_info[0] else target_id

            if src_file == tgt_file:
                # 同文件内调用不参与文件级社区分析
                skipped += 1
                continue

            source = src_file
            target = tgt_file

            if not source or not target:
                skipped += 1
                continue

            direction = 'caller→callee'
        else:
            continue

        if source == target:
            skipped += 1
            continue

        graph[source].add(target)
        graph[target].add(source)
        edge_directions[(source, target)] = direction

    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    # 节点路径格式分析：统计是 file_path 还是 fallback ID
    path_nodes = [n for n in all_nodes if '/' in n or '\\' in n]
    id_nodes = [n for n in all_nodes if '/' not in n and '\\' not in n]
    backslash_nodes = [n for n in all_nodes if '\\' in n]
    logger.info(
        f"[COMMUNITY] _build_graph: edge_type={edge_type}, "
        f"edges_in={len(edges)}, edges_used={len(graph)//2}, skipped={skipped}"
        f", nodes={len(all_nodes)}"
        f", file_path_nodes={len(path_nodes)}, fallback_id_nodes={len(id_nodes)}"
    )
    if backslash_nodes and len(backslash_nodes) < 20:
        logger.info(f"[COMMUNITY] 含反斜杠节点({len(backslash_nodes)}): {sorted(backslash_nodes)}")
    elif backslash_nodes:
        logger.info(f"[COMMUNITY] 含反斜杠节点: {len(backslash_nodes)} 个, 前10: {sorted(backslash_nodes)[:10]}")
    if id_nodes:
        logger.info(f"[COMMUNITY] ID-fallback 节点({len(id_nodes)}): {sorted(id_nodes)[:10]}")

    # 节点度分布（分桶统计）
    degree_bins = {"0": 0, "1-2": 0, "3-5": 0, "6-10": 0, "11-20": 0, "21-50": 0, "51-100": 0, "100+": 0}
    for node in all_nodes:
        deg = len(graph.get(node, set()))
        if deg == 0: degree_bins["0"] += 1
        elif deg <= 2: degree_bins["1-2"] += 1
        elif deg <= 5: degree_bins["3-5"] += 1
        elif deg <= 10: degree_bins["6-10"] += 1
        elif deg <= 20: degree_bins["11-20"] += 1
        elif deg <= 50: degree_bins["21-50"] += 1
        elif deg <= 100: degree_bins["51-100"] += 1
        else: degree_bins["100+"] += 1
    logger.info(f"[COMMUNITY] 节点度分布(前HUB): {dict(degree_bins)}")

    # 过滤枢纽和孤立节点
    filtered_graph, hub_nodes, orphan_nodes = _filter_hubs_and_orphans(graph, edge_directions)

    node_coreness = _compute_coreness(graph, all_nodes)
    logger.info(f"[COMMUNITY] k-core: computed coreness for {len(node_coreness)} nodes, max={max(node_coreness.values()) if node_coreness else 0}")

    # 过滤 edge_directions
    filtered_directions = {}
    for (s, t), d in edge_directions.items():
        if s not in hub_nodes and s not in orphan_nodes \
           and t not in hub_nodes and t not in orphan_nodes:
            filtered_directions[(s, t)] = d

    return dict(filtered_graph), filtered_directions, hub_nodes, orphan_nodes, node_coreness


def _filter_hubs_and_orphans(graph: Dict[str, Set[str]],
                              edge_directions: Dict = None
                              ) -> Tuple[Dict[str, Set[str]], Set[str], Set[str]]:
    """
    从图中检测并移除枢纽节点和孤立节点。

    枢纽: degree > max(HUB_MIN_DEGREE, total_nodes * HUB_DEGREE_RATIO)
    孤立: 移除枢纽后 degree ≤ ORPHAN_MAX_DEGREE

    Returns:
        (filtered_graph, hub_nodes, orphan_nodes)
    """
    # 收集所有节点及其度
    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    degrees = {}
    for node in all_nodes:
        deg = len(graph.get(node, set()))
        degrees[node] = deg

    total_nodes = len(all_nodes)
    hub_threshold = max(HUB_MIN_DEGREE, int(total_nodes * HUB_DEGREE_RATIO))

    # 度分布日志（含 HUB 前）
    top_degrees = sorted(degrees.items(), key=lambda x: -x[1])[:10]
    logger.info(
        f"[COMMUNITY] 度分布 top10: {[(n[:40], d) for n, d in top_degrees]}"
    )

    # 第一阶段：识别枢纽
    hub_nodes = set()
    for node, deg in degrees.items():
        if deg > hub_threshold:
            hub_nodes.add(node)

    if hub_nodes:
        hub_details = [(n[:40], degrees[n]) for n in sorted(hub_nodes, key=lambda x: -degrees[x])]
        logger.info(
            f"[COMMUNITY] 枢纽节点: {len(hub_nodes)}/{total_nodes}"
            f" (threshold={hub_threshold}, total_nodes={total_nodes}, "
            f"HUB_MIN_DEGREE={HUB_MIN_DEGREE}, HUB_DEGREE_RATIO={HUB_DEGREE_RATIO})"
            f" 详情: {hub_details}"
        )
    else:
        logger.info(
            f"[COMMUNITY] 无枢纽节点 (threshold={hub_threshold}, "
            f"max_deg={max(degrees.values()) if degrees else 0})"
        )

    # 第二阶段：构建排除枢纽的图，识别孤立节点
    remaining_degrees = {}
    for node in all_nodes:
        if node in hub_nodes:
            continue
        neighbors = graph.get(node, set())
        filtered_neighbors = {n for n in neighbors if n not in hub_nodes}
        remaining_degrees[node] = len(filtered_neighbors)

    # 移除 HUB 后度分布
    rem_bins = {"0": 0, "1-2": 0, "3-5": 0, "6-10": 0, "11-20": 0, "21+": 0}
    for deg in remaining_degrees.values():
        if deg == 0: rem_bins["0"] += 1
        elif deg <= 2: rem_bins["1-2"] += 1
        elif deg <= 5: rem_bins["3-5"] += 1
        elif deg <= 10: rem_bins["6-10"] += 1
        elif deg <= 20: rem_bins["11-20"] += 1
        else: rem_bins["21+"] += 1
    logger.info(f"[COMMUNITY] 移除枢纽后度分布: {dict(rem_bins)}")

    # 检查仅通过 HUB 连接的文件
    only_via_hub = 0
    for node, deg in remaining_degrees.items():
        if deg == 0:
            orig_deg = degrees.get(node, 0)
            if orig_deg > 0:
                only_via_hub += 1
    logger.info(
        f"[COMMUNITY] 移除枢纽后度归零节点: 原度>0={only_via_hub}, 原度=0={sum(1 for n, d in remaining_degrees.items() if d==0 and degrees.get(n,0)==0)}"
    )

    orphan_nodes = set()
    for node, deg in remaining_degrees.items():
        if deg <= ORPHAN_MAX_DEGREE:
            orphan_nodes.add(node)

    if orphan_nodes:
        orphan_paths = sorted(orphan_nodes)[:20]
        orphan_id_nodes = [n for n in orphan_nodes if '/' not in n and '\\' not in n]
        logger.info(
            f"[COMMUNITY] 孤立节点: {len(orphan_nodes)}/{total_nodes}"
            f" (max_deg={ORPHAN_MAX_DEGREE})"
            f" 样例: {orphan_paths}"
            f" 含ID-fallback={len(orphan_id_nodes)}"
        )

    # 构建最终图
    filtered_graph = {}
    for node in all_nodes:
        if node in hub_nodes or node in orphan_nodes:
            continue
        neighbors = graph.get(node, set())
        filtered_neighbors = {
            n for n in neighbors
            if n not in hub_nodes and n not in orphan_nodes
        }
        if filtered_neighbors:
            filtered_graph[node] = filtered_neighbors

    # 记录被移除的节点中哪些原本具有社区价值
    saved_hubs = {node: degrees.get(node, 0) for node in hub_nodes}
    if saved_hubs and logger.isEnabledFor(logging.DEBUG):
        sorted_hubs = sorted(saved_hubs.items(), key=lambda x: -x[1])[:10]
        logger.debug(f"[COMMUNITY] 枢纽节点(前10): {sorted_hubs}")

    return filtered_graph, hub_nodes, orphan_nodes


def _build_sub_graph(graph: Dict[str, Set[str]], nodes: Set[str]) -> Dict[str, Set[str]]:
    """构建子图（只包含指定节点及其之间的边）"""
    sub = defaultdict(set)
    node_set = set(nodes)
    for node in node_set:
        if node in graph:
            for neighbor in graph[node]:
                if neighbor in node_set:
                    sub[node].add(neighbor)
    return dict(sub)


def _compute_coreness(graph: Dict[str, Set[str]],
                      nodes: Set[str]) -> Dict[str, int]:
    """计算全图各节点的 k-core 核心度（coreness）。

    coreness = 节点所在最深 k-core 的 k 值：
    - 高 coreness（≥5）→ 该文件被大量文件紧密依赖（架构核心）
    - 低 coreness（1-2）→ 该文件依赖关系稀少（外围功能）

    O(m) 复杂度，基于 NetworkX 内置 core_number。
    """
    G = nx.Graph()
    for node in nodes:
        for neighbor in graph.get(node, set()):
            if neighbor in nodes and node != neighbor:
                G.add_edge(node, neighbor)
    if G.number_of_edges() == 0:
        return {}
    self_loops = list(nx.selfloop_edges(G))
    if self_loops:
        G.remove_edges_from(self_loops)
    return nx.core_number(G)


# ==================== 社区检测（Leiden 首选 / Louvain 回退）====================

def _detect_communities(graph: Dict[str, Set[str]],
                        nodes: Set[str]) -> List[Set[str]]:
    """社区检测 — Leiden（首选，连通性保证）/ Louvain（回退）"""
    if not nodes:
        return []

    G = nx.Graph()
    node_set = set(nodes)

    for node in nodes:
        if node in graph:
            for neighbor in graph[node]:
                if neighbor in node_set:
                    G.add_edge(node, neighbor)

    if G.number_of_nodes() == 0:
        return []

    sl = list(nx.selfloop_edges(G))
    if sl:
        G.remove_edges_from(sl)
        logger.info(f"[COMMUNITY] Removed {len(sl)} self-loop edge(s)")

    if G.number_of_nodes() > LARGE_GRAPH_NODE_THRESHOLD:
        logger.info(
            f"[COMMUNITY] Large graph ({G.number_of_nodes()} nodes > {LARGE_GRAPH_NODE_THRESHOLD}),"
            f" using Label Propagation for speed"
        )
        try:
            from networkx.algorithms.community import label_propagation_communities
            comms = list(label_propagation_communities(G))
            comm_map: Dict[int, Set[str]] = {
                i: set(c) for i, c in enumerate(comms) if len(c) >= 2
            }
            result = [comm for comm in comm_map.values() if len(comm) >= 2]
            if result:
                return result
        except Exception as e:
            logger.warning(f"[COMMUNITY] Label Propagation failed: {e}, falling back")

    if _LEIDEN_AVAILABLE and G.number_of_edges() > 0:
        try:
            node_list = list(G.nodes())
            node_to_idx = {n: i for i, n in enumerate(node_list)}
            edge_indices = [(node_to_idx[s], node_to_idx[t]) for s, t in G.edges()]
            g_ig = ig.Graph(len(node_list), edge_indices, directed=False)

            part = la.find_partition(g_ig, la.ModularityVertexPartition)

            comm_map: Dict[int, Set[str]] = {}
            for i, cid in enumerate(part.membership):
                comm_map.setdefault(cid, set()).add(node_list[i])

            result = [comm for comm in comm_map.values() if len(comm) >= 2]
            return result if result else [{node} for node in G.nodes()]
        except Exception as e:
            logger.warning(
                f"[COMMUNITY] Leiden failed: {e}, falling back to Louvain"
            )

    partition = community_louvain.best_partition(G)

    comm_map: Dict[int, Set[str]] = {}
    for node, cid in partition.items():
        comm_map.setdefault(cid, set()).add(node)

    result = [comm for comm in comm_map.values() if len(comm) >= 2]
    return result if result else [{node} for node in G.nodes()]


# ==================== 模块度计算 ====================

def _compute_modularity(communities: List[Set[str]],
                        graph: Dict[str, Set[str]],
                        degrees: Dict[str, int],
                        m: float) -> float:
    """
    计算标准模块度 Q

    Q = Σ_c [ l_c / m - (d_c / (2m))² ]

    其中:
    - l_c = 社区 c 内部边数（无向边）
    - d_c = 社区 c 内所有节点的度之和
    - m   = 全图边数
    """
    if m <= 0:
        return 0.0

    Q = 0.0
    for comm in communities:
        comm_nodes = list(comm)
        n = len(comm_nodes)

        # l_c: 内部无向边数
        l_c = 0
        for i in range(n):
            ni = comm_nodes[i]
            neighbors = graph.get(ni, set())
            for j in range(i + 1, n):
                if comm_nodes[j] in neighbors:
                    l_c += 1

        # d_c: 社区节点度和
        d_c = sum(degrees.get(ni, 0) for ni in comm_nodes)

        Q += l_c / m - (d_c / (2 * m)) ** 2

    return Q


# ==================== 保存结果 ====================

def _save_communities(task_id: str, edge_type: str, level: str,
                       parent_comm_id: Optional[str],
                       communities: List[Set[str]],
                       graph: Dict[str, Set[str]],
                       analysis_store,
                       edge_directions: Dict = None,
                       node_lookup: Dict = None,
                       node_coreness: Dict = None) -> Tuple[int, int, int]:
    """
    保存社区到 SQLite（含模块度质量分 + k-core 核心度元数据）

    Returns:
        (saved_count, hub_saved, orphan_saved)
    """
    if not communities:
        return 0, 0, 0

    if edge_directions is None:
        edge_directions = {}
    if node_coreness is None:
        node_coreness = {}

    # 计算全图度和边数用于模块度
    all_nodes = set()
    for comm in communities:
        all_nodes.update(comm)
    degrees = {}
    for node in all_nodes:
        deg = len(graph.get(node, set()))
        degrees[node] = deg
    m = sum(degrees.values()) / 2

    comm_docs = []
    hierarchies = []

    for i, comm_nodes in enumerate(communities):
        if parent_comm_id:
            parent_short = '-'.join(parent_comm_id.split('-')[-2:])
            comm_id = f"comm-{task_id[:8]}-{edge_type[:4].lower()}-{level}-{parent_short}-{i:04d}"
        else:
            comm_id = f"comm-{task_id[:8]}-{edge_type[:4].lower()}-{level}-{i:04d}"

        # 计算社区内的边
        edge_list = []
        node_list = list(comm_nodes)
        for node in comm_nodes:
            for neighbor in graph.get(node, set()):
                if neighbor in comm_nodes and neighbor > node:
                    direction = (
                        edge_directions.get((node, neighbor), '') or
                        edge_directions.get((neighbor, node), '') or
                        'bidirectional'
                    )
                    edge_list.append({
                        "source": node,
                        "target": neighbor,
                        "direction": direction,
                    })

        node_count = len(comm_nodes)
        edge_count = len(edge_list)
        file_count = len(set(comm_nodes)) if comm_nodes else 0

        metadata = {}
        if node_coreness:
            coreness_vals = [node_coreness.get(n, 0) for n in comm_nodes if n in node_coreness]
            if coreness_vals:
                metadata["avgCoreness"] = round(sum(coreness_vals) / len(coreness_vals), 2)
                metadata["maxCoreness"] = max(coreness_vals)
                metadata["coreNodeRatio"] = round(
                    sum(1 for v in coreness_vals if v >= 3) / len(coreness_vals), 3
                )

        comm_docs.append({
            "task_id": task_id,
            "edge_type": edge_type,
            "comm_lv": level,
            "parent_comm_id": parent_comm_id,
            "comm_id": comm_id,
            "node_list": node_list,
            "node_count": node_count,
            "file_count": file_count,
            "edge_list": edge_list,
            "edge_count": edge_count,
            "quality_score": round(_compute_modularity([comm_nodes], graph, degrees, m), 6) if m > 0 else 0.0,
            "description": f"{edge_type} community at {level}, {node_count} nodes, {edge_count} edges",
            "metadata": json.dumps(metadata) if metadata else "{}",
        })

        hierarchies.append({
            "task_id": task_id,
            "edge_type": edge_type,
            "comm_lv": level,
            "comm_id": comm_id,
            "parent_comm_id": parent_comm_id,
            "node_count": node_count,
            "file_count": file_count,
            "edge_count": edge_count,
            "quality_score": round(_compute_modularity([comm_nodes], graph, degrees, m), 6) if m > 0 else 0.0,
        })

    analysis_store.bulk_insert_communities(comm_docs)
    analysis_store.bulk_insert_hierarchy(hierarchies)

    return len(comm_docs), 0, 0


def _save_special_nodes(task_id: str, edge_type: str,
                         hub_nodes: Set[str], orphan_nodes: Set[str],
                         graph: Dict[str, Set[str]],
                         edge_directions: Dict,
                         analysis_store):
    """
    将枢纽节点和孤立节点保存到 graph_doc，comm_lv 分别为 'HUB' 和 'ORPHAN'
    """
    edge_directions = edge_directions or {}
    comm_docs = []
    degrees = {}

    # 保存枢纽节点
    if hub_nodes:
        for node in hub_nodes:
            # 收集该节点的所有边
            edge_list = []
            neighbors = graph.get(node, set())
            for neighbor in neighbors:
                direction = (
                    edge_directions.get((node, neighbor), '') or
                    edge_directions.get((neighbor, node), '') or
                    'bidirectional'
                )
                edge_list.append({
                    "source": node,
                    "target": neighbor,
                    "direction": direction,
                })
            deg = len(neighbors)
            degrees[node] = deg

            comm_id = f"hub-{task_id[:8]}-{edge_type[:4].lower()}-{node.replace(':', '_')[-20:]}"
            comm_docs.append({
                "task_id": task_id,
                "edge_type": edge_type,
                "comm_lv": "HUB",
                "parent_comm_id": None,
                "comm_id": comm_id,
                "node_list": [node],
                "node_count": 1,
                "edge_list": edge_list,
                "edge_count": len(edge_list),
                "quality_score": None,
                "description": f"HUB node: {node} (degree={deg}) — filtered out to avoid over-merging",
            })

    # 保存孤立节点
    if orphan_nodes:
        for node in orphan_nodes:
            neighbors = graph.get(node, set())
            edge_list = []
            for neighbor in neighbors:
                direction = (
                    edge_directions.get((node, neighbor), '') or
                    edge_directions.get((neighbor, node), '') or
                    'bidirectional'
                )
                edge_list.append({
                    "source": node,
                    "target": neighbor,
                    "direction": direction,
                })
            deg = len(neighbors)
            degrees[node] = deg

            comm_id = f"orph-{task_id[:8]}-{edge_type[:4].lower()}-{node.replace(':', '_')[-20:]}"
            comm_docs.append({
                "task_id": task_id,
                "edge_type": edge_type,
                "comm_lv": "ORPHAN",
                "parent_comm_id": None,
                "comm_id": comm_id,
                "node_list": [node],
                "node_count": 1,
                "edge_list": edge_list,
                "edge_count": len(edge_list),
                "quality_score": None,
                "description": f"ORPHAN node: {node} (degree={deg}) — too few connections after hub filtering",
            })

    if comm_docs:
        analysis_store.bulk_insert_communities(comm_docs)
        # 不写入 hierarchy（枢纽/孤立不属于层级结构）
        logger.info(f"[COMMUNITY] 保存特殊节点: {len(hub_nodes)} hubs, {len(orphan_nodes)} orphans")


# ==================== 递归子社区 ====================

def _get_sub_communities(task_id: str, edge_type: str, level: str,
                          graph: Dict[str, Set[str]],
                          min_node_cnt: int,
                          analysis_store) -> Dict[str, Set[str]]:
    """获取需要进一步递归的子社区（排除 HUB/ORPHAN）"""
    communities = analysis_store.get_communities(task_id, edge_type, level)
    result = {}

    for comm in communities:
        # 跳过枢纽和孤立标记
        if comm.get("comm_lv", "") in ("HUB", "ORPHAN"):
            continue
        if comm["node_count"] >= min_node_cnt:
            node_list = comm["node_list"]
            if isinstance(node_list, str):
                node_list = json.loads(node_list)
            result[comm["comm_id"]] = set(node_list)

    return result


# ==================== 社区去重：单子社区合并 ====================

def _deduplicate_single_child_communities(task_id: str, edge_type: str,
                                           analysis_store) -> int:
    """
    父社区只有一个子社区时，对比节点 Jaccard 相似度。
    若相似度 > 90%，判定为冗余，删除子社区。
    从最底层开始向上遍历，避免产生孤儿社区。
    """
    all_comms = analysis_store.get_communities(task_id, edge_type)
    if not all_comms:
        return 0

    comm_map = {}
    for c in all_comms:
        comm_map[c["comm_id"]] = c

    parent_children = defaultdict(list)
    for c in all_comms:
        parent_id = c.get("parent_comm_id")
        lv = c.get("comm_lv", "")
        if parent_id and lv not in ("HUB", "ORPHAN"):
            parent_children[parent_id].append(c)

    candidates = []
    for parent_id, children in parent_children.items():
        if len(children) != 1:
            continue
        parent = comm_map.get(parent_id)
        if not parent or parent.get("comm_lv", "") in ("HUB", "ORPHAN"):
            continue
        candidates.append((parent, children[0]))

    if not candidates:
        return 0

    candidates.sort(key=lambda x: x[1]["comm_lv"], reverse=True)

    to_delete = []
    for parent, child in candidates:
        parent_nodes = parent.get("node_list", [])
        child_nodes = child.get("node_list", [])
        if isinstance(parent_nodes, str):
            parent_nodes = json.loads(parent_nodes)
        if isinstance(child_nodes, str):
            child_nodes = json.loads(child_nodes)

        parent_set = set(parent_nodes)
        child_set = set(child_nodes)

        if not parent_set or not child_set:
            continue

        intersection = parent_set & child_set
        union = parent_set | child_set
        similarity = len(intersection) / len(union)

        logger.info(
            f"[COMMUNITY] 社区去重: parent={parent['comm_id']}({parent['comm_lv']})"
            f" child={child['comm_id']}({child['comm_lv']})"
            f" similarity={similarity:.4f}"
        )

        if similarity > 0.9:
            to_delete.append(child["comm_id"])

    if to_delete:
        analysis_store.delete_communities(task_id, edge_type, to_delete)
        analysis_store.delete_community_llm_results(task_id, edge_type, to_delete)

    return len(to_delete)
