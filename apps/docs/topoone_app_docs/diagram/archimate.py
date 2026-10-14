import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="archimate",
    patterns=[
        (r'\barchimate\b', 5),
        (r'#Business\b', 3),
        (r'#Application\b', 3),
        (r'#Technology\b', 3),
    ],
)

@dataclass
class ArchiElement:
    name: str
    alias: str
    layer: str = "Business"

@dataclass
class ArchiRelation:
    from_alias: str
    to_alias: str
    label: str = ""

@dataclass
class ArchimateData:
    title: str = ""
    elements: list[ArchiElement] = field(default_factory=list)
    relations: list[ArchiRelation] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

ARCHI_PAT = re.compile(r'^\s*archimate\s+(#\w+)?\s*"?([^"]+)"?\s+as\s+(\w[\w\d_]*)\s*$', re.IGNORECASE)
REL_PAT = re.compile(r'(\w[\w\d_]*)\s*(-->|\.\.>)\s*(\w[\w\d_]*)(?:\s*:\s*(.*))?\s*$')

def parse(raw: str) -> ArchimateData:
    data = ArchimateData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        m = ARCHI_PAT.match(s)
        if m:
            layer = m.group(1) or '#Business'
            name = m.group(2)
            alias = m.group(3)
            data.elements.append(ArchiElement(name=name, alias=alias, layer=layer))
            data.lines.append(s)
            continue
        m = REL_PAT.match(s)
        if m:
            data.relations.append(ArchiRelation(from_alias=m.group(1), to_alias=m.group(3), label=m.group(4) or ''))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: ArchimateData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
