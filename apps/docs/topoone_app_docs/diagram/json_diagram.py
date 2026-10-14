import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="json", start_marker="@startjson", end_marker="@endjson",
    parser_type="tree", patterns=[(r'@startjson\b', 5), (r'^\s*"', 1, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class JsonData:
    content: str = ""

def parse(raw: str) -> JsonData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return JsonData(content='\n'.join(content).strip())

def render(data: JsonData) -> str:
    return "@startjson\n" + data.content + "\n@endjson"
