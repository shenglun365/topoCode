from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="creole", start_marker="@startcreole", end_marker="@endcreole",
    parser_type="pass-through", patterns=[(r'@startcreole\b', 5)], supports_skinparam=False,
    supports_preproc=False, supports_layout=False,
)

@dataclass
class CreoleData:
    content: str = ""

def parse(raw: str) -> CreoleData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return CreoleData(content='\n'.join(content).strip())

def render(data: CreoleData) -> str:
    return f"@startcreole\n{data.content}\n@endcreole"
