import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_radar",
    patterns=[
        (r'\bradar-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class RadarCurve:
    name: str
    values: str

@dataclass
class RadarData:
    axes: str = ""
    curves: list[RadarCurve] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*radar-beta\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
AXIS_PAT = re.compile(r'^\s*axis\s+(.+?)\s*$', re.IGNORECASE)
CURVE_PAT = re.compile(r'^\s*curve\s+(\S+)\s*\{(.+?)\}\s*$', re.IGNORECASE)

def parse(raw: str) -> RadarData:
    data = RadarData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = AXIS_PAT.match(s)
        if m:
            data.axes = m.group(1).strip()
            continue
        m = CURVE_PAT.match(s)
        if m:
            data.curves.append(RadarCurve(name=m.group(1), values=m.group(2)))
            continue
        data.raw_lines.append(s)
    return data

def render(data: RadarData) -> str:
    lines = ['radar-beta']
    if data.axes:
        lines.append(f'    axis {data.axes}')
    for c in data.curves:
        lines.append(f'    curve {c.name}{{{c.values}}}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
