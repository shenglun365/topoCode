"""Go & Rust Web 框架解析器: Gin/Chi, Axum/Actix"""

from ..core.symbol_model import Node, Edge, EdgeKind, FileSymbolTable
from ..core.node_types import NodeKind, Provenance
from . import FrameworkResolver, register_resolver


class GoWebResolver(FrameworkResolver):
    name = "go_web"
    language = "go"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language != "go": continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and any(
                    pkg in n.name for pkg in ("github.com/gin-gonic", "github.com/go-chi",
                                               "github.com/gorilla/mux", "github.com/labstack/echo")
                ):
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        for n in nodes:
            if n.kind == NodeKind.FUNCTION and n.is_exported:
                edges.append(Edge(
                    source=n.id, target=n.id,
                    kind=EdgeKind.REFERENCES,
                    provenance=Provenance.FRAMEWORK,
                    file_path=n.file_path,
                    metadata={"go_handler": n.qualified_name},
                ))
        return edges


class RustWebResolver(FrameworkResolver):
    name = "rust_web"
    language = "rust"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language != "rust": continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and any(
                    crate in n.name for crate in ("axum", "actix", "rocket", "warp", "tide")
                ):
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        for n in nodes:
            if n.kind == NodeKind.FUNCTION and n.is_exported:
                d = n.decorators or []
                if any("get" in x or "route" in x or "post" in x for x in d):
                    edges.append(Edge(
                        source=n.id, target=n.id,
                        kind=EdgeKind.REFERENCES,
                        provenance=Provenance.FRAMEWORK,
                        file_path=n.file_path,
                        metadata={"rust_handler": n.qualified_name},
                    ))
        return edges


class RailsResolver(FrameworkResolver):
    name = "rails"
    language = "ruby"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language != "ruby": continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and "rails" in n.name:
                    return True
            # Check for controller files
            for n in t.nodes:
                if n.kind == NodeKind.CLASS and "Controller" in n.name:
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        controllers = [n for n in nodes if n.kind == NodeKind.CLASS and "Controller" in n.name]
        for ctrl in controllers:
            for n in nodes:
                if (n.file_path == ctrl.file_path and
                        n.kind == NodeKind.METHOD and
                        n.qualified_name.startswith(ctrl.name)):
                    edges.append(Edge(
                        source=ctrl.id, target=n.id,
                        kind=EdgeKind.CALLS,
                        provenance=Provenance.FRAMEWORK,
                        file_path=ctrl.file_path,
                        metadata={"rails_action": n.name},
                    ))
        return edges


register_resolver(GoWebResolver())
register_resolver(RustWebResolver())
register_resolver(RailsResolver())
