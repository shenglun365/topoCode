import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_journey",
    patterns=[
        (r'\bjourney\b', 20),
        (r'\d+\s*:\s*\w+', 1),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class JourneyTask:
    name: str
    score: str = "5"
    actors: list[str] = field(default_factory=list)

@dataclass
class JourneySection:
    name: str
    tasks: list[JourneyTask] = field(default_factory=list)

@dataclass
class JourneyData:
    title: str = ""
    sections: list[JourneySection] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*journey\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
SECTION_PAT = re.compile(r'^\s*section\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
TASK_PAT = re.compile(
    r'^\s*(.+?)\s*:\s*(\d+)\s*:\s*(.+?)\s*$'
)

def parse(raw: str) -> JourneyData:
    data = JourneyData()
    current_section: JourneySection = JourneySection(name='')
    data.sections.append(current_section)
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
        m = SECTION_PAT.match(s)
        if m:
            current_section = JourneySection(name=m.group(1).strip())
            data.sections.append(current_section)
            continue
        m = TASK_PAT.match(s)
        if m:
            name = m.group(1).strip()
            score = m.group(2).strip()
            actors_raw = m.group(3).strip()
            actors = [a.strip() for a in actors_raw.split(',') if a.strip()]
            current_section.tasks.append(JourneyTask(
                name=name, score=score, actors=actors,
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: JourneyData) -> str:
    lines = ['journey']
    if data.title:
        lines.append(f'    title {data.title}')
    for sec in data.sections:
        if sec.name:
            lines.append(f'    section {sec.name}')
        for task in sec.tasks:
            actor_str = ', '.join(task.actors) if task.actors else ''
            if actor_str:
                lines.append(f'    {task.name}: {task.score}: {actor_str}')
            else:
                lines.append(f'    {task.name}: {task.score}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
