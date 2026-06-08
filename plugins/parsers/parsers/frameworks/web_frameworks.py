"""核心框架解析器: Django, Flask, Spring, Express, React"""

from __future__ import annotations

from ..core.symbol_model import Node, Edge, EdgeKind, FileSymbolTable
from ..core.node_types import NodeKind, Provenance
from . import FrameworkResolver, register_resolver


class DjangoResolver(FrameworkResolver):
    name = "django"
    language = "python"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language != "python":
                continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and "django" in n.name:
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        urlpatterns = [n for n in nodes if n.name == "urlpatterns"]
        for up in urlpatterns:
            for n in nodes:
                if n.file_path == up.file_path and n.kind in (NodeKind.FUNCTION, NodeKind.METHOD):
                    edges.append(Edge(source=up.id, target=n.id, kind=EdgeKind.CALLS,
                                      provenance=Provenance.FRAMEWORK, file_path=up.file_path))
        return edges


class FlaskResolver(FrameworkResolver):
    name = "flask"
    language = "python"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language != "python":
                continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and n.name in ("flask", "fastapi"):
                    return True
            for n in t.nodes:
                if n.decorators and any("route" in d or "app." in d for d in n.decorators):
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        for n in nodes:
            if n.decorators and n.kind == NodeKind.FUNCTION:
                for deco in n.decorators:
                    if "route" in deco or "get(" in deco or "post(" in deco:
                        edges.append(Edge(
                            source=n.id, target=n.id,
                            kind=EdgeKind.REFERENCES,
                            provenance=Provenance.FRAMEWORK,
                            file_path=n.file_path,
                            metadata={"route_handler": n.qualified_name},
                        ))
        return edges


class SpringResolver(FrameworkResolver):
    name = "spring"
    language = "java"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language != "java":
                continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and "springframework" in n.name:
                    return True
            for n in t.nodes:
                if n.decorators:
                    for d in n.decorators:
                        if d in ("Controller", "RestController", "RequestMapping",
                                 "GetMapping", "PostMapping", "Service", "Component"):
                            return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        for n in nodes:
            if n.decorators and n.kind == NodeKind.METHOD:
                for d in n.decorators:
                    if any(a in d for a in ("Mapping", "Controller")):
                        edges.append(Edge(
                            source=n.id, target=n.id,
                            kind=EdgeKind.REFERENCES,
                            provenance=Provenance.FRAMEWORK,
                            file_path=n.file_path,
                            metadata={"spring_endpoint": n.qualified_name},
                        ))
        return edges


class ExpressResolver(FrameworkResolver):
    name = "express"
    language = "typescript"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language not in ("typescript", "javascript"):
                continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and n.name in ("express", "@nestjs/core"):
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        # Match app.get/post/put/delete(path, handler) patterns
        for n in nodes:
            if n.decorators and n.kind == NodeKind.METHOD:
                for d in n.decorators:
                    if any(a in d for a in ("Get", "Post", "Put", "Delete", "Patch")):
                        edges.append(Edge(
                            source=n.id, target=n.id,
                            kind=EdgeKind.REFERENCES,
                            provenance=Provenance.FRAMEWORK,
                            file_path=n.file_path,
                            metadata={"nestjs_endpoint": n.qualified_name},
                        ))
        return edges


class ReactResolver(FrameworkResolver):
    name = "react"
    language = "typescript"

    def detect(self, tables: list[FileSymbolTable]) -> bool:
        for t in tables:
            if t.language not in ("typescript", "javascript"):
                continue
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and n.name in ("react", "react-dom"):
                    return True
            for n in t.nodes:
                if n.kind == NodeKind.IMPORT and ("useState" in n.name or "useEffect" in n.name):
                    return True
        return False

    def extract(self, table: FileSymbolTable) -> list[Node]:
        return []

    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        edges: list[Edge] = []
        # Connect component renders to child components
        components = [n for n in nodes if n.kind == NodeKind.FUNCTION and n.is_exported
                      and n.name and n.name[0].isupper()]
        for comp in components:
            for n in nodes:
                if n.kind == NodeKind.FUNCTION and n.name and n.name[0].isupper() and n.id != comp.id:
                    if n.file_path == comp.file_path:
                        edges.append(Edge(
                            source=comp.id, target=n.id,
                            kind=EdgeKind.REFERENCES,
                            provenance=Provenance.FRAMEWORK,
                            file_path=comp.file_path,
                            metadata={"react_component": True},
                        ))
        return edges


# 注册
register_resolver(DjangoResolver())
register_resolver(FlaskResolver())
register_resolver(SpringResolver())
register_resolver(ExpressResolver())
register_resolver(ReactResolver())
