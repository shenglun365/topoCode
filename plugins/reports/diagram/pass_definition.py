from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="definition", start_marker="@startdef", end_marker="@enddef",
    parser_type="pass-through", patterns=[(r'@startdef\b', 5)], supports_skinparam=False,
    supports_preproc=False, supports_layout=False,
)

@dataclass
class DefinitionData:
    content: str = ""

def parse(raw: str) -> DefinitionData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return DefinitionData(content='\n'.join(content).strip())

def render(data: DefinitionData) -> str:
    return f"@startdef\n{data.content}\n@enddef"
