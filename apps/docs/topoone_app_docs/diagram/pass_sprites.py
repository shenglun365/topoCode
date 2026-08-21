from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="sprites", start_marker="@startsprites", end_marker="@endsprites",
    parser_type="pass-through", patterns=[(r'@startsprites\b', 5)], supports_skinparam=False,
    supports_preproc=True, supports_layout=False,
)

@dataclass
class SpritesData:
    content: str = ""

def parse(raw: str) -> SpritesData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@') and not l.strip().startswith('!')]
    return SpritesData(content='\n'.join(content).strip())

def render(data: SpritesData) -> str:
    return f"@startsprites\n{data.content}\n@endsprites"
