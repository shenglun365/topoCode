"""viewer 子包共享态（MS5-V2）。"""
import logging
import logging.handlers
import os

import topoone.engine.community_data as cd  # noqa: F401  （community 域经此处取用保持单源）

logger = logging.getLogger(__name__)

def _et_unified(et: str) -> str:
    """旧双线(INCLUDE/CALL)已并入 UNIFIED：URL 传入旧值一律按 UNIFIED 读取（EXTERNAL_* 外部线保留）。"""
    return "UNIFIED" if (et or "").upper() in ("INCLUDE", "CALL") else et

# M11：viewer/web-root SPA 产物在 apps/docs/dist（vite outDir；与 gateway /docs 资产挂载同源）
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dist")
