"""analysis.buildGraph —— KB 建图管线 RPC(API-157, 数据主权批E)。

把 analyst_runner Step1(AST 全节点+contains)/Step2(ResolutionEngine 跨文件
符号级边)/Step2.5(文件依赖 imports 边)/Step3(框架感知)/Step4(动态合成) 的
**纯构图核心**封装为无状态 RPC：输入 projectRoot+files，输出 KB 同构的
nodes/edges 全集（稳定 id 与 KB graph_node 同源 make_node_id）。

用户裁决: 组件划分严格采用 KB 算法——architect 采集改调本 RPC 拿与 KB
分析管线完全一致的图, 再喂 analysis.communityFromGraph → 划分一致。
零落库（AnalysisStore 以内存 Fake 复用 _extract_import_dependencies）。

Run: cd <repo> && python -m pytest packages/core/tests/test_build_graph.py -q
"""
import logging
import os
from typing import List, Optional

logger = logging.getLogger(__name__)

_MAX_BYTES = 500 * 1024


class _FakeAnalysisStore:
    """_extract_import_dependencies 的内存 analysis_store 替身(只读 import 节点)。"""

    def __init__(self, import_rows: List[dict]):
        self._rows = import_rows

    def get_graph_nodes(self, task_id: str, kind: str = None) -> List[dict]:
        if kind == "import":
            return self._rows
        return [r for r in self._rows if not kind or r.get("kind") == kind]


def _node_to_dict(n, rel) -> dict:
    """walker Node → graph_node 行形状(write_nodes 字段全集, 去 task_id)。"""
    return {
        "id": n.id, "kind": n.kind.value if hasattr(n.kind, "value") else str(n.kind),
        "name": n.name, "qualified_name": n.qualified_name,
        "file_path": rel(n.file_path), "language": n.language,
        "start_line": n.start_line, "end_line": n.end_line,
        "start_col": n.start_col, "end_col": n.end_col,
        "signature": n.signature, "visibility": n.visibility,
        "is_exported": bool(n.is_exported), "is_async": bool(n.is_async),
        "is_static": bool(n.is_static), "docstring": n.docstring,
        "type_parameters": n.type_parameters,
    }


def _edge_to_dict(e) -> dict:
    return {
        "source": e.source, "target": e.target,
        "kind": e.kind.value if hasattr(e.kind, "value") else str(e.kind),
        "line": e.line, "col": e.col, "file_path": e.file_path,
        "provenance": e.provenance.value if hasattr(e.provenance, "value") else str(e.provenance),
        "metadata": e.metadata,
    }


