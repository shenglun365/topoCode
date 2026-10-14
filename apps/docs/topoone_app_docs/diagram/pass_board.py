from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="board", start_marker="@startboard", end_marker="@endboard",
    parser_type="pass-through", patterns=[(r'@startboard\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class BoardData:
    content: str = ""

def parse(raw: str) -> BoardData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return BoardData(content='\n'.join(content).strip())

def render(data: BoardData) -> str:
    return f"@startboard\n{data.content}\n@endboard"
