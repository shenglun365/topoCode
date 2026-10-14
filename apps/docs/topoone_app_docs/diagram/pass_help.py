from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="help", start_marker="@startuml", end_marker="@enduml",
    parser_type="pass-through", patterns=[(r'^\s*help\b', 3), (r'@startuml\s+help\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class HelpData:
    content: str = ""

def parse(raw: str) -> HelpData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return HelpData(content='\n'.join(content).strip())

def render(data: HelpData) -> str:
    return f"@startuml\n{data.content}\n@enduml"
