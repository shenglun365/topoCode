import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="mindmap", start_marker="@startmindmap", end_marker="@endmindmap",
    parser_type="tree", patterns=[(r'@startmindmap\b', 5), (r'^\s*\*\*+\s+\S', 2, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class MmNode:
    text: str
    level: int
    children: list['MmNode'] = field(default_factory=list)

@dataclass
class MindmapData:
    title: str = ""
    root: MmNode = field(default_factory=lambda: MmNode(text="", level=0))

LINE_PAT = re.compile(r'^(\s*\*+)\s*(.*)$')

def parse(raw: str) -> MindmapData:
    root = MmNode(text="(root)", level=-1)
    stack = [root]
    for line in raw.split('\n'):
        s = line.strip()
        if not s or s.startswith('@') or s.startswith("'"):
            continue
        m = LINE_PAT.match(s)
        if not m:
            continue
        stars = m.group(1).rstrip()
        text = m.group(2).strip()
        level = len(stars.replace(' ', ''))
        node = MmNode(text=text, level=level)
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        stack.append(node)
    if root.children:
        root = root.children[0]
        root.level = 1
    return MindmapData(root=root)

def _render_node(n: MmNode, indent: int = 0) -> list[str]:
    prefix = '  ' * indent + '*' * n.level
    lines = [f'{prefix} {n.text}']
    for c in n.children:
        lines.extend(_render_node(c, indent + 1))
    return lines

def make_data(text: str) -> MindmapData:
    return parse(text)

def render(data: MindmapData) -> str:
    lines = ['@startmindmap']
    lines.extend(_render_node(data.root))
    lines.append('@endmindmap')
    return '\n'.join(lines)
