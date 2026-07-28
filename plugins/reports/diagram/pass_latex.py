from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="latex", start_marker="@startlatex", end_marker="@endlatex",
    parser_type="pass-through", patterns=[(r'@startlatex\b', 5)], supports_skinparam=False,
    supports_preproc=False, supports_layout=False,
)

@dataclass
class LatexData:
    content: str = ""

def parse(raw: str) -> LatexData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return LatexData(content='\n'.join(content).strip())

def render(data: LatexData) -> str:
    return f"@startlatex\n{data.content}\n@endlatex"
