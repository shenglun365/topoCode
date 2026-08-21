import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_eventmodeling",
    patterns=[
        (r'\beventmodeling\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class EventModelingData:
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*eventmodeling\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> EventModelingData:
    data = EventModelingData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        data.raw_lines.append(s)
    return data

def render(data: EventModelingData) -> str:
    lines = ['eventmodeling']
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
