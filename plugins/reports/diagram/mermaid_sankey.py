import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_sankey",
    patterns=[
        (r'\bsankey-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class SankeyLink:
    source: str
    target: str
    value: str

@dataclass
class SankeyData:
    links: list[SankeyLink] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*sankey-beta\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
LINK_PAT = re.compile(r'^\s*(.+?)\s*,\s*(.+?)\s*,\s*(\d+(?:\.\d+)?)\s*$')

def parse(raw: str) -> SankeyData:
    data = SankeyData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = LINK_PAT.match(s)
        if m:
            data.links.append(SankeyLink(
                source=m.group(1).strip().strip('"'),
                target=m.group(2).strip().strip('"'),
                value=m.group(3),
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: SankeyData) -> str:
    lines = ['sankey-beta']
    for link in data.links:
        lines.append(f'    {link.source}, {link.target}, {link.value}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
