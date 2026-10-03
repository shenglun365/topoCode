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
from . import logic_extract as _logic_extract  # noqa: E402,F401  (注册 extract_logic)
from . import component_view as _component_view  # noqa: E402,F401  (注册 gen_component_view)
from . import scope_extract as _scope_extract  # noqa: E402,F401  (注册 extract_scope)
from . import jobs_api as _jobs_api  # noqa: E402,F401  (jobs 列表/取消路由)
from . import llm_jobs as _llm_jobs  # noqa: E402,F401  (轻解析作业注册 B3)
from . import graph_collect as _graph_collect  # noqa: E402,F401  (数据主权批A: 注册 collect_graph)
from . import component_group as _component_group  # noqa: E402,F401  (数据主权批B: 注册 community_group)
from . import component_naming as _component_naming  # noqa: E402,F401  (数据主权批C: 注册 component_name)
from . import baseline_refresh as _baseline_refresh  # noqa: E402,F401  (数据主权批E: 注册 baseline_refresh 编排)
_llm_jobs.register_all()
