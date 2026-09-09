"""pytest 全局夹具：测试数据目录隔离。

必须在任何 topoone_app_architect 模块导入前设置 ARCH_DATA_DIR——
否则 store 会写进开发库 ~/.topocode（曾把测试会话/需求泄漏进会话中心）。
"""
import os
import tempfile

if not os.environ.get("ARCH_DATA_DIR"):
    os.environ["ARCH_DATA_DIR"] = tempfile.mkdtemp(prefix="topo-arch-test-")
