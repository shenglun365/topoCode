import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="activity",
    patterns=[
        (r'^:.*;$', 3, re.MULTILINE),
        (r'\bstart\b', 2),
        (r'\bstop\b', 2),
        (r'\bif\s*\(', 2),
        (r'\bendif\b', 2),
        (r'\bfork\b', 2),
        (r'\bpartition\b', 2),
    ],
)

@dataclass
class ActivityBlock:
    kind: str              # action | start | stop | if | else | endif | fork | partition
    text: str = ""
    children: list['ActivityBlock'] = field(default_factory=list)

@dataclass
class ActivityData:
    title: str = ""
    blocks: list[str] = field(default_factory=list)

def parse(raw: str) -> ActivityData:
    lines_out = []
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if s in ('start', 'stop', 'endif', 'end fork', 'endfork'):
            lines_out.append(s)
            continue
        if s.startswith(':'):
            if s.endswith(';'):
                lines_out.append(s)
                continue
            lines_out.append(s + ';')
            continue
        if s.startswith('if') or s.startswith('else') or s.startswith('elseif'):
            lines_out.append(s)
            continue
        if s.startswith('fork') or s.startswith('partition'):
            lines_out.append(s)
            continue
        if s.startswith('end'):
            lines_out.append(s)
            continue
        lines_out.append(s)
    return ActivityData(blocks=lines_out)

def render(data: ActivityData) -> str:
    return "@startuml\n" + '\n'.join(data.blocks) + "\n@enduml"
