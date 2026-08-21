"""
community_data.py — 统一社区图数据提取
======================================

分层架构：
  L1: 原始 DB 查询 → 返回行列表 (list[dict])
  L2: 结构化为文件级节点/边
  L3: 聚合/过滤/矩阵
  L4: 端到端函数 (1:1 映射 App IPC 方法)

所有函数接受 SQLiteContext (db)，返回 list/dict。
Web 端用 L4 作为端点，也允许用 L2+L3 自行组合扩展。
"""

from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════

def _infer_edge_type(comm_id: str) -> str:
    """从社区ID推断边类型: comm-xxx-call-... → CALL, comm-xxx-incl-... → INCLUDE"""
    if not comm_id:
        return ''
    parts = comm_id.split('-')
    if len(parts) >= 3:
        return 'CALL' if parts[2] == 'call' else 'INCLUDE' if parts[2] == 'incl' else ''
    return ''


def _make_rel(project_root: str):
    """返回路径规范化函数: file:/abs/path → rel/path"""
    __root = project_root.replace('\\', '/') if project_root else ''
    def _rel(p):
        if not p:
            return p
        if p.startswith('file:'):
            p = p[5:]
        p = p.replace('\\', '/')
        if __root and p.lower().startswith(__root.lower()):
            p = p[len(__root):]
        return p.lstrip('/')
    return _rel


def l0_ancestor(cid: str) -> str:
    """提取社区ID的L0祖先: comm-xxx-L3-0000-0001-0002 → comm-xxx-L0-0000"""
    parts = cid.split('-')
    lvl_start = -1
    for k, p in enumerate(parts):
        if re.match(r'^L\d+$', p) and lvl_start == -1:
            lvl_start = k
            break
    if lvl_start >= 0 and lvl_start + 1 < len(parts):
        pre = parts[:lvl_start]
        return '-'.join(pre) + f'-L0-{parts[lvl_start + 1]}'
    return cid


def _bad_id(v) -> bool:
    s = str(v).strip()
    return not s or s == 'None'


def _cid_level(cid: str) -> str:
    """从社区ID提取层级: comm-xxx-L3-0000 → L3"""
    m = re.search(r'-(L\d+)-', cid)
    return m.group(1) if m else ""


# ═══════════════════════════════════════════════════════
# L1 — 原始 DB 查询
# ═══════════════════════════════════════════════════════

def read_graph_doc_rows(db, task_id: str, edge_type: str,
                        comm_lv: str = '', comm_id: str = ''):
    """读取 graph_doc 行 (按层级+社区过滤)"""
    base_where = ["task_id=? AND edge_type=?"]
    base_params = [task_id, edge_type]
    if comm_id:
        base_where.append("comm_id=?")
        base_params.append(comm_id)
    if comm_lv:
        base_where.append("comm_lv=?")
        base_params.append(comm_lv)
    return db.fetchall(
        f"SELECT comm_id, comm_lv, node_list, edge_list "
        f"FROM graph_doc WHERE {' AND '.join(base_where)} "
        f"ORDER BY comm_lv, comm_id",
        tuple(base_params)
    )


def read_graph_doc_children(db, task_id: str, edge_type: str,
                              parent_comm_id: str):
    """读取子社区: graph_doc WHERE parent_comm_id = ? (下钻用)"""
    return db.fetchall(
        "SELECT comm_id, comm_lv, node_list FROM graph_doc "
        "WHERE task_id=? AND edge_type=? AND parent_comm_id=? "
        "ORDER BY comm_lv, comm_id",
        (task_id, edge_type, parent_comm_id)
    )


def read_community_hierarchy_maps(db, task_id: str, edge_type: str):
    """全量读取社区层级映射 (一次查询, 内存建索引).

    返回 (parent_of, children_of):
      parent_of[cid]  → 父社区 id ('', 顶级社区无父)
      children_of[pid] → [子社区 id, ...]  (pid 是否有子 = pid 是否在 children_of)
    """
    rows = db.fetchall(
        "SELECT comm_id, parent_comm_id FROM graph_doc "
        "WHERE task_id=? AND edge_type=?",
        (task_id, edge_type)
    )
    parent_of, children_of = {}, {}
    for r in rows:
        cid = r["comm_id"]
        pid = r["parent_comm_id"] or ''
        parent_of[cid] = pid
        if pid:
            children_of.setdefault(pid, []).append(cid)
    return parent_of, children_of


_RECURSION_DEPTH = 0
_MAX_RECURSE = 5


