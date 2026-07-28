import re
from dataclasses import dataclass, field
from ._meta import ParserMeta


meta = ParserMeta(
    name="class",
    patterns=[
        (r'\bclass\b', 3),
        (r'\binterface\b', 2),
        (r'\babstract\b', 1),
        (r'\benum\b', 1),
    ],
)


@dataclass
class ClassMember:
    visibility: str = ""    # + - # ~
    name: str = ""
    type: str = ""
    is_method: bool = False
    params: str = ""
    is_static: bool = False
    is_abstract: bool = False


@dataclass
class ClassEntity:
    name: str
    stereotype: str = "class"   # class | interface | abstract | enum
    members: list[ClassMember] = field(default_factory=list)


@dataclass
class ClassRelation:
    from_cls: str
    to_cls: str
    rel_type: str = "assoc"   # extends | implements | compose | aggregate | assoc | depend
    label: str = ""


@dataclass
class ClassData:
    title: str = ""
    classes: list[ClassEntity] = field(default_factory=list)
    relations: list[ClassRelation] = field(default_factory=list)


TITLE_PAT = re.compile(r'^\s*title\s+(.+)$', re.IGNORECASE)
REMOVE_PAT = re.compile(
    r"^\s*('|autonumber\b|skinparam\b|hide\b|show\b|@startuml\b|@enduml\b)"
)

# class / interface / abstract class / enum declarations
CLASS_DECL = re.compile(
    r'^\s*(class|interface|abstract\s+class|enum)\s+(\w[\w\d_]*)\s*'
)

# Member line: [+-#~] name : type
# or: [+-#~] name(params) : type
# with optional {static} {abstract}
MEMBER_LINE = re.compile(
    r'^\s*(\{static\}\s*|\{abstract\}\s*)*'
    r'([+#~-])?\s*'
    r'(\w[\w\d_]*)\s*'
    r'(?:\(([^)]*)\))?\s*'
    r'(?::\s*(.+))?\s*$'
)

# Relation patterns
REL_PATTERNS = [
    (re.compile(r'(\w[\w\d_]*)\s*--\|>\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'extends'),
    (re.compile(r'(\w[\w\d_]*)\s*\.\.\|>\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'implements'),
    (re.compile(r'(\w[\w\d_]*)\s*\*--\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'compose'),
    (re.compile(r'(\w[\w\d_]*)\s*o--\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'aggregate'),
    (re.compile(r'(\w[\w\d_]*)\s*\.\.>\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'depend'),
    (re.compile(r'(\w[\w\d_]*)\s*(--[>-]|\.\.-)\s*(\w[\w\d_]*)\s*(?::\s*(.*?))?\s*$'), 'assoc'),
]


def parse(raw: str) -> ClassData:
    data = ClassData()
    current_cls: ClassEntity | None = None
    brace_depth = 0

    for line in raw.split('\n'):
        s = line.strip()
        if not s or REMOVE_PAT.match(s):
            continue

        m = TITLE_PAT.match(s)
        if m:
            data.title = m.group(1).strip().strip('"')
            continue

        # Track braces for class bodies
        if brace_depth > 0:
            if s == '}':
                brace_depth -= 1
                if brace_depth == 0:
                    current_cls = None
                continue

        m = CLASS_DECL.match(s)
        if m:
            raw_stereo = m.group(1).lower()
            name = m.group(2)
            if 'abstract' in raw_stereo:
                stereo = 'abstract'
            elif raw_stereo == 'interface':
                stereo = 'interface'
            elif raw_stereo == 'enum':
                stereo = 'enum'
            else:
                stereo = 'class'
            current_cls = ClassEntity(name=name, stereotype=stereo)
            data.classes.append(current_cls)
            # Check if '{' on same line or next
            rest = s[m.end():].strip()
            if rest.startswith('{'):
                brace_depth = 1
                body = rest[1:].strip()
                if body:
                    if body.endswith('}'):
                        brace_depth = 0
                        current_cls = None
            elif '{' in rest:
                brace_depth = 1
            continue

        if s == '{':
            brace_depth = 1
            continue

        # Inside a class body
        if current_cls is not None:
            mm = MEMBER_LINE.match(s)
            if mm:
                is_static = bool(mm.group(1) and '{static}' in mm.group(1))
                is_abstract = bool(mm.group(1) and '{abstract}' in mm.group(1))
                visibility = mm.group(2) or ''
                member_name = mm.group(3)
                params = mm.group(4) or ''
                member_type = (mm.group(5) or '').strip()

                is_method = bool(params is not None and mm.group(4) is not None)
                current_cls.members.append(ClassMember(
                    visibility=visibility,
                    name=member_name,
                    type=member_type,
                    is_method=is_method,
                    params=params or '',
                    is_static=is_static,
                    is_abstract=is_abstract,
                ))
                continue

        # Relation
        for pat, rel_type in REL_PATTERNS:
            m = pat.match(s)
            if m:
                from_cls = m.group(1)
                n = len(m.groups())
                if n >= 4:
                    to_cls = m.group(3)
                    label = (m.group(4) or '').strip()
                else:
                    to_cls = m.group(2)
                    label = (m.group(3) or '').strip()
                data.relations.append(ClassRelation(
                    from_cls=from_cls, to_cls=to_cls,
                    rel_type=rel_type, label=label,
                ))
                break

    return data


def _render_visibility(v: str) -> str:
    return v if v in ('+', '-', '#', '~') else ''


def render(data: ClassData) -> str:
    lines = ['@startuml']
    if data.title:
        lines.append(f'title {data.title}')
        lines.append('')
    for c in data.classes:
        if c.stereotype == 'interface':
            lines.append(f'interface {c.name} {{')
        elif c.stereotype == 'abstract':
            lines.append(f'abstract class {c.name} {{')
        elif c.stereotype == 'enum':
            lines.append(f'enum {c.name} {{')
        else:
            lines.append(f'class {c.name} {{')
        for m in c.members:
            prefix = ''
            if m.is_abstract and m.is_static:
                prefix = '{static} {abstract} '
            elif m.is_static:
                prefix = '{static} '
            elif m.is_abstract:
                prefix = '{abstract} '
            vis = _render_visibility(m.visibility)
            if m.is_method:
                if m.type:
                    lines.append(f'  {prefix}{vis}{m.name}({m.params}) : {m.type}')
                else:
                    lines.append(f'  {prefix}{vis}{m.name}({m.params})')
            else:
                if m.type:
                    lines.append(f'  {prefix}{vis}{m.name} : {m.type}')
                else:
                    lines.append(f'  {prefix}{vis}{m.name}')
        lines.append('}')
    if data.relations:
        lines.append('')
        for r in data.relations:
            sym = {
                'extends': '--|>',
                'implements': '..|>',
                'compose': '*--',
                'aggregate': 'o--',
                'depend': '..>',
                'assoc': '-->',
            }.get(r.rel_type, '-->')
            line = f'{r.from_cls} {sym} {r.to_cls}'
            if r.label:
                line += f' : {r.label}'
            lines.append(line)
    lines.append('@enduml')
    return '\n'.join(lines)