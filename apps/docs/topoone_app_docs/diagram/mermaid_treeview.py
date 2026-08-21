import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_treeview",
    patterns=[
        (r'\btreeView-beta\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class TreeViewNode:
    name: str
    children: list['TreeViewNode'] = field(default_factory=list)
    depth: int = 0

@dataclass
class TreeViewData:
    root: TreeViewNode | None = None
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*treeView-beta\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> TreeViewData:
    data = TreeViewData()
    nodes: list[TreeViewNode] = []
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
        stripped = s.rstrip('/')
        depth = indent // 4
        name = stripped.strip()
        node = TreeViewNode(name=name, depth=depth)
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

def _render_node(node: TreeViewNode, indent: int) -> list[str]:
    lines = []
    lines.append(f'{"    " * indent}{node.name}')
    for child in node.children:
        lines.extend(_render_node(child, indent + 1))
    return lines

def render(data: TreeViewData) -> str:
    lines = ['treeView-beta']
    if data.root:
        lines.extend(_render_node(data.root, 0))
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