def expand_communities_to_depth(db, task_id: str, edge_type: str,
                                  rows: list, depth: int):
    """按深度批量展开社区（单次全量查询 + 内存遍历）"""
    depth = max(1, min(depth, _MAX_RECURSE))
    if depth <= 1 or not rows:
        return rows

    # 一次性读取所有行，构建 comm_by_id + children_of 映射
    all_rows = db.fetchall(
        "SELECT comm_id, comm_lv, node_list, parent_comm_id FROM graph_doc "
        "WHERE task_id=? AND edge_type=?",
        (task_id, edge_type)
    )
    comm_by_id = {r["comm_id"]: dict(r) for r in all_rows}
    children_of = {}
    for r in all_rows:
        pid = r.get("parent_comm_id")
        if pid:
            children_of.setdefault(pid, []).append(r["comm_id"])

    # 逐层展开: 叶子节点保留, 有子节点展开到下一层
    result = []
    current = rows
    for d in range(1, depth + 1):
        next_level = []
        for r in current:
            cid = r["comm_id"]
            child_ids = children_of.get(cid, [])
            if child_ids and d < depth:
                for child_cid in child_ids:
                    if child_cid in comm_by_id:
                        next_level.append(comm_by_id[child_cid])
            else:
                result.append(r)
        current = next_level
        if not next_level:
            break

    return result


def read_graph_doc_all_nodes(db, task_id: str, edge_type: str,
                              comm_lv: str = ''):
    """读取所有 graph_doc 行的 node_list (用于构建 file→comm 映射)"""
    if comm_lv:
        return db.fetchall(
            "SELECT comm_id, node_list FROM graph_doc "
            "WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (task_id, edge_type, comm_lv)
        )
    return db.fetchall(
        "SELECT comm_id, node_list FROM graph_doc "
        "WHERE task_id=? AND edge_type=?",
        (task_id, edge_type)
    )


def read_graph_edges(db, task_id: str, kind: str):
    """读取 graph_edge 行 (kind = 'imports' | 'calls')"""
    return db.fetchall(
        "SELECT source_id, target_id FROM graph_edge "
        "WHERE task_id=? AND kind=?",
        (task_id, kind)
    )


def read_graph_node_map(db, task_id: str, symbol_ids: set):
    """hex hash → file_path 映射 (用于 CALL 边解析)"""
    if not symbol_ids:
        return {}
    sym_list = list(symbol_ids)
    result = {}
    batch_size = 900
    for i in range(0, len(sym_list), batch_size):
        batch = sym_list[i:i + batch_size]
        placeholders = ",".join(["?"] * len(batch))
        rows = db.fetchall(
            f"SELECT id, file_path FROM graph_node "
            f"WHERE task_id=? AND id IN ({placeholders})",
            (task_id, *batch)
        )
        for row in rows:
            fp = row["file_path"] or ""
            if fp:
                result[row["id"]] = fp
    return result


def read_community_names(db, task_id: str, edge_type: str):
    """读取社区 LLM 名称"""
    rows = db.fetchall(
        "SELECT comm_id, name FROM community_llm_results "
        "WHERE task_id=? AND edge_type=?",
        (task_id, edge_type)
    )
    return {r["comm_id"]: r["name"] or r["comm_id"] for r in rows}


def read_community_hierarchy(db, task_id: str, edge_type: str,
                              parent_comm_id: str = None):
    """读取社区层级 (children)"""
    if parent_comm_id:
        rows = db.fetchall(
            """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                      h.edge_type, r.name AS llm_name
               FROM community_hierarchy h
               LEFT JOIN community_llm_results r
                 ON r.task_id = h.task_id AND r.edge_type = h.edge_type
                 AND r.comm_lv = h.comm_lv AND r.comm_id = h.comm_id
               WHERE h.task_id = ? AND h.edge_type = ? AND h.parent_comm_id = ?
               ORDER BY h.comm_lv, h.comm_id""",
            (task_id, edge_type, parent_comm_id)
        )
    else:
        rows = db.fetchall(
            """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                      h.edge_type, r.name AS llm_name
               FROM community_hierarchy h
               LEFT JOIN community_llm_results r
                 ON r.task_id = h.task_id AND r.edge_type = h.edge_type
                 AND r.comm_lv = h.comm_lv AND r.comm_id = h.comm_id
               WHERE h.task_id = ? AND h.edge_type = ? AND h.parent_comm_id IS NULL
               ORDER BY h.comm_lv, h.comm_id""",
            (task_id, edge_type)
        )
    result = []
    for row in rows:
        result.append({
            "commId": row["comm_id"],
            "commLv": row["comm_lv"],
            "parentCommId": row.get("parent_comm_id", "") or "",
            "name": row.get("llm_name") or "",
            "hasDoc": bool(row.get("llm_name")),
            "nodeCount": row.get("node_count") or 0,
            "edgeType": row.get("edge_type", edge_type),
        })
    return result


def read_cascade_levels(db, task_id: str, edge_type: str):
    """读取所有级联层级"""
    rows = db.fetchall(
        """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                  h.edge_count, r.name AS llm_name
           FROM community_hierarchy h
           LEFT JOIN community_llm_results r
             ON r.task_id = h.task_id AND r.edge_type = h.edge_type
             AND r.comm_lv = h.comm_lv AND r.comm_id = h.comm_id
           WHERE h.task_id = ? AND h.edge_type = ?
           ORDER BY h.comm_lv, h.comm_id""",
        (task_id, edge_type)
    )
    groups = {}
    for r in rows:
        lv = r["comm_lv"]
        if lv not in groups:
            groups[lv] = []
        groups[lv].append({
            "commId": r["comm_id"],
            "commLv": lv,
            "parentCommId": r.get("parent_comm_id", "") or "",
            "name": r.get("llm_name") or r["comm_id"],
            "nodeCount": r.get("node_count") or 0,
            "edgeCount": r.get("edge_count") or 0,
        })
    return [{"lv": k, "items": v} for k, v in sorted(groups.items())]


