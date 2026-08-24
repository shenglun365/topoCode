"""tAgent 宿主适配 — DataProvider / PipelineDataProvider / 流水线回调（INTEGRATION.md §5）。

主项目 multi_db + project_db → tAgent 协议：
  - TopoDataProvider:             KB 数据读（文件/符号/图/边/AST），kb_pipeline / chat / architect 三场景共用
  - TopoPipelineProvider:         KB 流水线读（层级组件 / 批次文件 / 项目摘要 / 总览）
  - build_topo_pipeline_callbacks: 流水线写回调（组件落库 / 总览落库 / 摘要生成 / 文件摘要）

表（project.db）: graph_node / graph_edge / graph_doc / community_hierarchy /
community_llm_results / file_summaries / report_subdocs / base_node
表（main.db）:   projects.summary
"""

from __future__ import annotations

import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _to_rel(path: str, root: str) -> str:
    if not path or not root:
        return path
    rel = os.path.relpath(path, root) if os.path.isabs(path) else path
    return rel.replace("\\", "/")


def _to_abs(path: str, root: str) -> str:
    if not path or not root:
        return path
    return os.path.join(root, path) if not os.path.isabs(path) else path


def _rows_to_dicts(rows) -> list[dict]:
    return [dict(r) for r in rows]


class TopoDataProvider:
    """tAgent DataProvider — 主项目 project_db（原始行 dict 契约）。"""

    def __init__(self, multi_db, project_db, project_root: str = "",
                 project_id: str = "", task_id: str = ""):
        self._multi_db = multi_db
        self._db = project_db
        self._root = project_root
        self._project_id = project_id
        self._task_id = task_id

    # ── 文件 ──

    def file_content(self, path: str, limit: int = 10000) -> Optional[str]:
        # 读盘不依赖 DB（provider 允许 project_db=None 的纯文件场景）
        abs_path = _to_abs(path, self._root)
        if self._root:
            real_root = os.path.realpath(self._root)
            real_path = os.path.realpath(abs_path)
            if real_path != real_root and not real_path.startswith(real_root + os.sep):
                logger.warning("[TopoProvider] file_content path outside root: %s", path)
                return None
        if not os.path.isfile(abs_path):
            return None
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
                return f.read(limit)
        except OSError:
            return None

    def file_ranks(self, task_id: str) -> list[dict]:
        if not self._db:
            return []
        tid = task_id or self._task_id
        try:
            from topoone.engine.task_manager import _compute_file_ranks
            components = []
            for et in ("INCLUDE", "CALL"):
                for row in self._db.execute(
                    "SELECT comm_id, quality_score FROM community_hierarchy "
                    "WHERE task_id=? AND edge_type=? AND comm_lv='L0' ORDER BY node_count DESC",
                    (tid, et),
                ).fetchall():
                    components.append({"id": row["comm_id"],
                                       "metadata": {"qualityScore": row["quality_score"] or 0}})
            ranks = _compute_file_ranks(tid, self._db, components, self._root)
            return [
                {"path": f["file_path"], "rank": i + 1, "score": f.get("score", 0)}
                for i, f in enumerate(ranks.get("files", []))
            ]
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoProvider] file_ranks failed: %s", e)
            return []

    # ── 符号 ──

    def symbol_detail(self, symbol_id: str) -> Optional[dict]:
        if not self._db or not symbol_id:
            return None
        try:
            row = self._db.execute(
                "SELECT * FROM graph_node WHERE id = ?", (symbol_id,)).fetchone()
        except Exception:  # noqa: BLE001
            return None
        if not row:
            return None
        d = dict(row)
        if d.get("file_path"):
            d["file_path"] = _to_rel(d["file_path"], self._root)
        return d

    def symbol_search(self, keyword: str, kind: str = "", limit: int = 20) -> list[dict]:
        if not self._db or not keyword:
            return []
        try:
            where, params = ["name LIKE ?"], [f"%{keyword}%"]
            if kind:
                where.append("kind = ?")
                params.append(kind)
            rows = self._db.execute(
                f"SELECT id, name, kind, file_path, start_line, end_line, signature, docstring "
                f"FROM graph_node WHERE {' AND '.join(where)} ORDER BY name LIMIT ?",
                (*params, int(limit)),
            ).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoProvider] symbol_search failed: %s", e)
            return []
        out = []
        for d in _rows_to_dicts(rows):
            if d.get("file_path"):
                d["file_path"] = _to_rel(d["file_path"], self._root)
            out.append(d)
        return out

    # ── 图 / 边 ──

    def neighbors(self, symbol_id: str, relation: Optional[str] = None,
                  task_id: str = "") -> list[dict]:
        if not self._db or not symbol_id:
            return []
        try:
            where, params = ["(source_id = ? OR target_id = ?)"], [symbol_id, symbol_id]
            if relation:
                where.append("kind = ?")
                params.append(relation)
            tid = task_id or self._task_id
            if tid:
                where.append("task_id = ?")
                params.append(tid)
            rows = self._db.execute(
                f"SELECT * FROM graph_edge WHERE {' AND '.join(where)}", params).fetchall()
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoProvider] neighbors failed: %s", e)
            return []
        out = []
        for d in _rows_to_dicts(rows):
            d["relation"] = d.get("kind", "")
            out.append(d)
        return out

    def community_subgraph(self, task_id: str, comm_id: str,
                           comm_lv: str = "", edge_type: str = "") -> Optional[dict]:
        if not self._db or not comm_id:
            return None
        tid = task_id or self._task_id
        candidates: list[tuple[str, str]] = []
        if edge_type and comm_lv:
            candidates.append((edge_type, comm_lv))
        if edge_type:
            candidates.append((edge_type, ""))
        if comm_lv:
            candidates.append(("", comm_lv))
        candidates.extend([("INCLUDE", ""), ("CALL", "")])
        for et, cl in candidates:
            params: list = [tid, comm_id]
            sql = "SELECT * FROM graph_doc WHERE task_id=? AND comm_id=?"
            if et:
                sql += " AND edge_type=?"
                params.append(et)
            if cl:
                sql += " AND comm_lv=?"
                params.append(cl)
            try:
                rows = self._db.execute(sql, params).fetchall()
            except Exception as e:  # noqa: BLE001
                logger.warning("[TopoProvider] community_subgraph failed: %s", e)
                return None
            if rows:
                result = {"edge_type": et, "comm_lv": cl or "any", "nodes": [], "edges": []}
                for r in rows:
                    d = dict(r)
                    for key, target in (("node_list", "nodes"), ("edge_list", "edges")):
                        if d.get(key):
                            try:
                                result[target].extend(json.loads(d[key]))
                            except (json.JSONDecodeError, TypeError):
                                pass
                return result
        return None

    def edge_detail(self, edge_id: str) -> Optional[dict]:
        if not self._db or not edge_id:
            return None
        try:
            row = self._db.execute(
                "SELECT * FROM graph_edge WHERE id = ?", (edge_id,)).fetchone()
        except Exception:  # noqa: BLE001
            return None
        if not row:
            return None
        d = dict(row)
        d["relation"] = d.get("kind", "")
        d["type"] = d.get("kind", "")
        d["dependency_type"] = d.get("kind", "")
        return d

    def ast_node(self, node_id: str, file_id: str = "") -> Optional[dict]:
        if not self._db or not node_id:
            return None
        try:
            sql, params = "SELECT * FROM base_node WHERE node_id=?", [node_id]
            if file_id:
                sql += " AND file_id=?"
                params.append(file_id)
            row = self._db.execute(sql, params).fetchone()
        except Exception:  # noqa: BLE001
            return None
        return dict(row) if row else None

    def resolve_task_id(self, comm_id: str) -> str:
        if not self._db or not comm_id:
            return ""
        try:
            row = self._db.execute(
                "SELECT task_id FROM graph_doc WHERE comm_id=? LIMIT 1", (comm_id,)).fetchone()
            return row["task_id"] if row else ""
        except Exception:  # noqa: BLE001
            return ""

    def graph_query(self, query: str) -> list[dict]:
        if not self._db:
            return []
        if not query.lstrip().upper().startswith("SELECT"):
            return []
        try:
            rows = self._db.execute(query).fetchall()
            return _rows_to_dicts(rows)
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoProvider] graph_query failed: %s", e)
            return []


