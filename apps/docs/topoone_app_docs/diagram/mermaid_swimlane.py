import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_swimlane",
    patterns=[
        (r'\bswimlane-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class SwimlaneData:
    direction: str = "LR"
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*swimlane-beta(?:\s+(LR|TB))?\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> SwimlaneData:
    data = SwimlaneData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        m = HEADER_PAT.match(s)
        if m:
            if m.group(1):
                data.direction = m.group(1).upper()
            continue
        data.raw_lines.append(s)
    return data

def render(data: SwimlaneData) -> str:
    lines = [f'swimlane-beta {data.direction}']
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
