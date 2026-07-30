import html
from typing import Optional, Any
import re

from ._meta import ParserMeta

from . import sequence, component
from . import class_diagram
from . import mermaid_flowchart, mermaid_sequence
from . import mermaid_class, mermaid_state, mermaid_er, mermaid_gantt
from . import mermaid_pie, mermaid_journey, mermaid_timeline
from . import mermaid_gitgraph, mermaid_mindmap, mermaid_block
from . import mermaid_requirement, mermaid_architecture, mermaid_c4
from . import mermaid_swimlane, mermaid_kanban, mermaid_xychart
from . import mermaid_sankey, mermaid_quadrant, mermaid_packet
from . import mermaid_venn, mermaid_zenuml, mermaid_ishikawa
from . import mermaid_treemap, mermaid_treeview, mermaid_radar
from . import mermaid_wardley, mermaid_cynefin, mermaid_eventmodeling
from . import mermaid_info

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

    def classify(self, code: str, prefix: str = "", exclude_prefix: str = "") -> Optional[str]:
        best_type = None
        best_score = 0
        best_hits = -1
        for name, module in self._entries.items():
            if prefix and not name.startswith(prefix):
                continue
            if exclude_prefix and name.startswith(exclude_prefix):
                continue
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

    def rebuild(self, code: str, diag_type: Optional[str] = None,
                prefix: str = "", exclude_prefix: str = "") -> dict:
        if diag_type is None or diag_type == "auto":
            diag_type = self.classify(code, prefix=prefix, exclude_prefix=exclude_prefix)
        if diag_type is None or diag_type not in self._entries:
            raise ValueError(f"Unable to identify diagram type")
        parser = self._entries[diag_type]
        code = html.unescape(code)
        code = re.sub(r'<br\s*/?>', lambda _: chr(92) + 'n', code, flags=re.IGNORECASE)
        if parser.meta.supports_skinparam or parser.meta.supports_preproc or parser.meta.supports_layout:
            if parser.meta.preproc_engine == "mermaid":
                from .mermaid_preproc import extract_shared, reapply_shared
            else:
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


def classify_plantuml(code: str) -> Optional[str]:
    return PARSER_REGISTRY.classify(code, exclude_prefix="mermaid_")


def classify_mermaid(code: str) -> Optional[str]:
    return PARSER_REGISTRY.classify(code, prefix="mermaid_")


def rebuild_plantuml(code: str, diag_type: Optional[str] = None) -> dict:
    return PARSER_REGISTRY.rebuild(code, diag_type, exclude_prefix="mermaid_")


def rebuild_mermaid(code: str, diag_type: Optional[str] = None) -> dict:
    if diag_type and not diag_type.startswith("mermaid_") and diag_type != "auto":
        diag_type = f"mermaid_{diag_type}"
    return PARSER_REGISTRY.rebuild(code, diag_type, prefix="mermaid_")


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


def _register_all_mermaid():
    for mod in [
        mermaid_flowchart, mermaid_sequence,
        mermaid_class, mermaid_state, mermaid_er, mermaid_gantt,
        mermaid_pie, mermaid_journey, mermaid_timeline,
        mermaid_gitgraph, mermaid_mindmap, mermaid_block,
        mermaid_requirement, mermaid_architecture, mermaid_c4,
        mermaid_swimlane, mermaid_kanban, mermaid_xychart,
        mermaid_sankey, mermaid_quadrant, mermaid_packet,
        mermaid_venn, mermaid_zenuml, mermaid_ishikawa,
        mermaid_treemap, mermaid_treeview, mermaid_radar,
        mermaid_wardley, mermaid_cynefin, mermaid_eventmodeling,
        mermaid_info,
    ]:
        PARSER_REGISTRY.register(mod)


_register_all()
_register_all_mermaid()
