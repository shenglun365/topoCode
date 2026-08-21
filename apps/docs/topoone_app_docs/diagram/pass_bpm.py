from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="bpm", start_marker="@startbpm", end_marker="@endbpm",
    parser_type="pass-through", patterns=[(r'@startbpm\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class BpmData:
    content: str = ""

def parse(raw: str) -> BpmData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return BpmData(content='\n'.join(content).strip())

def render(data: BpmData) -> str:
    return f"@startbpm\n{data.content}\n@endbpm"
