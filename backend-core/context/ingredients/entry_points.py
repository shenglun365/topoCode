from typing import Any

from ..ingredient import ContextIngredient


class EntryPointsIngredient(ContextIngredient):
    name = "entry_points"

    def collect(self, ctx) -> list[dict]:
        rows = ctx.db.execute(
            """SELECT file_path, name FROM graph_node
               WHERE task_id=? AND name IN ('main','run','start','Main')
                 AND kind='function' LIMIT 10""",
            (ctx.task_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def format(self, data: list[dict]) -> str:
        if not data:
            return ""
        lines = []
        for r in data:
            lines.append(f"- {r['file_path']} → {r['name']}()")
        return "## 入口点\n" + "\n".join(lines)
