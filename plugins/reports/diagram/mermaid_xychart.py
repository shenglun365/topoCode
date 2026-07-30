import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_xychart",
    patterns=[
        (r'\bxychart-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class XYChartData:
    title: str = ""
    x_axis: str = ""
    y_axis: str = ""
    bars: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*xychart-beta\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
X_AXIS_PAT = re.compile(r'^\s*x-axis\s+(.+?)\s*$', re.IGNORECASE)
Y_AXIS_PAT = re.compile(r'^\s*y-axis\s+(.+?)\s*$', re.IGNORECASE)
BAR_PAT = re.compile(r'^\s*bar\s+(\[.*\])\s*$', re.IGNORECASE)
LINE_PAT = re.compile(r'^\s*line\s+(\[.*\])\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> XYChartData:
    data = XYChartData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = TITLE_PAT.match(s)
        if m:
            data.title = m.group(1).strip()
            continue
        m = X_AXIS_PAT.match(s)
        if m:
            data.x_axis = m.group(1).strip()
            continue
        m = Y_AXIS_PAT.match(s)
        if m:
            data.y_axis = m.group(1).strip()
            continue
        m = BAR_PAT.match(s)
        if m:
            data.bars.append(m.group(1))
            continue
        m = LINE_PAT.match(s)
        if m:
            data.lines.append(m.group(1))
            continue
        data.raw_lines.append(s)
    return data

def render(data: XYChartData) -> str:
    lines = ['xychart-beta']
    if data.title:
        lines.append(f'    title {data.title}')
    if data.x_axis:
        lines.append(f'    x-axis {data.x_axis}')
    if data.y_axis:
        lines.append(f'    y-axis {data.y_axis}')
    for bar in data.bars:
        lines.append(f'    bar {bar}')
    for line_val in data.lines:
        lines.append(f'    line {line_val}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
