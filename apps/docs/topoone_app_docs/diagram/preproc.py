import re
from dataclasses import dataclass, field
from typing import Optional

"""
Shared preprocessor for PlantUML diagrams.

Extracts shared blocks (skinparam, <style>, !include/!define, direction,
page config, comment headers) from raw code before type-specific parsing,
and re-applies them after rendering.
"""

SKINPARAM_PAT = re.compile(
    r'^\s*skinparam\b.*$',
    re.IGNORECASE | re.MULTILINE
)

STYLE_BLOCK_PAT = re.compile(
    r'^\s*<style>.*?</style>',
    re.DOTALL | re.IGNORECASE | re.MULTILINE
)

PREPROC_PAT = re.compile(
    r'^\s*!((?:include|define|undef|ifdef|ifndef|endif|else|if)\b.*)$',
    re.IGNORECASE | re.MULTILINE
)

DIRECTION_PAT = re.compile(
    r'^\s*(left\s+to\s+right\s+direction|top\s+to\s+bottom\s+direction)\s*$',
    re.IGNORECASE | re.MULTILINE
)

PAGE_PAT = re.compile(
    r'^\s*page\s+.*$',
    re.IGNORECASE | re.MULTILINE
)

COMMENT_LINE_PAT = re.compile(r"^\s*'.*$", re.MULTILINE)

TITLE_PAT = re.compile(r'^\s*title\s+(.+)$', re.IGNORECASE)

START_MARKER_PAT = re.compile(
    r'^\s*@start\w+\s*$', re.MULTILINE
)
END_MARKER_PAT = re.compile(
    r'^\s*@end\w+\s*$', re.MULTILINE
)


@dataclass
class PreprocContext:
    skinparams: list[str] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)
    preproc_lines: list[str] = field(default_factory=list)
    direction: str = ""               # "left to right direction" | "top to bottom direction"
    page_configs: list[str] = field(default_factory=list)
    title: str = ""
    comment_lines: list[str] = field(default_factory=list)
    start_marker: str = ""
    end_marker: str = ""


_ENTITY_START_RE = re.compile(
    r'^\s*(?:\[|(?:component|package|rectangle|folder|node|frame|'
    r'cloud|database|storage|actor|usecase|class|interface|enum|'
    r'state|object|artifact|boundary|control|entity|collections)\s)',
    re.IGNORECASE
)


def _is_entity_line(s: str) -> bool:
    return bool(_ENTITY_START_RE.match(s))


def _flatten_skinparam_block(lines: list[str]) -> tuple[list[str], list[str]]:
    first = lines[0].strip() if lines else ''
    m = re.match(r'^\s*skinparam\s+(\w+)\s*\{', first, re.IGNORECASE)
    if not m:
        return lines, []

    type_name = m.group(1)
    styling: list[str] = []
    declarations: list[str] = []
    for line in lines[1:]:
        stripped = line.strip()
        if not stripped or stripped == '}' or stripped.startswith("'"):
            continue
        if stripped.endswith('}'):
            stripped = stripped[:-1].strip()
            if not stripped:
                continue
        if _is_entity_line(stripped):
            declarations.append(stripped)
        else:
            styling.append(f"skinparam {type_name} {stripped}")

    return styling, declarations


def extract_shared(code: str) -> tuple[PreprocContext, str]:
    ctx = PreprocContext()
    lines = code.split('\n')
    kept: list[str] = []
    marker_found = False
    skinparam_block: list[str] | None = None

    for line in lines:
        stripped = line.rstrip()

        # Start/end markers
        m = re.match(r'^\s*(@start\w+)', stripped, re.IGNORECASE)
        if m:
            ctx.start_marker = stripped.strip()
            continue
        m = re.match(r'^\s*(@end\w+)', stripped, re.IGNORECASE)
        if m:
            ctx.end_marker = stripped.strip()
            continue

        # Multi-line skinparam block
        if skinparam_block is not None:
            skinparam_block.append(stripped)
            if stripped.strip() == '}':
                styling, declarations = _flatten_skinparam_block(skinparam_block)
                ctx.skinparams.extend(styling)
                kept.extend(declarations)
                skinparam_block = None
            continue

        if re.match(r"^\s*'.*$", stripped):
            ctx.comment_lines.append(stripped)
            continue

        if re.match(r'^\s*skinparam\b', stripped, re.IGNORECASE):
            if stripped.strip().endswith('{'):
                skinparam_block = [stripped]
                continue
            ctx.skinparams.append(stripped)
            continue

        # <style> ... </style> multi-line
        if re.match(r'^\s*<style>\s*$', stripped, re.IGNORECASE):
            ctx.styles.append(stripped)
            marker_found = True
            continue
        if marker_found:
            ctx.styles.append(stripped)
            if re.match(r'^\s*</style>\s*$', stripped, re.IGNORECASE):
                marker_found = False
            continue

        if re.match(r'^\s*!', stripped):
            ctx.preproc_lines.append(stripped)
            continue

        if re.match(r'^\s*(left\s+to\s+right\s+direction|top\s+to\s+bottom\s+direction)\s*$', stripped, re.IGNORECASE):
            ctx.direction = stripped.strip()
            continue

        if re.match(r'^\s*page\s+', stripped, re.IGNORECASE):
            ctx.page_configs.append(stripped)
            continue

        m = re.match(r'^\s*title\s+(.+)$', stripped, re.IGNORECASE)
        if m:
            ctx.title = m.group(1).strip().strip('"')
            continue

        kept.append(stripped)

    if skinparam_block is not None:
        styling, declarations = _flatten_skinparam_block(skinparam_block)
        ctx.skinparams.extend(styling)
        kept.extend(declarations)

    ctx.start_marker = ctx.start_marker or "@startuml"
    ctx.end_marker = ctx.end_marker or "@enduml"
    return ctx, '\n'.join(kept)


