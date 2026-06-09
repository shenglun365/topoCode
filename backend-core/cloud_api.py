"""Cloud API Protocol — 云端通信接口定义和数据类型。

本模块仅定义接口，云端服务待详细设计后再实现。
本地通过 cloud_api_config 表存储连接配置。
"""

from dataclasses import dataclass, field
from typing import Optional
from enum import Enum


class CloudServiceStatus(Enum):
    DISABLED = "disabled"
    CONFIGURED = "configured"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass
class CloudConfig:
    """云端连接配置。存储于 cloud_api_config 表。"""
    api_key: str = ""
    endpoint: str = "https://cloud.topocode.dev"
    enabled: bool = False
    privacy_upload_metrics: bool = False
    privacy_upload_patterns: bool = False
    privacy_allow_benchmark_contrib: bool = False


# ═══════════════════════════════════════════
# 云端 MCP Tools 接口定义（预留）
# ═══════════════════════════════════════════

@dataclass
class CloudSearchRequest:
    """topocode_cloud_search 请求"""
    language: str
    framework: Optional[str] = None
    community_count_range: Optional[str] = None  # "5-15"


@dataclass
class CloudSearchResult:
    """topocode_cloud_search 响应"""
    projects: list[dict] = field(default_factory=list)
    total: int = 0


@dataclass
class CloudBenchmarkRequest:
    """topocode_cloud_benchmark 请求"""
    project_id: str
    metrics: dict = field(default_factory=dict)
    compare_against: Optional[str] = None


@dataclass
class CloudBenchmarkResult:
    """topocode_cloud_benchmark 响应"""
    project_id: str = ""
    comparisons: list[dict] = field(default_factory=list)
    summary: str = ""


@dataclass
class CloudPatternMatchRequest:
    """topocode_cloud_pattern_match 请求"""
    project_id: str
    community_metrics: dict = field(default_factory=dict)


@dataclass
class CloudPatternMatchResult:
    """topocode_cloud_pattern_match 响应"""
    patterns: list[dict] = field(default_factory=list)
    best_match: Optional[dict] = None


@dataclass
class CloudEvolutionRefRequest:
    """topocode_cloud_evolution_ref 请求"""
    change_description: str
    language: Optional[str] = None


@dataclass
class CloudEvolutionRefResult:
    """topocode_cloud_evolution_ref 响应"""
    references: list[dict] = field(default_factory=list)
    summary: str = ""


# ═══════════════════════════════════════════
# 云端 API 客户端接口（预留）
# ═══════════════════════════════════════════

class CloudAPIClient:
    """云端 API 客户端基类。当前为占位实现，待详细设计。"""

    def __init__(self, config: CloudConfig):
        self._config = config

    @property
    def status(self) -> CloudServiceStatus:
        if not self._config.enabled:
            return CloudServiceStatus.DISABLED
        if not self._config.api_key:
            return CloudServiceStatus.CONFIGURED
        return CloudServiceStatus.CONFIGURED  # 暂未连接

    async def search(self, req: CloudSearchRequest) -> CloudSearchResult:
        raise NotImplementedError("Cloud API not yet implemented")

    async def benchmark(self, req: CloudBenchmarkRequest) -> CloudBenchmarkResult:
        raise NotImplementedError("Cloud API not yet implemented")

    async def pattern_match(self, req: CloudPatternMatchRequest) -> CloudPatternMatchResult:
        raise NotImplementedError("Cloud API not yet implemented")

    async def evolution_ref(self, req: CloudEvolutionRefRequest) -> CloudEvolutionRefResult:
        raise NotImplementedError("Cloud API not yet implemented")