# ═══════════════════════════════════════════════════════
# L2 — 文件级数据提取
# ═══════════════════════════════════════════════════════

def extract_file_nodes(raw_rows, et: str, _rel, name_map: dict):
    """从 graph_doc 行提取文件级节点 (id, label, commId, commLv)"""
    nodes = {}
    for r in raw_rows:
        cid = r["comm_id"]
        clv = r["comm_lv"]
        try:
            raw = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = [raw]

        if et == "CALL":
            for node_id in raw:
                if isinstance(node_id, dict):
                    nid = str(node_id.get("id", ""))
                else:
                    nid = str(node_id)
                if _bad_id(nid):
                    continue
                nid = nid.replace('\\', '/')
                clean = nid.split(':')[0] if ':' in nid else nid
                if clean and clean not in nodes:
                    label = clean.split("/")[-1] if "/" in clean else clean
                    nodes[clean] = {"id": clean, "label": label, "commId": cid, "commLv": clv}
        else:
            for node_id in raw:
                if isinstance(node_id, dict):
                    nid = str(node_id.get("id", "")).replace('\\', '/')
                    label = node_id.get("name", "") or nid.split("/")[-1] if "/" in nid else nid
                else:
                    nid = str(node_id).replace('\\', '/')
                    label = nid.split("/")[-1] if "/" in nid else nid
                if _bad_id(nid):
                    continue
                nid = _rel(nid)
                if nid and nid not in nodes:
                    nodes[nid] = {"id": nid, "label": label, "commId": cid, "commLv": clv}
    return nodes


def extract_file_edges(raw_rows, et: str, _rel, existing_nodes: dict):
    """从 graph_doc 行提取文件级边"""
    edges = {}
    nodes = dict(existing_nodes)

    def _add_node(fid, cid, clv):
        if fid not in nodes:
            fid = fid.replace('\\', '/')
            label = fid.split("/")[-1] if "/" in fid else fid
            nodes[fid] = {"id": fid, "label": label, "commId": cid, "commLv": clv}

    for r in raw_rows:
        cid = r["comm_id"]
        clv = r["comm_lv"]
        try:
            raw = json.loads(r["edge_list"]) if isinstance(r["edge_list"], str) else r["edge_list"] or []
        except Exception:
            raw = []
        if not isinstance(raw, list):
            raw = [raw]

        if et == "CALL":
            for edge in raw:
                if isinstance(edge, dict):
                    src, tgt = edge.get("source", ""), edge.get("target", "")
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    src, tgt = edge[0], edge[1]
                else:
                    continue
                s = _rel(str(src))
                t = _rel(str(tgt))
                if not s or not t:
                    continue
                s = s.split(':')[0] if ':' in s else s
                t = t.split(':')[0] if ':' in t else t
                if _bad_id(s) or _bad_id(t) or s == t:
                    continue
                eid = f"{s}\u2192{t}"
                if eid not in edges:
                    edges[eid] = {"id": eid, "source": s, "target": t}
                _add_node(s, cid, clv)
                _add_node(t, cid, clv)
        else:
            for edge in raw:
                if isinstance(edge, dict):
                    src, tgt = edge.get("source", ""), edge.get("target", "")
                elif isinstance(edge, (list, tuple)) and len(edge) >= 2:
                    src, tgt = edge[0], edge[1]
                else:
                    continue
                s = _rel(str(src))
                t = _rel(str(tgt))
                if not s or not t or s == t:
                    continue
                eid = f"{s}\u2192{t}"
                if eid not in edges:
                    edges[eid] = {"id": eid, "source": s, "target": t}
                _add_node(s, cid, clv)
                _add_node(t, cid, clv)

    return list(edges.values()), nodes


def build_file_comm_map(raw_rows, _rel):
    """构建 file_path → {commId, commLv} 映射 (从 graph_doc node_list)"""
    fcomm = {}
    for r in raw_rows:
        cid = r["comm_id"]
        try:
            nlist = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
        except Exception:
            nlist = []
        for n in (nlist if isinstance(nlist, list) else [nlist]):
            if isinstance(n, dict):
                key = str(n.get("id", ""))
            elif isinstance(n, str):
                key = n
            else:
                continue
            fp = _rel(key)
            if fp:
                clean = fp.split(':')[0] if ':' in fp else fp
                if clean and clean not in fcomm:
                    fcomm[clean] = cid
    return fcomm


