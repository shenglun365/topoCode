import re
from dataclasses import dataclass, field

@dataclass
class TimelineEvent:
    date: str
    text: str

@dataclass
class TimelineSection:
    name: str
    events: list[TimelineEvent] = field(default_factory=list)

@dataclass
class TimelineData:
    title: str = ""
    sections: list[TimelineSection] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*timeline\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
SECTION_PAT = re.compile(r'^\s*section\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
EVENT_PAT = re.compile(r'^\s*(.+?)\s*:\s*(.+?)\s*$')

def parse(raw: str) -> TimelineData:
    data = TimelineData()
    current_section: TimelineSection = TimelineSection(name='')
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
            current_section = TimelineSection(name=m.group(1).strip())
            data.sections.append(current_section)
            continue
        m = EVENT_PAT.match(s)
        if m:
            current_section.events.append(TimelineEvent(
                date=m.group(1).strip(), text=m.group(2).strip(),
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: TimelineData) -> str:
    lines = ['timeline']
    if data.title:
        lines.append(f'    title {data.title}')
    for sec in data.sections:
        if sec.name:
            lines.append(f'    section {sec.name}')
        for ev in sec.events:
            lines.append(f'    {ev.date} : {ev.text}')
    for line in data.raw_lines:
        lines.append(f'    {line}')
    return '\n'.join(lines)
