from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="jcckit", start_marker="@startjcckit", end_marker="@endjcckit",
    parser_type="pass-through", patterns=[(r'@startjcckit\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class JcckitData:
    content: str = ""

def parse(raw: str) -> JcckitData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return JcckitData(content='\n'.join(content).strip())

def render(data: JcckitData) -> str:
    return f"@startjcckit\n{data.content}\n@endjcckit"
