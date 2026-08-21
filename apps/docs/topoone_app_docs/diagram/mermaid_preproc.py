import re
from dataclasses import dataclass, field

"""
Shared preprocessor for Mermaid diagrams.

Extracts shared blocks (%%{init}, %% comments) from raw code before
type-specific parsing, and re-applies them after rendering.
"""

INIT_BLOCK_PAT = re.compile(
    r'^\s*%%\{init:\s*(.+?)\s*\}%%\s*$',
    re.DOTALL | re.MULTILINE,
)

COMMENT_LINE_PAT = re.compile(r'^\s*%%[^{].*$', re.MULTILINE)

SEPARATOR_PAT = re.compile(r'^\s*---\s*$', re.MULTILINE)


@dataclass
class MermaidPreprocContext:
    init_blocks: list[str] = field(default_factory=list)
    comment_lines: list[str] = field(default_factory=list)
    separators: list[str] = field(default_factory=list)


def extract_shared(code: str) -> tuple[MermaidPreprocContext, str]:
    ctx = MermaidPreprocContext()
    lines = code.split('\n')
    kept: list[str] = []
    in_init_block = False
    init_buffer: list[str] = []

    for line in lines:
        stripped = line.rstrip()

        if SEPARATOR_PAT.match(stripped):
            ctx.separators.append(stripped)
            continue

        if COMMENT_LINE_PAT.match(stripped):
            ctx.comment_lines.append(stripped)
            continue

        m = re.match(r'^\s*%%\{init:\s*$', stripped, re.IGNORECASE)
        if m:
            in_init_block = True
            init_buffer = [stripped]
            continue
        if in_init_block:
            init_buffer.append(stripped)
            if stripped.strip().endswith('}%%'):
                in_init_block = False
                ctx.init_blocks.append('\n'.join(init_buffer))
                init_buffer = []
            continue

        m = INIT_BLOCK_PAT.match(stripped)
        if m:
            ctx.init_blocks.append(stripped)
            continue

        kept.append(stripped)

    if in_init_block and init_buffer:
        ctx.init_blocks.append('\n'.join(init_buffer))

    return ctx, '\n'.join(kept)


def reapply_shared(rendered: str, ctx: MermaidPreprocContext) -> str:
    lines = rendered.split('\n')
    result: list[str] = []
    has_shared = bool(ctx.init_blocks or ctx.comment_lines or ctx.separators)
    inserted = False

    for line in lines:
        if not inserted and has_shared:
            if ctx.comment_lines:
                result.extend(ctx.comment_lines)
            if ctx.separators:
                result.extend(ctx.separators)
            if ctx.init_blocks:
                for block in ctx.init_blocks:
                    result.extend(block.split('\n'))
            inserted = True
        result.append(line)

    if not inserted and has_shared:
        if ctx.comment_lines:
            result.extend(ctx.comment_lines)
        if ctx.separators:
            result.extend(ctx.separators)
        if ctx.init_blocks:
            for block in ctx.init_blocks:
                result.extend(block.split('\n'))

    return '\n'.join(result)
