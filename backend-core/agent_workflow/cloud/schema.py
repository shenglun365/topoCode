"""
匿名化数据结构定义。

定义 Topocode-cloud 上传的元数据格式。
不上传任何源代码、文件路径、社区名称。
"""

from dataclasses import dataclass, field


@dataclass
class AnonymizedCommunityStats:
    """单个社区的匿名化统计"""

    level: str                     # "L0" / "L1" / ...
    node_count: int
    file_count: int
    edge_count: int
    quality_score: float
    edge_type: str                 # "INCLUDE" / "CALL"


@dataclass
class AnonymizedProjectStats:
    """项目整体匿名化统计"""

    project_fingerprint: str       # 脱敏标识（SHA256 截断的前 16 字符）
    total_communities: int
    levels: int
    total_nodes: int
    total_files: int
    edge_types: list[str]
    communities: list[AnonymizedCommunityStats] = field(default_factory=list)


@dataclass
class CloudUploadRequest:
    """上传请求体"""

    stats: AnonymizedProjectStats
    api_version: str = "v1"
    client_version: str = ""


@dataclass
class CloudUploadResponse:
    """上传响应体"""

    received: bool
    insights: list[dict] = field(default_factory=list)
    benchmark: dict = field(default_factory=dict)
    patterns: list[dict] = field(default_factory=list)
