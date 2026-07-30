import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_mindmap",
    patterns=[
        (r'\bmindmap\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class MindmapNode:
    text: str
    shape: str = ""
    icon: str = ""
    css_class: str = ""
    children: list['MindmapNode'] = field(default_factory=list)
    depth: int = 0

@dataclass
class MindmapData:
    root: MindmapNode | None = None
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*mindmap\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

SIMPLE_TEXT = re.compile(r'^\s*(\S[\S ]*?)\s*(?:::icon\(([^)]*)\))?(?:::(.+))?\s*$')
SHAPE_MAP: list[tuple[re.Pattern, str]] = [
    (re.compile(r'\(\(\(([^)]*)\)\)\)'), 'double_circle'),
    (re.compile(r'\(\(([^)]*)\)\)'), 'circle'),
    (re.compile(r'\(([^)]*)\)'), 'round'),
    (re.compile(r'\{\{([^}]*)}}'), 'hexagon'),
    (re.compile(r'\[([^\]]*)\]'), 'rect'),
]

def _parse_node(s: str, depth: int) -> MindmapNode | None:
    for pat, shape in SHAPE_MAP:
        m = pat.search(s)
        if m:
            content = m.group(1)
            rest = s[m.end():]
            icon_m = re.search(r'::icon\(([^)]*)\)', rest)
            css_m = re.search(r'::(\w+)', rest)
            return MindmapNode(
                text=content.strip(), shape=shape,
                icon=icon_m.group(1) if icon_m else '',
                css_class=css_m.group(1) if css_m else '',
                depth=depth,
            )
    m = SIMPLE_TEXT.match(s)
    if m:
        return MindmapNode(
            text=m.group(1).strip(), shape='',
            icon=m.group(2) or '', css_class=m.group(3) or '',
            depth=depth,
        )
    return None

def parse(raw: str) -> MindmapData:
    data = MindmapData()
    nodes: list[MindmapNode] = []
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        indent = len(line) - len(line.lstrip())
        depth = indent // 2
        node = _parse_node(s, depth)
        if node:
            nodes.append(node)
        else:
            data.raw_lines.append(s)
    if nodes:
        data.root = nodes[0]
        stack = [data.root]
        for node in nodes[1:]:
            while stack and stack[-1].depth >= node.depth:
                stack.pop()
            if stack:
                stack[-1].children.append(node)
            stack.append(node)
    return data

def _render_node(node: MindmapNode, indent: int) -> list[str]:
    lines = []
    shape_map = {
        'rect': ('[', ']'), 'round': ('(', ')'),
        'circle': ('((', '))'), 'double_circle': ('(((', ')))'),
        'hexagon': ('{{', '}}'),
    }
    shape_pair = shape_map.get(node.shape)
    if shape_pair and node.shape != 'rect':
        l, r = shape_pair
        text = f'{l}{node.text}{r}'
    else:
        text = node.text
    suffix = ''
    if node.icon:
        suffix += f' ::icon({node.icon})'
    if node.css_class:
        suffix += f' :::{node.css_class}'
    lines.append(f'{"  " * indent}{text}{suffix}')
    for child in node.children:
        lines.extend(_render_node(child, indent + 1))
    return lines

def render(data: MindmapData) -> str:
    lines = ['mindmap']
    if data.root:
        lines.extend(_render_node(data.root, 0))
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
