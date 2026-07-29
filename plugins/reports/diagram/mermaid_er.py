import re
from dataclasses import dataclass, field

@dataclass
class ERAttribute:
    type: str = ""
    name: str = ""
    constraint: str = ""

@dataclass
class EREntity:
    name: str
    attributes: list[ERAttribute] = field(default_factory=list)

@dataclass
class ERRelation:
    from_entity: str
    to_entity: str
    from_card: str = "||"
    to_card: str = "o{"
    label: str = ""

@dataclass
class ERDiagramData:
    entities: list[EREntity] = field(default_factory=list)
    relations: list[ERRelation] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*erDiagram\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

REL_PAT = re.compile(
    r'^\s*(\w[\w\d_]*)\s+'
    r'(\|[\|\|o]|\}[\|o])'
    r'(--|\.\.)'
    r'([\|o]\||[\|o]\{)'
    r'\s+(\w[\w\d_]*)'
    r'(?:\s*:\s*(.*?))?\s*$'
)

ENTITY_OPEN = re.compile(r'^\s*(\w[\w\d_]*)\s*\{?\s*$')
CLOSE_BRACE = re.compile(r'^\s*\}\s*$')
ATTR_PAT = re.compile(
    r'^\s*(\w[\w\d_]*)\s+(\w[\w\d_]*)\s*(PK|FK|UK)?\s*$'
)

def parse(raw: str) -> ERDiagramData:
    data = ERDiagramData()
    seen_entities: dict[str, EREntity] = {}
    current_entity: EREntity | None = None
    in_entity_body = False

    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            if in_entity_body:
                data.raw_lines.append('')
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue

        if in_entity_body:
            if CLOSE_BRACE.match(s):
                in_entity_body = False
                current_entity = None
                continue
            m = ATTR_PAT.match(s)
            if m and current_entity is not None:
                current_entity.attributes.append(ERAttribute(
                    type=m.group(1), name=m.group(2),
                    constraint=(m.group(3) or ''),
                ))
            else:
                data.raw_lines.append(s)
            continue

        if CLOSE_BRACE.match(s):
            continue

        m = REL_PAT.match(s)
        if m:
            from_entity, left_card, line, right_card, to_entity = \
                m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            label = (m.group(6) or '').strip()
            data.relations.append(ERRelation(
                from_entity=from_entity, to_entity=to_entity,
                from_card=left_card, to_card=right_card,
                label=label,
            ))
            for ename in (from_entity, to_entity):
                if ename not in seen_entities:
                    ent = EREntity(name=ename)
                    seen_entities[ename] = ent
                    data.entities.append(ent)
            continue

        m = ENTITY_OPEN.match(s)
        if m:
            name = m.group(1)
            if name in seen_entities:
                current_entity = seen_entities[name]
            else:
                ent = EREntity(name=name)
                seen_entities[name] = ent
                data.entities.append(ent)
                current_entity = ent
            if s.rstrip().endswith('{'):
                in_entity_body = True
            continue

        data.raw_lines.append(s)

    return data

def render(data: ERDiagramData) -> str:
    lines = ['erDiagram']

    for ent in data.entities:
        if ent.attributes:
            lines.append(f'    {ent.name} {{')
            for attr in ent.attributes:
                if attr.constraint:
                    lines.append(f'        {attr.type} {attr.name} {attr.constraint}')
                else:
                    lines.append(f'        {attr.type} {attr.name}')
            lines.append('    }')
        else:
            lines.append(f'    {ent.name}')

    for r in data.relations:
        card = f'{r.from_card}{r.to_card}'
        if r.label:
            lines.append(f'    {r.from_entity} {r.from_card}--{r.to_card} {r.to_entity} : {r.label}')
        else:
            lines.append(f'    {r.from_entity} {r.from_card}--{r.to_card} {r.to_entity}')

    for line in data.raw_lines:
        lines.append(f'    {line}')

    return '\n'.join(lines)
