"""
元数据脱敏 — 从项目分析结果提取匿名化统计。

原则:
  - 不上传源代码
  - 不上传文件路径
  - 不上传社区名称
  - 仅提取可聚合的统计数字
"""

import hashlib
import logging
from typing import Optional

from .schema import AnonymizedProjectStats, AnonymizedCommunityStats

logger = logging.getLogger(__name__)


def anonymize_project(project_root: str, communities: list[dict]) -> AnonymizedProjectStats:
    """
    从社区数据中提取匿名化统计。

    Args:
        project_root: 项目根目录（用于生成脱敏指纹）
        communities: 社区列表，每个 dict 含:
            - level, node_count, file_count, edge_count, quality_score, edge_type

    Returns:
        AnonymizedProjectStats
    """
    fingerprint = hashlib.sha256(project_root.encode()).hexdigest()[:16]

    comm_stats = []
    for c in communities:
        comm_stats.append(AnonymizedCommunityStats(
            level=str(c.get("level", "L0")),
            node_count=int(c.get("node_count", 0)),
            file_count=int(c.get("file_count", 0)),
            edge_count=int(c.get("edge_count", 0)),
            quality_score=float(c.get("quality_score", 0)),
            edge_type=str(c.get("edge_type", "INCLUDE")),
        ))

    edge_types = list(set(c.edge_type for c in comm_stats))
    total_nodes = sum(c.node_count for c in comm_stats)
    total_files = sum(c.file_count for c in comm_stats)
    levels = len(set(c.level for c in comm_stats))

    return AnonymizedProjectStats(
        project_fingerprint=fingerprint,
        total_communities=len(comm_stats),
        levels=levels,
        total_nodes=total_nodes,
        total_files=total_files,
        edge_types=edge_types,
        communities=comm_stats,
    )


def anonymize_community(community: dict) -> AnonymizedCommunityStats:
    """单个社区脱敏"""
    return AnonymizedCommunityStats(
        level=str(community.get("level", "L0")),
        node_count=int(community.get("node_count", 0)),
        file_count=int(community.get("file_count", 0)),
        edge_count=int(community.get("edge_count", 0)),
        quality_score=float(community.get("quality_score", 0)),
        edge_type=str(community.get("edge_type", "INCLUDE")),
    )
