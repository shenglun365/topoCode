
"""公共测试夹具(规范化环节六) — 环境隔离/客户端/WS 助手单源。

旧形态: 每个测试文件手写 _setup/_env/_client(同一套 env 重置五连,
四处漂移——有的 reset_req 有的没有) + WS 收发助手两份签名不同。
新规范: 环境隔离用 isolate_arch()/arch_env 夹具; WS 助手从
tests.ws_helpers 导入; 新测试禁止再手写 env 重置序列。
"""
from __future__ import annotations

import pytest

import topoone_app_architect.ctx as C


def isolate_arch(tmp_path, monkeypatch) -> str:
    """architect 环境隔离: 独立数据目录 + 单例/上下文全重置。返回 data 路径。"""
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    return data


@pytest.fixture()
def arch_env(tmp_path, monkeypatch) -> str:
    """环境隔离夹具(等价 isolate_arch)。"""
    return isolate_arch(tmp_path, monkeypatch)


@pytest.fixture()
def client(arch_env):
    """裸 TestClient(LLM 未 stub——需要 stub 的测试自建, 如 test_direct_commands)。"""
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    return TestClient(build_app(data_dir=arch_env))


# ── 数据主权批E: 测试默认禁用 KB buildGraph 主路径(真调 KB 全量解析
# 40s+/次 → 全量超时)——默认强制降级逐文件路径; 主路径行为由
# test_build_graph 冒烟(KB 侧)与显式 mock 用例覆盖。 ──
import pytest as _pytest


@_pytest.fixture(autouse=True)
def _no_buildgraph(monkeypatch):
    import topoone_app_architect.kb_gateway as _kg
    monkeypatch.setattr(_kg, "call_kb",
                        lambda *a, **k: (_ for _ in ()).throw(Exception("kb disabled in tests")))
