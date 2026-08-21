import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_venn",
    patterns=[
        (r'\bvenn-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class VennData:
    title: str = ""
    sets: list[str] = field(default_factory=list)
    unions: list[list[str]] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*venn-beta\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
SET_PAT = re.compile(r'^\s*set\s+(.+?)\s*$', re.IGNORECASE)
UNION_PAT = re.compile(r'^\s*union\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> VennData:
    data = VennData()
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
        m = SET_PAT.match(s)
        if m:
            data.sets.append(m.group(1).strip())
            continue
        m = UNION_PAT.match(s)
        if m:
            parts = [p.strip() for p in m.group(1).split(',')]
            data.unions.append(parts)
            continue
        data.raw_lines.append(s)
    return data

def render(data: VennData) -> str:
    lines = ['venn-beta']
    if data.title:
        lines.append(f'    title {data.title}')
    for s in data.sets:
        lines.append(f'    set {s}')
    for u in data.unions:
        lines.append(f'    union {", ".join(u)}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
