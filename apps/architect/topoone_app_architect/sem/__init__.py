"""sem — semantic_assets 内核子包（A1 拆分，纯移动）。

router 实例驻留于此：briefs/impact 等模块的路由随各自逻辑就地注册，
facade(semantic_assets.py) 与 arch_routes/__init__ 经此引用。
"""
from fastapi import APIRouter

router = APIRouter()

# 作业子系统(批1-3/1-4/2-4)：统一调度器注册执行体 + jobs API 路由。
from . import sync_extract as _sync_extract  # noqa: E402,F401  (注册 extract_delta)
from . import unowned as _unowned  # noqa: E402,F401  (注册 extract_unowned)
from . import structural_extract as _structural_extract  # noqa: E402,F401  (注册 extract_impl)
from . import jobs_api as _jobs_api  # noqa: E402,F401  (jobs 列表/取消路由)
