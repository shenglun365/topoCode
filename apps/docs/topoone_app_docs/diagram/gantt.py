import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="gantt",
    patterns=[
        (r'(?:Project|project)\s+starts\b', 3),
        (r'requires\s+\d+\s+days?', 2),
        (r'starts\s+at\b', 2),
        (r'happens\s+at\b', 2),
        (r'\[.*?\]\s+requires\b', 2),
    ],
)

@dataclass
class GanttTask:
    name: str
    alias: str = ""
    duration: str = ""
    depends_on: list[str] = field(default_factory=list)
    color: str = ""

@dataclass
class GanttMilestone:
    name: str
    alias: str = ""
    time_ref: str = ""

@dataclass
class GanttData:
    title: str = ""
    start_date: str = ""
    tasks: list[GanttTask] = field(default_factory=list)
    milestones: list[GanttMilestone] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

TASK_PAT = re.compile(r'^\s*\[([^\]]+)\]\s+(?:as\s+(\w[\w\d_]*))?\s*requires\s+(.+?)$')
MILESTONE_PAT = re.compile(r'^\s*<([^>]+)>\s+(?:as\s+(\w[\w\d_]*))?\s*happens\s+at\b', re.IGNORECASE)
PROJECT_PAT = re.compile(r'^\s*(?:Project|project)\s+starts\s+(.+)$', re.IGNORECASE)
DEP_PAT = re.compile(r'^\s*\[([^\]]+)\]\s+starts\s+at\b', re.IGNORECASE)
COLOR_PAT = re.compile(r'is\s+colored\s+in\s+(#\w+)', re.IGNORECASE)
MILESTONE_ALT = re.compile(r'^\s*<([^>]+)>\s*happens\s+at\b', re.IGNORECASE)

def parse(raw: str) -> GanttData:
    data = GanttData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        m = PROJECT_PAT.match(s)
        if m:
            data.start_date = m.group(1).strip()
            data.lines.append(s)
            continue
        m = TASK_PAT.match(s)
        if m:
            name = m.group(1)
            alias = m.group(2) or name
            dur = m.group(3).strip()
            data.tasks.append(GanttTask(name=name, alias=alias, duration=dur))
            data.lines.append(s)
            continue
        m = MILESTONE_PAT.match(s)
        if m:
            name = m.group(1)
            alias = m.group(2) or name
            data.milestones.append(GanttMilestone(name=name, alias=alias))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: GanttData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