class TopoPipelineProvider(TopoDataProvider):
    """tAgent PipelineDataProvider + DataProvider（同一 project_db）。

    流水线子 runtime 的 kit 工具（read_file/search_symbols/...）复用
    DataProvider 接口，故继承 TopoDataProvider 双协议合一。
    """

    def __init__(self, multi_db, project_db, project_root: str = "",
                 project_id: str = "", task_id: str = ""):
        super().__init__(multi_db, project_db, project_root=project_root,
                         project_id=project_id, task_id=task_id)

    def list_level_components(self, task_id: str, level: str,
                              include_analyzed: bool = True) -> list[dict]:
        """层级组件。include_analyzed=True 全部；False 仅未分析（status != completed 或无 name）。"""
        if not self._db:
            return []
        tid = task_id or self._task_id
        results: list[dict] = []
        analyzed_ids: set[str] = set()
        if not include_analyzed:
            try:
                for et in ("INCLUDE", "CALL"):
                    for r in self._db.execute(
                        "SELECT comm_id FROM community_llm_results "
                        "WHERE task_id=? AND edge_type=? AND comm_lv=? "
                        "AND status='completed' AND name IS NOT NULL AND name != ''",
                        (tid, et, level),
                    ).fetchall():
                        analyzed_ids.add(r["comm_id"])
            except Exception as e:  # noqa: BLE001
                logger.warning("[TopoPipeline] analyzed filter failed: %s", e)
        for et in ("INCLUDE", "CALL"):
            try:
                rows = self._db.execute(
                    "SELECT comm_id, file_count, node_count, quality_score FROM community_hierarchy "
                    "WHERE task_id=? AND edge_type=? AND comm_lv=? ORDER BY node_count DESC",
                    (tid, et, level),
                ).fetchall()
            except Exception as e:  # noqa: BLE001
                logger.warning("[TopoPipeline] level_components failed: %s", e)
                continue
            for row in rows:
                cid = row["comm_id"]
                if not include_analyzed and cid in analyzed_ids:
                    continue
                results.append({
                    "id": cid, "type": "community", "name": cid,
                    "level": level, "edgeType": et,
                    "metadata": {"fileCount": row["file_count"] or 0,
                                 "nodeCount": row["node_count"] or 0,
                                 "qualityScore": row["quality_score"] or 0},
                })
        return results

    def list_batch_files(self, task_id: str, project_id: str, batch: str,
                         include_cached: bool = True) -> list[str]:
        """批次文件（P0/P1/P2 由 _compute_file_ranks 划分）。
        include_cached=True 全部；False 仅未缓存（file_summaries 无摘要）。"""
        if not self._db:
            return []
        tid = task_id or self._task_id
        pid = project_id or self._project_id
        try:
            from topoone.engine.task_manager import _compute_file_ranks
            components = []
            for et in ("INCLUDE", "CALL"):
                for row in self._db.execute(
                    "SELECT comm_id, quality_score FROM community_hierarchy "
                    "WHERE task_id=? AND edge_type=? AND comm_lv='L0' ORDER BY node_count DESC",
                    (tid, et),
                ).fetchall():
                    components.append({"id": row["comm_id"],
                                       "metadata": {"qualityScore": row["quality_score"] or 0}})
            ranks = _compute_file_ranks(tid, self._db, components, self._root)
            files = [f["file_path"] for f in ranks.get("files", []) if f.get("batch") == batch]
            if not include_cached and pid:
                cached = {
                    r["file_path"] for r in self._db.execute(
                        "SELECT file_path FROM file_summaries WHERE project_id=? AND summary IS NOT NULL",
                        (pid,),
                    ).fetchall()
                }
                files = [f for f in files if f not in cached]
            return files
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoPipeline] batch_files failed: %s", e)
            return []

    def get_project_summary(self, project_id: str) -> Optional[str]:
        pid = project_id or self._project_id
        if not pid:
            return None
        try:
            row = self._multi_db.main_db.execute(
                "SELECT summary FROM projects WHERE id=?", (pid,)).fetchone()
            summary = row["summary"] if row else None
            return summary or None
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoPipeline] project_summary failed: %s", e)
            return None

    def has_overview(self, task_id: str) -> bool:
        if not self._db:
            return False
        tid = task_id or self._task_id
        try:
            row = self._db.execute(
                "SELECT id FROM report_subdocs WHERE task_id=? AND comm_id='overall'",
                (tid,)).fetchone()
            return row is not None
        except Exception:  # noqa: BLE001
            return False

    def list_overview_rows(self, task_id: str) -> dict:
        """总览上下文：{"INCLUDE": [rows], "CALL": [rows]}，row = {comm_id, name, summary, comm_lv}。"""
        if not self._db:
            return {"INCLUDE": [], "CALL": []}
        tid = task_id or self._task_id
        out: dict[str, list[dict]] = {"INCLUDE": [], "CALL": []}
        try:
            for et in ("INCLUDE", "CALL"):
                rows = self._db.execute(
                    "SELECT comm_id, name, name_manual, summary, comm_lv FROM community_llm_results "
                    "WHERE task_id=? AND edge_type=? ORDER BY comm_lv, comm_id",
                    (tid, et),
                ).fetchall()
                for r in rows:
                    out[et].append({
                        "comm_id": r["comm_id"],
                        "name": r["name_manual"] or r["name"] or "",
                        "summary": r["summary"] or "",
                        "comm_lv": r["comm_lv"],
                    })
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoPipeline] overview_rows failed: %s", e)
        return out

    def list_key_file_summaries(self, task_id: str, project_id: str) -> list[tuple]:
        """关键文件摘要 [(file_path, summary)]（摘要最长 top 20）。"""
        if not self._db:
            return []
        tid = task_id or self._task_id
        pid = project_id or self._project_id
        try:
            rows = None
            if tid:
                rows = self._db.execute(
                    "SELECT file_path, summary FROM file_summaries WHERE task_id=? "
                    "ORDER BY summary_len DESC LIMIT 20", (tid,)).fetchall()
            if not rows and pid:
                rows = self._db.execute(
                    "SELECT file_path, summary FROM file_summaries WHERE project_id=? "
                    "ORDER BY summary_len DESC LIMIT 20", (pid,)).fetchall()
            return [(r["file_path"], r["summary"]) for r in (rows or [])]
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoPipeline] key_file_summaries failed: %s", e)
            return []


