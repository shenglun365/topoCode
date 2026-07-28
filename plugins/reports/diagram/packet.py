import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="packet", start_marker="@startpacketdiag", end_marker="@endpacketdiag",
    parser_type="tree", patterns=[(r'@startpacketdiag\b', 5), (r'\d+-\d+:', 2)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class PacketData:
    content: str = ""

def parse(raw: str) -> PacketData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return PacketData(content='\n'.join(content).strip())

def render(data: PacketData) -> str:
    return "@startpacketdiag\n" + data.content + "\n@endpacketdiag"
