import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_architecture",
    patterns=[
        (r'\barchitecture-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class ArchService:
    name: str
    icon: str = ""
    label: str = ""
    group: str = ""

@dataclass
class ArchEdge:
    from_name: str
    from_dir: str
    to_name: str
    to_dir: str

@dataclass
class ArchitectureData:
    services: list[ArchService] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)
    edges: list[ArchEdge] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*architecture-beta\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
SERVICE_PAT = re.compile(
    r'^\s*service\s+(\w[\w\d_]*)\s*\((\w+)\)\s*\[([^\]]*)\]\s*(?:in\s+(\w[\w\d_]*))?\s*$',
    re.IGNORECASE,
)
GROUP_PAT = re.compile(r'^\s*group\s+(\w[\w\d_]*)\s*$', re.IGNORECASE)
EDGE_PAT = re.compile(
    r'^\s*(\w[\w\d_]*):([LRBT])\s*--\s*([LRBT]):(\w[\w\d_]*)\s*$',
)

def parse(raw: str) -> ArchitectureData:
    data = ArchitectureData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = SERVICE_PAT.match(s)
        if m:
            data.services.append(ArchService(
                name=m.group(1), icon=m.group(2),
                label=m.group(3), group=m.group(4) or '',
            ))
            continue
        m = GROUP_PAT.match(s)
        if m:
            data.groups.append(m.group(1))
            continue
        m = EDGE_PAT.match(s)
        if m:
            data.edges.append(ArchEdge(
                from_name=m.group(1), from_dir=m.group(2),
                to_name=m.group(4), to_dir=m.group(3),
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: ArchitectureData) -> str:
    lines = ['architecture-beta']
    for srv in data.services:
        line = f'    service {srv.name}({srv.icon})[{srv.label}]'
        if srv.group:
            line += f' in {srv.group}'
        lines.append(line)
    for g in data.groups:
        lines.append(f'    group {g}')
    for e in data.edges:
        lines.append(f'    {e.from_name}:{e.from_dir} -- {e.to_dir}:{e.to_name}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
