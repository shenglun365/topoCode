from typing import Any

from ..ingredient import ContextIngredient


class ExportedSymbolsIngredient(ContextIngredient):
    name = "exported_symbols"

    def collect(self, ctx) -> list[tuple[str, str]]:
        if not ctx.file_paths or not ctx.fp_map:
            return []
        results = []
        for fp in ctx.file_paths:
            for n in ctx.fp_map.get(fp, []):
                if n.get("is_exported"):
                    results.append((n.get("name", ""), n.get("kind", "")))
        return results

    def format(self, data: list[tuple[str, str]]) -> str:
        if not data:
            return ""
        items = [f"{n}({k})" for n, k in data[:15]]
        return f"Public interface: {', '.join(items)}"
