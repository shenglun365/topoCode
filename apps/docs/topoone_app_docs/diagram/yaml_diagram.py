import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="yaml", start_marker="@startyaml", end_marker="@endyaml",
    parser_type="tree", patterns=[(r'@startyaml\b', 5), (r'^\s*\w+:\s+\S', 1, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class YamlData:
    content: str = ""

def parse(raw: str) -> YamlData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return YamlData(content='\n'.join(content).strip())

def render(data: YamlData) -> str:
    return "@startyaml\n" + data.content + "\n@endyaml"
