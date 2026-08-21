import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="deployment",
    patterns=[
        (r'\bnode\b', 3),
        (r'\bartifact\b', 3),
        (r'\bdatabase\b', 2),
        (r'\bcomponent\b', -5),
    ],
)

@dataclass
class DepElement:
    name: str
    alias: str = ""
    kind: str = "node"
    children: list['DepElement'] = field(default_factory=list)

@dataclass
class DepRelation:
    from_name: str
    to_name: str
    label: str = ""

@dataclass
class DeploymentData:
    title: str = ""
    elements: list[DepElement] = field(default_factory=list)
    relations: list[DepRelation] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

NODE_WITH_ALIAS = re.compile(r'^\s*(node|artifact|database)\s+"([^"]+)"\s+as\s+(\w[\w\d_]*)\s*(?:\{)?\s*$', re.IGNORECASE)
NODE_SHORT = re.compile(r'^\s*(node|artifact|database)\s+"([^"]+)"\s*(?:\{)?\s*$', re.IGNORECASE)
NODE_ALIAS_ONLY = re.compile(r'^\s*(node|artifact|database)\s+(\w[\w\d_]*)\s*(?:\{)?\s*$', re.IGNORECASE)
RELATION = re.compile(r'(\w[\w\d_]*)\s*(-->|\.\.>)\s*(\w[\w\d_]*)(?:\s*:\s*(.*))?\s*$')
CLOSE_BRACE = re.compile(r'^\s*\}\s*$')

def parse(raw: str) -> DeploymentData:
    data = DeploymentData()
    brace_depth = 0
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        if CLOSE_BRACE.match(s):
            brace_depth -= 1
            data.lines.append(s)
            continue
        m = NODE_WITH_ALIAS.match(s)
        if m:
            name = m.group(2)
            alias = m.group(3)
            kind = m.group(1).lower()
            has_brace = s.rstrip().endswith('{')
            if has_brace:
                brace_depth += 1
            data.elements.append(DepElement(name=name, alias=alias, kind=kind))
            data.lines.append(s)
            continue
        m = NODE_SHORT.match(s)
        if m:
            name = m.group(2)
            kind = m.group(1).lower()
            has_brace = s.rstrip().endswith('{')
            if has_brace:
                brace_depth += 1
            data.elements.append(DepElement(name=name, alias=name, kind=kind))
            data.lines.append(s)
            continue
        m = NODE_ALIAS_ONLY.match(s)
        if m:
            name = m.group(2)
            kind = m.group(1).lower()
            has_brace = s.rstrip().endswith('{')
            if has_brace:
                brace_depth += 1
            data.elements.append(DepElement(name=name, alias=name, kind=kind))
            data.lines.append(s)
            continue
        if s == '{':
            brace_depth += 1
            data.lines.append(s)
            continue
        m = RELATION.match(s)
        if m:
            data.relations.append(DepRelation(from_name=m.group(1), to_name=m.group(3), label=m.group(4) or ''))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: DeploymentData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
