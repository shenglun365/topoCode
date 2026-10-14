"""module.* 模块命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""

from topoone.rpc.zmq_server import ZMQServer
def register_module_methods(server: ZMQServer, module_manager=None):
    """注册模块管理方法（registry 查询 / 下载 / 安装 / 卸载 / 更新）"""
    from topoone.engine.module_manager import get_module_manager
    mm = module_manager or get_module_manager()

    @server.register("module.listRegistry")
    def list_module_registry(registry_url: str = None):
        mm.fetch_registry(registry_url)
        return {
            mod_id: {
                "id": mod.id,
                "name": mod.name,
                "version": mod.version,
                "description": mod.description,
                "size_kb": mod.size_kb,
                "platforms": list(mod.platforms) if mod.platforms else [],
                "dependencies": mod.dependencies,
            }
            for mod_id, mod in mm.list_registry().items()
        }

    @server.register("module.getInstalled")
    def get_installed_modules():
        installed = mm.get_installed()
        return {
            mod_id: {
                "id": mod.id,
                "name": mod.name,
                "version": mod.version,
                "description": mod.description,
                "entry": mod.entry,
                "size_kb": mod.size_kb,
                "loaded": mod.loaded,
                "dependencies": mod.dependencies,
            }
            for mod_id, mod in installed.items()
        }

    @server.register("module.install")
    def install_module(name: str, registry_url: str = None):
        success = mm.install(name, registry_url)
        return {"success": success}

    @server.register("module.uninstall")
    def uninstall_module(name: str):
        success = mm.uninstall(name)
        return {"success": success}

    @server.register("module.update")
    def update_module(name: str, registry_url: str = None):
        success = mm.update(name, registry_url)
        return {"success": success}

    @server.register("module.search")
    def search_module(query: str):
        results = {}
        for mod_id, mod in mm.list_registry().items():
            if query.lower() in mod_id.lower() or query.lower() in mod.name.lower():
                results[mod_id] = {
                    "id": mod.id,
                    "name": mod.name,
                    "version": mod.version,
                    "description": mod.description,
                    "size_kb": mod.size_kb,
                    "platforms": list(mod.platforms) if mod.platforms else [],
                }
        return results

    return server


# ==================== 渲染方法 ====================