def build_graph_from_files(proj_path: str, files: List[str],
                           max_bytes: int = _MAX_BYTES) -> dict:
    """KB 建图管线纯内存版（与 analyst_runner Step1/2/2.5/3/4 同构）。

    返回 {nodes, edges, stats}；stats 记录 parsed/skipped 与各边计数。"""
    from parsers.core.walker import TreeSitterWalker, _detect_language
    from parsers.core.resolver import ResolutionEngine
    from parsers.languages import EXTRACTORS
    from parsers.language_loader import get_parser
    from parsers.core.symbol_model import Edge
    from parsers.core.node_types import EdgeKind, Provenance

    proj_path = os.path.abspath(proj_path or ".")
    if not os.path.isdir(proj_path):
        return {"error": f"projectRoot not found: {proj_path}",
                "nodes": [], "edges": [], "stats": {}}
    nodes: List[dict] = []
    contains_edges: List[Edge] = []
    tables = []
    stats = {"parsed": 0, "skipped": 0, "failed": 0,
             "contains": 0, "resolved": 0, "imports": 0,
             "framework": 0, "synthetic": 0}

    def _rel(fp: str) -> str:
        try:
            return os.path.relpath(fp, proj_path).replace(os.sep, "/")
        except ValueError:
            return fp.replace(os.sep, "/")

    # ── Step1: AST 解析(全节点, 含 import/file) + contains ──
    for rel in files or []:
        rel = rel.replace(os.sep, "/")
        abs_path = os.path.join(proj_path, rel)
        if not os.path.isfile(abs_path):
            stats["skipped"] += 1
            continue
        lang_key = _detect_language(abs_path)
        if not lang_key:
            stats["skipped"] += 1
            continue
        if lang_key == "c" and abs_path.endswith((".h", ".hh")):
            from parsers.core.config_files import detect_header_language
            lang_key = detect_header_language(abs_path) or lang_key
        extractor = EXTRACTORS.get(lang_key)
        parser = get_parser(lang_key) if lang_key else None
        if extractor is None or parser is None:
            stats["skipped"] += 1
            continue
        try:
            src = open(abs_path, "rb").read()
            if len(src) > max_bytes:
                stats["skipped"] += 1
                continue
            table = TreeSitterWalker(abs_path, src, lang_key, extractor).extract()
            table.file_path = rel
        except Exception as e:  # noqa: BLE001
            logger.warning("[buildGraph] parse %s failed: %s", rel, e)
            stats["failed"] += 1
            continue
        tables.append(table)
        stats["parsed"] += 1
        for n in table.nodes:
            nodes.append(_node_to_dict(n, lambda fp: _rel(fp)))
        contains_edges.extend(table.edges or [])
    stats["contains"] = len(contains_edges)

    # ── Step2: 跨文件引用解析(符号级 calls/imports/extends/implements/type_refs) ──
    # resolve() 为流式设计: 尾部无条件 _flush_edges() 清空返回值——必须传
    # edge_callback 收集(与 analyst_runner 写库同消费模式), 否则恒返回空。
    collected: List[Edge] = []
    resolved: List[Edge] = []
    if tables:
        try:
            resolver = ResolutionEngine()
            resolved = resolver.resolve(tables, edge_callback=collected.extend) or []
            resolved = collected or resolved
        except Exception as e:  # noqa: BLE001
            logger.warning("[buildGraph] reference resolution failed: %s", e)
    stats["resolved"] = len(resolved)

    # ── Step2.5: 文件依赖 imports 边(复用 analyst_runner 实现, 内存 Fake store) ──
    from topoone.engine.analyst_runner import _extract_import_dependencies
    import_rows = [n for n in nodes if n.get("kind") == "import"]
    import_edges: List[Edge] = []
    if import_rows:
        try:
            import_edges = _extract_import_dependencies(
                _FakeAnalysisStore(import_rows), "buildgraph", tables, proj_path) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("[buildGraph] import dependencies failed: %s", e)
    stats["imports"] = len(import_edges)

    # ── Step3: 框架感知 ──
    framework_edges: List[Edge] = []
    if tables:
        try:
            from parsers.frameworks import run_all as run_frameworks
            framework_edges = run_frameworks(tables) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("[buildGraph] framework awareness failed: %s", e)
    stats["framework"] = len(framework_edges)

    # ── Step4: 动态合成(回调注册/事件/匿名类桥接) ──
    synthetic_dicts: List[dict] = []
    if tables:
        try:
            from parsers.core.synthesis import DynamicSynthesizer
            all_nodes = [n for t in tables for n in t.nodes]
            edge_dicts = [_edge_to_dict(e) for e in resolved]
            edge_dicts += [_edge_to_dict(e) for e in framework_edges]
            synthetic_dicts = DynamicSynthesizer().synthesize(
                all_nodes, edge_dicts, tables) or []
        except Exception as e:  # noqa: BLE001
            logger.warning("[buildGraph] dynamic synthesis failed: %s", e)
    stats["synthetic"] = len(synthetic_dicts)

    edges = [_edge_to_dict(e) for e in contains_edges]
    edges += [_edge_to_dict(e) for e in resolved]
    edges += [_edge_to_dict(e) for e in import_edges]
    edges += [_edge_to_dict(e) for e in framework_edges]
    edges += synthetic_dicts
    return {"nodes": nodes, "edges": edges, "stats": stats}


def register(server):
    """注册 analysis.buildGraph（API-157）。"""

    @server.register("analysis.buildGraph")
    def build_graph(projectRoot: str = None, root: str = None,
                    files: Optional[list] = None, maxBytes: int = _MAX_BYTES):
        """KB 建图管线(无状态): 文件集 → 全节点/全边(与 KB 分析管线同构)。

        projectRoot/root: 项目根绝对路径; files: 相对路径列表(缺省跳过)。
        返回 {nodes, edges, stats}——节点 id 与 KB graph_node 同源(make_node_id)。"""
        root_path = projectRoot or root
        if not root_path or not os.path.isdir(root_path):
            return {"error": "projectRoot is required", "nodes": [], "edges": [], "stats": {}}
        try:
            return build_graph_from_files(root_path, files or [],
                                          max_bytes=int(maxBytes or _MAX_BYTES))
        except Exception as e:  # noqa: BLE001
            logger.exception("[buildGraph] failed")
            return {"error": str(e), "nodes": [], "edges": [], "stats": {}}
