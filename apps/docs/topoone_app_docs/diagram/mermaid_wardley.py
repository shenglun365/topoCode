import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_wardley",
    patterns=[
        (r'\bwardley-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class WardleyComponent:
    name: str
    x: str
    y: str

@dataclass
class WardleyEdge:
    from_name: str
    to_name: str

@dataclass
class WardleyData:
    title: str = ""
    components: list[WardleyComponent] = field(default_factory=list)
    edges: list[WardleyEdge] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*wardley-beta\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
COMPONENT_PAT = re.compile(
    r'^\s*component\s+(\w[\w\d_]*)\s+\[(.+?)\s*,\s*(.+?)\]\s*$', re.IGNORECASE
)
EDGE_PAT = re.compile(r'^\s*(\w[\w\d_]*)\s*->\s*(\w[\w\d_]*)\s*$')
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> WardleyData:
    data = WardleyData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = TITLE_PAT.match(s)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue
        m = COMPONENT_PAT.match(s)
        if m:
            data.components.append(WardleyComponent(
                name=m.group(1), x=m.group(2).strip(), y=m.group(3).strip(),
            ))
            continue
        m = EDGE_PAT.match(s)
        if m:
            data.edges.append(WardleyEdge(from_name=m.group(1), to_name=m.group(2)))
            continue
        data.raw_lines.append(s)
    return data

def render(data: WardleyData) -> str:
    lines = ['wardley-beta']
    if data.title:
        lines.append(f'    title {data.title}')
    for c in data.components:
        lines.append(f'    component {c.name} [{c.x}, {c.y}]')
    for e in data.edges:
        lines.append(f'    {e.from_name} -> {e.to_name}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
