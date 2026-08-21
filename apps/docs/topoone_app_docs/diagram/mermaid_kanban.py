import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_kanban",
    patterns=[
        (r'\bkanban\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class KanbanColumn:
    name: str
    tasks: list[str] = field(default_factory=list)

@dataclass
class KanbanData:
    columns: list[KanbanColumn] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*kanban\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> KanbanData:
    data = KanbanData()
    current_col: KanbanColumn | None = None
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
        if indent < 4:
            current_col = KanbanColumn(name=stripped)
            data.columns.append(current_col)
        elif current_col is not None:
            current_col.tasks.append(stripped)
        else:
            data.raw_lines.append(s)
    return data

def render(data: KanbanData) -> str:
    lines = ['kanban']
    for col in data.columns:
        lines.append(f'    {col.name}')
        for task in col.tasks:
            lines.append(f'        {task}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
