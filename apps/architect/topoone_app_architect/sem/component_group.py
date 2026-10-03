"""architect 自有组件目录：KB 社区算力调用 + 落库（数据主权批B）。

链路：arch_graph_node/edge 快照（collect_graph 产物）→ KB
analysis.communityFromGraph（无状态两线 Louvain + UNIFIED，零持久化）→
组件树换算 → arch_components/arch_component_hierarchy（save_components）。

组件命名不在本作业内（commId 即名）——批C component_name 快速命名作业
按 owns 指纹生成中文名+一句话职责后覆盖。
"""
from __future__ import annotations

import json
import logging

from ..store.graph import ComponentStore, GraphStore
from . import job_runner
from .job_runner import JobCtx

logger = logging.getLogger(__name__)


def _job_community_group(ctx: JobCtx) -> dict:
    from ..kb_gateway import call_kb
    from .graph_collect import read_graph_baseline

    pid = ctx.pid
    # 无需 root: 快照读取/组件落库全按 pid; KB 算力调用为无状态喂图
    anchor = read_graph_baseline(pid)
    head = (anchor or {}).get("head") or ""
    if not head:
        return {"error": "无基线锚(先运行 collect-graph 采集)"}
    rev = f"baseline:{head}"
    nodes = GraphStore.nodes(pid, rev, limit=100000)
    edges = GraphStore.edges(pid, rev, limit=300000)
    if not nodes:
        return {"error": f"图谱快照为空({rev})(先运行 collect-graph 采集)"}

    ctx.progress(total=3, done=1, current="调用 KB 社区算力")
    # 传参精简: KB 端只消费 id/kind/name/qualified_name/file_path 与 source/target/kind/line
    slim_nodes = [{k: n.get(k) for k in
                   ("id", "kind", "name", "qualified_name", "file_path")} for n in nodes]
    slim_edges = [{"source": e["source"], "target": e["target"],
                   "kind": e["kind"], "line": e.get("line") or 0} for e in edges]
    res = call_kb("analysis.communityFromGraph", nodes=slim_nodes, edges=slim_edges)
    if not isinstance(res, dict):
        return {"error": "KB 社区算力不可达(call_kb 返回空)"}
    if res.get("error"):
        return {"error": f"KB 社区分组失败: {res.get('error')}"}

    ctx.progress(total=3, done=2, current="组件树落库")
    comps, hier = [], []
    for c in res.get("components") or []:
        cid = c.get("commId")
        if not cid:
            continue
        lvl = str(c.get("level") or "L0")
        comps.append({
            "id": cid, "name": cid, "summary": "",
            "owns": c.get("files") or [], "source": "community",
        })
        hier.append({
            "childId": cid, "parentId": c.get("parentId") or "",
            "level": int(lvl[1:]) if lvl[1:].isdigit() else 0,
        })
    written = ComponentStore.replace_rev(pid, rev, comps, hier)
    result = {
        "rev": rev, "components": written["components"],
        "hierarchy": written["hierarchy"],
        "levels": res.get("levels") or 0,
        "counts": res.get("counts") or {},
    }
    logger.info("[community-group] 完成: %s", json.dumps(result, ensure_ascii=False)[:300])
    return result


job_runner.register("community_group", _job_community_group)  # noqa: E305
