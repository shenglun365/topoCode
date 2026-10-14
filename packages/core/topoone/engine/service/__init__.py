"""engine.service — kb RPC 方法注册（按命名空间解构，原 core_service.py）。

M10: knowledge.* 已切出为 workbench 子项目（topoone_app_workbench，kind=core），
改由核心进程 register_all 末尾的 manifest 加载注册（见 topoone.engine.app）。
M11: render.* 已切出为 docs 子项目（topoone_app_docs，kind=service，:3481），由 docs 服务进程注册。
report.* 保留在核心：report_service.py（13 只读方法）+ task_manager.py（5 个 subdoc 写方法），
gateway 按命名空间路由无法拆分 report.*，且 subdoc 写方法需主库写权限（docs 只读），故整体留核心。
"""
from topoone.engine.service.project import register_project_methods
from topoone.engine.service.dir import register_dir_methods
from topoone.engine.service.version import register_version_methods
from topoone.engine.service.settings import register_settings_methods
from topoone.engine.service.backend import register_backend_methods
from topoone.engine.service.module import register_module_methods
from topoone.engine.service.baseline_readiness import register_baseline_readiness_methods
from topoone.engine.report_service import register_report_methods

def register_all_engine_methods(server, multi_db, module_manager=None, plugin_manager=None):
    """注册全部引擎命名空间方法（core 引擎命名空间；knowledge 见 manifest，render 见 docs 服务）。"""
    register_project_methods(server, multi_db)
    register_dir_methods(server, multi_db)
    register_version_methods(server, multi_db)
    register_settings_methods(server, multi_db)
    register_backend_methods(server, multi_db, plugin_manager)
    register_module_methods(server, module_manager)
    register_baseline_readiness_methods(server, multi_db)
    register_report_methods(server, multi_db)
    return server
