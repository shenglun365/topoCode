"""render.* 渲染命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""

from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
def register_render_methods(server: ZMQServer, multi_db: MultiDBManager):
    """注册渲染服务方法"""

    @server.register("render.plantuml")
    def render_plantuml(code: str, format: str = "svg", use_remote: bool = True):
        try:
            from topoone.engine.plantuml_service import render_plantuml as _render
            data = _render(code, format, use_remote)
            import base64
            return {
                "data": base64.b64encode(data).decode("ascii"),
                "format": format,
                "size": len(data),
            }
        except Exception as e:
            msg = str(e)
            if 'PlantUML render failed:' in msg:
                raise  # 保持 _render_remote 的详细错误
            raise RuntimeError(f"PlantUML render failed: {e}")

    @server.register("render.testPlantuml")
    def test_plantuml(use_remote: bool = True):
        try:
            from topoone.engine.plantuml_service import test_plantuml_connection
            return test_plantuml_connection(use_remote)
        except Exception as e:
            return {"status": "error", "error": str(e)}

    return server


# ==================== 辅助函数 ====================
# 注：report.* 保留在核心（report_service.py + task_manager.py subdoc 写方法），
# docs 服务只注册 render.*（见 main.py）。
