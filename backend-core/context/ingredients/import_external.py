from typing import Any

from ..ingredient import ContextIngredient


class ImportExternalIngredient(ContextIngredient):
    name = "import_external"

    def collect(self, ctx) -> list[str]:
        if not ctx.file_paths:
            return []
        placeholders = ",".join("?" for _ in ctx.file_paths)
        rows = ctx.db.execute(
            f"""SELECT DISTINCT name FROM graph_node
                WHERE task_id=? AND kind='import' AND file_path IN ({placeholders})
                  AND name NOT LIKE './%' AND name NOT LIKE '../%'
                  AND name NOT LIKE '/%'
                LIMIT 20""",
            (ctx.task_id, *list(ctx.file_paths))
        ).fetchall()
        return sorted(set(r[0].split("/")[0] for r in rows if r[0]))

    def format(self, data: list[str]) -> str:
        if not data:
            return ""
        return f"外部依赖: {', '.join(data)}"
