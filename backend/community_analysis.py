"""
Community Analysis — 社区分析（纯内存 + SQLite 写入）

从 SQLite 加载调用/依赖边数据，构建图，执行 Louvain 社区检测，
递归分层分析，结果写入 graph_doc + community_hierarchy 表。
"""
import json
import logging
import uuid
from collections import defaultdict
from typing import Dict, List, Set, Tuple, Optional

logger = logging.getLogger(__name__)


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
        {"community_count": int, "levels": int}
    """
    logger.info(f"[COMMUNITY] analyze_communities 入口: task_id={task_id}, edge_type={edge_type}, min_node_cnt={min_node_cnt}")

    # 1. 从 SQLite 加载边数据
    if edge_type == "INCLUDE":
        edges = analysis_store.get_dep_edges(task_id)
    elif edge_type == "CALL":
        edges = analysis_store.get_call_edges(task_id)
    else:
        logger.warning(f"未知的 edge_type: {edge_type}")
        return {"community_count": 0, "levels": 0}

    logger.info(f"[COMMUNITY] {edge_type}: 加载边数据完成, count={len(edges)}")
    if edges:
        logger.info(f"[COMMUNITY] {edge_type}: 首条边样例 keys={list(edges[0].keys())}")

    if not edges:
        logger.info(f"[COMMUNITY] {edge_type}: 没有边数据，跳过")
        return {"community_count": 0, "levels": 0}

    # 2. 构建图（邻接表）+ 方向映射
    graph, edge_directions = _build_graph(edges, edge_type)
    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    if len(all_nodes) < min_node_cnt:
        logger.info(f"[COMMUNITY] {edge_type}: 节点数 {len(all_nodes)} < {min_node_cnt}，跳过")
        return {"community_count": 0, "levels": 0}

    logger.info(f"[COMMUNITY] {edge_type}: 图包含 {len(all_nodes)} 个节点, {len(edges)} 条边")

    # 3. 执行社区检测
    communities = _detect_communities(graph, all_nodes)

    if not communities:
        return {"community_count": 0, "levels": 0}

    # 4. 保存 L0 层级
    level = "L0"
    parent_comm_id = None
    saved = _save_communities(task_id, edge_type, level, parent_comm_id,
                               communities, graph, analysis_store, edge_directions)

    # 5. 检测是否需要备选方案（CALL 图连通性过高）
    # 条件：CALL 类型 + L0 只有 1 个社区 + 质量分 < 0.01
    use_fallback = False
    if edge_type == "CALL" and len(communities) == 1:
        # 检查质量分
        l0_comms = analysis_store.get_communities(task_id, edge_type, "L0")
        if l0_comms and l0_comms[0].get("quality_score", 1.0) < 0.01:
            use_fallback = True
            logger.info(
                f"[COMMUNITY] CALL: 检测到超级连通分量（1 个社区，质量分={l0_comms[0]['quality_score']:.4f}），"
                f"启用备选方案：过滤同文件内调用"
            )

    if use_fallback:
        # 清除已保存的社区数据
        analysis_store.clear_communities_for_task(task_id, edge_type)
        logger.info(f"[COMMUNITY] CALL: 已清除默认方案的社区数据，重新分析")

        # 重新构建图（过滤同文件内调用）
        graph, edge_directions = _build_graph(edges, edge_type, filter_intra_file=True)
        all_nodes = set(graph.keys())
        for neighbors in graph.values():
            all_nodes.update(neighbors)

        if len(all_nodes) < min_node_cnt:
            logger.info(f"[COMMUNITY] CALL (备选): 节点数 {len(all_nodes)} < {min_node_cnt}，跳过")
            return {"community_count": 0, "levels": 0}

        logger.info(f"[COMMUNITY] CALL (备选): 图包含 {len(all_nodes)} 个节点")

        # 重新执行社区检测
        communities = _detect_communities(graph, all_nodes)
        if not communities:
            return {"community_count": 0, "levels": 0}

        # 重新保存 L0
        saved = _save_communities(task_id, edge_type, level, parent_comm_id,
                                   communities, graph, analysis_store, edge_directions)
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
                new_saved += _save_communities(
                    task_id, edge_type, new_level, parent_id,
                    sub_comms, sub_graph, analysis_store, edge_directions
                )
                total_count += new_saved

        if new_saved == 0:
            break
        level = new_level

    fallback_tag = " (备选)" if use_fallback else ""
    logger.info(f"[COMMUNITY] {edge_type}{fallback_tag}: 共 {total_count} 个社区")

    return {"community_count": total_count, "levels": len(level) - 1}


def _build_graph(edges: List[Dict], edge_type: str, filter_intra_file: bool = False) -> tuple:
    """
    从边数据构建无向图（邻接表）

    Args:
        edges: 边数据列表
        edge_type: "INCLUDE" 或 "CALL"
        filter_intra_file: 是否过滤同文件内调用（仅对 CALL 有效）

    Returns:
        (graph, edge_directions)
        graph: 无向邻接表 {node → set(neighbors)}
        edge_directions: 有向边映射 {(source, target) → direction_label}
            direction_label: "caller→callee" | "INCLUDE"
    """
    graph = defaultdict(set)
    edge_directions = {}  # (source, target) → direction label
    skipped = 0
    intra_skipped = 0  # 同文件内调用被过滤的数量

    for edge in edges:
        if edge_type == "INCLUDE":
            source = str(edge.get("file_id", ""))
            target = edge.get("include_path", "")
            if not source or not target:
                skipped += 1
                continue
        elif edge_type == "CALL":
            caller_file = str(edge.get("caller_file_id", ""))
            callee_file = str(edge.get("callee_file_id", ""))
            caller_func = edge.get("caller_func_name", "")
            callee_name = edge.get("callee_name", "")

            # 过滤 callee_file_id 为 None 的边（外部库调用，无法追踪到具体文件）
            if not callee_file or callee_file == "None":
                skipped += 1
                continue

            source = f"{caller_file}:{caller_func}"
            target = f"{callee_file}:{callee_name}"
            if not source or not target or source == ":None" or target == ":None":
                skipped += 1
                continue

            # 过滤同文件内调用（备选方案）
            if filter_intra_file and caller_file and callee_file and caller_file == callee_file:
                intra_skipped += 1
                continue

            # 保留方向：caller → callee
            edge_directions[(source, target)] = 'caller→callee'
        else:
            continue

        graph[source].add(target)
        graph[target].add(source)  # 无向图

    all_nodes = set(graph.keys())
    for neighbors in graph.values():
        all_nodes.update(neighbors)

    log_msg = f"[COMMUNITY] _build_graph: edge_type={edge_type}, edges_in={len(edges)}, edges_used={len(edges)-skipped-intra_skipped}, skipped={skipped}"
    if filter_intra_file:
        log_msg += f", intra_file_skipped={intra_skipped}"
    log_msg += f", nodes={len(all_nodes)}"
    logger.info(log_msg)

    return dict(graph), edge_directions


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


def _detect_communities(graph: Dict[str, Set[str]],
                        nodes: Set[str]) -> List[Set[str]]:
    """
    社区检测 — 简化版 Louvain 算法

    使用贪心模块化优化，返回社区列表（每个社区是节点集合）
    """
    if not nodes:
        return []

    # 初始化：每个节点一个社区
    communities = {node: {node} for node in nodes}
    node_to_comm = {node: node for node in nodes}

    # 计算度
    degrees = {node: len(neighbors) for node, neighbors in graph.items()}
    m = sum(degrees.values()) / 2  # 边数
    if m == 0:
        return list(communities.values())

    improved = True
    max_iterations = 100
    iteration = 0

    while improved and iteration < max_iterations:
        improved = False
        iteration += 1

        for node in nodes:
            if node not in graph:
                continue

            current_comm = node_to_comm[node]
            current_comm_id = current_comm

            # 计算当前社区的模块度贡献
            current_delta = _delta_q(node, current_comm_id, communities, graph, degrees, m)

            # 检查邻居社区
            neighbor_comms = defaultdict(float)
            for neighbor in graph.get(node, set()):
                comm_id = node_to_comm.get(neighbor)
                if comm_id and comm_id != current_comm_id:
                    neighbor_comms[comm_id] += 1

            best_comm = current_comm_id
            best_delta = current_delta

            for comm_id, ki_ext in neighbor_comms.items():
                delta = _delta_q(node, comm_id, communities, graph, degrees, m)
                if delta > best_delta:
                    best_delta = delta
                    best_comm = comm_id

            if best_comm != current_comm_id:
                # 移除节点
                communities[current_comm_id].discard(node)
                if not communities[current_comm_id]:
                    del communities[current_comm_id]
                # 加入新社区
                if best_comm not in communities:
                    communities[best_comm] = set()
                communities[best_comm].add(node)
                node_to_comm[node] = best_comm
                improved = True

    # 过滤掉太小的社区
    result = [comm for comm in communities.values() if len(comm) >= 2]

    return result if result else [{node} for node in nodes]


def _delta_q(node: str, comm_id, communities: Dict,
             graph: Dict, degrees: Dict, m: float) -> float:
    """计算节点移动到社区的模块度变化"""
    if comm_id not in communities:
        return 0.0

    ki = degrees.get(node, 0)
    sigma_in = 0
    for neighbor in graph.get(node, set()):
        if neighbor in communities.get(comm_id, set()):
            sigma_in += 1

    sigma_tot = sum(degrees.get(n, 0) for n in communities.get(comm_id, set()))

    if m == 0:
        return 0.0

    return sigma_in / m - (ki * sigma_tot) / (2 * m * m)


def _save_communities(task_id: str, edge_type: str, level: str,
                       parent_comm_id: Optional[str],
                       communities: List[Set[str]],
                       graph: Dict[str, Set[str]],
                       analysis_store,
                       edge_directions: Dict = None) -> int:
    """保存社区到 SQLite"""
    if not communities:
        return 0

    if edge_directions is None:
        edge_directions = {}

    comm_docs = []
    hierarchies = []

    for i, comm_nodes in enumerate(communities):
        comm_id = f"comm-{task_id[:8]}-{level}-{i:04d}"

        # 计算社区内的边（保留有向信息）
        edge_list = []
        node_list = list(comm_nodes)
        for node in comm_nodes:
            for neighbor in graph.get(node, set()):
                if neighbor in comm_nodes and neighbor > node:  # 避免重复
                    # 查询方向
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

        # 计算质量评分（简化：密度 = 边数 / (节点数 * (节点数-1) / 2)）
        node_count = len(comm_nodes)
        edge_count = len(edge_list)
        max_edges = node_count * (node_count - 1) / 2 if node_count > 1 else 1
        quality_score = edge_count / max_edges if max_edges > 0 else 0

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
            "quality_score": round(quality_score, 4),
            "description": f"{edge_type} community at {level}, {node_count} nodes, density={quality_score:.2f}",
        })

        hierarchies.append({
            "task_id": task_id,
            "edge_type": edge_type,
            "comm_lv": level,
            "comm_id": comm_id,
            "parent_comm_id": parent_comm_id,
            "node_count": node_count,
            "quality_score": round(quality_score, 4),
        })

    analysis_store.bulk_insert_communities(comm_docs)
    analysis_store.bulk_insert_hierarchy(hierarchies)

    return len(comm_docs)


def _get_sub_communities(task_id: str, edge_type: str, level: str,
                          graph: Dict[str, Set[str]],
                          min_node_cnt: int,
                          analysis_store) -> Dict[str, Set[str]]:
    """获取需要进一步递归的子社区"""
    communities = analysis_store.get_communities(task_id, edge_type, level)
    result = {}

    for comm in communities:
        if comm["node_count"] >= min_node_cnt:
            # 解析 node_list JSON
            node_list = comm["node_list"]
            if isinstance(node_list, str):
                node_list = json.loads(node_list)
            result[comm["comm_id"]] = set(node_list)

    return result
