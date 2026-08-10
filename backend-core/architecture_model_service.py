"""architecture.model — 从 KB 分析图为项目构建真实架构模型 (KB-REQ-17 组件索引接管)。

数据来源（项目库 project.db）：
  - graph_doc        ：分层社区（L0/L1, INCLUDE），node_list=社区文件清单
  - community_llm_results：社区 LLM 名称/摘要/组件类型
  - graph_edge       ：imports 跨社区引用边 → dependsOn
  - source_files     ：文件语言
  - graph_node       ：符号行号 → codeMappings
  - project_versions ：版本差异 → change 归属

语义与 kb-contract 对齐：只读，不写；architect 经 data_api /zmq/architecture.model 调用。
返回形状与 architect 消费的架构模型一致（components / erTables / ormMappings /
entityClasses / executionFlows / dataFlows）。
"""
from __future__ import annotations

import json
import logging
import os
import re

logger = logging.getLogger(__name__)

_MODEL_KEYS = ("components", "erTables", "ormMappings", "entityClasses",
               "executionFlows", "dataFlows")

_KIND_HINTS = (
    (("routes",), "service"),
    (("service", "services"), "service"),
    (("model", "models", "dal", "repo", "repository"), "data"),
    (("config", "conf", "const", "enum", "common", "util", "utils", "helper"), "shared"),
    (("main", "app", "bootstrap", "entry", "server", "worker", "cron"), "entry"),
)

_GENERIC_LLM_KINDS = {"community", "component", "", None}


def _empty_model() -> dict:
    return {k: [] for k in _MODEL_KEYS}


def _rel(root: str, p: str) -> str:
    """file:/abs → rel（相对项目根）。"""
    if not p:
        return p
    if p.startswith("file:"):
        p = p[5:]
    p = p.replace("\\", "/")
    if root and p.lower().startswith(root.lower()):
        p = p[len(root):]
    return p.lstrip("/")


def _infer_kind(files) -> str:
    if files:
        for kw, kind in _KIND_HINTS:
            for f in files:
                if any(seg in f.lower() for seg in kw):
                    return kind
    return "service"


def _derive_name(comm_id: str, files) -> str:
    """社区名：优先 LLM 名；否则按文件路径族取名。"""
    # 取文件共同路径段族：e.g. routes/* → "routes"
    rels = [f for f in files if f]
    if rels:
        dirs = [os.path.dirname(f) for f in rels if os.path.dirname(f)]
        if dirs:
            # 多数目录的首段作为族名
            heads = [d.split("/")[0] for d in dirs]
            if heads:
                common = max(set(heads), key=heads.count)
                return common or comm_id
    return comm_id


def _community_change(file_change: dict, files) -> str:
    """按版本差异归属组件 change。无 ≥2 个版本 → same(纯基线)。

    change ∈ added | modified | same：
      - 组件内文件全部为 added 且存在新增 → added
      - 组件内存在 added/modified 文件 → modified
      - 其余 → same
    """
    rels = set(files)
    if not rels:
        return "same"
    states = {file_change.get(f, "same") for f in rels}
    if states <= {"added"}:
        return "added"
    if states & {"added", "modified"}:
        return "modified"
    return "same"


