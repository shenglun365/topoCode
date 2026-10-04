"""analysis.buildGraph(API-157)——KB 建图管线无状态 RPC 测试。

验证与 analyst_runner 管线同构: walker 全节点(含 import/file)、contains、
ResolutionEngine 跨文件符号级 calls、文件依赖 imports 边、框架/合成不炸。

Run: cd <repo> && python -m pytest packages/core/tests/test_build_graph.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _repo)
# 与 plugin_manager 运行时一致: topoone/plugins/parsers 挂入 sys.path
_PLUGINS_PARSERS = os.path.abspath(os.path.join(_repo, "topoone", "plugins", "parsers"))
if _PLUGINS_PARSERS not in sys.path:
    sys.path.insert(0, _PLUGINS_PARSERS)

from topoone.engine.task_api.build_graph import build_graph_from_files  # noqa: E402


@pytest.fixture()
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "util.ts").write_text(
        "export function fmt(n: number): string {\n  return `n${n}`\n}\n", encoding="utf-8")
    (root / "src" / "app.ts").write_text(
        "import { fmt } from './util'\n"
        "export function render(): string {\n  return fmt(1)\n}\n", encoding="utf-8")
    return str(root)


def test_build_graph_nodes_and_contains(proj):
    out = build_graph_from_files(proj, ["src/util.ts", "src/app.ts"])
    assert "error" not in out
    kinds = {}
    for n in out["nodes"]:
        kinds[n["kind"]] = kinds.get(n["kind"], 0) + 1
    # walker 全节点: file 虚拟节点 + 函数 + import 节点(KB 管线含 import)
    assert kinds.get("file") == 2
    assert kinds.get("import") >= 1
    assert kinds.get("function") >= 2
    # contains 边存在(walker 生成)
    assert any(e["kind"] == "contains" for e in out["edges"])
    assert out["stats"]["parsed"] == 2


def test_build_graph_cross_file_calls(proj):
    """Step2 ResolutionEngine: app.render → util.fmt 跨文件符号级 calls 边。"""
    out = build_graph_from_files(proj, ["src/util.ts", "src/app.ts"])
    nodes = {n["name"]: n for n in out["nodes"]}
    fa, fb = nodes.get("render"), nodes.get("fmt")
    assert fa and fb
    cross = [e for e in out["edges"]
             if e["kind"] == "calls" and e["source"] == fa["id"] and e["target"] == fb["id"]]
    assert cross, f"缺少跨文件 calls 边: {[(e['source'][-20:], e['target'][-20:]) for e in out['edges'] if e['kind'] == 'calls']}"


def test_build_graph_file_import_edges(proj):
    """Step2.5: import 节点 → 文件依赖边(source file → target file)。"""
    out = build_graph_from_files(proj, ["src/util.ts", "src/app.ts"])
    file_ids = {n["id"] for n in out["nodes"] if n["kind"] == "file"}
    imp = [e for e in out["edges"] if e["kind"] == "imports"
           and e["source"] in file_ids and e["target"] in file_ids]
    assert imp, "缺少文件级 imports 依赖边"
    ends = {(e["source"], e["target"]) for e in imp}
    id_by_file = {n["id"]: n["file_path"] for n in out["nodes"] if n["kind"] == "file"}
    pair = {(id_by_file[s], id_by_file[t]) for s, t in ends}
    assert ("src/app.ts", "src/util.ts") in pair


def test_build_graph_stable_ids_match_graph_node_shape(proj):
    out = build_graph_from_files(proj, ["src/util.ts"])
    for n in out["nodes"]:
        assert set(n) >= {"id", "kind", "name", "qualified_name", "file_path",
                          "language", "start_line", "end_line"}
        assert n["file_path"].startswith("src/")   # 相对路径
    for e in out["edges"]:
        assert set(e) >= {"source", "target", "kind"}


def test_build_graph_bad_root():
    out = build_graph_from_files("/nonexistent-xyz", ["a.ts"])
    assert "error" in out
