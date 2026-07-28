import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="state",
    patterns=[
        (r'\bstate\b', 4),
        (r'state\s+"', 4),
        (r'\[\*\]', 3),
        (r'-->\s+\[\*\]', 2),
        (r'\bfork\b', 2),
        (r'\bhistory\b', 1),
    ],
)

@dataclass
class StateNode:
    name: str
    alias: str = ""
    kind: str = "state"
    children: list['StateNode'] = field(default_factory=list)

@dataclass
class StateTransition:
    from_name: str
    to_name: str
    label: str = ""
    arrow: str = "-->"

@dataclass
class StateData:
    title: str = ""
    nodes: list[StateNode] = field(default_factory=list)
    transitions: list[StateTransition] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

STATE_DECL_PAT = re.compile(r'^\s*state\s+"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*(?:\{)?\s*$')
STATE_DECL_SHORT_PAT = re.compile(r'^\s*state\s+(\w[\w\d_]*)\s*(?:\{)?\s*$')
TRANS_PAT = re.compile(r'^\s*(\S[\w\d_]*|\*\])\s*(-->|->)\s*(\S[\w\d_]*|\*\])(?:\s*:\s*(.*))?\s*$')
BRACKET_START_PAT = re.compile(r'^\s*\[\*\]\s*$')
BRACKET_END_PAT = re.compile(r'^\s*\[\*\]\s*$')
FORK_PAT = re.compile(r'^\s*(fork|join)\b', re.IGNORECASE)
CLOSE_BRACE = re.compile(r'^\s*\}\s*$')

def _normalize_name(s: str) -> str:
    if s == '*]':
        return '[*]'
    return s

def parse(raw: str) -> StateData:
    data = StateData()
    brace_depth = 0
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        if CLOSE_BRACE.match(s):
            brace_depth -= 1
            data.lines.append(s)
            continue
        if STATE_DECL_PAT.match(s) or STATE_DECL_SHORT_PAT.match(s):
            brace = s.rstrip().endswith('{')
            if brace:
                brace_depth += 1
            data.lines.append(s)
            continue
        if re.match(r'^\s*state\s+\w', s):
            data.lines.append(s)
            if s.rstrip().endswith('{'):
                brace_depth += 1
            continue
        if s == '{':
            brace_depth += 1
            data.lines.append(s)
            continue
        m = TRANS_PAT.match(s)
        if m:
            data.transitions.append(StateTransition(
                from_name=_normalize_name(m.group(1)),
                to_name=_normalize_name(m.group(3)),
                label=m.group(4) or '',
                arrow=m.group(2),
            ))
            data.lines.append(s)
            continue
        if FORK_PAT.match(s):
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def _trans_render(t: StateTransition) -> str:
    line = f'{t.from_name} {t.arrow} {t.to_name}'
    if t.label:
        line += f' : {t.label}'
    return line

def render(data: StateData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
