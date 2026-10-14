import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="wbs", start_marker="@startwbs", end_marker="@endwbs",
    parser_type="tree", patterns=[(r'@startwbs\b', 5), (r'^\s*\*\*+\s+\S', 2, re.MULTILINE)],
    supports_skinparam=False, supports_preproc=False, supports_layout=False,
    min_score=3,
)

@dataclass
class WbsNode:
    text: str
    level: int
    children: list['WbsNode'] = field(default_factory=list)

@dataclass
class WbsData:
    title: str = ""
    root: WbsNode = field(default_factory=lambda: WbsNode(text="", level=0))

LINE_PAT = re.compile(r'^(\s*\*+)\s*(.*)$')

def parse(raw: str) -> WbsData:
    root = WbsNode(text="(root)", level=-1)
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
        node = WbsNode(text=text, level=level)
        while stack and stack[-1].level >= level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        stack.append(node)
    if root.children:
        root = root.children[0]
        root.level = 1
    return WbsData(root=root)

def _render_node(n: WbsNode, indent: int = 0) -> list[str]:
    prefix = '  ' * indent + '*' * n.level
    lines = [f'{prefix} {n.text}']
    for c in n.children:
        lines.extend(_render_node(c, indent + 1))
    return lines

def make_data(text: str) -> WbsData:
    return parse(text)

def render(data: WbsData) -> str:
    lines = ['@startwbs']
    lines.extend(_render_node(data.root))
    lines.append('@endwbs')
    return '\n'.join(lines)
