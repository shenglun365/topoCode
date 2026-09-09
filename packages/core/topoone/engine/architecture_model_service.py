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


def _resolve_view_task_ids(multi_db, project_id: str) -> list:
    """基线视图挂载任务解析（未挂载 = 空列表，外部读取应为空）。"""
    try:
        from topoone.engine.view_service import resolve_view_task_ids
        return resolve_view_task_ids(multi_db, project_id)
    except Exception as e:
        logger.warning("[architecture] view resolve failed: %s", e)
        return []


def build_architecture_model(multi_db, project_id: str, *,
                             task_id: str = "", level: str = "L1",
                             edge_type: str = "UNIFIED") -> dict:
    """为 KB 项目构建真实架构模型。

    任务来源：显式 task_id（内部消费方）＞ 基线视图挂载任务（对外契约）。
    多个挂载任务分区拼凑项目全貌（comm_id 内嵌任务前缀，天然命名空间隔离）。
    任务/社区缺失时返回空模型（不抛异常）。
    """
    if not project_id:
        return _empty_model()

    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT id, root_path FROM projects WHERE id = ?", (project_id,))
    if not project:
        return _empty_model()
    root = project.get("root_path") or ""

    tids = [task_id] if task_id else _resolve_view_task_ids(multi_db, project_id)
    if not tids:
        return _empty_model()

    try:
        project_db = multi_db.get_project_db(project_id)
    except Exception as e:
        logger.warning("[architecture.model] project db unavailable: %s", e)
        return _empty_model()

    et = (edge_type or "UNIFIED").upper()
    lv = (level or "L1").upper()

    # ── 语言（项目级，一次） ────────────────────────────────
    lang_of = {}
    try:
        for r in project_db.fetchall("SELECT file_path, language FROM source_files"):
            lang_of.setdefault(_rel(root, r["file_path"]), r["language"] or "")
    except Exception:
        pass

    # ── 版本差异 change（项目级，一次） ─────────────────────
    versions = []
    try:
        import topoone.engine.version_sync_service as vss
        versions = vss.list_versions(multi_db, project_id)
    except Exception:
        versions = []
    file_change: dict = {}
    if len(versions) >= 2:
        try:
            import topoone.engine.version_sync_service as vss
            diff = vss.diff_versions(multi_db, project_id,
                                     versions[-1]["id"], versions[0]["id"])
            for f in diff.get("added") or []:
                file_change[_rel(root, f)] = "added"
            for f in diff.get("modified") or []:
                file_change[_rel(root, f)] = "modified"
        except Exception as e:
            logger.warning("[architecture.model] version diff failed: %s", e)

    # ── 逐挂载任务取社区，合并（视图分区不重叠 → file_comm 无冲突） ──
    file_comm = {}
    # 社区 → 文件
    comm_files: dict = {}
    depends_on: dict = {}
    line_of: dict = {}
    merged_rows = []
    merged_llm = {}
    for tid in tids:
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
            continue
        merged_rows.extend(rows)
        try:
            for r in project_db.fetchall(
                    "SELECT comm_id, name, summary, component_type FROM community_llm_results "
                    "WHERE task_id = ? AND edge_type = ?", (tid, et)):
                merged_llm[r["comm_id"]] = r
        except Exception:
            pass
        try:
            for r in project_db.fetchall(
                    "SELECT file_path, MIN(start_line) AS line FROM graph_node "
                    "WHERE task_id = ? AND kind != 'file' GROUP BY file_path", (tid,)):
                rel = _rel(root, r["file_path"])
                line_of.setdefault(rel, int(r["line"] or 1))
        except Exception:
            pass
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
        # imports 跨社区边 → dependsOn
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

    rows = merged_rows
    llm = merged_llm
    if not rows:
        return _empty_model()

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
    """组件目录（选择器专用）：UNIFIED 单套组件树（L0/L1），
    附带父组件 / 文件数 / 类型等元数据。

    任务来源：显式 task_id（内部消费方）＞ 基线视图挂载任务（对外契约）；
    多个挂载任务分区拼凑项目全貌（comm_id 内嵌任务前缀，天然命名空间隔离）。

    返回 { components, edgeTypes, levels, taskId, taskIds, view }，
    供 `/kb/assets/search` 做「按类型 / 层级」筛选与列表信息展示。
    """
    if not project_id:
        return {"components": [], "edgeTypes": [], "levels": [], "taskId": "", "taskIds": []}

    main_db = multi_db.main_db
    project = main_db.fetchone("SELECT id, root_path FROM projects WHERE id = ?", (project_id,))
    if not project:
        return {"components": [], "edgeTypes": [], "levels": [], "taskId": "", "taskIds": []}
    root = project.get("root_path") or ""

    tids = [task_id] if task_id else _resolve_view_task_ids(multi_db, project_id)
    if not tids:
        return {"components": [], "edgeTypes": [], "levels": [],
                "taskId": "", "taskIds": [],
                "view": {"mountedTaskIds": [], "stale": False,
                         "hint": "基线视图未挂载任务，请在 KB 端挂载分析任务"}}

    try:
        project_db = multi_db.get_project_db(project_id)
    except Exception as e:
        logger.warning("[architecture.catalog] project db unavailable: %s", e)
        return {"components": [], "edgeTypes": [], "levels": [], "taskId": "", "taskIds": []}

    # ── 全量社区：UNIFIED 单套口径（组件统一，kb-unified-components-plan）──
    edge_types = ["UNIFIED"]
    levels = ["L0", "L1"]

    # ── 语言（项目级，一次） ────────────────────────────────
    lang_of = {}
    try:
        for r in project_db.fetchall("SELECT file_path, language FROM source_files"):
            lang_of.setdefault(_rel(root, r["file_path"]), r["language"] or "")
    except Exception:
        pass

    # ── 版本差异 change（项目级，一次） ─────────────────────
    file_change = {}
    try:
        import topoone.engine.version_sync_service as vss
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

    # ── 逐挂载任务取社区/LLM 名/依赖边，合并（视图分区不重叠） ──
    file_comm: dict = {}
    comm_files: dict = {}
    depends_on: dict = {}
    task_of_comm: dict = {}
    merged_rows = []
    merged_llm = {}
    for tid in tids:
        try:
            rows = project_db.fetchall(
                "SELECT comm_id, comm_lv, parent_comm_id, node_list, edge_list, "
                "file_count, edge_count, node_count, description "
                "FROM graph_doc WHERE task_id = ? AND edge_type = 'UNIFIED' "
                "ORDER BY quality_score DESC",
                (tid,))
        except Exception:
            rows = []
        if not rows:
            continue
        merged_rows.extend(rows)
        # LLM 名称 / 摘要 / 类型(按 comm_id 去重；comm_id 内嵌任务前缀，跨任务不冲突)
        try:
            for r in project_db.fetchall(
                    "SELECT comm_id, name, name_manual, summary, component_type FROM community_llm_results "
                    "WHERE task_id = ?", (tid,)):
                merged_llm.setdefault(r["comm_id"], r)
        except Exception:
            pass
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
            task_of_comm[cid] = tid
        # imports 依赖边 → dependsOn
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

    rows = merged_rows
    llm = merged_llm

    # ── 组件名 / 父组件名(LLM 名优先，缺失则按路径族推导；人工命名 name_manual 最高优先) ──
    def _name(cid: str) -> str:
        meta = llm.get(cid)
        if meta:
            manual = (meta.get("name_manual") or "").strip()
            if manual:
                return manual
            if meta.get("name"):
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
        edge_type = _edge_type_of(cid) or "UNIFIED"
        lv = row.get("comm_lv") or "L0"
        resp = [f.split("/")[-1].rsplit(".", 1)[0] for f in files if f][:6]
        components.append({
            "id": cid,
            "name": _name(cid),
            # named=False 表示 KB 尚未解析(无 LLM/人工名，name 为路径族推导的临时名)，
            # 消费方可据此改显组件 id(如概览「组件变更情况」)。
            "named": bool((llm.get(cid) or {}).get("name_manual") or (llm.get(cid) or {}).get("name")),
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
            "taskId": task_of_comm.get(cid, ""),
        })

    from topoone.engine.view_service import view_summary
    return {
        "components": components,
        "edgeTypes": edge_types,
        "levels": levels,
        "taskId": tids[0] if len(tids) == 1 else "",
        "taskIds": tids,
        "view": view_summary(multi_db, project_id),
    }


def _edge_type_of(cid: str) -> str:
    """从社区 id 推断分析类型（组件统一后仅有 UNIFIED；旧前缀兜底映射）。"""
    lower = (cid or "").lower()
    if "-call-" in lower:
        return "CALL"
    if "-uni-" in lower:
        return "UNIFIED"
    return "UNIFIED"


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