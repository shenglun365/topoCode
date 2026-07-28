from typing import Optional, Any
import re

from ._meta import ParserMeta

from . import sequence, component
from . import class_diagram
from . import mermaid_flowchart, mermaid_sequence

from . import (
    state, activity, usecase, deployment,
    archimate, object_diagram as object_diagram_mod, timing,
    gantt, network, wireframe, mindmap, wbs,
    json_diagram as json_diagram_mod, yaml_diagram as yaml_diagram_mod,
    hcl, files, git, packet, chen_eer, ebnf,
    pass_math, pass_latex, pass_regex, pass_definition,
    pass_creole, pass_help, pass_sprites, pass_chart,
    pass_flow, pass_board, pass_bpm, pass_salt, pass_dot, pass_ditaa,
    pass_chronology, pass_jcckit,
)

class ParserRegistry:
    def __init__(self):
        self._entries: dict[str, Any] = {}

    def register(self, module: Any) -> None:
        if not hasattr(module, 'meta') or not isinstance(getattr(module, 'meta', None), ParserMeta):
            raise ValueError(f"Module {module.__name__} has no valid 'meta' attribute")
        self._entries[module.meta.name] = module

    def get(self, name: str) -> Optional[Any]:
        return self._entries.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._entries

    def classify(self, code: str) -> Optional[str]:
        best_type = None
        best_score = 0
        best_hits = -1
        for name, module in self._entries.items():
            meta = module.meta
            if not meta.patterns:
                continue
            total = 0
            hits = 0
            for pat_entry in meta.patterns:
                if len(pat_entry) == 3:
                    pat_str, score, flags = pat_entry
                else:
                    pat_str, score = pat_entry
                    flags = 0
                n = len(re.findall(pat_str, code, flags))
                total += score * n
                if n > 0:
                    hits += 1
            if total > best_score or (total == best_score and hits > best_hits):
                best_score = total
                best_hits = hits
                best_type = name
        if best_type is None or best_score < self._entries[best_type].meta.min_score:
            return None
        return best_type

    def rebuild(self, code: str, diag_type: Optional[str] = None) -> dict:
        if diag_type is None or diag_type == "auto":
            diag_type = self.classify(code)
        if diag_type is None or diag_type not in self._entries:
            raise ValueError(f"Unable to identify PlantUML diagram type")
        parser = self._entries[diag_type]
        code = re.sub(r'<br\s*/?>', lambda _: chr(92) + 'n', code, flags=re.IGNORECASE)
        if parser.meta.supports_skinparam or parser.meta.supports_preproc or parser.meta.supports_layout:
            from .preproc import extract_shared, reapply_shared
            ctx, cleaned = extract_shared(code)
            data = parser.parse(cleaned)
            rebuilt = parser.render(data)
            result_code = reapply_shared(rebuilt, ctx)
        else:
            data = parser.parse(code)
            result_code = parser.render(data)
        return {"code": result_code, "type": diag_type}

    def render(self, name: str, data: Any) -> str:
        if name not in self._entries:
            raise ValueError(f"Unknown type: {name}")
        return self._entries[name].render(data)

    @property
    def names(self) -> list[str]:
        return list(self._entries.keys())


PARSER_REGISTRY = ParserRegistry()
MERMAID_REGISTRY: dict[str, object] = {}

def register(name: str, parser_cls: object, registry=None):
    if registry is None:
        registry = PARSER_REGISTRY
    registry[name] = parser_cls

def _classify(code: str, type_scores: list) -> Optional[str]:
    best_type = None
    best_score = 0
    for t, patterns in type_scores:
        s = sum(score * len(re.findall(pat, code, re.MULTILINE)) for pat, score in patterns)
        if s > best_score:
            best_score = s
            best_type = t
    return best_type if best_score >= 2 else None

def classify_plantuml(code: str) -> Optional[str]:
    return PARSER_REGISTRY.classify(code)

def classify_mermaid(code: str) -> Optional[str]:
    return _classify(code, [
        ("flowchart", [
            (r'\bgraph\s+(TB|TD|LR|RL|BT)\b', 3),
            (r'--[>-]', 1),
            (r'[\[\(\{][^\]\)\}]*[\]\)\}]', 1),
        ]),
        ("mermaid_sequence", [
            (r'\bsequenceDiagram\b', 3),
            (r'\bparticipant\b', 2),
            (r'\bactor\b', 2),
            (r'\w+\s*-+[->]\s*\w+\s*:', 2),
        ]),
    ])

def rebuild_plantuml(code: str, diag_type: Optional[str] = None) -> dict:
    return PARSER_REGISTRY.rebuild(code, diag_type)

def rebuild_mermaid(code: str, diag_type: Optional[str] = None) -> dict:
    if not diag_type or diag_type == "auto":
        diag_type = classify_mermaid(code)
    if not diag_type or diag_type not in MERMAID_REGISTRY:
        raise ValueError(f"Unable to identify Mermaid diagram type")
    parser = MERMAID_REGISTRY[diag_type]
    data = parser.parse(code)
    rebuilt = parser.render(data)
    return {"code": rebuilt, "type": diag_type}

def _register_all():
    for mod in [
        sequence, component, class_diagram,
        state, activity, usecase, deployment,
        archimate, object_diagram_mod, timing,
        gantt, network, wireframe, mindmap, wbs,
        json_diagram_mod, yaml_diagram_mod, hcl, files, git,
        packet, chen_eer, ebnf,
        pass_math, pass_latex, pass_regex, pass_definition,
        pass_creole, pass_help, pass_sprites, pass_chart,
        pass_flow, pass_board, pass_bpm, pass_salt, pass_dot, pass_ditaa,
        pass_chronology, pass_jcckit,
    ]:
        PARSER_REGISTRY.register(mod)

_register_all()

register("flowchart", mermaid_flowchart, MERMAID_REGISTRY)
register("mermaid_sequence", mermaid_sequence, MERMAID_REGISTRY)
