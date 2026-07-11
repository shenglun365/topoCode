#!/usr/bin/env python3
"""AST 结构诊断脚本 (v2)

用法:
  python scripts/analyze_ast.py <file_path>
  python scripts/analyze_ast.py <file_path> --lang python
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'plugins', 'parsers'))

from parsers.core.walker import TreeSitterWalker, _detect_language
from parsers.core.resolver import ResolutionEngine
from parsers.languages import EXTRACTORS


def analyze(file_path: str, lang: str = None):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    if lang is None:
        lang = _detect_language(file_path)
    if lang is None:
        print(f"Cannot detect language for: {file_path}")
        return

    extractor = EXTRACTORS.get(lang)
    if extractor is None:
        print(f"No extractor for language: {lang}")
        return

    print(f"Language: {lang}")
    src = open(file_path, "rb").read()
    walker = TreeSitterWalker(file_path, src, lang, extractor)
    table = walker.extract()

    print(f"\n=== Nodes ({len(table.nodes)}) ===")
    for n in table.nodes:
        if n.kind.value == "file":
            continue
        sig = f" [{n.signature}]" if n.signature else ""
        vis = f" ({n.visibility})" if n.visibility else ""
        exp = " *exported*" if n.is_exported else ""
        print(f"  [{n.kind.value:12s}] {n.qualified_name}{sig}{vis}{exp}")

    print(f"\n=== Unresolved References ({len(table.unresolved_refs)}) ===")
    for r in table.unresolved_refs[:20]:
        print(f"  [{r.reference_kind.value:12s}] {r.reference_name} @L{r.line}")

    if len(table.unresolved_refs) > 20:
        print(f"  ... and {len(table.unresolved_refs) - 20} more")

    print(f"\n=== Contains Edges ({len(walker.edges)}) ===")
    print(f"  Total: {len(walker.edges)}")


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="AST structure analyzer")
    p.add_argument("file", help="Source file to analyze")
    p.add_argument("--lang", help="Force language (e.g. python, java)")
    args = p.parse_args()
    analyze(args.file, args.lang)
