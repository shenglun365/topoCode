"""降级项目源码分析能力特征测试(重定位·KB 重规划第一期)。

定位核心能力①「源代码数据资产管理」的正确形态: 直接打开的工作目录(未关联
KB, degraded)也必须能完成 存量代码分析——extract(域内管道) → 本地资产落库 →
地图可查。cv-258 教训: 链路存在但从未被验证/引导, LLM 只能读 package.json 交差。

能力对齐纪律: 只验证既有链路(extract_scope→三级符号源→SemanticAssetsStore→
map_tools), 不新建管道; codegraph 显式关闭(monkeypatch)以覆盖纯降级路径。
"""
from __future__ import annotations

import pytest

from topoone_app_architect import store
from topoone_app_architect.agent.tools.impl.semantic import tool_semantic_extract
from topoone_app_architect.agent.tools.impl.map import tool_map_overview

FIXTURE_TS = """// 叙事引擎场景编译器(fixture)
export class SceneCompiler {
  constructor(private cache: Map<string, unknown>) {}

  compile(raw: unknown): unknown {
    return raw
  }
}

export function buildTimeline(scenes: string[]): string[] {
  return scenes.map((s) => s.trim())
}
"""

FIXTURE_TS2 = """// SVG 渲染器(fixture)
export class SvgRenderer {
  render(node: unknown): string {
    return "<svg/>"
  }
}

export function measureText(text: string): number {
  return text.length
}
"""


@pytest.fixture()
def degraded_project(arch_env, tmp_path, monkeypatch):
    """未关联 KB 的直接打开目录: 无 codegraph(显式关) + 无基线 + 本地 .ts 代码。"""
    root = tmp_path / "proj"
    (root / "packages" / "engine" / "src").mkdir(parents=True)
    (root / "packages" / "engine" / "src" / "scene.ts").write_text(FIXTURE_TS)
    (root / "packages" / "engine" / "src" / "svg.ts").write_text(FIXTURE_TS2)
    # codegraph 强制走降级(实时扫描路径)——主源路径由生产 ensure_synced 负责
    import topoone_app_architect.sem.codegraph as cg
    monkeypatch.setattr(cg, "ensure_synced", lambda root, timeout=90: False)
    # LLM stub(即时失败→符号名启发式, 免真实端点连接重试拖慢测试)
    import topoone_app_architect.arch_routes.tagent_se as _tse

    class _NoLLM:
        def __init__(self, *a, **k):
            pass

        def chat(self, *a, **k):
            raise RuntimeError("test: llm off")

    monkeypatch.setattr(_tse, "KbGatewayLLMClient", _NoLLM)
    pid = "proj-degraded1"
    store.ProjectsStore.create({
        "id": pid, "name": "degraded-fixture",
        "root_path": str(root), "active": 1, "mode": "existing",
    })
    return {"root": str(root), "pid": pid}


def test_degraded_project_extract_produces_local_assets(degraded_project):
    """cv-258 重放判据: 无 KB 项目 extract → 本地资产落库 > 0。"""
    res = tool_semantic_extract(
        degraded_project["root"], degraded_project["pid"],
        scope={"type": "project"})
    assert not res.get("error"), f"提取报错: {res}"
    assert res.get("count", 0) > 0, f"降级项目应能提取出资产: {res}"
    assets = store.SemanticAssetsStore.all(degraded_project["pid"], limit=100) or []
    assert len(assets) == res["count"]


def test_degraded_project_map_overview_shows_assets(degraded_project):
    """落库后资产地图立即可见(map_tools 读本地 SemanticAssetsStore)。"""
    tool_semantic_extract(degraded_project["root"], degraded_project["pid"],
                          scope={"type": "project"})
    md = tool_map_overview(degraded_project["root"],
                           degraded_project["pid"])["markdown"]
    assert "语义资产" in md
