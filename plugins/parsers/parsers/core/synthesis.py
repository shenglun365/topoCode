"""DynamicSynthesizer — 补充静态分析无法捕获的动态边

处理:
  1. 回调注册: on("event", handler) → calls 边
  2. EventEmitter: emit ↔ on 连接
  3. 匿名类→接口桥接
"""

from __future__ import annotations

from ..core.symbol_model import Node, Edge, EdgeKind, FileSymbolTable
from ..core.node_types import NodeKind, Provenance


class DynamicSynthesizer:
    """动态分配合成器"""

    def synthesize(
        self,
        nodes: list[Node],
        edges: list[Edge],
        tables: list[FileSymbolTable],
    ) -> list[Edge]:
        synthetic: list[Edge] = []

        synthetic += self._synthesize_callbacks(nodes, edges, tables)
        synthetic += self._synthesize_event_emitters(nodes, edges, tables)
        synthetic += self._synthesize_anonymous_impls(nodes, edges)

        for e in synthetic:
            e.provenance = Provenance.SYNTHESIZER

        return synthetic

    # ── 回调注册 ───────────────────────────────────────

    def _synthesize_callbacks(
        self, nodes: list[Node], edges: list, tables: list[FileSymbolTable]
    ) -> list[Edge]:
        """on(event, handler) 或 addEventListener(event, handler) → calls"""
        result: list[Edge] = []
        node_by_id = {n.id: n for n in nodes}

        for e in _find_edges_by_kind(edges, "calls"):
            src = _edge_source(e)
            tgt = _edge_target(e)
            callee_node = node_by_id.get(tgt) if tgt else None
            if not callee_node:
                continue
            callee_name = callee_node.name.lower()
            if callee_name in ("on", "addlistener", "addeventlistener",
                               "subscribe", "register", "then"):
                result.append(Edge(
                    source=src, target=tgt,
                    kind=EdgeKind.CALLBACK,
                    provenance=Provenance.SYNTHESIZER,
                    metadata={"pattern": "callback_registration"},
                ))
        return result

    # ── EventEmitter ────────────────────────────────────

    def _synthesize_event_emitters(
        self, nodes: list[Node], edges: list, tables: list[FileSymbolTable]
    ) -> list[Edge]:
        """emit(event) ↔ on(event, handler) 连接"""
        result: list[Edge] = []
        node_by_id = {n.id: n for n in nodes}

        emit_calls = []
        on_calls = []

        for e in _find_edges_by_kind(edges, "calls"):
            tgt = _edge_target(e)
            callee_node = node_by_id.get(tgt) if tgt else None
            if not callee_node:
                continue
            if callee_node.name.lower() in ("emit", "dispatch", "fire", "trigger", "send"):
                emit_calls.append(e)
            elif callee_node.name.lower() in ("on", "addlistener", "subscribe"):
                on_calls.append(e)

        for emit in emit_calls:
            for on_edge in on_calls:
                emit_src = _edge_source(emit)
                on_src = _edge_source(on_edge)
                if emit_src == on_src:
                    continue
                emit_node = node_by_id.get(emit_src)
                on_node = node_by_id.get(on_src)
                if emit_node and on_node and emit_node.file_path == on_node.file_path:
                    result.append(Edge(
                        source=emit_src, target=on_src,
                        kind=EdgeKind.CALLS,
                        provenance=Provenance.SYNTHESIZER,
                        metadata={"pattern": "event_emitter"},
                    ))

        return result

    # ── 匿名类桥接 ──────────────────────────────────────

    def _synthesize_anonymous_impls(
        self, nodes: list[Node], edges: list
    ) -> list[Edge]:
        """匿名类 new Runnable() { run() {} } → implements 边"""
        result: list[Edge] = []
        node_by_id = {n.id: n for n in nodes}

        anon_classes = [n for n in nodes if "<$anon@" in n.name]
        for anon in anon_classes:
            extends_targets = [
                e for e in _find_edges_by_kind(edges, "extends")
                if _edge_source(e) == anon.id and _edge_target(e)
            ]
            for ext in extends_targets:
                result.append(Edge(
                    source=anon.id, target=_edge_target(ext),
                    kind=EdgeKind.IMPLEMENTS,
                    provenance=Provenance.SYNTHESIZER,
                    metadata={"pattern": "anonymous_impl"},
                ))

        return result


def _edge_source(e) -> str:
    if isinstance(e, dict): return e.get("source", "")
    return e.source if hasattr(e, 'source') else ""


def _edge_target(e) -> str:
    if isinstance(e, dict): return e.get("target", "")
    return e.target if hasattr(e, 'target') else ""


def _find_edges_by_kind(edges: list, kind: str) -> list:
    """兼容 Edge 对象或 dict 的查询"""
    result = []
    for e in edges:
        if isinstance(e, dict):
            if e.get("kind") == kind:
                result.append(e)
        elif hasattr(e, 'kind'):
            val = e.kind.value if hasattr(e.kind, 'value') else str(e.kind)
            if val == kind:
                result.append(e)
    return result