def build_architecture_model(multi_db, project_id: str, *,
                             task_id: str = "", level: str = "L1",
                             edge_type: str = "INCLUDE") -> dict:
    """为 KB 项目构建真实架构模型。任务/社区缺失时返回空模型（不抛异常）。"""
    if not project_id:
        return _empty_model()

    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT id, root_path FROM projects WHERE id = ?", (project_id,))
    if not project:
        return _empty_model()
    root = project.get("root_path") or ""

    # 最新 done 任务
    tid = task_id
    if not tid:
        row = main_db.fetchone(
            "SELECT id FROM analysis_tasks WHERE project_id = ? AND status = 'done' "
            "ORDER BY created_at DESC LIMIT 1", (project_id,))
        tid = row["id"] if row else None
    if not tid:
        return _empty_model()

    try:
        project_db = multi_db.get_project_db(project_id)
    except Exception as e:
        logger.warning("[architecture.model] project db unavailable: %s", e)
        return _empty_model()

    et = (edge_type or "INCLUDE").upper()
    lv = (level or "L1").upper()

    # ── 社区（L1 优先，空则 L0） ─────────────────────────────
    rows = project_db.fetchall(
        "SELECT comm_id, comm_lv, node_list, edge_list, description "
        "FROM graph_doc WHERE task_id = ? AND edge_type = ? AND comm_lv = ? "
        "ORDER BY quality_score DESC", (tid, et, lv))
    if not rows and lv != "L0":
        rows = project_db.fetchall(
            "SELECT comm_id, comm_lv, node_list, edge_list, description "
            "FROM graph_doc WHERE task_id = ? AND edge_type = ? AND comm_lv = 'L0' "
            "ORDER BY quality_score DESC", (tid, et))
    if not rows:
        return _empty_model()

    # ── LLM 名称/摘要/类型 ───────────────────────────────────
    llm = {}
    try:
        for r in project_db.fetchall(
                "SELECT comm_id, name, summary, component_type FROM community_llm_results "
                "WHERE task_id = ? AND edge_type = ?", (tid, et)):
            llm[r["comm_id"]] = r
    except Exception:
        pass

    # ── 语言 ────────────────────────────────────────────────
    lang_of = {}
    try:
        for r in project_db.fetchall("SELECT file_path, language FROM source_files"):
            lang_of.setdefault(_rel(root, r["file_path"]), r["language"] or "")
    except Exception:
        pass

    # 文件 → 社区
    file_comm = {}
    # 社区 → 文件
    comm_files: dict = {}
    for row in rows:
        cid = row["comm_id"]
        try:
            node_list = row.get("node_list")
            files = json.loads(node_list) if isinstance(node_list, str) else (node_list or [])
        except Exception:
            files = []
        rel_files = [_rel(root, f) for f in files]
        rel_files = [f for f in rel_files if f]
        comm_files[cid] = rel_files
        for f in rel_files:
            file_comm[f] = cid

    # ── imports 跨社区边 → dependsOn ───────────────────────
    dep_edges = []
    try:
        for r in project_db.fetchall(
                "SELECT source_id, target_id FROM graph_edge "
                "WHERE task_id = ? AND kind = 'imports'", (tid,)):
            src = _rel(root, r["source_id"])
            tgt = _rel(root, r["target_id"])
            if src and tgt and file_comm.get(src) and file_comm.get(tgt):
                dep_edges.append((file_comm[src], file_comm[tgt]))
    except Exception:
        pass
    depends_on: dict = {}
    for a, b in dep_edges:
        if a != b:
            depends_on.setdefault(a, set()).add(b)

    # ── 版本差异 change ─────────────────────────────────────
    versions = []
    try:
        import version_sync_service as vss
        versions = vss.list_versions(multi_db, project_id)
    except Exception:
        versions = []
    file_change: dict = {}
    if len(versions) >= 2:
        try:
            import version_sync_service as vss
            diff = vss.diff_versions(multi_db, project_id,
                                     versions[-1]["id"], versions[0]["id"])
            for f in diff.get("added") or []:
                file_change[_rel(root, f)] = "added"
            for f in diff.get("modified") or []:
                file_change[_rel(root, f)] = "modified"
        except Exception as e:
            logger.warning("[architecture.model] version diff failed: %s", e)

    # ── 符号行号 → codeMappings ─────────────────────────────
    line_of: dict = {}
    try:
        for r in project_db.fetchall(
                "SELECT file_path, MIN(start_line) AS line FROM graph_node "
                "WHERE task_id = ? AND kind != 'file' GROUP BY file_path", (tid,)):
            rel = _rel(root, r["file_path"])
            line_of[rel] = int(r["line"] or 1)
    except Exception:
        pass

    components = []
    code_mappings = []
    for order, row in enumerate(rows):
        cid = row["comm_id"]
        files = comm_files.get(cid, [])
        meta = llm.get(cid)
        name = ((meta.get("name") if meta and meta.get("name") else "")
                or _derive_name(cid, files))
        if (meta and meta.get("summary")):
            summary = meta["summary"]
        elif row.get("description"):
            summary = row["description"]
        else:
            summary = ""
        resp = [f.split("/")[-1].rsplit(".", 1)[0] for f in files if f][:6]
        llm_kind = meta and meta.get("component_type")
        kind = llm_kind if llm_kind not in _GENERIC_LLM_KINDS else _infer_kind(files)
        comp = {
            "id": cid,
            "name": name,
            "kind": kind,
            "desc": (summary or "").strip()[:400],
            "lang": _lang_from(lang_of, files),
            "change": _community_change(file_change, files),
            "responsibilities": resp or ["（社区无文件）"],
            "owns": files,
            "dependsOn": sorted(depends_on.get(cid, [])),
            "order": order,
        }
        components.append(comp)
        for f in files[:8]:
            code_mappings.append({
                "id": f"cm-{cid}-{_slug(f)}",
                "targetType": "component", "targetId": cid, "targetName": name,
                "file": f, "line": f"L{line_of.get(f, 1)}",
                "level": "logical", "note": name,
            })

    # 按 order 排序后脱去内部字段
    components.sort(key=lambda c: c.get("order", 0))
    for c in components:
        c.pop("order", None)

    entity_classes = []
    return {
        "components": components,
        "codeMappings": code_mappings,
        "entityClasses": entity_classes,
        "erTables": [],
        "ormMappings": [],
        "executionFlows": [],
        "dataFlows": [],
    }


