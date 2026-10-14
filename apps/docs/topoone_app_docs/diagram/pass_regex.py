from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="regex", start_marker="@startregex", end_marker="@endregex",
    parser_type="pass-through", patterns=[(r'@startregex\b', 5)], supports_skinparam=False,
    supports_preproc=False, supports_layout=False,
)

@dataclass
class RegexData:
    content: str = ""

def parse(raw: str) -> RegexData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return RegexData(content='\n'.join(content).strip())

def render(data: RegexData) -> str:
    return f"@startregex\n{data.content}\n@endregex"
