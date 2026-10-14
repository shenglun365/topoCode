from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="salt", start_marker="@startsalt", end_marker="@endsalt",
    parser_type="pass-through", patterns=[(r'@startsalt\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class SaltData:
    content: str = ""

def parse(raw: str) -> SaltData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return SaltData(content='\n'.join(content).strip())

def render(data: SaltData) -> str:
    return f"@startsalt\n{data.content}\n@endsalt"