def extract_cross_file_edges(db, task_id: str, et: str,
                              file_comm: dict, _rel,
                              hash_to_path: dict = None):
    """从 graph_edge 提取跨社区文件级边 (补充 graph_doc 中不存在的跨社区边)"""
    kind = "imports" if et == "INCLUDE" else "calls"
    all_ge = db.fetchall(
        "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
        (task_id, kind)
    )
    edges = {}
    nodes = {}
    hp = hash_to_path or {}

    for e in all_ge:
        src = _rel(e["source_id"] or "")
        tgt = _rel(e["target_id"] or "")
        if not src or not tgt:
            continue
        if ':' in src:
            src = src.split(':')[0]
        if ':' in tgt:
            tgt = tgt.split(':')[0]
        src = hp.get(src, src)
        tgt = hp.get(tgt, tgt)
        src_comm = file_comm.get(src)
        tgt_comm = file_comm.get(tgt)
        if not src_comm or not tgt_comm:
            continue
        eid = f"{src}\u2192{tgt}"
        if eid not in edges:
            edges[eid] = {"id": eid, "source": src, "target": tgt}
        if src not in nodes:
            nodes[src] = {"id": src, "label": src.split("/")[-1] if "/" in src else src,
                          "commId": src_comm or "", "commLv": ""}
        if tgt not in nodes:
            nodes[tgt] = {"id": tgt, "label": tgt.split("/")[-1] if "/" in tgt else tgt,
                          "commId": tgt_comm or "", "commLv": ""}

    return list(edges.values()), nodes


def extract_cross_comm_file_edges(task_id: str, et: str,
                                   file_comm: dict, _rel,
                                   all_ge: list,
                                   hash_to_path: dict = None):
    """提取跨社区文件级边 (仅保留不同社区的边, pre-fetched all_ge)"""
    edges = {}
    nodes = {}
    hp = hash_to_path or {}

    for e in all_ge:
        src = _rel(e["source_id"] or "")
        tgt = _rel(e["target_id"] or "")
        if not src or not tgt:
            continue
        if ':' in src:
            src = src.split(':')[0]
        if ':' in tgt:
            tgt = tgt.split(':')[0]
        src = hp.get(src, src)
        tgt = hp.get(tgt, tgt)
        src_comm = file_comm.get(src)
        tgt_comm = file_comm.get(tgt)
        if not src_comm or not tgt_comm or src_comm == tgt_comm:
            continue
        eid = f"{src}\u2192{tgt}"
        if eid not in edges:
            edges[eid] = {"id": eid, "source": src, "target": tgt}
        if src not in nodes:
            nodes[src] = {"id": src, "label": src.split("/")[-1] if "/" in src else src,
                          "commId": src_comm or "", "commLv": _cid_level(src_comm)}
        if tgt not in nodes:
            nodes[tgt] = {"id": tgt, "label": tgt.split("/")[-1] if "/" in tgt else tgt,
                          "commId": tgt_comm or "", "commLv": _cid_level(tgt_comm)}

    return list(edges.values()), nodes


def resolve_call_symbols(db, task_id: str, all_ge: list, _rel):
    """从 graph_edge CALL 边提取需要解析的符号 hash → file_path"""
    if not all_ge:
        return {}
    hash_ids = set()
    for e in all_ge:
        for col in ("source_id", "target_id"):
            val = e[col] or ""
            if not val:
                continue
            clean = _rel(val)
            if not clean:
                continue
            if ":" in clean:
                clean = clean.split(":")[0]
            if clean and "/" not in clean:
                hash_ids.add(clean)
    if not hash_ids:
        return {}
    result = {}
    sym_list = list(hash_ids)
    batch_size = 900
    for i in range(0, len(sym_list), batch_size):
        batch = sym_list[i:i + batch_size]
        placeholders = ",".join(["?"] * len(batch))
        rows = db.fetchall(
            f"SELECT id, file_path FROM graph_node WHERE task_id=? AND id IN ({placeholders})",
            (task_id, *batch)
        )
        for row in rows:
            fp = row["file_path"] or ""
            if fp:
                result[row["id"]] = _rel(fp)
    return result


# ═══════════════════════════════════════════════════════
# L2 — 外部依赖/调用提取
# ═══════════════════════════════════════════════════════

def extract_external_deps(db, task_id: str):
    """未解析的 import — 外部依赖 (匹配 getExternalStats)"""
    import_nodes = db.fetchall(
        "SELECT name, file_path FROM graph_node WHERE task_id=? AND kind='import'",
        (task_id,)
    )
    edge_rows = db.fetchall(
        """SELECT gn_src.file_path, json_extract(ge.metadata, '$.module') AS module
           FROM graph_edge ge
           JOIN graph_node gn_src
             ON gn_src.id = ge.source_id AND gn_src.task_id = ge.task_id
           WHERE ge.task_id = ? AND ge.kind = 'imports'""",
        (task_id,)
    )
    resolved = set()
    for er in edge_rows:
        fp = er["file_path"] or ""
        mod = er["module"] or ""
        if fp and mod:
            resolved.add((fp, mod))

    dep_map = {}
    for imp in import_nodes:
        pkg = imp["name"] or ""
        fp = imp["file_path"] or ""
        if not pkg or (fp, pkg) in resolved:
            continue
        if pkg not in dep_map:
            dep_map[pkg] = {"package": pkg, "fileCount": 0, "files": []}
        dep_map[pkg]["fileCount"] += 1
        if fp not in dep_map[pkg]["files"]:
            dep_map[pkg]["files"].append(fp)

    return sorted(dep_map.values(), key=lambda x: -x["fileCount"])[:100]


