import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="chen_eer", start_marker="@startchen", end_marker="@endchen",
    parser_type="tree", patterns=[(r'@startchen\b', 5), (r'\bentity\b', 3), (r'\brelationship\b', 3)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class ChenData:
    content: str = ""

def parse(raw: str) -> ChenData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return ChenData(content='\n'.join(content).strip())

def render(data: ChenData) -> str:
    return "@startchen\n" + data.content + "\n@endchen"
