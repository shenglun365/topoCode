"""pytest 全局夹具：测试数据目录隔离。

必须在任何 topoone_app_architect 模块导入前设置 ARCH_DATA_DIR——
否则 store 会写进开发库 ~/.topocode（曾把测试会话/需求泄漏进会话中心）。
"""
import os

import pytest
import tempfile

if not os.environ.get("ARCH_DATA_DIR"):
    os.environ["ARCH_DATA_DIR"] = tempfile.mkdtemp(prefix="topo-arch-test-")


@pytest.fixture(autouse=True)
def _isolate_arch_ctx():
    """每测试清 architect 请求上下文(contextvar 泄漏隔离: 前序测试的
    conv/req/project 残留会串库串需求)。"""
    from topoone_app_architect.arch_routes import ctx
    tk = (ctx.set_conv(""), ctx.set_req(""), ctx.set_project(""))
    yield
    ctx.reset_conv(tk[0]); ctx.reset_req(tk[1]); ctx.reset_project(tk[2])
