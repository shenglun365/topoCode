import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="object",
    patterns=[
        (r'\bobject\b', 3),
        (r'^\w+\s*:', 1, re.MULTILINE),
    ],
)

@dataclass
class ObjInstance:
    name: str
    alias: str = ""
    fields: list[str] = field(default_factory=list)

@dataclass
class ObjRelation:
    from_name: str
    to_name: str
    label: str = ""

@dataclass
class ObjectData:
    title: str = ""
    objects: list[ObjInstance] = field(default_factory=list)
    relations: list[ObjRelation] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

OBJECT_PAT = re.compile(r'^\s*object\s+"([^"]+)"\s*(?:as\s+(\w[\w\d_]*))?\s*$', re.IGNORECASE)
OBJECT_SHORT = re.compile(r'^\s*object\s+(\w[\w\d_]*)\s*$', re.IGNORECASE)
FIELD_PAT = re.compile(r'^\s+(\w[\w\d_]*)\s*:\s*(.+)$')
REL_PAT = re.compile(r'(\w[\w\d_]*)\s*(-->|\.\.>)\s*(\w[\w\d_]*)(?:\s*:\s*(.*))?\s*$')

def parse(raw: str) -> ObjectData:
    data = ObjectData()
    for line in raw.split('\n'):
        s = line.rstrip()
        if not s:
            data.lines.append('')
            continue
        m = OBJECT_PAT.match(s) or OBJECT_SHORT.match(s)
        if m:
            name = m.group(2) if m.lastindex == 2 else m.group(1).strip('"')
            alias = m.group(2) if m.lastindex == 2 and hasattr(m, 'group') and m.group(2) else name
            data.lines.append(s)
            continue
        m = REL_PAT.match(s)
        if m:
            data.relations.append(ObjRelation(from_name=m.group(1), to_name=m.group(3), label=m.group(4) or ''))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: ObjectData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
