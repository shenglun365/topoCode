import re
from dataclasses import dataclass, field
from typing import Optional
from ._meta import ParserMeta


meta = ParserMeta(
    name="component",
    patterns=[
        (r'\bcomponent\b', 3),
        (r'\[[a-zA-Z\u4e00-\u9fff][^\]]*\]', 2),
        (r'\bpackage\b', 1),
        (r'\brectangle\b', 1),
    ],
)


@dataclass
class CompEntity:
    name: str
    alias: str
    description: str = ""


@dataclass
class CompRelation:
    from_alias: str
    to_alias: str
    label: str = ""
    arrow: str = "-->"


@dataclass
class ComponentData:
    title: str = ""
    entities: list[CompEntity] = field(default_factory=list)
    relations: list[CompRelation] = field(default_factory=list)


ENTITY_DECL_PAT = re.compile(
    r'^\s*component\s+"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*$'
)
ENTITY_DECL_WITH_DESC_PAT = re.compile(
    r'^\s*component\s+"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*:\s*(.+?)\s*$'
)
BRACKET_AS_PAT = re.compile(
    r'^\s*\[([^\]]+)\]\s+as\s+(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'
)
BRACKET_PAT = re.compile(
    r'^\s*\[([^\]]+)\]\s*$'
)
RELATION_PAT = re.compile(
    r'^\s*(\w[\w\d_]*)\s*(--[>-]|\.\.[>-])\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'
)
TITLE_PAT = re.compile(r'^\s*title\s+(.+)$', re.IGNORECASE)
REMOVE_PAT = re.compile(
    r"^\s*('|autonumber\b|skinparam\b|@startuml\b|@enduml\b|package\b|rectangle\b|folder\b)"
)


def _strip_line(line: str) -> Optional[str]:
    s = line.strip()
    if not s or REMOVE_PAT.match(s):
        return None
    return s


def parse(raw: str) -> ComponentData:
    data = ComponentData()
    alias_to_name: dict[str, str] = {}
    seen_aliases: set[str] = set()

    lines = raw.split('\n')
    cleaned = []
    for line in lines:
        stripped = _strip_line(line)
        if stripped is not None:
            cleaned.append(stripped)

    for line in cleaned:
        m = TITLE_PAT.match(line)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue

        m = ENTITY_DECL_WITH_DESC_PAT.match(line)
        if m:
            name = m.group(1)
            alias = m.group(2)
            desc = m.group(3).strip()
            if alias not in seen_aliases:
                data.entities.append(CompEntity(name=name, alias=alias, description=desc))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = ENTITY_DECL_PAT.match(line)
        if m:
            name = m.group(1)
            alias = m.group(2)
            if alias not in seen_aliases:
                data.entities.append(CompEntity(name=name, alias=alias))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = BRACKET_AS_PAT.match(line)
        if m:
            name = m.group(1)
            alias = m.group(2)
            desc = (m.group(3) or '').strip()
            if alias not in seen_aliases:
                data.entities.append(CompEntity(name=name, alias=alias, description=desc))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = BRACKET_PAT.match(line)
        if m:
            name = m.group(1)
            alias = re.sub(r'[^a-zA-Z0-9_]', '_', name)
            if alias not in seen_aliases:
                data.entities.append(CompEntity(name=name, alias=alias))
                alias_to_name[alias] = name
                seen_aliases.add(alias)
            continue

        m = RELATION_PAT.match(line)
        if m:
            from_alias = m.group(1)
            arrow = m.group(2)
            to_alias = m.group(3)
            label = (m.group(4) or '').strip()
            # ensure implied entities exist
            for a, n in [(from_alias, from_alias), (to_alias, to_alias)]:
                if a not in seen_aliases:
                    data.entities.append(CompEntity(name=n, alias=a))
                    alias_to_name[a] = n
                    seen_aliases.add(a)
            data.relations.append(CompRelation(
                from_alias=from_alias,
                to_alias=to_alias,
                label=label,
                arrow=arrow,
            ))

    return data


def render(data: ComponentData) -> str:
    lines = ['@startuml']
    if data.title:
        lines.append(f'title {data.title}')
        lines.append('')
    for e in data.entities:
        if e.description:
            lines.append(f'component "{e.name}" as {e.alias} : {e.description}')
        else:
            lines.append(f'component "{e.name}" as {e.alias}')
    if data.entities:
        lines.append('')
    for r in data.relations:
        line = f'{r.from_alias} {r.arrow} {r.to_alias}'
        if r.label:
            line += f' : {r.label}'
        lines.append(line)
    lines.append('@enduml')
    return '\n'.join(lines)