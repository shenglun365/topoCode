import re
from dataclasses import dataclass, field

@dataclass
class PieData:
    title: str = ""
    items: list[tuple[str, str]] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*pie\s+(?:title\s+(.+?))?\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
ITEM_PAT = re.compile(r'^\s*"([^"]*)"\s*:\s*(\d+(?:\.\d+)?)\s*$')

def parse(raw: str) -> PieData:
    data = PieData()
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
                data.title = m.group(1).strip().strip('"')
            continue
        m = ITEM_PAT.match(s)
        if m:
            data.items.append((m.group(1), m.group(2)))
            continue
        data.raw_lines.append(s)
    return data

def render(data: PieData) -> str:
    if data.title:
        lines = [f'pie title {data.title}']
    else:
        lines = ['pie']
    for label, value in data.items:
        lines.append(f'    "{label}" : {value}')
    for line in data.raw_lines:
        lines.append(f'    {line}')
    return '\n'.join(lines)