def extract_external_calls(db, task_id: str):
    """target_id 为空的 calls — 外部调用 (匹配 getExternalStats)"""
    rows = db.fetchall(
        """SELECT ge.source_id, gn.file_path, ge.metadata
           FROM graph_edge ge
           LEFT JOIN graph_node gn
             ON gn.id = ge.source_id AND gn.task_id = ge.task_id
           WHERE ge.task_id = ? AND ge.kind = 'calls' AND ge.target_id = ''""",
        (task_id,)
    )
    call_map = {}
    for row in rows:
        sid = (row["source_id"] or "").replace('\\', '/')
        fp = (row["file_path"] or sid).replace('\\', '/')
        meta_str = row["metadata"] or "{}"
        try:
            meta = json.loads(meta_str)
        except Exception:
            meta = {}
        name = meta.get("expression") or meta.get("callee") or ""
        if not name:
            if sid.startswith("file:"):
                basename = sid.split("/")[-1] if "/" in sid else sid
                if basename in ("__init__.py", "__init__.ts", "__init__.js",
                                "index.ts", "index.js", "index.tsx", "index.jsx"):
                    parts = sid.replace("file:", "", 1).split("/")
                    name = parts[-2] if len(parts) >= 2 else basename
                else:
                    name = basename
            elif fp and fp != sid:
                name = fp
            else:
                name = sid[:16]
        if name not in call_map:
            call_map[name] = {"name": name, "count": 0, "files": []}
        call_map[name]["count"] += 1
        if fp not in call_map[name]["files"]:
            call_map[name]["files"].append(fp)

    return sorted(call_map.values(), key=lambda x: -x["count"])[:100]


# ═══════════════════════════════════════════════════════
# L3 — 聚合/过滤
# ═══════════════════════════════════════════════════════

def _short_cid(cid: str) -> str:
    """社区 ID 缩短: level + 全部序列段"""
    parts = cid.split("-")
    lv = None
    seqs = []
    for p in parts:
        if re.match(r'^L\d+$', p):
            if lv is None:
                lv = p
        elif re.match(r'^\d+$', p):
            seqs.append(p)
    if lv and seqs:
        return f"{lv}-{'-'.join(seqs)}"
    return "-".join(parts[-2:]) if len(parts) >= 2 else cid


def aggregate_to_community_graph(file_nodes: list, file_edges: list,
                                  comm_meta: list):
    """文件级数据 → 社区级节点 + 跨社区边"""
    node_map = {n["id"]: n.get("commId", "") for n in file_nodes if n.get("commId")}
    comm_name = {c["commId"]: c.get("name", c["commId"]) for c in comm_meta}

    comm_nodes = {}
    for n in file_nodes:
        cid = n.get("commId")
        if cid and cid not in comm_nodes:
            comm_nodes[cid] = {"id": cid, "label": comm_name.get(cid, cid),
                               "commLv": n.get("commLv", "")}

    comm_edges = {}
    for e in file_edges:
        sc = node_map.get(e["source"])
        tc = node_map.get(e["target"])
        if sc and tc and sc != tc:
            a, b = sorted([sc, tc])
            eid = f"{_short_cid(a)}\u2194{_short_cid(b)}"
            if eid not in comm_edges:
                comm_edges[eid] = {"id": eid, "source": a, "target": b,
                                    "bidirectional": (sc != a)}
            elif not comm_edges[eid]["bidirectional"]:
                comm_edges[eid]["bidirectional"] = True

    return (list(comm_nodes.values()), list(comm_edges.values()))


