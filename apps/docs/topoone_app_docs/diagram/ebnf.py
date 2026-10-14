import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="ebnf", start_marker="@startebnf", end_marker="@endebnf",
    parser_type="tree", patterns=[(r'@startebnf\b', 5), (r'^\s*\w+\s*=', 2, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class EbnfData:
    content: str = ""

def parse(raw: str) -> EbnfData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith("'")]
    return EbnfData(content='\n'.join(content).strip())

def render(data: EbnfData) -> str:
    return "@startebnf\n" + data.content + "\n@endebnf"
