import re
from dataclasses import dataclass, field

@dataclass
class StateNode:
    name: str
    kind: str = "state"
    children: list['StateNode'] = field(default_factory=list)
    raw_body: list[str] = field(default_factory=list)

@dataclass
class StateTransition:
    from_name: str
    to_name: str
    label: str = ""
    arrow: str = "-->"

@dataclass
class StateDiagramData:
    title: str = ""
    nodes: list[StateNode] = field(default_factory=list)
    transitions: list[StateTransition] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*stateDiagram-v2\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
TRANS_PAT = re.compile(
    r'^\s*(\[\*\]|\w[\w\d_]*)\s*(-->|->)\s*(\[\*\]|\w[\w\d_]*)(?:\s*:\s*(.*))?\s*$'
)
STATE_DECL = re.compile(r'^\s*state\s+(\w[\w\d_]*)\s*\{?\s*$', re.IGNORECASE)
STATE_DECL_QUOTED = re.compile(
    r'^\s*state\s+"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*\{?\s*$', re.IGNORECASE
)
CLOSE_BRACE = re.compile(r'^\s*\}\s*$')
FORK_PAT = re.compile(r'^\s*(fork|join)\b', re.IGNORECASE)

def parse(raw: str) -> StateDiagramData:
    data = StateDiagramData()
    current_composite: StateNode | None = None
    in_composite = False
    composite_depth = 0
    accumulating_body = False

    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            if in_composite:
                current_composite.raw_body.append('')
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

        if in_composite:
            if CLOSE_BRACE.match(s):
                composite_depth -= 1
                if composite_depth <= 0:
                    current_composite.raw_body.append(s)
                    in_composite = False
                    current_composite = None
                    accumulating_body = False
                    continue
                current_composite.raw_body.append(s)
                continue
            if re.match(r'^\s*state\s+', s, re.IGNORECASE) and s.rstrip().endswith('{'):
                composite_depth += 1
                current_composite.raw_body.append(s)
                continue
            current_composite.raw_body.append(s)
            continue

        if CLOSE_BRACE.match(s):
            continue

        m = STATE_DECL_QUOTED.match(s)
        if m:
            name = m.group(2)
            node = StateNode(name=name)
            data.nodes.append(node)
            if s.rstrip().endswith('{'):
                in_composite = True
                current_composite = node
                composite_depth = 1
                node.raw_body.append(s)
            continue

        m = STATE_DECL.match(s)
        if m:
            name = m.group(1)
            node = StateNode(name=name)
            data.nodes.append(node)
            if s.rstrip().endswith('{'):
                in_composite = True
                current_composite = node
                composite_depth = 1
                node.raw_body.append(s)
            continue

        m = TRANS_PAT.match(s)
        if m:
            data.transitions.append(StateTransition(
                from_name=m.group(1), to_name=m.group(3),
                label=(m.group(4) or '').strip(), arrow=m.group(2),
            ))
            continue

        if FORK_PAT.match(s):
            data.raw_lines.append(s)
            continue

        data.raw_lines.append(s)

    return data

def render(data: StateDiagramData) -> str:
    lines = ['stateDiagram-v2']
    if data.title:
        lines.append(f'    title {data.title}')

    for node in data.nodes:
        if node.raw_body:
            for body_line in node.raw_body:
                lines.append(f'    {body_line}')
        else:
            lines.append(f'    state {node.name}')

    for t in data.transitions:
        if t.label:
            lines.append(f'    {t.from_name} {t.arrow} {t.to_name} : {t.label}')
        else:
            lines.append(f'    {t.from_name} {t.arrow} {t.to_name}')

    for line in data.raw_lines:
        lines.append(f'    {line}')

    return '\n'.join(lines)
