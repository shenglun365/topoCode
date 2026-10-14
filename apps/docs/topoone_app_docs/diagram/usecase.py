import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="usecase",
    patterns=[
        (r'\busecase\b', 3),
        (r'\bactor\b', 2),
        (r'\([^)]+\)', 1),
        (r'\.\.>\s*.*<<include>>', 2),
        (r'\.\.>\s*.*<<extend>>', 2),
    ],
)

@dataclass
class UcElement:
    name: str
    kind: str = "actor"
    alias: str = ""

@dataclass
class UcRelation:
    from_name: str
    to_name: str
    rel_type: str = "assoc"
    arrow: str = "-->"

@dataclass
class UsecaseData:
    title: str = ""
    elements: list[UcElement] = field(default_factory=list)
    relations: list[UcRelation] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

ACTOR_PAT = re.compile(r'^\s*actor\s+"?([^"\s]+)"?\s*(?:as\s+(\w[\w\d_]*))?\s*$', re.IGNORECASE)
USECASE_PAT = re.compile(r'^\s*usecase\s+\(([^)]+)\)\s*(?:as\s+(\w[\w\d_]*))?\s*$', re.IGNORECASE)
USECASE_ALIAS_PAT = re.compile(r'^\s*\(([^)]+)\)\s*(?:as\s+(\w[\w\d_]*))?\s*$')
REL_PAT = re.compile(r'(\w[\w\d_]*|\([^)]+\))\s*(-->|\.\.>|--\|>)\s*(\w[\w\d_]*|\([^)]+\))(?:\s*:\s*(.*))?\s*$')
DIRECTION_PAT = re.compile(r'^\s*left\s+to\s+right\s+direction', re.IGNORECASE)

def parse(raw: str) -> UsecaseData:
    data = UsecaseData()
    seen_actors: set[str] = set()
    seen_usecases: set[str] = set()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        if DIRECTION_PAT.match(s):
            data.lines.append(s)
            continue
        m = ACTOR_PAT.match(s)
        if m:
            name = m.group(1)
            alias = m.group(2) or name
            if name not in seen_actors:
                data.elements.append(UcElement(name=name, kind="actor", alias=alias))
                seen_actors.add(name)
            data.lines.append(s)
            continue
        m = USECASE_PAT.match(s)
        if m:
            name = m.group(1)
            alias = m.group(2) or name
            if name not in seen_usecases:
                data.elements.append(UcElement(name=name, kind="usecase", alias=alias))
                seen_usecases.add(name)
            data.lines.append(s)
            continue
        m = USECASE_ALIAS_PAT.match(s)
        if m:
            name = m.group(1)
            alias = m.group(2) or name
            if name not in seen_usecases:
                data.elements.append(UcElement(name=name, kind="usecase", alias=alias))
                seen_usecases.add(name)
            data.lines.append(s)
            continue
        m = REL_PAT.match(s)
        if m:
            from_name = m.group(1).strip('()')
            arrow = m.group(2)
            to_name = m.group(3).strip('()')
            label = m.group(4) or ''
            rel_type = 'assoc'
            if '|>' in arrow:
                rel_type = 'generalize'
            elif '<<include>>' in label.lower():
                rel_type = 'include'
            elif '<<extend>>' in label.lower():
                rel_type = 'extend'
            data.relations.append(UcRelation(from_name=from_name, to_name=to_name, rel_type=rel_type, arrow=arrow))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: UsecaseData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
