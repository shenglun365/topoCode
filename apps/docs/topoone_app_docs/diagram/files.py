import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="files", start_marker="@startfiles", end_marker="@endfiles",
    parser_type="tree", patterns=[(r'@startfiles\b', 5), (r'^\s*/', 1, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class FilesData:
    content: str = ""

def parse(raw: str) -> FilesData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return FilesData(content='\n'.join(content).strip())

def render(data: FilesData) -> str:
    return "@startfiles\n" + data.content + "\n@endfiles"
