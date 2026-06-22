from typing import Any

from ..ingredient import ContextIngredient


class CommunityInfoIngredient(ContextIngredient):
    name = "community_info"

    def collect(self, ctx) -> dict:
        parts = {"id": ctx.comm_id}
        if hasattr(ctx, '_comm_meta') and ctx._comm_meta:
            meta = ctx._comm_meta
            parts["node_count"] = meta.get("nodeCount", 0)
            parts["file_count"] = meta.get("fileCount", 0)
            parts["quality_score"] = meta.get("qualityScore")
            parts["edge_count"] = meta.get("edgeCount", 0)
            parts["edge_label"] = meta.get("edgeLabel", "")
        return parts

    def format(self, data: dict) -> str:
        lines = [f"组件ID: {data.get('id', '')}"]
        nc = data.get("node_count")
        if nc:
            lines.append(f"节点数: {nc}")
        fc = data.get("file_count")
        if fc:
            lines.append(f"文件数: {fc}")
        qs = data.get("quality_score")
        if qs is not None:
            lines.append(f"质量分: {qs:.4f}")
        ec = data.get("edge_count")
        el = data.get("edge_label")
        if ec:
            lines.append(f"边数: {ec} ({el})" if el else f"边数: {ec}")
        return "\n".join(lines)
