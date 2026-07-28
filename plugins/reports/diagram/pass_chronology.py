from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="chronology", start_marker="@startchronology", end_marker="@endchronology",
    parser_type="pass-through", patterns=[(r'@startchronology\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class ChronologyData:
    content: str = ""

def parse(raw: str) -> ChronologyData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return ChronologyData(content='\n'.join(content).strip())

def render(data: ChronologyData) -> str:
    return f"@startchronology\n{data.content}\n@endchronology"