def build_heatmap_matrix(db, task_id: str, et: str, comm_lv: str,
                          _rel):
    """构建 community×community 热力图矩阵"""
    doc_rows = db.fetchall(
        "SELECT comm_id, node_list FROM graph_doc "
        "WHERE task_id=? AND edge_type=? AND comm_lv=?",
        (task_id, et, comm_lv)
    )
    if not doc_rows:
        return {"rows": [], "cols": [], "matrix": [], "maxCount": 0}

    node_comm = {}
    comm_order = []
    for r in doc_rows:
        cid = r["comm_id"]
        comm_order.append(cid)
        try:
            nodes = json.loads(r["node_list"]) if r["node_list"] else []
        except Exception:
            nodes = []
        for n in (nodes if isinstance(nodes, list) else [nodes]):
            key = n["id"] if isinstance(n, dict) else str(n)
            if key:
                node_comm[key] = cid

    name_rows = db.fetchall(
        "SELECT comm_id, name FROM community_llm_results "
        "WHERE task_id=? AND edge_type=? AND comm_lv=?",
        (task_id, et, comm_lv)
    )
    name_map = {r["comm_id"]: r["name"] or r["comm_id"] for r in name_rows}
    comm_names = [name_map.get(cid, cid) for cid in comm_order]

    kind = "imports" if et == "INCLUDE" else "calls"
    all_edges = db.fetchall(
        "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
        (task_id, kind)
    )

    sym_map = {}
    if et == "CALL":
        sym_ids = set()
        for e in all_edges:
            if e["source_id"]: sym_ids.add(e["source_id"])
            if e["target_id"]: sym_ids.add(e["target_id"])
        if sym_ids:
            sym_list = list(sym_ids)
            batch_size = 900
            for i in range(0, len(sym_list), batch_size):
                batch = sym_list[i:i + batch_size]
                placeholders = ",".join("?" * len(batch))
                rows = db.fetchall(
                    f"SELECT id, file_path FROM graph_node "
                    f"WHERE task_id=? AND id IN ({placeholders})",
                    [task_id] + batch
                )
                for gr in rows:
                    sym_map[gr["id"]] = gr["file_path"] or ""

    n = len(comm_order)
    comm_index = {cid: i for i, cid in enumerate(comm_order)}
    matrix = [[0] * n for _ in range(n)]

    for e in all_edges:
        src_raw = e["source_id"] or ""
        tgt_raw = e["target_id"] or ""
        if not src_raw or not tgt_raw:
            continue
        if et == "INCLUDE":
            src_key = _rel(src_raw)
            tgt_key = _rel(tgt_raw)
        else:
            src_key = _rel(sym_map.get(src_raw, ""))
            tgt_key = _rel(sym_map.get(tgt_raw, ""))
        src_comm = node_comm.get(src_key)
        tgt_comm = node_comm.get(tgt_key)
        if src_comm and tgt_comm and src_comm != tgt_comm:
            si = comm_index.get(src_comm)
            ti = comm_index.get(tgt_comm)
            if si is not None and ti is not None:
                matrix[si][ti] += 1

    max_count = max(max(row) for row in matrix) if n > 0 else 0
    return {
        "rows": comm_names, "cols": comm_names,
        "matrix": matrix, "maxCount": max_count,
        "commIds": comm_order
    }


def _build_file_comm_for_external(db, task_id: str, et: str, _rel):
    """构建 file → [{communityId}] 映射 (用于外部统计)"""
    rows = db.fetchall(
        "SELECT comm_id, node_list FROM graph_doc "
        "WHERE task_id=? AND edge_type=?",
        (task_id, et)
    )
    fcomm = {}
    for r in rows:
        cid = r["comm_id"]
        try:
            nodes = json.loads(r["node_list"]) if r["node_list"] else []
        except Exception:
            nodes = []
        for fp in (nodes if isinstance(nodes, list) else [nodes]):
            key = str(fp) if isinstance(fp, str) else str(fp.get("id", ""))
            key = _rel(key)
            if not key:
                continue
            if key not in fcomm:
                fcomm[key] = []
            if not any(x["communityId"] == cid for x in fcomm[key]):
                fcomm[key].append({"communityId": cid})
    return fcomm


def inject_community_names(items: list, db, task_id: str, et: str):
    """为外部统计项附加 community 归属名称"""
    rows = db.fetchall(
        "SELECT comm_id, name FROM community_llm_results "
        "WHERE task_id=? AND comm_lv='L0'",
        (task_id,)
    )
    comm_names = {r["comm_id"]: r["name"] for r in rows if r["name"]}

    # Build file→comm maps for both edge types
    # We need project_root for _rel — but get_external_stats provides it via the wrapper
    pass  # Implemented inline in get_external_stats for simplicity


# ═══════════════════════════════════════════════════════
# L4 — 端到端函数
# ═══════════════════════════════════════════════════════

def get_community_graph_file(db, task_id: str, edge_type: str,
                              comm_lv: str, comm_id: str = '',
                              project_root: str = ''):
    """文件级社区图: graph_doc 节点 + edge_list 边"""
    _rel = _make_rel(project_root)
    rows = read_graph_doc_rows(db, task_id, edge_type, comm_lv, comm_id)
    if not rows:
        return {"nodes": [], "edges": [], "commIds": []}

    name_map = read_community_names(db, task_id, edge_type)

    nodes = extract_file_nodes(rows, edge_type, _rel, name_map)
    edge_list, nodes = extract_file_edges(rows, edge_type, _rel, nodes)

    comm_ids_meta = []
    for r in rows:
        cid = r["comm_id"]
        comm_ids_meta.append({
            "commId": cid, "commLv": r["comm_lv"],
            "name": name_map.get(cid, cid)
        })

    return {
        "nodes": list(nodes.values()),
        "edges": edge_list,
        "commIds": comm_ids_meta
    }


