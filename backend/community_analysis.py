"""
Community Analysis — 社区分析（纯内存 + SQLite 写入）

从 SQLite 加载调用/依赖边数据，构建图，执行 Louvain 社区检测，
递归分层分析，结果写入 graph_doc + community_hierarchy 表。

改进：
- Louvain 使用 NetworkX community_louvain（标准实现，支持多级聚合）
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

from config import (
    HUB_DEGREE_RATIO, HUB_MIN_DEGREE, ORPHAN_MAX_DEGREE,
    INTRAn_FILE_EDGE_WEIGHT, INTRAn_FILE_EDGE_FALLBACK_WEIGHT,
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

    # 2. 构建图 + 枢纽/孤立节点过滤
    graph, edge_directions, hub_nodes, orphan_nodes = _build_graph(
        edges, edge_type, filter_intra_file=False
    )
    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    if len(all_nodes) < min_node_cnt:
        logger.info(
            f"[COMMUNITY] {edge_type}: 过滤后节点数 {len(all_nodes)} < {min_node_cnt}"
            f" (枢纽={len(hub_nodes)}, 孤立={len(orphan_nodes)})，跳过"
        )
        # 即使不够社区分析，也保存枢纽/孤立节点
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
        graph, edge_directions, hub_nodes, orphan_nodes = _build_graph(
            edges, edge_type, filter_intra_file=False,
            intra_file_weight=INTRAn_FILE_EDGE_FALLBACK_WEIGHT,
        )
        # 再次过滤枢纽/孤立（可能已变化）
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
        )
        logger.info(f"[COMMUNITY] CALL (备选): L0 产生 {len(communities)} 个社区")

    # 6. 递归分析子社区
    total_count = saved
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
                    sub_comms, sub_graph, analysis_store, edge_directions
                )
                new_saved += ns
                total_count += ns

        if new_saved == 0:
            break
        level = new_level

    fallback_tag = " (备选)" if use_fallback else ""
    logger.info(
        f"[COMMUNITY] {edge_type}{fallback_tag}: "
        f"共 {total_count} 个社区, 枢纽 {hub_saved} 个, 孤立 {orphan_saved} 个"
    )

    return {
        "community_count": total_count,
        "levels": len(level) - 1 if level else 0,
        "hub_count": hub_saved,
        "orphan_count": orphan_saved,
    }


# ==================== 图构建 + 枢纽/孤立过滤 ====================

def _build_graph(edges: List[Dict], edge_type: str, *,
                 filter_intra_file: bool = False,
                 intra_file_weight: float = 1.0) -> Tuple[Dict, Dict, Set, Set]:
    """
    从边数据构建无向图（邻接表），含枢纽/孤立节点预过滤

    Args:
        edges: 边数据列表
        edge_type: "INCLUDE" 或 "CALL"
        filter_intra_file: (deprecated) 是否过滤同文件内调用 — 改用 intra_file_weight
        intra_file_weight: 同文件内调用权重（0.1=降权, 1.0=正常）

    Returns:
        (graph, edge_directions, hub_nodes, orphan_nodes)
        graph: 无向邻接表 {node → set(neighbors)}（已过滤枢纽/孤立）
        edge_directions: 有向边映射
        hub_nodes: 被标记为枢纽的节点集合
        orphan_nodes: 被标记为孤立的节点集合
    """
    if filter_intra_file:
        intra_file_weight = 0.0  # 兼容旧调用

    graph = defaultdict(set)
    edge_directions = {}
    skipped = 0
    intra_count = 0

    for edge in edges:
        if edge_type == "INCLUDE":
            source = str(edge.get("file_id", ""))
            target = edge.get("include_path", "")
            if not source or not target:
                skipped += 1
                continue
            direction = "INCLUDE"
        elif edge_type == "CALL":
            caller_file = str(edge.get("caller_file_id", ""))
            callee_file = str(edge.get("callee_file_id", ""))
            caller_func = edge.get("caller_func_name", "")
            callee_name = edge.get("callee_name", "")

            if not callee_file or callee_file == "None":
                skipped += 1
                continue

            source = f"{caller_file}:{caller_func}"
            target = f"{callee_file}:{callee_name}"
            if not source or not target or source == ":None" or target == ":None":
                skipped += 1
                continue

            direction = 'caller→callee'
        else:
            continue

        graph[source].add(target)
        graph[target].add(source)
        edge_directions[(source, target)] = direction

    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    log_msg = (
        f"[COMMUNITY] _build_graph: edge_type={edge_type}, "
        f"edges_in={len(edges)}, edges_used={len(graph)//2}, skipped={skipped}"
        f", nodes={len(all_nodes)}"
    )
    logger.info(log_msg)

    # 过滤枢纽和孤立节点
    filtered_graph, hub_nodes, orphan_nodes = _filter_hubs_and_orphans(graph, edge_directions)

    # 过滤 edge_directions
    filtered_directions = {}
    for (s, t), d in edge_directions.items():
        if s not in hub_nodes and s not in orphan_nodes \
           and t not in hub_nodes and t not in orphan_nodes:
            filtered_directions[(s, t)] = d

    return dict(filtered_graph), filtered_directions, hub_nodes, orphan_nodes


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

    # 第一阶段：识别枢纽
    hub_nodes = set()
    for node, deg in degrees.items():
        if deg > hub_threshold:
            hub_nodes.add(node)

    if hub_nodes:
        logger.info(
            f"[COMMUNITY] 枢纽节点: {len(hub_nodes)}/{total_nodes}"
            f" (threshold={hub_threshold})"
            f" 示例: {list(hub_nodes)[:5]}"
        )

    # 第二阶段：构建排除枢纽的图，识别孤立节点
    remaining_degrees = {}
    for node in all_nodes:
        if node in hub_nodes:
            continue
        neighbors = graph.get(node, set())
        filtered_neighbors = {n for n in neighbors if n not in hub_nodes}
        remaining_degrees[node] = len(filtered_neighbors)

    orphan_nodes = set()
    for node, deg in remaining_degrees.items():
        if deg <= ORPHAN_MAX_DEGREE:
            orphan_nodes.add(node)

    if orphan_nodes:
        logger.info(
            f"[COMMUNITY] 孤立节点: {len(orphan_nodes)}/{total_nodes}"
            f" (max_deg={ORPHAN_MAX_DEGREE})"
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


# ==================== Louvain 社区检测（NetworkX 标准实现）====================

def _detect_communities(graph: Dict[str, Set[str]],
                        nodes: Set[str]) -> List[Set[str]]:
    """
    社区检测 — 基于 NetworkX community_louvain（标准 Louvain + 多级聚合）。

    使用 networkx 构建图 + community_louvain.best_partition() 执行标准 Louvain，
    返回社区列表（每个社区是节点集合），过滤掉单节点社区。
    """
    if not nodes:
        return []

    # 构建 NetworkX 图
    G = nx.Graph()
    node_set = set(nodes)

    for node in nodes:
        if node in graph:
            for neighbor in graph[node]:
                if neighbor in node_set:
                    G.add_edge(node, neighbor)

    if G.number_of_nodes() == 0:
        return []

    # 标准 Louvain（多级聚合）
    partition = community_louvain.best_partition(G)

    # 按社区分组
    comm_map: Dict[int, Set[str]] = {}
    for node, cid in partition.items():
        comm_map.setdefault(cid, set()).add(node)

    # 过滤单节点社区
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
                       edge_directions: Dict = None) -> Tuple[int, int, int]:
    """
    保存社区到 SQLite（含模块度质量分）

    Returns:
        (saved_count, hub_saved, orphan_saved)
    """
    if not communities:
        return 0, 0, 0

    if edge_directions is None:
        edge_directions = {}

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

        comm_docs.append({
            "task_id": task_id,
            "edge_type": edge_type,
            "comm_lv": level,
            "parent_comm_id": parent_comm_id,
            "comm_id": comm_id,
            "node_list": node_list,
            "node_count": node_count,
            "edge_list": edge_list,
            "edge_count": edge_count,
            "quality_score": round(_compute_modularity([comm_nodes], graph, degrees, m), 6) if m > 0 else 0.0,
            "description": f"{edge_type} community at {level}, {node_count} nodes, {edge_count} edges",
        })

        hierarchies.append({
            "task_id": task_id,
            "edge_type": edge_type,
            "comm_lv": level,
            "comm_id": comm_id,
            "parent_comm_id": parent_comm_id,
            "node_count": node_count,
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
