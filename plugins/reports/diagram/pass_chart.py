from ._meta import ParserMeta
from dataclasses import dataclass

meta = ParserMeta(
    name="chart", start_marker="@startchart", end_marker="@endchart",
    parser_type="pass-through", patterns=[(r'@startchart\b', 5), (r'\bbar\b\s+"', 3)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
)

@dataclass
class ChartData:
    content: str = ""

def parse(raw: str) -> ChartData:
    lines = raw.split('\n')
    content = [l for l in lines if not l.strip().startswith('@')]
    return ChartData(content='\n'.join(content).strip())

def render(data: ChartData) -> str:
    return f"@startchart\n{data.content}\n@endchart"
