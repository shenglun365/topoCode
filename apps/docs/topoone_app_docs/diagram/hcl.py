import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="hcl", start_marker="@starthcl", end_marker="@endhcl",
    parser_type="tree", patterns=[(r'@starthcl\b', 5), (r'resource\s+"\w+"\s+"', 3)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class HclData:
    content: str = ""

def parse(raw: str) -> HclData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return HclData(content='\n'.join(content).strip())

def render(data: HclData) -> str:
    return "@starthcl\n" + data.content + "\n@endhcl"
