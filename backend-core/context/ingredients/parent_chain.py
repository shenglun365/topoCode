from typing import Any

from ..ingredient import ContextIngredient


class ParentChainIngredient(ContextIngredient):
    name = "parent_chain"

    def collect(self, ctx) -> list[str]:
        cid = ctx.comm_id
        if not cid.startswith("comm-") or "L0" in cid:
            return []
        parts = cid.split("-")
        try:
            lv_idx = next(i for i, p in enumerate(parts) if p.startswith("L"))
        except StopIteration:
            return []
        current_lv = int(parts[lv_idx][1])
        results = []
        while current_lv > 0:
            current_lv -= 1
            parent_parts = list(parts)
            parent_parts[lv_idx] = f"L{current_lv}"
            parent_cid = "-".join(parent_parts)
            row = ctx.db.execute(
                "SELECT name, summary FROM community_llm_results WHERE task_id=? AND comm_id=?",
                (ctx.task_id, parent_cid)
            ).fetchone()
            if row:
                results.append(
                    f"祖级组件 L{current_lv}（{row['name'] or parent_cid}）: {(row['summary'] or '')[:300]}"
                )
        return results

    def format(self, data: list[str]) -> str:
        return "\n".join(data)
