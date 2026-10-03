"""analysis.communityFromGraph — 无状态社区分组算力（数据主权批B）。

定位：architect 自有图谱基线（arch_graph_node/edge）的社区划分由 KB 提供算法
算力——喂任意图数据（nodes/edges），内存库跑 INCLUDE/CALL 两线 Louvain +
UNIFIED 对齐合并，返回组件树即抛。

与 workspace.snapshot 同形态契约：
- **零持久化**：不建 analysis_task、不写任何磁盘库（:memory: 即抛）；
- **无状态**：不读项目注册表/基线/挂载，输入即全部事实；
- **算法演进单源**：与 KB 自身分析共用 community_analysis/unified_merge，
  KB 侧算法升级 architect 直接受益（不分叉）。

输入（architect 统一符号模型，camelCase/snake_case 均收）：
- nodes: [{id, kind, name, file_path, ...}]（须含 file 虚拟节点/文件路径字段）
- edges: [{source, target, kind, line?}]（仅 calls/imports 参与划分，其余忽略）
输出：{components: [{commId, level, parentId, files, nodeCount, fileCount,
qualityScore}], levels, counts}
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_TASK = "communityFromGraph"      # 内存库任务轴占位 id
_MAX_NODES = 50000
_MAX_EDGES = 200000

_NODE_DEFAULTS = dict(qualified_name="", file_id="", language="",
                      start_line=0, start_col=0, end_line=0, end_col=0,
                      signature="", visibility="", is_exported=0, is_async=0,
                      is_static=0, docstring="", decorators="",
                      type_parameters="")


def register_community_from_graph(server, multi_db) -> None:
    @server.register("analysis.communityFromGraph")
    def community_from_graph(nodes=None, edges=None, taskLabel=None):
        try:
            return _run(nodes or [], edges or [])
        except Exception as e:  # noqa: BLE001
            logger.warning("[communityFromGraph] 分组失败: %s", e, exc_info=True)
            return {"error": str(e), "components": [], "levels": 0}


def _run(nodes: list, edges: list) -> dict:
    if not nodes or not edges:
        return {"components": [], "levels": 0,
                "counts": {"inputNodes": len(nodes), "inputEdges": len(edges)},
                "note": "空图"}

    from topoone.db.manager import SQLiteContext
    from topoone.db.schema.project import PROJECT_DB_TABLES_SQL
    from topoone.engine.store.analysis_store import AnalysisStore
    from topoone.plugins.community import community_analysis, unified_merge

    in_nodes = [n for n in nodes if isinstance(n, dict) and n.get("id")][:_MAX_NODES]
    in_edges = [e for e in edges if isinstance(e, dict) and e.get("source")
                and e.get("target")][:_MAX_EDGES]
    node_ids = {n["id"] for n in in_nodes}

    db = SQLiteContext(":memory:", label="kb:communityFromGraph")
    db.executescript(PROJECT_DB_TABLES_SQL)
    store = AnalysisStore(db)

    n_rows = []
    for n in in_nodes:
        row = dict(_NODE_DEFAULTS)
        row.update({k: n.get(k) for k in row if n.get(k) is not None})
        n_rows.append((
            n["id"], _TASK, n.get("kind") or "symbol", n.get("name") or "",
            row["qualified_name"], row.get("file_path") or "", row["file_id"],
            row["language"], row["start_line"], row["start_col"],
            row["end_line"], row["end_col"], row["signature"], row["visibility"],
            int(bool(row["is_exported"])), row["is_async"], row["is_static"],
            row["docstring"], row["decorators"], row["type_parameters"],
        ))
    with db._lock:
        db._conn and db._conn.executemany(
            "INSERT OR REPLACE INTO graph_node (id, task_id, kind, name, "
            "qualified_name, file_path, file_id, language, start_line, start_col, "
            "end_line, end_col, signature, visibility, is_exported, is_async, "
            "is_static, docstring, decorators, type_parameters) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", n_rows)
        db._conn.commit()

    e_rows = []
    seen = set()
    for e in in_edges:
        if e.get("kind") not in ("calls", "imports"):
            continue
        src, tgt = e["source"], e["target"]
        if src not in node_ids or tgt not in node_ids:
            continue  # 未解析符号名(跨文件名字)无法归文件对, 丢弃
        key = (src, tgt, e["kind"])
        if key in seen:
            continue
        seen.add(key)
        e_rows.append((
            f"{src}->{tgt}:{key[2]}:{e.get('line') or 0}", _TASK, src, tgt,
            key[2], "external", int(e.get("line") or 0), int(e.get("col") or 0),
            "", "{}",
        ))
    if e_rows:
        store.bulk_insert_edges([
            {"id": r[0], "task_id": r[1], "source_id": r[2], "target_id": r[3],
             "kind": r[4], "provenance": r[5], "line": r[6], "col": r[7],
             "file_path": r[8], "metadata": r[9]}
            for r in e_rows])

    # 两线 Louvain + UNIFIED 对齐合并（与 KB 自身分析同一算法单源）
    inc = community_analysis.analyze_communities(_TASK, store, "INCLUDE")
    call = community_analysis.analyze_communities(_TASK, store, "CALL")
    uni = unified_merge.analyze_unified(_TASK, store)

    # 读 UNIFIED 树：graph_doc(成员) + community_hierarchy(层级/质量)
    id2file = {n["id"]: (n.get("file_path") or n.get("filePath") or "")
               for n in in_nodes}
    docs = store.get_communities(_TASK, "UNIFIED")
    components = []
    for d in docs:
        try:
            members = json.loads(d.get("node_list") or "[]")
        except Exception:  # noqa: BLE001
            members = []
        files = []
        for m in members:
            fp = id2file.get(m) or (m if isinstance(m, str) and
                                    ("/" in m or "." in m) else "")
            if fp and fp not in files:
                files.append(fp)
        files.sort()
        components.append({
            "commId": d.get("comm_id"), "level": d.get("comm_lv"),
            "parentId": d.get("parent_comm_id") or "",
            "files": files,
            "nodeCount": int(d.get("node_count") or len(members)),
            "fileCount": int(d.get("file_count") or len(files)),
            "qualityScore": d.get("quality_score") or 0,
        })
    components.sort(key=lambda c: (str(c["level"]), -int(c["nodeCount"])))
    return {
        "components": components,
        "levels": int(uni.get("levels") or 0),
        "counts": {
            "inputNodes": len(in_nodes), "inputEdges": len(in_edges),
            "usedEdges": len(e_rows),
            "includeCommunities": int(inc.get("community_count") or 0),
            "callCommunities": int(call.get("community_count") or 0),
            "unifiedComponents": int(uni.get("community_count") or 0),
        },
    }