def get_community_graph_component(db, task_id: str, edge_type: str,
                                   comm_lv: str, comm_id: str = '',
                                   project_root: str = '',
                                   depth: int = 1):
    """组件级社区图: graph_doc 节点 + graph_edge 跨社区边. depth 控制展开层数"""
    _rel = _make_rel(project_root)

    # 下钻模式：查子社区
    # 下钻模式：查子社区
    if comm_id:
        rows = read_graph_doc_children(db, task_id, edge_type, comm_id)
        if not rows:
            rows = read_graph_doc_rows(db, task_id, edge_type, '', comm_id)
        if not rows:
            inferred = _infer_edge_type(comm_id)
            if inferred and inferred != edge_type:
                rows = read_graph_doc_children(db, task_id, inferred, comm_id) or \
                       read_graph_doc_rows(db, task_id, inferred, '', comm_id) or []
                if rows:
                    edge_type = inferred  # 更新下游使用的边类型
    else:
        rows = read_graph_doc_rows(db, task_id, edge_type, comm_lv, comm_id)

    # depth > 1: 递归展开子社区
    rows = expand_communities_to_depth(db, task_id, edge_type, rows, depth)
    if not rows:
        return {"nodes": [], "edges": [], "commIds": []}

    name_map = read_community_names(db, task_id, edge_type)

    # 文件节点 (需要 commId 元数据)
    nodes = extract_file_nodes(rows, edge_type, _rel, name_map)

    # 文件→社区映射 (下钻: 子社区范围; 全局: 当前层级全部)
    file_comm = build_file_comm_map(rows, _rel)

    # graph_edge 跨社区边 + hash 解析 (一次查询，复用)
    kind = "imports" if edge_type == "INCLUDE" else "calls"
    all_ge = read_graph_edges(db, task_id, kind)
    hash_to_path = resolve_call_symbols(db, task_id, all_ge, _rel) if edge_type == "CALL" else {}

    cross_edges, cross_nodes = extract_cross_comm_file_edges(
        task_id, edge_type, file_comm, _rel,
        all_ge, hash_to_path
    )
    for fid, nd in cross_nodes.items():
        if fid not in nodes:
            nodes[fid] = nd

    file_data = {"nodes": list(nodes.values()), "edges": cross_edges}
    comm_nodes, comm_edges = aggregate_to_community_graph(
        file_data["nodes"], file_data["edges"],
        [{"commId": k, "name": v} for k, v in name_map.items()])
    # 节点数上限检查
    MAX_NODES = 5000
    if len(comm_nodes) > MAX_NODES:
        return {
            "nodes": [], "edges": [], "commIds": [],
            "error": True,
            "message": f"\u8282\u70b9\u6570\u8d85\u8fc7{MAX_NODES}\uff0c\u8bf7\u7f29\u5c0f\u67e5\u8be2\u8303\u56f4\uff08\u9009\u62e9\u66f4\u5177\u4f53\u7684\u793e\u533a\uff09\u6216\u964d\u4f4e\u751f\u6210\u6df1\u5ea6\uff08depth\uff09"
        }
    # hasChildren + parentId: 全量层级映射 (一次查询, 语义同 read_community_hierarchy_maps)
    parent_of, children_of = read_community_hierarchy_maps(db, task_id, edge_type)
    for n in comm_nodes:
        n["hasChildren"] = n["id"] in children_of
        n["parentId"] = parent_of.get(n["id"], '')
    # commIds — 仅含最终图中出现的社区
    comm_ids_meta = []
    for n in comm_nodes:
        cid = n["id"]
        comm_ids_meta.append({
            "commId": cid, "commLv": n.get("commLv", ""),
            "name": n["label"]
        })
    return {
        "nodes": comm_nodes,
        "edges": comm_edges,
        "commIds": comm_ids_meta
    }


def get_external_stats(db, task_id: str, project_root: str = ''):
    """外部依赖/调用 — 完整数据 (匹配 get_external_stats)"""
    external_deps = extract_external_deps(db, task_id)
    external_calls = extract_external_calls(db, task_id)

    _rel = _make_rel(project_root)

    # 附加社区归属 (L0)
    include_fcomm = _build_file_comm_for_external(db, task_id, "INCLUDE", _rel)
    call_fcomm = _build_file_comm_for_external(db, task_id, "CALL", _rel)

    name_rows = db.fetchall(
        "SELECT comm_id, name FROM community_llm_results "
        "WHERE task_id=?",
        (task_id,)
    )
    comm_names = {r["comm_id"]: r["name"] for r in name_rows if r["name"]}

    def _inject(items, fcomm):
        for item in items:
            item_files = item.get("files", [])
            item_comms = []
            seen = set()
            for f in item_files:
                for c in fcomm.get(_rel(f), []):
                    cid = c["communityId"]
                    if cid not in seen:
                        seen.add(cid)
                        item_comms.append({
                            "communityId": cid,
                            "name": comm_names.get(cid) or None
                        })
            item["communities"] = item_comms

    _inject(external_deps, include_fcomm)
    _inject(external_calls, call_fcomm)

    return {
        "externalDeps": external_deps,
        "externalCalls": external_calls,
        "totalExternalDeps": len(external_deps),
        "totalExternalCalls": len(external_calls),
    }


