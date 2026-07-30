import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_gantt",
    patterns=[
        (r'\bgantt\b', 20),
        (r'\bsection\b', 1),
        (r'(\d{4}-\d{2}-\d{2}|\d+d)', 1),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class GanttTask:
    name: str
    status: str = ""
    id: str = ""
    dependency: str = ""
    duration: str = ""
    is_milestone: bool = False

@dataclass
class GanttSection:
    name: str
    tasks: list[GanttTask] = field(default_factory=list)

@dataclass
class GanttData:
    title: str = ""
    date_format: str = "YYYY-MM-DD"
    axis_format: str = ""
    sections: list[GanttSection] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*gantt\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
DATE_FORMAT_PAT = re.compile(r'^\s*dateFormat\s+(.+?)\s*$', re.IGNORECASE)
AXIS_FORMAT_PAT = re.compile(r'^\s*axisFormat\s+(.+?)\s*$', re.IGNORECASE)
SECTION_PAT = re.compile(r'^\s*section\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

TASK_PAT = re.compile(
    r'^\s*(.+?)\s*:\s*'
    r'(?:(done|active|crit|milestone)\s*,\s*)?'
    r'(\w[\w\d_]*)?\s*'
    r'(?:,\s*(after\s+\w[\w\d_]*|\d{4}-\d{2}-\d{2}))?\s*'
    r'(?:,\s*(.+?))?\s*$'
)

def parse(raw: str) -> GanttData:
    data = GanttData()
    current_section: GanttSection | None = None
    seen_ids: set[str] = set()

    for line in raw.split('\n'):
        s = line.strip()
        if not s:
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
        m = DATE_FORMAT_PAT.match(s)
        if m:
            data.date_format = m.group(1).strip()
            continue
        m = AXIS_FORMAT_PAT.match(s)
        if m:
            data.axis_format = m.group(1).strip()
            continue
        m = SECTION_PAT.match(s)
        if m:
            current_section = GanttSection(name=m.group(1).strip())
            data.sections.append(current_section)
            continue

        m = TASK_PAT.match(s)
        if m:
            task_name = m.group(1).strip()
            task_status = (m.group(2) or '').lower()
            task_id = m.group(3) or ''
            task_dep = m.group(4) or ''
            task_dur = m.group(5) or ''
            is_milestone = task_status == 'milestone' or (task_dur == '0d')
            if task_id and task_id not in seen_ids:
                seen_ids.add(task_id)
            task = GanttTask(
                name=task_name, status=task_status,
                id=task_id, dependency=task_dep,
                duration=task_dur, is_milestone=is_milestone,
            )
            if current_section is not None:
                current_section.tasks.append(task)
            else:
                sec = GanttSection(name='')
                sec.tasks.append(task)
                data.sections.append(sec)
                current_section = sec
            continue

        data.raw_lines.append(s)

    return data

def render(data: GanttData) -> str:
    lines = ['gantt']
    if data.title:
        lines.append(f'    title {data.title}')
    if data.date_format:
        lines.append(f'    dateFormat {data.date_format}')
    if data.axis_format:
        lines.append(f'    axisFormat {data.axis_format}')

    for sec in data.sections:
        if sec.name:
            lines.append(f'    section {sec.name}')
        for task in sec.tasks:
            parts = [f'    {task.name} :']
            if task.status:
                parts[0] += task.status
                if task.id:
                    parts[0] += f', {task.id}'
            elif task.id:
                parts[0] += task.id

            if task.dependency:
                if task.status or task.id:
                    parts[0] += f', {task.dependency}'
                else:
                    parts[0] += f' {task.dependency}'
            if task.duration:
                if task.status or task.id or task.dependency:
                    parts[0] += f', {task.duration}'
                else:
                    parts[0] += f' {task.duration}'
            lines.append(parts[0])

    for line in data.raw_lines:
        lines.append(f'{line}')

    return '\n'.join(lines)
