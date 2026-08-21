from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="ditaa", start_marker="@startditaa", end_marker="@endditaa",
    parser_type="pass-through", patterns=[(r'@startditaa\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class DitaaData:
    content: str = ""

def parse(raw: str) -> DitaaData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return DitaaData(content='\n'.join(content).strip())

def render(data: DitaaData) -> str:
    return f"@startditaa\n{data.content}\n@endditaa"
