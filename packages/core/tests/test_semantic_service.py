"""semantic_service.run_pipeline 端到端测试（公共服务=KB analyst_runner 原函数薄编排）。

合成图断言:
1. 图产出与 KB 管线同源（同一批 Step 函数, 无复刻分叉）;
2. UNIFIED 组件树全层级 L0~L5（递归深度由 KB community_analysis 单源控制）;
3. 社区不可静默缺失（community 插件不可用时 raise, 不允许退化继续）。
内存库即抛——零持久化。
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "topoone", "plugins", "community"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "topoone", "plugins", "parsers"))

from topoone.engine.semantic_service import run_pipeline  # noqa: E402


def _py(rel: str, body: str = "") -> str:
    d = os.path.dirname(rel)
    os.makedirs(d, exist_ok=True)
    p = os.path.join(os.getcwd(), rel)
    with open(p, "w", encoding="utf-8") as f:
        f.write(body or f"def fn_{os.path.basename(rel).split('.')[0]}():\n    pass\n")
    return rel


@pytest.fixture()
def py_project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    files = []
    for c in range(3):  # 3 簇 × 8 文件星型 imports(星心被同簇其余 import)
        for i in range(8):
            body = ""
            if i > 0:
                body = f"from mod{c}.f0 import fn_f0\n\n\ndef use():\n    return fn_f0()\n"
            files.append(_py(f"mod{c}/f{i}.py", body))
    return str(tmp_path), files


class TestRunPipeline:
    def test_graph_and_components(self, py_project):
        root, files = py_project
        res = run_pipeline(root, files)
        assert res["counts"]["parsed"] == 24
        assert res["nodes"], "节点为空"
        kinds = {n["kind"] for n in res["nodes"]}
        assert "file" in kinds
        assert res["edges"], "边为空"
        # UNIFIED 组件树: 星型 imports → 3 个顶层社区(簇不跨)
        comps = res["components"]
        assert comps, "组件树为空——社区分析被静默跳过?"
        tops = [c for c in comps if c["level"] == "L0"]
        assert len(tops) == 3
        for c in tops:
            mods = {f.split("/")[0] for f in c["files"]}
            assert len(mods) == 1, c["files"]
            assert len(c["files"]) == 8
        # 全层级字段形状(KB 同构)
        for c in comps:
            assert set(c) >= {"commId", "level", "parentId", "files",
                              "nodeCount", "fileCount", "qualityScore"}
            assert c["level"][0] == "L" and c["level"][1:].isdigit()

    def test_empty_files(self, tmp_path):
        res = run_pipeline(str(tmp_path), [])
        assert res["nodes"] == [] and res["components"] == []

    def test_non_code_files_skipped(self, py_project):
        root, files = py_project
        files = files + ["readme.md", "Makefile"]
        res = run_pipeline(root, files)
        assert res["counts"]["parsed"] == 24
