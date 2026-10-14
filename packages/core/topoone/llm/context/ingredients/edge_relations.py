from typing import Any

from ..ingredient import ContextIngredient


class EdgeRelationsIngredient(ContextIngredient):
    name = "edge_relations"

    def collect(self, ctx) -> dict:
        if not ctx.edge_list:
            return {"lines": [], "out": 0, "in": 0}
        lines = []
        out_cnt = 0
        in_cnt = 0
        fps = ctx.file_paths
        for e in ctx.edge_list:
            if isinstance(e, dict):
                src = (e.get("source") or e.get("source_id") or "")[:60]
                tgt = (e.get("target") or e.get("target_id") or "")[:60]
                kind = e.get("kind", "")
                if src and tgt:
                    lines.append(f"{src} → {tgt}" + (f" ({kind})" if kind else ""))
                if src in fps:
                    out_cnt += 1
                if tgt in fps:
                    in_cnt += 1
            elif isinstance(e, str):
                lines.append(e[:80])
        return {"lines": lines, "out": out_cnt, "in": in_cnt}

    def format(self, data: dict) -> str:
        parts = []
        if data.get("lines"):
            parts.append(f"Edge relations ({len(data['lines'])}): {'; '.join(data['lines'])}")
        out_cnt = data.get("out", 0)
        in_cnt = data.get("in", 0)
        if out_cnt or in_cnt:
            parts.append(f"Call direction: local→external {out_cnt}, external→local {in_cnt}")
        return "\n".join(parts)
