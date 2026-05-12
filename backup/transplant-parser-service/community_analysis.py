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
    # 1. 从 SQLite 加载边数据
    if edge_type == "INCLUDE":
        edges = analysis_store.get_dep_edges(task_id)
    elif edge_type == "CALL":
        edges = analysis_store.get_call_edges(task_id)
    else:
        logger.warning(f"未知的 edge_type: {edge_type}")
        return {"community_count": 0, "levels": 0}

    if not edges:
        logger.info(f"[COMMUNITY] {edge_type}: 没有边数据，跳过")
        return {"community_count": 0, "levels": 0}

    # 2. 构建图（邻接表）
    graph = _build_graph(edges, edge_type)
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
                               communities, graph, analysis_store)

    # 5. 递归分析子社区
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
                    sub_comms, sub_graph, analysis_store
                )
                total_count += new_saved

        if new_saved == 0:
            break
        level = new_level

    logger.info(f"[COMMUNITY] {edge_type}: 共 {total_count} 个社区")

    return {"community_count": total_count, "levels": len(level) - 1}


def _build_graph(edges: List[Dict], edge_type: str) -> Dict[str, Set[str]]:
    """从边数据构建无向图（邻接表）"""
    graph = defaultdict(set)

    for edge in edges:
        if edge_type == "INCLUDE":
            source = str(edge.get("file_id", ""))
            target = edge.get("include_path", "")
            if not source or not target:
                continue
        elif edge_type == "CALL":
            source = f"{edge.get('caller_file_id', '')}:{edge.get('caller_func_name', '')}"
            target = f"{edge.get('callee_file_id', '')}:{edge.get('callee_name', '')}"
            if not source or not target or source == ":None" or target == ":None":
                continue
        else:
            continue

        graph[source].add(target)
        graph[target].add(source)  # 无向图

    return dict(graph)


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
                       analysis_store) -> int:
    """保存社区到 SQLite"""
    if not communities:
        return 0

    comm_docs = []
    hierarchies = []

    for i, comm_nodes in enumerate(communities):
        comm_id = f"comm-{task_id[:8]}-{level}-{i:04d}"

        # 计算社区内的边
        edge_list = []
        node_list = list(comm_nodes)
        for node in comm_nodes:
            for neighbor in graph.get(node, set()):
                if neighbor in comm_nodes and neighbor > node:  # 避免重复
                    edge_list.append({"source": node, "target": neighbor})

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
