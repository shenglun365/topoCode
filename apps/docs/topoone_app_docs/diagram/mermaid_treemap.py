import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_treemap",
    patterns=[
        (r'\btreemap\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class TreemapNode:
    name: str
    value: str = ""
    children: list['TreemapNode'] = field(default_factory=list)
    depth: int = 0

@dataclass
class TreemapData:
    root: TreemapNode | None = None
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*treemap\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> TreemapData:
    data = TreemapData()
    nodes: list[TreemapNode] = []
    for line in raw.split('\n'):
        s = line.rstrip()
        if not s.strip():
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        indent = len(s) - len(s.lstrip())
        stripped = s.strip()
        depth = indent // 4
        if ':' in stripped:
            name, _, value = stripped.partition(':')
            name = name.strip().strip('"')
            value = value.strip()
        else:
            name = stripped.strip('"')
            value = ''
        node = TreemapNode(name=name, value=value, depth=depth)
        nodes.append(node)
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

def _render_node(node: TreemapNode, indent: int) -> list[str]:
    lines = []
    name = f'"{node.name}"' if ' ' in node.name else node.name
    if node.value:
        lines.append(f'{"    " * indent}{name}: {node.value}')
    else:
        lines.append(f'{"    " * indent}{name}')
    for child in node.children:
        lines.extend(_render_node(child, indent + 1))
    return lines

def render(data: TreemapData) -> str:
    lines = ['treemap']
    if data.root:
        lines.extend(_render_node(data.root, 0))
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
