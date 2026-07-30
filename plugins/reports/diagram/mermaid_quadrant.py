import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_quadrant",
    patterns=[
        (r'\bquadrantChart\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class QuadrantPoint:
    name: str
    x: str
    y: str

@dataclass
class QuadrantData:
    title: str = ""
    x_axis: str = ""
    y_axis: str = ""
    quadrants: list[str] = field(default_factory=list)
    points: list[QuadrantPoint] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*quadrantChart\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
X_AXIS_PAT = re.compile(r'^\s*x-axis\s+(.+?)\s*$', re.IGNORECASE)
Y_AXIS_PAT = re.compile(r'^\s*y-axis\s+(.+?)\s*$', re.IGNORECASE)
QUAD_PAT = re.compile(r'^\s*quadrant-\d\s+(.+?)\s*$', re.IGNORECASE)
POINT_PAT = re.compile(r'^\s*(.+?)\s*:\s*\[(.+?)\s*,\s*(.+?)\]\s*$')
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> QuadrantData:
    data = QuadrantData()
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
            data.title = m.group(1).strip().strip('"')
            continue
        m = X_AXIS_PAT.match(s)
        if m:
            data.x_axis = m.group(1).strip()
            continue
        m = Y_AXIS_PAT.match(s)
        if m:
            data.y_axis = m.group(1).strip()
            continue
        m = QUAD_PAT.match(s)
        if m:
            data.quadrants.append(m.group(1).strip())
            continue
        m = POINT_PAT.match(s)
        if m:
            data.points.append(QuadrantPoint(
                name=m.group(1).strip(), x=m.group(2).strip(), y=m.group(3).strip(),
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: QuadrantData) -> str:
    lines = ['quadrantChart']
    if data.title:
        lines.append(f'    title {data.title}')
    if data.x_axis:
        lines.append(f'    x-axis {data.x_axis}')
    if data.y_axis:
        lines.append(f'    y-axis {data.y_axis}')
    for i, q in enumerate(data.quadrants, 1):
        lines.append(f'    quadrant-{i} {q}')
    for p in data.points:
        lines.append(f'    {p.name}: [{p.x}, {p.y}]')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
