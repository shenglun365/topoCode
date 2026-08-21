import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_cynefin",
    patterns=[
        (r'\bcynefin-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class CynefinData:
    title: str = ""
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*cynefin-beta\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> CynefinData:
    data = CynefinData()
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
        data.raw_lines.append(s)
    return data

def render(data: CynefinData) -> str:
    lines = ['cynefin-beta']
    if data.title:
        lines.append(f'    title {data.title}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
