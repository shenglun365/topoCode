import re
from dataclasses import dataclass, field
from typing import Optional


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_requirement",
    patterns=[
        (r'\brequirementDiagram\b', 20),
        (r'\brequirement\b', 2),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class ReqBlock:
    kind: str = "requirement"
    name: str = ""
    id: str = ""
    text: str = ""
    risk: str = ""
    verify_method: str = ""
    type: str = ""

@dataclass
class ReqRelation:
    from_name: str
    to_name: str
    rel_type: str = "satisfies"

@dataclass
class RequirementData:
    blocks: list[ReqBlock] = field(default_factory=list)
    relations: list[ReqRelation] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*requirementDiagram\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

BLOCK_OPEN = re.compile(
    r'^\s*(requirement|functionalRequirement|element)\s+(\w[\w\d_]*)\s*\{?\s*$',
    re.IGNORECASE,
)
BLOCK_PROP = re.compile(r'^\s*(\w+)\s*:\s*(.+?)\s*$')
CLOSE_BRACE = re.compile(r'^\s*\}\s*$')
REL_PAT = re.compile(
    r'^\s*(\w[\w\d_]*)\s*-\s*(satisfies|contains|derives|traces|verifies|refines)\s*->\s*(\w[\w\d_]*)\s*$',
    re.IGNORECASE,
)

def parse(raw: str) -> RequirementData:
    data = RequirementData()
    current_block: ReqBlock | None = None
    in_block = False
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        if in_block:
            if CLOSE_BRACE.match(s):
                in_block = False
                current_block = None
                continue
            m = BLOCK_PROP.match(s)
            if m:
                key = m.group(1).lower()
                val = m.group(2).strip().strip('"')
                if current_block:
                    if key == 'id':
                        current_block.id = val
                    elif key == 'text':
                        current_block.text = val
                    elif key == 'risk':
                        current_block.risk = val
                    elif key == 'verifymethod':
                        current_block.verify_method = val
                    elif key == 'type' and current_block.kind == 'element':
                        current_block.type = val
                continue
            data.raw_lines.append(s)
            continue
        if CLOSE_BRACE.match(s):
            continue
        m = BLOCK_OPEN.match(s)
        if m:
            current_block = ReqBlock(kind=m.group(1).lower(), name=m.group(2))
            data.blocks.append(current_block)
            in_block = True
            continue
        m = REL_PAT.match(s)
        if m:
            data.relations.append(ReqRelation(
                from_name=m.group(1), to_name=m.group(3),
                rel_type=m.group(2).lower(),
            ))
            continue
        data.raw_lines.append(s)
    return data

def render(data: RequirementData) -> str:
    lines = ['requirementDiagram']
    for block in data.blocks:
        lines.append(f'    {block.kind} {block.name} {{')
        if block.id:
            lines.append(f'    id: {block.id}')
        if block.text:
            lines.append(f'    text: {block.text}')
        if block.risk:
            lines.append(f'    risk: {block.risk}')
        if block.verify_method:
            lines.append(f'    verifymethod: {block.verify_method}')
        if block.type:
            lines.append(f'    type: {block.type}')
        lines.append('    }')
    for r in data.relations:
        lines.append(f'    {r.from_name} - {r.rel_type} -> {r.to_name}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
