import re
from dataclasses import dataclass, field
from ._meta import ParserMeta

meta = ParserMeta(
    name="timing",
    patterns=[
        (r'\btiming\s+diagram\b', 5),
        (r'\bclock\b', 3),
        (r'\bbinary\b', 2),
        (r'\bconcise\b', 2),
        (r'@\d+', 1, re.MULTILINE),
    ],
)

@dataclass
class TimingClock:
    name: str
    period: str = "5"

@dataclass
class TimingSignal:
    name: str
    kind: str = "binary"

@dataclass
class TimingData:
    title: str = ""
    clocks: list[TimingClock] = field(default_factory=list)
    signals: list[TimingSignal] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)

CLOCK_PAT = re.compile(r'^\s*clock\s+(\w[\w\d_]*)\s+period\s+(\d+)', re.IGNORECASE)
BINARY_PAT = re.compile(r'^\s*binary\s+(\w[\w\d_]*)', re.IGNORECASE)
CONCISE_PAT = re.compile(r'^\s*concise\s+(\w[\w\d_]*)', re.IGNORECASE)

def parse(raw: str) -> TimingData:
    data = TimingData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            data.lines.append('')
            continue
        m = CLOCK_PAT.match(s)
        if m:
            data.clocks.append(TimingClock(name=m.group(1), period=m.group(2)))
            data.lines.append(s)
            continue
        m = BINARY_PAT.match(s)
        if m:
            data.signals.append(TimingSignal(name=m.group(1), kind='binary'))
            data.lines.append(s)
            continue
        m = CONCISE_PAT.match(s)
        if m:
            data.signals.append(TimingSignal(name=m.group(1), kind='concise'))
            data.lines.append(s)
            continue
        data.lines.append(s)
    return data

def render(data: TimingData) -> str:
    return "@startuml\n" + '\n'.join(data.lines) + "\n@enduml"
