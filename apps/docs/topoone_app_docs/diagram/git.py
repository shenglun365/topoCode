import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="git", start_marker="@startgit", end_marker="@endgit",
    parser_type="tree", patterns=[(r'@startgit\b', 5), (r'^\s*\*\s+\S', 1, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class GitData:
    content: str = ""

def parse(raw: str) -> GitData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return GitData(content='\n'.join(content).strip().lstrip('* '))

def render(data: GitData) -> str:
    return "@startgit\n* " + data.content + "\n@endgit"