def build_topo_pipeline_callbacks(multi_db, project_id: str, task_id: str,
                                  model_id: str = "", project_root: str = "",
                                  concurrency: int = 1):
    """构建 tAgent PipelineCallbacks（写/副作用走主项目生产路径）。"""
    from topocode_agent.workflows.pipeline import PipelineCallbacks

    data_dir = getattr(multi_db, "data_dir", "") or ""
    pid = project_id

    def _save_component_result(payload: dict) -> None:
        try:
            from topoone.engine.ingest import write_ingest
            comp_id = payload.get("component_id", "")
            write_ingest(pid, "community_result", {
                "task_id": payload.get("task_id") or task_id,
                "project_id": pid,
                "edge_type": payload.get("edge_type", ""),
                "comm_lv": payload.get("comm_lv", "L0"),
                "comm_id": comp_id,
                "name": payload.get("analyzed_name", "") or comp_id,
                "summary": payload.get("functional_summary", ""),
                "model_id": model_id,
                "template_id": "tagent",
                "component_type": payload.get("component_type", "community"),
                "status": payload.get("status", "completed"),
            }, data_dir=data_dir)
            logger.info("[TopoPipeline] component ingest: %s status=%s",
                        comp_id, payload.get("status", "completed"))
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoPipeline] save_component_result failed: %s", e)

    def _save_overview(payload: dict) -> None:
        try:
            from topoone.engine.report_tree_service import save_overall_doc
            save_overall_doc(multi_db, payload.get("task_id") or task_id,
                             payload.get("title", "Architecture Overview"),
                             payload.get("content", ""))
            logger.info("[TopoPipeline] overview saved len=%d", len(payload.get("content", "")))
        except Exception as e:  # noqa: BLE001
            logger.warning("[TopoPipeline] save_overview failed: %s", e)

    async def _generate_project_summary(pid_arg: str, language: str = "") -> None:
        from topoone.engine.report_service import _do_generate_project_summary
        await _do_generate_project_summary(multi_db, pid_arg, language=language)

    async def _file_summarizer(paths: list, focus: str = ""):
        """文件摘要（LLM + file_summaries 缓存）— 走主项目 SubAgent 生产路径。"""
        from topoone.agent.agent_workflow.file_summary_cache import FileSummaryCache
        from topoone.agent.agent_workflow.sub_agent import SubAgent
        from topoone.agent.agent_workflow.path_utils import to_abs

        out: list[dict] = []
        if not paths:
            return out
        project_db = multi_db.get_project_db(pid) if pid else None
        cache = FileSummaryCache(project_db, pid, project_root, data_dir=data_dir) \
            if project_db else None
        sub = SubAgent(
            project_root=project_root,
            model_id=model_id,
            multi_db=multi_db,
            project_db=project_db,
            task_id=task_id,
        )
        safe_files = []
        for fp in paths[:10]:
            abs_path = to_abs(fp, project_root) if project_root else fp
            if abs_path:
                safe_files.append(abs_path)
        result = await sub.summarize_files(
            files=safe_files,
            task_id=task_id,
            project_id=pid,
            file_cache=cache,
            focus=focus,
            max_concurrent=max(1, min(int(concurrency), 10)),
        )
        for s in result.summaries:
            out.append({"path": s["path"], "summary": s.get("summary", ""),
                        "cached": bool(s.get("cached"))})
        return out

    return PipelineCallbacks(
        save_component_result=_save_component_result,
        save_overview=_save_overview,
        generate_project_summary=_generate_project_summary,
        file_summarizer=_file_summarizer,
    )
