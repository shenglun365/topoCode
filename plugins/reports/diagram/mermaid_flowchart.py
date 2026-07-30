import re
from dataclasses import dataclass, field



from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_flowchart",
    patterns=[
        (r'\bgraph\s+(TB|TD|LR|RL|BT)\b', 20),
        (r'--[>-]', 1),
        (r'[\[\(\{][^\]\)\}]*[\]\)\}]', 1),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class FlowNode:
    id: str
    text: str
    shape: str = "rect"


@dataclass
class FlowEdge:
    from_id: str
    to_id: str
    label: str = ""
    style: str = "arrow"


@dataclass
class FlowchartData:
    title: str = ""
    direction: str = "TB"
    nodes: list[FlowNode] = field(default_factory=list)
    edges: list[FlowEdge] = field(default_factory=list)


GRAPH_PAT = re.compile(r'^\s*graph\s+(TB|TD|LR|RL|BT)\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
REMOVE_PAT = re.compile(r"^\s*(%|%%|@startuml\b|@enduml\b)")

INLINE_NODE = re.compile(
    r'(\w[\w\d_]*)\s*(?:\(\(([^)]*)\)\)|\(([^)]+)\)|\(\[([^\]]*)\]\)|\{([^}]*)\}|\[([^\]]*)\])'
)


def _extract_nodes(text: str) -> dict[str, tuple[str, str]]:
    rv: dict[str, tuple[str, str]] = {}
    for m in INLINE_NODE.finditer(text):
        nid = m.group(1)
        content = m.group(2) or m.group(3) or m.group(4) or m.group(5) or m.group(6) or ''
        shape = 'rect'
        if m.group(2) is not None:
            shape = 'circle'    # ((text))
        elif m.group(3) is not None:
            shape = 'round'     # (text)
        elif m.group(4) is not None:
            shape = 'stadium'   # ([text])
        elif m.group(5) is not None:
            shape = 'diamond'   # {text}
        if nid not in rv:
            rv[nid] = (content.strip() or nid, shape)
    return rv


EDGE_PAT = re.compile(
    r'(\w[\w\d_]*).*?(-->|==>|-\.->|---?)\s*(?:\|(.+?)\|)?\s*(\w[\w\d_]*)'
)


def parse(raw: str) -> FlowchartData:
    data = FlowchartData()
    node_map: dict[str, FlowNode] = {}
    edges: list[FlowEdge] = []

    for line in raw.split('\n'):
        s = line.strip()
        if not s or REMOVE_PAT.match(s):
            continue

        m = GRAPH_PAT.match(s)
        if m:
            data.direction = m.group(1).upper().replace('TD', 'TB')
            continue
        m = TITLE_PAT.match(s)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue

        inline = _extract_nodes(s)
        for nid, (text, shape) in inline.items():
            if nid not in node_map:
                node_map[nid] = FlowNode(id=nid, text=text, shape=shape)

        m = EDGE_PAT.search(s)
        if m:
            from_id = m.group(1)
            sym = m.group(2)
            label = (m.group(3) or '').strip()
            to_id = m.group(4)
            for nid in (from_id, to_id):
                if nid not in node_map:
                    node_map[nid] = FlowNode(id=nid, text=nid)
            edges.append(FlowEdge(
                from_id=from_id, to_id=to_id, label=label, style=_edge_style(sym)
            ))

    data.nodes = list(node_map.values())
    data.edges = edges
    return data


def _edge_style(sym: str) -> str:
    if sym == '==>':
        return 'thick'
    if sym == '-.->':
        return 'dotted'
    if sym in ('---', '----'):
        return 'line'
    return 'arrow'


def _shape_sym(shape: str) -> tuple[str, str]:
    return {
        'round': ('(', ')'),
        'diamond': ('{', '}'),
        'circle': ('((', '))'),
        'stadium': ('([', '])'),
    }.get(shape, ('[', ']'))


def render(data: FlowchartData) -> str:
    lines = [f'graph {data.direction}']
    for n in data.nodes:
        l, r = _shape_sym(n.shape)
        lines.append(f'    {n.id}{l}{n.text}{r}')
    for e in data.edges:
        sym = {'line': '---', 'thick': '===', 'dotted': '-.->'}.get(e.style, '-->')
        if e.label:
            lines.append(f'    {e.from_id} {sym}|{e.label}| {e.to_id}')
        else:
            lines.append(f'    {e.from_id} {sym} {e.to_id}')
    return '\n'.join(lines)