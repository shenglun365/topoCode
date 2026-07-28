import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MSeqParticipant:
    name: str
    alias: str
    type: str = "participant"


@dataclass
class MSeqMessage:
    from_alias: str
    to_alias: str
    label: str
    arrow: str = "->>"


@dataclass
class MSequenceData:
    title: str = ""
    participants: list[MSeqParticipant] = field(default_factory=list)
    messages: list[MSeqMessage] = field(default_factory=list)


HEADER_PAT = re.compile(r'^\s*sequenceDiagram\s*$', re.IGNORECASE)

PARTICIPANT_AS_PAT = re.compile(
    r'^\s*(participant|actor)\s+(\w[\w\d_]*)\s+as\s+(\w[\w\d_]*)\s*$', re.IGNORECASE
)
PARTICIPANT_PAT = re.compile(
    r'^\s*(participant|actor)\s+(\w[\w\d_]*)\s*$', re.IGNORECASE
)
PARTICIPANT_QUOTED_PAT = re.compile(
    r'^\s*(participant|actor)\s+"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*$', re.IGNORECASE
)

ARROW_PAT = re.compile(
    r'^\s*(\w[\w\d_]*)\s*(->>?|--x|-x|-->?>?|-->>?)\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'
)

TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
REMOVE_PAT = re.compile(
    r"^\s*(Note\b|activate\b|deactivate\b|loop\b|alt\b|else\b|opt\b|rect\b|end\b|@startuml\b|@enduml\b)"
)


def parse(raw: str) -> MSequenceData:
    data = MSequenceData()
    alias_to_name: dict[str, str] = {}
    seen_aliases: set[str] = set()

    lines = raw.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        if not s or REMOVE_PAT.match(s):
            continue
        cleaned.append(s)

    for line in cleaned:
        m = HEADER_PAT.match(line)
        if m:
            continue

        m = TITLE_PAT.match(line)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue

        m = PARTICIPANT_QUOTED_PAT.match(line)
        if m:
            ptype = m.group(1).lower()
            name = m.group(2)
            alias = m.group(3)
            if alias not in seen_aliases:
                data.participants.append(MSeqParticipant(name=name, alias=alias, type=ptype))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = PARTICIPANT_AS_PAT.match(line)
        if m:
            ptype = m.group(1).lower()
            name = m.group(2)
            alias = m.group(3)
            if alias not in seen_aliases:
                data.participants.append(MSeqParticipant(name=name, alias=alias, type=ptype))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = PARTICIPANT_PAT.match(line)
        if m:
            ptype = m.group(1).lower()
            name = m.group(2)
            alias = name
            if alias not in seen_aliases:
                data.participants.append(MSeqParticipant(name=name, alias=alias, type=ptype))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = ARROW_PAT.match(line)
        if m:
            from_alias = m.group(1)
            arrow = m.group(2)
            to_alias = m.group(3)
            label = m.group(4) or ''
            for a in (from_alias, to_alias):
                if a not in seen_aliases:
                    data.participants.append(MSeqParticipant(name=a, alias=a))
                    alias_to_name[a] = a
                    seen_aliases.add(a)
            data.messages.append(MSeqMessage(
                from_alias=from_alias, to_alias=to_alias,
                label=label, arrow=_norm_arrow(arrow)
            ))

    return data


def _norm_arrow(raw: str) -> str:
    if raw in ('->', '-->', '->>', '-->>', '-x', '--x'):
        return raw
    if raw.startswith('--'):
        if raw.endswith('>>'):
            return '-->>'
        if raw.endswith('x'):
            return '--x'
        return '-->'
    if raw.endswith('>>'):
        return '->>'
    if raw.endswith('x'):
        return '-x'
    return '->'


def render(data: MSequenceData) -> str:
    lines = ['sequenceDiagram']
    if data.title:
        lines.append(f'    title: {data.title}')
    for p in data.participants:
        if p.alias == p.name:
            lines.append(f'    {p.type} {p.name}')
        else:
            lines.append(f'    {p.type} {p.name} as {p.alias}')
    if data.participants:
        lines.append('')
    for m in data.messages:
        msg = f'    {m.from_alias} {m.arrow} {m.to_alias}'
        if m.label:
            msg += f' : {m.label}'
        lines.append(msg)
    return '\n'.join(lines)