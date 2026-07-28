from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="dot", start_marker="@startdot", end_marker="@enddot",
    parser_type="pass-through", patterns=[(r'@startdot\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class DotData:
    content: str = ""

def parse(raw: str) -> DotData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return DotData(content='\n'.join(content).strip())

def render(data: DotData) -> str:
    return f"@startdot\n{data.content}\n@enddot"
