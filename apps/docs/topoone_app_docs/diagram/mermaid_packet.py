import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_packet",
    patterns=[
        (r'\bpacket-beta\b', 30),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class PacketField:
    bits: str
    label: str

@dataclass
class PacketData:
    fields: list[PacketField] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*packet-beta\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
FIELD_PAT = re.compile(r'^\s*(\d+-\d+)\s*:\s*"([^"]*)"\s*$')

def parse(raw: str) -> PacketData:
    data = PacketData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = FIELD_PAT.match(s)
        if m:
            data.fields.append(PacketField(bits=m.group(1), label=m.group(2)))
            continue
        data.raw_lines.append(s)
    return data

def render(data: PacketData) -> str:
    lines = ['packet-beta']
    for f in data.fields:
        lines.append(f'    {f.bits}: "{f.label}"')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
