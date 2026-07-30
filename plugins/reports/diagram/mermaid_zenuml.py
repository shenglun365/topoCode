import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_zenuml",
    patterns=[
        (r'\bzenuml\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class ZenUmlMessage:
    from_participant: str
    to_participant: str
    label: str

@dataclass
class ZenUmlData:
    title: str = ""
    messages: list[ZenUmlMessage] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*zenuml\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
MESSAGE_PAT = re.compile(
    r'^\s*(?:"([^"]+)"|(\w[\w\d_]*))\s*->\s*(?:"([^"]+)"|(\w[\w\d_]*))\s*:\s*(.+?)\s*$'
)

def parse(raw: str) -> ZenUmlData:
    data = ZenUmlData()
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
        m = MESSAGE_PAT.match(s)
        if m:
            frm = m.group(1) or m.group(2)
            to = m.group(3) or m.group(4)
            data.messages.append(ZenUmlMessage(
                from_participant=frm, to_participant=to,
                label=m.group(5).strip(),
            ))
            continue
        data.raw_lines.append(s)
    return data

def _quote_name(name: str) -> str:
    return f'"{name}"' if ' ' in name else name

def render(data: ZenUmlData) -> str:
    lines = ['zenuml']
    if data.title:
        lines.append(f'    title {data.title}')
    for msg in data.messages:
        frm = _quote_name(msg.from_participant)
        to = _quote_name(msg.to_participant)
        lines.append(f'    {frm}->{to}: {msg.label}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