def get_community_children(db, task_id: str, edge_type: str,
                            parent_comm_id: str = None):
    """社区子节点列表 (匹配社区层级查询)"""
    fallback_types = ['CALL', 'INCLUDE']
    if edge_type and edge_type in fallback_types:
        fallback_types.remove(edge_type)

    for attempt_et in ([edge_type] if edge_type else []) + fallback_types:
        result = read_community_hierarchy(db, task_id, attempt_et, parent_comm_id or None)
        if result:
            return result

    # 空 parent = 查顶级
    if not parent_comm_id:
        return read_community_hierarchy(db, task_id, edge_type, None)
    return []


def get_cascade_levels(db, task_id: str, edge_type: str):
    """返回级联层级结构"""
    return {"levels": read_cascade_levels(db, task_id, edge_type)}


def get_heatmap(db, task_id: str, edge_type: str,
                project_root: str = '', comm_lv: str = 'L0',
                size: int = 10):
    """返回热力图数据"""
    _rel = _make_rel(project_root)
    result = build_heatmap_matrix(db, task_id, edge_type, comm_lv, _rel)
    result["size"] = size
    return result


def _cid_level_backend(cid: str) -> str:
    """提取社区 ID 中的层级标记"""
    parts = cid.split('-')
    for p in parts:
        if re.match(r'^L\d+$', p):
            return p
    return 'L0'


def _parse_node_list(node_list):
    """安全解析 graph_doc.node_list JSON"""
    try:
        nlist = json.loads(node_list) if node_list else []
    except Exception:
        nlist = []
    if not isinstance(nlist, list):
        nlist = [nlist]
    return nlist


def get_external_graph(db, task_id: str, edge_type: str,
                       depth: int = 1, comm_id: str = '',
                       project_root: str = ''):
    """
    外部依赖/调用图 — 后端聚合，前端单接口消费

    Depth 语义 (与内部图统一):
       根视图: depth=N → 显示 L0 ~ L(N-1) 层社区
       下钻:   depth=N → 从 drilled community 所在层级起，向下 N 层

    Drill 语义:
       将图范围限定在 drilled community 的子树内 (parent_comm_id 追溯)
    """
    base_et = edge_type.replace("EXTERNAL_", "")
    _rel = _make_rel(project_root)

    # ── 1. 提取外部项 ──
    items = extract_external_deps(db, task_id) if base_et == "INCLUDE" \
            else extract_external_calls(db, task_id)
    if not items:
        return {"nodes": [], "edges": []}

    # ── 2. 单次加载社区全量数据 ──
    rows = db.fetchall(
        "SELECT comm_id, comm_lv, parent_comm_id, node_list FROM graph_doc "
        "WHERE task_id=? AND edge_type=?",
        (task_id, base_et)
    )

    # 倒排索引: rel_path → set(cid)
    file_cids = {}
    for r in rows:
        cid = r["comm_id"]
        for node in _parse_node_list(r["node_list"]):
            key = _rel(str(node) if isinstance(node, str) else str(node.get("id", "")))
            if key:
                file_cids.setdefault(key, set()).add(cid)

    # 树索引: 统一走 read_community_hierarchy_maps
    parent_of, children_of = read_community_hierarchy_maps(db, task_id, base_et)

    # 社区名称
    name_rows = db.fetchall(
        "SELECT comm_id, name FROM community_llm_results WHERE task_id=?",
        (task_id,)
    )
    comm_names = {r["comm_id"]: r["name"] or r["comm_id"] for r in name_rows}

    # ── 3. 过滤 ──
    drill_cv = int(_cid_level_backend(comm_id)[1:]) if comm_id else 0
    max_lv = drill_cv + depth - 1  # 允许的最高绝对层级

    def _in_subtree(cid):
        """cid 是否在 drilled community 的子树内（含自身）"""
        if not comm_id:
            return True
        cur = cid
        while True:
            if cur == comm_id:
                return True
            if cur not in parent_of:
                break
            cur = parent_of[cur]
        return False

    visible = {}  # ext_id → set(cid)
    for item in items:
        ext_id = "ext-" + (item.get("package") or item.get("name"))
        cids = set()
        for f in item.get("files", []):
            for cid in file_cids.get(_rel(f), ()):
                cv = int(_cid_level_backend(cid)[1:])
                if cv > max_lv:
                    continue
                if not _in_subtree(cid):
                    continue
                cids.add(cid)
        if cids:
            visible[ext_id] = cids

    # ── 4. 序列化 ──
    nodes = {}
    edges = []

    def _add_node(nid, label, is_ext, lv='L0'):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "label": label, "isExternal": is_ext, "commLv": lv}

    for ext_id, cids in visible.items():
        label = ext_id[4:]  # strip "ext-"
        _add_node(ext_id, label, True, 'L0')
        for cid in sorted(cids):
            _add_node(cid, comm_names.get(cid, cid), False, _cid_level_backend(cid))
            edges.append({"id": f"{ext_id}->{cid}", "source": ext_id, "target": cid})

    # hasChildren + parentId
    for nid in list(nodes.keys()):
        nodes[nid]["parentId"] = parent_of.get(nid, '')
        if not nodes[nid].get("isExternal"):
            nodes[nid]["hasChildren"] = nid in children_of

    return {"nodes": list(nodes.values()), "edges": edges}
