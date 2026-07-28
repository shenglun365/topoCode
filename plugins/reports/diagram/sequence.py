import re
from dataclasses import dataclass, field
from typing import Optional
from ._meta import ParserMeta


meta = ParserMeta(
    name="sequence",
    patterns=[
        (r'\bparticipant\b', 3),
        (r'\bactor\b', 3),
        (r'\w+\s*-+[->]\s*\w+\s*:', 2),
        (r'\w+\s*-+[->]\s*\w+\s*$', 1),
        (r'\bactivate\b', 1),
        (r'\bdeactivate\b', 1),
    ],
)


@dataclass
class SeqParticipant:
    name: str
    alias: str
    type: str = "participant"


@dataclass
class SeqMessage:
    from_alias: str
    to_alias: str
    label: str
    arrow: str = "->"
    activate: bool = False
    deactivate: bool = False


@dataclass
class SequenceData:
    title: str = ""
    participants: list[SeqParticipant] = field(default_factory=list)
    messages: list[SeqMessage] = field(default_factory=list)


ARROW_PAT = re.compile(
    r'^\s*(\w[\w\d_]*)\s*(<-+[>-]?|-+[->][>-]?)\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'
)
PARTICIPANT_PAT = re.compile(
    r'^\s*(participant|actor|boundary|control|entity|database)\s+'
    r'"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*$',
    re.IGNORECASE
)
PARTICIPANT_SHORT_PAT = re.compile(
    r'^\s*(participant|actor|boundary|control|entity|database)\s+'
    r'"?([^"\s]+)"?\s*$',
    re.IGNORECASE
)
TITLE_PAT = re.compile(r'^\s*title\s+(.+)$', re.IGNORECASE)
ACTIVATE_PAT = re.compile(r'^\s*activate\s+(\w[\w\d_]*)')
DEACTIVATE_PAT = re.compile(r'^\s*deactivate\s+(\w[\w\d_]*)')
REMOVE_PAT = re.compile(r"^\s*('|autonumber\b|skinparam\b|@startuml\b|@enduml\b)")


def _strip_line(line: str) -> Optional[str]:
    s = line.strip()
    if not s or REMOVE_PAT.match(s):
        return None
    return s


def parse(raw: str) -> SequenceData:
    data = SequenceData()
    alias_to_name: dict[str, str] = {}
    seen_aliases: set[str] = set()

    lines = raw.split('\n')
    cleaned = []
    for line in lines:
        stripped = _strip_line(line)
        if stripped is not None:
            cleaned.append(stripped)

    # pass 1: title, participants, activate/deactivate
    for line in cleaned:
        m = TITLE_PAT.match(line)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue
        m = PARTICIPANT_PAT.match(line)
        if m:
            name = m.group(2)
            alias = m.group(3)
            ptype = m.group(1).lower()
            if alias not in seen_aliases:
                data.participants.append(SeqParticipant(name=name, alias=alias, type=ptype))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue
        m = PARTICIPANT_SHORT_PAT.match(line)
        if m:
            name = m.group(2)
            alias = name
            ptype = m.group(1).lower()
            if alias not in seen_aliases:
                data.participants.append(SeqParticipant(name=name, alias=alias, type=ptype))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

    # pass 2: arrows (messages), collect implied participants, activate/deactivate
    current_activate: set[str] = set()
    for line in cleaned:
        # activate/deactivate standalone lines
        m = ACTIVATE_PAT.match(line)
        if m:
            current_activate.add(m.group(1))
            continue
        m = DEACTIVATE_PAT.match(line)
        if m:
            current_activate.discard(m.group(1))
            continue
        # arrow line
        m = ARROW_PAT.match(line)
        if m:
            from_alias = m.group(1)
            arrow = m.group(2)
            to_alias = m.group(3)
            label = m.group(4) or ''
            is_activate = from_alias in current_activate
            current_activate.discard(from_alias)
            # collect implied participants
            for a in (from_alias, to_alias):
                if a not in seen_aliases:
                    data.participants.append(SeqParticipant(name=a, alias=a))
                    alias_to_name[a] = a
                    seen_aliases.add(a)
            data.messages.append(SeqMessage(
                from_alias=from_alias,
                to_alias=to_alias,
                label=label,
                arrow=_normalize_arrow(arrow),
                activate=is_activate,
            ))

    return data


def _normalize_arrow(raw: str) -> str:
    if raw.startswith('<-'):
        if raw == '<<--' or raw == '<<-':
            return '<<--'
        if '--' in raw or raw.count('-') > 1:
            return '<--'
        if '#' in raw:
            return '<-#'
        return '<-'
    else:
        if raw.startswith('->>') or raw.startswith('-->>'):
            return '->>'
        if raw.startswith('-#'):
            return '-#'
        if '--' in raw or raw.count('-') > 1:
            return '-->'
        if '#' in raw:
            return '-#'
        return '->'


def render(data: SequenceData) -> str:
    lines = ['@startuml']
    if data.title:
        lines.append(f'title {data.title}')
        lines.append('')
    for p in data.participants:
        if p.alias == p.name:
            lines.append(f'{p.type} {p.name}')
        else:
            lines.append(f'{p.type} "{p.name}" as {p.alias}')
    if data.participants:
        lines.append('')
    for m in data.messages:
        if m.activate:
            lines.append(f'activate {m.from_alias}')
        msg_line = f'{m.from_alias} {m.arrow} {m.to_alias}'
        if m.label:
            msg_line += f' : {m.label}'
        if m.deactivate:
            if m.label:
                lines.append(msg_line)
            else:
                lines.append(msg_line)
            lines.append(f'deactivate {m.to_alias}')
        else:
            lines.append(msg_line)
    lines.append('@enduml')
    return '\n'.join(lines)