def build_component_catalog(multi_db, project_id: str, *,
                            task_id: str = "") -> dict:
    """组件目录（选择器专用）：合并 依赖分析(INCLUDE) 与 调用分析(CALL)、
    以及 L0/L1 两层社区，附带父组件 / 文件数 / 类型等元数据。

    返回 { components: [...], edgeTypes: [...], levels: [...] }，
    供 `/kb/assets/search` 做「按类型 / 层级」筛选与列表信息展示。
    """
    if not project_id:
        return {"components": [], "edgeTypes": [], "levels": []}

    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT id, root_path FROM projects WHERE id = ?", (project_id,))
    if not project:
        return {"components": [], "edgeTypes": [], "levels": []}
    root = project.get("root_path") or ""

    tid = task_id
    if not tid:
        row = main_db.fetchone(
            "SELECT id FROM analysis_tasks WHERE project_id = ? AND status = 'done' "
            "ORDER BY created_at DESC LIMIT 1", (project_id,))
        tid = row["id"] if row else None
    if not tid:
        return {"components": [], "edgeTypes": [], "levels": []}

    try:
        project_db = multi_db.get_project_db(project_id)
    except Exception as e:
        logger.warning("[architecture.catalog] project db unavailable: %s", e)
        return {"components": [], "edgeTypes": [], "levels": []}

    # ── 全量社区：跨 edge_type × comm_lv ──────────────────────────────
    edge_types = ["INCLUDE", "CALL"]
    levels = ["L0", "L1"]
    rows = []
    try:
        rows = project_db.fetchall(
            "SELECT comm_id, comm_lv, parent_comm_id, node_list, edge_list, "
            "file_count, edge_count, node_count, description "
            "FROM graph_doc WHERE task_id = ? ORDER BY quality_score DESC",
            (tid,))
    except Exception:
        pass

    # ── LLM 名称 / 摘要 / 类型(按 comm_id 去重，忽略分析类型差异) ──
    llm = {}
    try:
        for r in project_db.fetchall(
                "SELECT comm_id, name, summary, component_type FROM community_llm_results "
                "WHERE task_id = ?", (tid,)):
            llm.setdefault(r["comm_id"], r)
    except Exception:
        pass

    # ── 语言 ────────────────────────────────────────────────
    lang_of = {}
    try:
        for r in project_db.fetchall("SELECT file_path, language FROM source_files"):
            lang_of.setdefault(_rel(root, r["file_path"]), r["language"] or "")
    except Exception:
        pass

    # ── 版本差异 change ─────────────────────────────────────
    file_change = {}
    try:
        import version_sync_service as vss
        versions = vss.list_versions(multi_db, project_id)
        if len(versions) >= 2:
            diff = vss.diff_versions(multi_db, project_id,
                                     versions[-1]["id"], versions[0]["id"])
            for f in diff.get("added") or []:
                file_change[_rel(root, f)] = "added"
            for f in diff.get("modified") or []:
                file_change[_rel(root, f)] = "modified"
    except Exception as e:
        logger.warning("[architecture.catalog] version diff failed: %s", e)

    # ── 文件 → 社区 映射(按 comm_id，兼容跨分析类型重复文件) ──
    file_comm: dict = {}
    comm_files: dict = {}
    for row in rows:
        cid = row["comm_id"]
        try:
            node_list = row.get("node_list")
            files = json.loads(node_list) if isinstance(node_list, str) else (node_list or [])
        except Exception:
            files = []
        rel_files = [_rel(root, f) for f in files]
        rel_files = [f for f in rel_files if f]
        comm_files[cid] = rel_files
        for f in rel_files:
            file_comm[f] = cid

    # ── 依赖边(imports) → dependsOn ────────────────────────
    depends_on: dict = {}
    try:
        for r in project_db.fetchall(
                "SELECT source_id, target_id FROM graph_edge "
                "WHERE task_id = ? AND kind = 'imports'", (tid,)):
            src = _rel(root, r["source_id"])
            tgt = _rel(root, r["target_id"])
            if src and tgt and file_comm.get(src) and file_comm.get(tgt):
                a, b = file_comm[src], file_comm[tgt]
                if a != b:
                    depends_on.setdefault(a, set()).add(b)
    except Exception:
        pass

    # ── 组件名 / 父组件名(LLM 名优先，缺失则按路径族推导) ──
    def _name(cid: str) -> str:
        meta = llm.get(cid)
        if meta and meta.get("name"):
            return meta["name"]
        return _derive_name(cid, comm_files.get(cid, []))

    def _summary(cid: str, desc: str = "") -> str:
        meta = llm.get(cid)
        if meta and meta.get("summary"):
            return meta["summary"]
        return desc or ""

    def _kind(cid: str, files) -> str:
        meta = llm.get(cid)
        k = (meta or {}).get("component_type")
        return k if k not in _GENERIC_LLM_KINDS else _infer_kind(files)

    # ── 组装 components(跨类型、层级) ───────────────────────
    components = []
    for row in rows:
        cid = row["comm_id"]
        files = comm_files.get(cid, [])
        parent_id = row.get("parent_comm_id")
        edge_type = _edge_type_of(cid) or "INCLUDE"
        lv = row.get("comm_lv") or "L0"
        resp = [f.split("/")[-1].rsplit(".", 1)[0] for f in files if f][:6]
        components.append({
            "id": cid,
            "name": _name(cid),
            "kind": _kind(cid, files),
            "desc": (_summary(cid, row.get("description") or "") or "").strip()[:400],
            "lang": _lang_from(lang_of, files),
            "change": _community_change(file_change, files),
            "responsibilities": resp or ["（社区无文件）"],
            "owns": files,
            "dependsOn": sorted(depends_on.get(cid, [])),
            "level": lv,
            "edgeType": edge_type,
            "parentId": parent_id,
            "parentName": _name(parent_id) if parent_id else None,
            "fileCount": len(files),
            "nodeCount": int(row.get("node_count") or 0),
            "edgeCount": int(row.get("edge_count") or 0),
            "taskId": tid,
        })

    return {
        "components": components,
        "edgeTypes": edge_types,
        "levels": levels,
        "taskId": tid,
    }


def _edge_type_of(cid: str) -> str:
    """从社区 id 推断分析类型(INCLUDE=依赖分析 / CALL=调用分析)。"""
    lower = (cid or "").lower()
    if "-call-" in lower:
        return "CALL"
    return "INCLUDE"


def _lang_from(lang_of: dict, files) -> str:
    langs = {}
    for f in files:
        l = lang_of.get(f)
        if l:
            langs[l] = langs.get(l, 0) + 1
    if langs:
        return max(langs, key=langs.get)
    return ""


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "-", (text or "").strip("-")) or "x"