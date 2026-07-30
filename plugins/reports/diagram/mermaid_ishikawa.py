import re
from dataclasses import dataclass, field


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_ishikawa",
    patterns=[
        (r'\bishikawa\b', 20),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class IshikawaCategory:
    name: str
    causes: list[str] = field(default_factory=list)

@dataclass
class IshikawaData:
    title: str = ""
    categories: list[IshikawaCategory] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

HEADER_PAT = re.compile(r'^\s*ishikawa\s*$', re.IGNORECASE)
COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")

def parse(raw: str) -> IshikawaData:
    data = IshikawaData()
    current_cat: IshikawaCategory | None = None
    title_set = False
    for line in raw.split('\n'):
        s = line.rstrip()
        if not s.strip():
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        indent = len(s) - len(s.lstrip())
        stripped = s.strip()
        if not title_set:
            data.title = stripped
            title_set = True
        elif indent <= 4:
            current_cat = IshikawaCategory(name=stripped)
            data.categories.append(current_cat)
        elif current_cat is not None:
            current_cat.causes.append(stripped)
        else:
            data.raw_lines.append(s)
    return data

def render(data: IshikawaData) -> str:
    lines = ['ishikawa']
    if data.title:
        lines.append(f'    {data.title}')
    for cat in data.categories:
        lines.append(f'        {cat.name}')
        for cause in cat.causes:
            lines.append(f'            {cause}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
