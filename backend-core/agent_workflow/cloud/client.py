"""
云端通信客户端 — Phase 2 实现。

预留接口:
  upload_anonymized_stats(project_root, communities) → CloudUploadResponse
  check_cloud_availability() → bool
"""

import logging
from typing import Optional

from .schema import CloudUploadRequest, CloudUploadResponse, AnonymizedProjectStats

logger = logging.getLogger(__name__)

_CLOUD_ENDPOINT = "https://cloud.topocode.ai/api/v1/arch-stats"


async def upload_anonymized_stats(
    stats: AnonymizedProjectStats,
    endpoint: Optional[str] = None,
    timeout: float = 10.0,
) -> CloudUploadResponse:
    """
    上传匿名化统计数据到 Topocode-cloud。

    Phase 2 实现 — 当前为占位。
    """
    logger.info("[cloud] upload skipped (Phase 2 feature)")
    return CloudUploadResponse(received=False)


async def check_cloud_availability(endpoint: Optional[str] = None) -> bool:
    """检测云端服务是否可用。Phase 2 实现。"""
    return False
