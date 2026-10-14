"""version.* 版本同步命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""

from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
def register_version_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册 KB 版本基线 + 增量更新 + 更新请求方法。

    对外契约（architect 经 data_api /zmq/{method} 代理调用）：
      version.list / version.get / version.preview / version.sync /
      version.diff / version.materialize /
      knowledge.pullRequest / knowledge.pendingUpdates /
      knowledge.updateConfirm / knowledge.updateCancel
    """
    import topoone.engine.version_sync_service as vss

    @server.register("version.list")
    def version_list(project_id: str = None, projectId: str = None):
        return vss.list_versions(multi_db, project_id or projectId)

    @server.register("version.get")
    def version_get(project_id: str = None, version_id: str = None,
                    projectId: str = None, versionId: str = None):
        return vss.get_version(multi_db, project_id or projectId, version_id or versionId)

    @server.register("version.preview")
    def version_preview(project_id: str = None, branch: str = "", head: str = "",
                        projectId: str = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: version.preview 退役(architect 自管基线)"}

    @server.register("version.sync")
    def version_sync(project_id: str = None, branch: str = "", head: str = "",
                     label: str = "", stages: dict = None, force: bool = False,
                     request_id: str = None, task_id: str = None,
                     projectId: str = None, requestId: str = None,
                     taskId: str = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: version.sync 退役(architect 自管基线)"}

    @server.register("version.diff")
    def version_diff(project_id: str = None, from_id: str = None, to_id: str = None,
                     projectId: str = None, fromId: str = None, toId: str = None):
        return vss.diff_versions(multi_db, project_id or projectId,
                                 from_id or fromId, to_id or toId)

    @server.register("version.materialize")
    def version_materialize(project_id: str = None, version_id: str = None,
                            projectId: str = None, versionId: str = None):
        return vss.materialize(multi_db, project_id or projectId, version_id or versionId)

    @server.register("version.cleanup")
    def version_cleanup(project_id: str = None, keep_versions: int = 0,
                        projectId: str = None, keepVersions: int = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: version.cleanup 退役(architect 自管基线)"}

    @server.register("knowledge.pullRequest")
    def knowledge_pull_request(project_id: str = None, repo_url: str = "",
                               local_repo_path: str = "", branch: str = "",
                               head: str = "", note: str = "",
                               projectId: str = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: knowledge.pullRequest 退役(architect 自管基线)"}

    @server.register("knowledge.pendingUpdates")
    def knowledge_pending_updates(project_id: str = None, projectId: str = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: knowledge.pendingUpdates 退役(architect 自管基线)"}

    @server.register("knowledge.updateConfirm")
    def knowledge_update_confirm(request_id: str = None, method: str = "pull",
                                 requestId: str = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: knowledge.updateConfirm 退役(architect 自管基线)"}

    @server.register("knowledge.updateCancel")
    def knowledge_update_cancel(request_id: str = None, requestId: str = None):
        # KB 去基线化(2026-10 裁决): 版本同步/预览/清理编排退役——architect 自管基线。
        # 保留注册空壳(旧调用方得明确错误而非 404), 表壳冻结一版周期后清。
        return {"retired": True, "success": False,
                "error": "KB 已去基线化: knowledge.updateCancel 退役(architect 自管基线)"}

    @server.register("architecture.model")
    def architecture_model(project_id: str = None, task_id: str = "",
                           level: str = "L1", edge_type: str = "INCLUDE",
                           projectId: str = None, taskId: str = None):
        """(KB-REQ-17) 项目真实架构模型：由分析图社区/节点/边/版本差异构建。

        architect 前端的组件索引、代码映射、依赖关系均来自此处，取代静态演示模型。
        """
        from topoone.engine.architecture_model_service import build_architecture_model
        pid = project_id or projectId
        tid = task_id or taskId
        return build_architecture_model(multi_db, pid, task_id=tid,
                                        level=level, edge_type=edge_type)

    @server.register("architecture.catalog")
    def architecture_catalog(project_id: str = None, task_id: str = "",
                             projectId: str = None, taskId: str = None):
        """(KB-REQ-17) 组件目录：合并 依赖分析(INCLUDE)/调用分析(CALL) 与 L0/L1
        层社区，附带父组件 / 文件数 / 类型元数据，供组件选择器筛选。"""
        from topoone.engine.architecture_model_service import build_component_catalog
        pid = project_id or projectId
        tid = task_id or taskId
        return build_component_catalog(multi_db, pid, task_id=tid)

    return server


# ==================== 代码分析方法 ====================

# analysis.* 方法已迁移到 task_manager.py
from topoone.engine.task_manager import register_analysis_methods


# ==================== 知识库方法 ====================
