from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="math", start_marker="@startmath", end_marker="@endmath",
    parser_type="pass-through", patterns=[(r'@startmath\b', 5)], supports_skinparam=False,
    supports_preproc=False, supports_layout=False,
)

@dataclass
class MathData:
    content: str = ""

def parse(raw: str) -> MathData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return MathData(content='\n'.join(content).strip())

def render(data: MathData) -> str:
    return f"@startmath\n{data.content}\n@endmath"
