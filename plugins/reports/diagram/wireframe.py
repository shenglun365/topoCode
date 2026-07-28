import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="wireframe",
    patterns=[
        (r'\bsalt\s*\{', 5),
        (r'\[.*?\]\s*\[.*?\]', 2),
        (r'^[\w\u4e00-\u9fff]+\s*\[.*?\]', 2, re.MULTILINE),
    ],
)

@dataclass
class WireframeData:
    content: str = ""
    lines: list[str] = field(default_factory=list)

REMOVE_PAT = re.compile(r"^\s*('|skinparam\b|@startuml\b|@enduml\b)")

def parse(raw: str) -> WireframeData:
    out = []
    for line in raw.split('\n'):
        s = line.rstrip()
        if not s or REMOVE_PAT.match(s):
            continue
        out.append(s)
    return WireframeData(content='\n'.join(out), lines=out)

def render(data: WireframeData) -> str:
    return "@startuml\n" + data.content + "\n@enduml"
