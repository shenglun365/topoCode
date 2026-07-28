from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="flow", start_marker="@startflow", end_marker="@endflow",
    parser_type="pass-through", patterns=[(r'@startflow\b', 5)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class FlowData:
    content: str = ""

def parse(raw: str) -> FlowData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return FlowData(content='\n'.join(content).strip())

def render(data: FlowData) -> str:
    return f"@startflow\n{data.content}\n@endflow"
