from typing import Any

from ..ingredient import ContextIngredient


class FileCentralityIngredient(ContextIngredient):
    name = "file_centrality"

    def collect(self, ctx) -> list[dict]:
        if not ctx.file_paths:
            return []
        placeholders = ",".join("?" for _ in ctx.file_paths)
        rows = ctx.db.execute(
            f"""SELECT gn.file_path, COUNT(*) AS refs
                FROM graph_edge ge
                JOIN graph_node gn ON gn.id = ge.target_id AND gn.task_id = ge.task_id
                WHERE ge.task_id=? AND ge.kind IN ('calls','imports')
                  AND gn.file_path IN ({placeholders})
                GROUP BY gn.file_path ORDER BY refs DESC LIMIT 5""",
            (ctx.task_id, *list(ctx.file_paths))
        ).fetchall()
        return [dict(r) for r in rows]

    def format(self, data: list[dict]) -> str:
        if not data:
            return ""
        items = [f"{r['file_path']} ({r['refs']} refs)" for r in data]
        return f"Core files (by reference count): {'; '.join(items)}"