def reapply_shared(rendered: str, ctx: PreprocContext) -> str:
    lines = rendered.split('\n')
    result: list[str] = []

    has_start = any(re.match(r'^\s*@start\w+', l) for l in lines[:3])
    has_end = any(re.match(r'^\s*@end\w+', l) for l in lines[-3:])

    has_shared = bool(ctx.comment_lines or ctx.title or ctx.direction
                      or ctx.skinparams or ctx.styles
                      or ctx.preproc_lines or ctx.page_configs)

    for line in lines:
        if has_start and re.match(r'^\s*@start\w+', line):
            result.append(line)
            if has_shared:
                if ctx.comment_lines:
                    result.extend(ctx.comment_lines)
                if ctx.title:
                    result.append(f'title {ctx.title}')
                if ctx.direction:
                    result.append(ctx.direction)
                if ctx.skinparams:
                    result.append('')
                    result.extend(ctx.skinparams)
                if ctx.styles:
                    result.append('')
                    result.extend(ctx.styles)
                if ctx.preproc_lines:
                    result.append('')
                    result.extend(ctx.preproc_lines)
                if ctx.page_configs:
                    result.append('')
                    result.extend(ctx.page_configs)
            continue
        if re.match(r'^\s*@end\w+', line):
            result.append(line)
            continue
        result.append(line)

    if not has_start:
        result.append(ctx.start_marker)
        if has_shared:
            if ctx.comment_lines:
                result.extend(ctx.comment_lines)
            if ctx.title:
                result.append(f'title {ctx.title}')
            if ctx.direction:
                result.append(ctx.direction)
            if ctx.skinparams:
                result.append('')
                result.extend(ctx.skinparams)
            if ctx.styles:
                result.append('')
                result.extend(ctx.styles)
            if ctx.preproc_lines:
                result.append('')
                result.extend(ctx.preproc_lines)
            if ctx.page_configs:
                result.append('')
                result.extend(ctx.page_configs)
    if not has_end:
        result.append(ctx.end_marker)

    return '\n'.join(result)


def markers_from_type(diag_type: str) -> tuple[str, str]:
    marker_map = {
        "mindmap": ("@startmindmap", "@endmindmap"),
        "wbs": ("@startwbs", "@endwbs"),
        "json": ("@startjson", "@endjson"),
        "yaml": ("@startyaml", "@endyaml"),
        "hcl": ("@starthcl", "@endhcl"),
        "files": ("@startfiles", "@endfiles"),
        "git": ("@startgit", "@endgit"),
        "ebnf": ("@startebnf", "@endebnf"),
        "packet": ("@startpacketdiag", "@endpacketdiag"),
        "chen_eer": ("@startchen", "@endchen"),
        "math": ("@startmath", "@endmath"),
        "latex": ("@startlatex", "@endlatex"),
        "regex": ("@startregex", "@endregex"),
        "definition": ("@startdef", "@enddef"),
        "creole": ("@startcreole", "@endcreole"),
        "sprites": ("@startsprites", "@endsprites"),
        "chart": ("@startchart", "@endchart"),
        "flow": ("@startflow", "@endflow"),
        "board": ("@startboard", "@endboard"),
        "bpm": ("@startbpm", "@endbpm"),
        "salt": ("@startsalt", "@endsalt"),
        "dot": ("@startdot", "@enddot"),
        "ditaa": ("@startditaa", "@endditaa"),
        "help": ("@startuml help", ""),
        "sequence": ("@startuml", "@enduml"),
        "component": ("@startuml", "@enduml"),
        "class": ("@startuml", "@enduml"),
        "state": ("@startuml", "@enduml"),
        "activity": ("@startuml", "@enduml"),
        "usecase": ("@startuml", "@enduml"),
        "deployment": ("@startuml", "@enduml"),
        "archimate": ("@startuml", "@enduml"),
        "object": ("@startuml", "@enduml"),
        "timing": ("@startuml", "@enduml"),
        "gantt": ("@startuml", "@enduml"),
        "network": ("@startuml", "@enduml"),
        "wireframe": ("@startuml", "@enduml"),
    }
    return marker_map.get(diag_type, ("@startuml", "@enduml"))
