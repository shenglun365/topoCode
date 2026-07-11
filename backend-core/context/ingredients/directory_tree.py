import os
from collections import Counter
from typing import Any

from ..ingredient import ContextIngredient


class DirectoryTreeIngredient(ContextIngredient):
    name = "directory_tree"

    def collect(self, ctx) -> list[str]:
        if not ctx.file_paths:
            return []
        dir_tree = Counter()
        for fp in ctx.file_paths:
            d = ctx.resolve_path(os.path.dirname(fp))
            if d and d != '.':
                parts = d.split('/')
                for i in range(1, len(parts) + 1):
                    dir_tree['/'.join(parts[:i])] += 1
        if not dir_tree:
            return []
        seen = set()
        lines = []
        for d in sorted(dir_tree):
            if d not in seen:
                seen.add(d)
                depth = d.count('/')
                lines.append(f"{'  ' * depth}{os.path.basename(d)}/ ({dir_tree[d]})")
        return lines[:20]

    def format(self, data: list[str]) -> str:
        if not data:
            return ""
        return "Directory structure:\n" + "\n".join(data)
