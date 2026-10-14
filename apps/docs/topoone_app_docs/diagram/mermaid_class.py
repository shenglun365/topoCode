import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_class",
    patterns=[
        (r'\bclassDiagram\b', 20),
        (r'\bclass\s+\w', 2),
        (r'\bnamespace\b', 1),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class ClassMember:
    visibility: str = ""
    name: str = ""
    params: str = ""
    type: str = ""
    is_method: bool = False
    is_static: bool = False
    is_abstract: bool = False

@dataclass
class ClassEntity:
    name: str
    stereotype: str = "class"
    members: list[ClassMember] = field(default_factory=list)

@dataclass
class ClassRelation:
    from_cls: str
    to_cls: str
    rel_type: str = "assoc"
    label: str = ""

@dataclass
class ClassDiagramData:
    title: str = ""
    classes: list[ClassEntity] = field(default_factory=list)
    relations: list[ClassRelation] = field(default_factory=list)
    raw_blocks: list[list[str]] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*classDiagram\s*$', re.IGNORECASE)
TITLE_PAT = re.compile(r'^\s*title\s+(.+?)\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
CLASS_DECL = re.compile(r'^\s*class\s+(\w[\w\d_]*)\s*\{?\s*$')
STEREOTYPE_LINE = re.compile(r'^\s*<<(.+?)>>\s*$')
NAMESPACE_OPEN = re.compile(r'^\s*namespace\s+(\w[\w\d_]*)\s*\{?\s*$', re.IGNORECASE)
CLASSDEF_PAT = re.compile(r'^\s*classDef\s+', re.IGNORECASE)
CSSCLASS_PAT = re.compile(r'^\s*cssClass\s+', re.IGNORECASE)

REL_PATTERNS = [
    (re.compile(r'(\w[\w\d_]*)\s*<\|--\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'extends'),
    (re.compile(r'(\w[\w\d_]*)\s*<\|\.\.\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'implements'),
    (re.compile(r'(\w[\w\d_]*)\s*\*--\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'compose'),
    (re.compile(r'(\w[\w\d_]*)\s*o--\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'aggregate'),
    (re.compile(r'(\w[\w\d_]*)\s*\.\.>\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'depend'),
    (re.compile(r'(\w[\w\d_]*)\s*(?:--[>-]|\.\.-)\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'assoc'),
    (re.compile(r'(\w[\w\d_]*)\s*--\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'link'),
]

def _parse_member(s: str) -> ClassMember | None:
    s = s.strip()
    if not s:
        return None
    is_static = '{static}' in s
    is_abstract = '{abstract}' in s
    s = s.replace('{static}', '').replace('{abstract}', '').strip()
    visibility = ''
    if s and s[0] in '+#~-':
        visibility = s[0]
        s = s[1:].strip()
    paren_idx = s.find('(')
    if paren_idx >= 0:
        close_idx = s.find(')', paren_idx)
        if close_idx >= 0:
            name = s[:paren_idx].strip()
            params = s[paren_idx + 1:close_idx].strip()
            rest = s[close_idx + 1:].strip()
            type_str = rest[1:].strip() if rest.startswith(':') else rest
            return ClassMember(
                visibility=visibility, name=name, params=params,
                type=type_str, is_method=True,
                is_static=is_static, is_abstract=is_abstract,
            )
    if ':' in s:
        name, _, type_str = s.partition(':')
        return ClassMember(
            visibility=visibility, name=name.strip(), type=type_str.strip(),
            is_method=False, is_static=is_static, is_abstract=is_abstract,
        )
    return ClassMember(
        visibility=visibility, name=s.strip(),
        is_method=False, is_static=is_static, is_abstract=is_abstract,
    )

def _rel_sym(rel_type: str) -> str:
    return {
        'extends': '<|--', 'implements': '<|..',
        'compose': '*--', 'aggregate': 'o--',
        'depend': '..>', 'assoc': '-->', 'link': '--',
    }.get(rel_type, '-->')

def _collect_block(lines: list[str], start_idx: int) -> tuple[list[str], int]:
    block: list[str] = []
    depth = 0
    i = start_idx
    while i < len(lines):
        s = lines[i].strip()
        block.append(lines[i])
        depth += s.count('{') - s.count('}')
        if depth <= 0:
            return block, i + 1
        i += 1
    return block, i

def _classify_raw_line(s: str) -> str:
    stripped = s.strip()
    if COMMENT_PAT.match(stripped) or REMOVE_PAT.match(stripped):
        return 'comment'
    if HEADER_PAT.match(stripped):
        return 'header'
    if TITLE_PAT.match(stripped):
        return 'title'
    if NAMESPACE_OPEN.match(stripped):
        return 'namespace'
    if CLASSDEF_PAT.match(stripped) or CSSCLASS_PAT.match(stripped):
        return 'styling'
    if STEREOTYPE_LINE.match(stripped):
        return 'stereotype'
    if CLASS_DECL.match(stripped):
        return 'class_decl'
    return 'other'

def parse(raw: str) -> ClassDiagramData:
    data = ClassDiagramData()
    seen_classes: dict[str, ClassEntity] = {}
    ns_class_names: set[str] = set()
    current_class: ClassEntity | None = None
    in_class_body = False
    lines = raw.split('\n')
    i = 0
    while i < len(lines):
        s = lines[i].strip()
        if not s:
            i += 1
            continue

        cat = _classify_raw_line(lines[i])

        if cat == 'header':
            i += 1
            continue
        if cat == 'title':
            m = TITLE_PAT.match(s)
            if m:
                data.title = m.group(1).strip().strip('"')
            i += 1
            continue
        if cat == 'namespace':
            block, i = _collect_block(lines, i)
            data.raw_blocks.append(('namespace', block))
            for line in block:
                m = CLASS_DECL.match(line.strip())
                if m:
                    ns_class_names.add(m.group(1))
            continue
        if cat in ('comment', 'styling'):
            data.raw_blocks.append(('other', [lines[i]]))
            i += 1
            continue

        if cat == 'stereotype' and not in_class_body:
            m = STEREOTYPE_LINE.match(s)
            if m and current_class is not None:
                current_class.stereotype = f'<<{m.group(1)}>>'
                i += 1
                continue
            data.raw_blocks.append(('other', [lines[i]]))
            i += 1
            continue

        if cat == 'class_decl' and not in_class_body:
            m = CLASS_DECL.match(s)
            if m:
                name = m.group(1)
                cls = ClassEntity(name=name)
                seen_classes[name] = cls
                data.classes.append(cls)
                if s.rstrip().endswith('{'):
                    in_class_body = True
                    current_class = cls
                else:
                    current_class = cls
                i += 1
                continue

        if not in_class_body:
            found_rel = False
            for pat, rtype in REL_PATTERNS:
                m = pat.match(s)
                if m:
                    cfrom, cto = m.group(1), m.group(2)
                    label = (m.group(3) or '').strip() if m.lastindex >= 3 else ''
                    data.relations.append(ClassRelation(
                        from_cls=cfrom, to_cls=cto,
                        rel_type=rtype, label=label,
                    ))
                    for cname in (cfrom, cto):
                        if cname not in seen_classes and cname not in ns_class_names:
                            cls = ClassEntity(name=cname)
                            seen_classes[cname] = cls
                            data.classes.append(cls)
                    found_rel = True
                    break
            if found_rel:
                i += 1
                continue
            if s == '}':
                i += 1
                continue
            data.raw_blocks.append(('other', [lines[i]]))
            i += 1
            continue

        if s == '}':
            if in_class_body:
                in_class_body = False
                current_class = None
            i += 1
            continue

        if STEREOTYPE_LINE.match(s) and current_class is not None:
            m = STEREOTYPE_LINE.match(s)
            current_class.stereotype = f'<<{m.group(1)}>>'
            i += 1
            continue

        member = _parse_member(s)
        if member is not None and current_class is not None:
            current_class.members.append(member)
        else:
            data.raw_blocks.append(('other', [lines[i]]))
        i += 1

    return data

def render(data: ClassDiagramData) -> str:
    lines = ['classDiagram']
    if data.title:
        lines.append(f'    title {data.title}')

    ns_blocks: list[list[str]] = []
    other_blocks: list[list[str]] = []
    for kind, block in data.raw_blocks:
        if kind == 'namespace':
            ns_blocks.append(block)
        else:
            other_blocks.append(block)

    for cls in data.classes:
        if cls.members or (cls.stereotype and cls.stereotype != 'class'):
            lines.append(f'    class {cls.name} {{')
            if cls.stereotype and cls.stereotype != 'class':
                lines.append(f'        {cls.stereotype}')
        else:
            lines.append(f'    class {cls.name}')
            continue
        for m in cls.members:
            parts = []
            if m.is_static:
                parts.append('{static}')
            if m.is_abstract:
                parts.append('{abstract}')
            parts.append(m.visibility)
            parts.append(m.name)
            if m.is_method:
                parts.append(f'({m.params})')
            if m.type:
                parts.append(f' : {m.type}')
            lines.append(f'        {"".join(parts).strip()}')
        lines.append('    }')

    for block in ns_blocks:
        for raw_line in block:
            lines.append(raw_line.rstrip())

    for r in data.relations:
        sym = _rel_sym(r.rel_type)
        if r.label:
            lines.append(f'    {r.from_cls} {sym} {r.to_cls} : {r.label}')
        else:
            lines.append(f'    {r.from_cls} {sym} {r.to_cls}')

    for block in other_blocks:
        for raw_line in block:
            lines.append(raw_line.rstrip())

    return '\n'.join(lines)
