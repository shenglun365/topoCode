"""Task Manager — analysis.* RPC 门面（MS5-V1 拆分后稳定进口）。

实现主体在 engine/task_api/（六域 + common + 锁序聚合）。本门面保三个稳定进口：
① register_analysis_methods —— engine/app.py、service/version.py 注册入口
② _compute_file_ranks 等模块级工具 —— agent 侧 3 处惰性引用 + test_tagent_host 字符串打桩
③ git/positions 八函数 —— service/project.py `_tm_*` 别名消费
"""
from topoone.engine.task_api import register_analysis_methods
# 工具函数经 __getattr__ 惰性委托 task_api.common（保持测试打桩接缝穿透）
from topoone.engine.task_api.git_info import (  # noqa: F401
    detect_git_info, save_git_info, get_git_info, check_import_status,
)
from topoone.engine.task_api.positions import (  # noqa: F401
    save_positions, load_positions, list_position_keys, clear_positions,
)


def __getattr__(name):
    """惰性委托（PEP 562）：_compute_file_ranks 等工具的实现真身在 task_api.common，
    属性访问时转发——测试 monkeypatch common 侧即可穿透本门面。"""
    if name in ("_FIELD_MAP", "_resolve_node_list_items", "_compute_file_ranks",
                "_count_batched_source_files", "_reset_tasks_to_pending", "_with_fixed_report_types"):
        from topoone.engine.task_api import common
        return getattr(common, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
