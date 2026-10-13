"""map_tools MCP 工具面回归(2610 A)。

cv-11 实证两处服务端 bug(异常被 run_tool 包装成 markdown, 执行器只能绕路):
- map.overview 无 project 提示路径调 ProjectsStore.list()(不存在, 应为 .all)
- tool_graph component 分支漏 import build_component_catalog → NameError
"""
from __future__ import annotations

from topoone_app_architect.sem.map_tools import run_tool


def test_overview_no_project_lists_without_error(arch_env):
    """无参 overview(多项目歧义) → 提示传 project + 清单, 不再 AttributeError。"""
    from topoone_app_architect import store
    store.ProjectsStore.create({"id": "proj-a", "name": "演示项目",
                                "rootPath": "/tmp/proj-a", "active": 0})
    store.ProjectsStore.create({"id": "proj-b", "name": "次项目",
                                "rootPath": "/tmp/proj-b", "active": 0})
    r = run_tool("map.overview", {})
    assert "无法唯一定位项目" in r
    assert "proj-a" in r and "proj-b" in r, "项目清单应可见(.all 回归)"
    assert "工具执行失败" not in r and "has no attribute" not in r


def test_graph_component_renders_without_nameerror(arch_env):
    """graph component → 出 mermaid 图, 不再 NameError(漏 import 回归)。"""
    from topoone_app_architect import store
    store.ProjectsStore.create({"id": "proj-a", "name": "演示项目",
                                "rootPath": "/tmp/proj-a", "active": 0})
    r = run_tool("map.graph", {"kind": "component", "project": "proj-a"})
    assert "mermaid" in r
    assert "生成失败" not in r and "not defined" not in r
