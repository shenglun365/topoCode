import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_c4",
    patterns=[
        (r'\bC4Context\b', 20),
        (r'\bC4Container\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class C4Element:
    kind: str
    alias: str
    label: str
    desc: str = ""

@dataclass
class C4Boundary:
    kind: str
    alias: str
    label: str
    elements: list[C4Element] = field(default_factory=list)

@dataclass
class C4Rel:
    from_alias: str
    to_alias: str
    label: str = ""
    tech: str = ""

@dataclass
class C4Data:
    diagram_type: str = "C4Context"
    title: str = ""
    elements: list[C4Element] = field(default_factory=list)
    boundaries: list[C4Boundary] = field(default_factory=list)
    relations: list[C4Rel] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*(C4Context|C4Container)\s*$')
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

ELEM_KINDS = (
    r'Person_Ext|Person|System_Ext|System|ContainerDb|Container'
    r'|System_Boundary|Enterprise_Boundary'
)

ELEM_PAT = re.compile(
    rf'^\s*({ELEM_KINDS})\((\w[\w\d_]*),\s*"([^"]*)"\s*(?:,\s*"([^"]*)")?\)\s*$',
)
REL_PAT = re.compile(
    r'^\s*Rel\((\w[\w\d_]*),\s*(\w[\w\d_]*),\s*"([^"]*)"(?:\s*,\s*"([^"]*)")?\)\s*$',
    re.IGNORECASE,
)
BOUNDARY_OPEN = re.compile(
    rf'^\s*(System_Boundary|Enterprise_Boundary)\((\w[\w\d_]*),\s*"([^"]*)"\)\s*\{{?\s*$'
)
CLOSE_BRACE = re.compile(r'^\s*\}\s*$')

def parse(raw: str) -> C4Data:
    data = C4Data()
    current_boundary: C4Boundary | None = None
    in_boundary = False

    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        m = HEADER_PAT.match(s)
        if m:
            data.diagram_type = m.group(1)
            continue
        m = TITLE_PAT.match(s)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue
        if in_boundary:
            if CLOSE_BRACE.match(s):
                in_boundary = False
                current_boundary = None
                continue
            m = ELEM_PAT.match(s)
            if m:
                elem = C4Element(kind=m.group(1), alias=m.group(2), label=m.group(3), desc=m.group(4) or '')
                if current_boundary is not None:
                    current_boundary.elements.append(elem)
                continue
            data.raw_lines.append(s)
            continue
        if CLOSE_BRACE.match(s):
            continue
        m = BOUNDARY_OPEN.match(s)
        if m:
            current_boundary = C4Boundary(kind=m.group(1), alias=m.group(2), label=m.group(3))
            data.boundaries.append(current_boundary)
            in_boundary = True
            continue
        m = ELEM_PAT.match(s)
        if m:
            data.elements.append(C4Element(
                kind=m.group(1), alias=m.group(2),
                label=m.group(3), desc=m.group(4) or '',
            ))
            continue
        m = REL_PAT.match(s)
        if m:
            data.relations.append(C4Rel(
                from_alias=m.group(1), to_alias=m.group(2),
                label=m.group(3), tech=m.group(4) or '',
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: C4Data) -> str:
    lines = [f'{data.diagram_type}']
    if data.title:
        lines.append(f'    title {data.title}')
    for elem in data.elements:
        if elem.desc:
            lines.append(f'    {elem.kind}({elem.alias}, "{elem.label}", "{elem.desc}")')
        else:
            lines.append(f'    {elem.kind}({elem.alias}, "{elem.label}")')
    for b in data.boundaries:
        lines.append(f'    {b.kind}({b.alias}, "{b.label}") {{')
        for elem in b.elements:
            if elem.desc:
                lines.append(f'        {elem.kind}({elem.alias}, "{elem.label}", "{elem.desc}")')
            else:
                lines.append(f'        {elem.kind}({elem.alias}, "{elem.label}")')
        lines.append('    }')
    for r in data.relations:
        if r.tech:
            lines.append(f'    Rel({r.from_alias}, {r.to_alias}, "{r.label}", "{r.tech}")')
        else:
            lines.append(f'    Rel({r.from_alias}, {r.to_alias}, "{r.label}")')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
