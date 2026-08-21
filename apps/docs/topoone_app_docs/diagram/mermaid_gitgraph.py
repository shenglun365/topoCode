import re
from dataclasses import dataclass, field
from typing import Union


from ._meta import ParserMeta



meta = ParserMeta(
    name="mermaid_gitgraph",
    patterns=[
        (r'\bgitGraph\b', 20),
        (r'\bcommit\b', 2),
        (r'\bbranch\b', 2),
    ],
    min_score=4,
    supports_preproc=False,
    preproc_engine="mermaid",
)
@dataclass
class GitCommit:
    id: str = ""
    tag: str = ""
    commit_type: str = "NORMAL"

@dataclass
class GitBranch:
    name: str

@dataclass
class GitCheckout:
    name: str

@dataclass
class GitMerge:
    branch: str
    id: str = ""
    tag: str = ""

@dataclass
class GitCherryPick:
    id: str

GitAction = Union[GitCommit, GitBranch, GitCheckout, GitMerge, GitCherryPick]

@dataclass
class GitGraphData:
    actions: list[GitAction] = field(default_factory=list)
    raw_lines: list[str] = field(default_factory=list)

COMMENT_PAT = re.compile(r'^\s*%%')
REMOVE_PAT = re.compile(r"^\s*(@startuml\b|@enduml\b)")
HEADER_PAT = re.compile(r'^\s*gitGraph\s*$', re.IGNORECASE)
COMMIT_PAT = re.compile(
    r'^\s*commit\s*'
    r'(?:\s*id:\s*"([^"]*)")?'
    r'(?:\s*tag:\s*"([^"]*)")?'
    r'(?:\s*type:\s*(NORMAL|REVERSE|HIGHLIGHT))?'
    r'\s*$', re.IGNORECASE
)
BRANCH_PAT = re.compile(r'^\s*branch\s+(\S[\w\d_/-]*)\s*$', re.IGNORECASE)
CHECKOUT_PAT = re.compile(r'^\s*checkout\s+(\S[\w\d_/-]*)\s*$', re.IGNORECASE)
MERGE_PAT = re.compile(
    r'^\s*merge\s+(\S[\w\d_/-]*)'
    r'(?:\s+id:\s*"([^"]*)")?'
    r'(?:\s+tag:\s*"([^"]*)")?'
    r'\s*$', re.IGNORECASE
)
CHERRY_PICK_PAT = re.compile(r'^\s*cherry-pick\s+(\S[\w\d_/-]*)\s*$', re.IGNORECASE)

def _parse_commit(s: str) -> GitCommit | None:
    m = COMMIT_PAT.match(s)
    if m:
        return GitCommit(
            id=m.group(1) or '',
            tag=m.group(2) or '',
            commit_type=(m.group(3) or 'NORMAL').upper(),
        )
    return None

def parse(raw: str) -> GitGraphData:
    data = GitGraphData()
    for line in raw.split('\n'):
        s = line.strip()
        if not s:
            continue
        if COMMENT_PAT.match(s) or REMOVE_PAT.match(s):
            data.raw_lines.append(s)
            continue
        if HEADER_PAT.match(s):
            continue
        m = BRANCH_PAT.match(s)
        if m:
            data.actions.append(GitBranch(name=m.group(1)))
            continue
        m = CHECKOUT_PAT.match(s)
        if m:
            data.actions.append(GitCheckout(name=m.group(1)))
            continue
        m = MERGE_PAT.match(s)
        if m:
            data.actions.append(GitMerge(
                branch=m.group(1), id=m.group(2) or '',
                tag=m.group(3) or '',
            ))
            continue
        m = CHERRY_PICK_PAT.match(s)
        if m:
            data.actions.append(GitCherryPick(id=m.group(1)))
            continue
        commit = _parse_commit(s)
        if commit:
            data.actions.append(commit)
            continue
        data.raw_lines.append(s)
    return data

def render(data: GitGraphData) -> str:
    lines = ['gitGraph']
    for action in data.actions:
        if isinstance(action, GitCommit):
            parts = ['commit']
            if action.id:
                parts.append(f'id:"{action.id}"')
            if action.tag:
                parts.append(f'tag:"{action.tag}"')
            if action.commit_type != 'NORMAL':
                parts.append(f'type:{action.commit_type}')
            lines.append(f'    {" ".join(parts)}')
        elif isinstance(action, GitBranch):
            lines.append(f'    branch {action.name}')
        elif isinstance(action, GitCheckout):
            lines.append(f'    checkout {action.name}')
        elif isinstance(action, GitMerge):
            parts = [f'merge {action.branch}']
            if action.id:
                parts.append(f'id:"{action.id}"')
            if action.tag:
                parts.append(f'tag:"{action.tag}"')
            lines.append(f'    {" ".join(parts)}')
        elif isinstance(action, GitCherryPick):
            lines.append(f'    cherry-pick {action.id}')
    for line in data.raw_lines:
        lines.append(f'{line}')
    return '\n'.join(lines)
