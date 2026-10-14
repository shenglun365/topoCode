import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="network",
    patterns=[
        (r'\bnwdiag\b', 5),
        (r'\bnetwork\s+\w', 3),
        (r'\baddress\b', 2),
    ],
)

@dataclass
class NetNetwork:
    name: str
    address: str = ""
    nodes: list[tuple[str, str]] = field(default_factory=list)

@dataclass
class NetRelation:
    from_name: str
    to_name: str

@dataclass
class NetworkData:
    title: str = ""
    networks: list[NetNetwork] = field(default_factory=list)
    relations: list[NetRelation] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

NWDIAG_START = re.compile(r'^\s*nwdiag\s*\{', re.IGNORECASE)
NETWORK_PAT = re.compile(r'^\s*network\s+(\w[\w\d_]*)\s*\{?', re.IGNORECASE)
ADDRESS_PAT = re.compile(r'^\s*address\s+"([^"]+)"', re.IGNORECASE)
NODE_PAT = re.compile(r'^\s*(\w[\w\d_]*)\s*\[\s*address\s*=\s*"([^"]*)"\s*\]')
REL_PAT = re.compile(r'(\w[\w\d_]*)\s*(<->|-->|\.\.)\s*(\w[\w\d_]*)')

def parse(raw: str) -> NetworkData:
    data = NetworkData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        if NWDIAG_START.match(s) or re.match(r'^\s*\}', s):
            data.lines.append(s)
            continue
        m = NETWORK_PAT.match(s)
        if m:
            data.lines.append(s)
            continue
        m = NODE_PAT.match(s)
        if m:
            data.lines.append(s)
            continue
        m = ADDRESS_PAT.match(s)
        if m:
            data.lines.append(s)
            continue
        m = REL_PAT.match(s)
        if m:
            data.relations.append(NetRelation(from_name=m.group(1), to_name=m.group(3)))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: NetworkData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
