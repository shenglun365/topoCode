"""task_api 共享层（MS5-V1）——原 register_analysis_methods 闭包的显式化。

Shared 在 register 入口绑定 (server, multi_db)，六域经其实例访问共享能力；
本模块另承载原 task_manager 的模块级工具函数（_compute_file_ranks 等，
经门面继续导出供 agent 侧惰性引用与测试打桩）。
"""
import logging
import os

from topoone.engine.store.task_store import TaskStore

logger = logging.getLogger(__name__)

# 字段映射 (camelCase → snake_case)
_FIELD_MAP = {
    "excludeDirs": "exclude_dirs",
    "reportTypes": "report_types",
    "patternType": "pattern_type",
    "selectedExtensions": "selected_extensions",
}

def _resolve_node_list_items(items: list, task_id: str, project_db) -> dict[str, list[str]]:
    """批量将 node_list 条目解析为文件路径。返回 item → [resolved_path] 映射。"""
    import os as _os
    result: dict[str, list[str]] = {}
    unresolved_ids: list[str] = []
    for item in items:
        if not item or not isinstance(item, str):
            continue
        if _os.path.isabs(item) or '/' in item or '\\' in item:
            result[item] = [item.replace('\\', '/')]
        else:
            unresolved_ids.append(item)
    if unresolved_ids:
        placeholders = ",".join("?" for _ in unresolved_ids)
        try:
            for row in project_db.execute(
                f"SELECT id, file_path FROM graph_node WHERE id IN ({placeholders}) AND task_id=? AND file_path!=''",
                (*unresolved_ids, task_id)
            ).fetchall():
                result.setdefault(row["id"], []).append(row["file_path"])
        except Exception:
            pass
    return result


def _compute_file_ranks(task_id: str, project_db, components: list,
                         project_root: str = "") -> dict:
    """计算文件重要度评分并分批次。"""
    from collections import Counter
    import json as _rj
    import os as _os

    file_to_comms: dict[str, set[str]] = {}
    file_edges: Counter = Counter()
    file_sizes: dict[str, int] = {}
    comm_quality: dict[str, float] = {}

    cid_list = [c.get("id", "") for c in components if c.get("id")]
    doc_map: dict[str, str] = {}
    if cid_list:
        placeholders = ",".join("?" for _ in cid_list)
        try:
            for row in project_db.execute(
                f"SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND comm_id IN ({placeholders})",
                (task_id, *cid_list)
            ).fetchall():
                doc_map[row["comm_id"]] = row["node_list"]
        except Exception:
            pass

    all_cid_items: dict[str, list] = {}
    for c in components:
        cid = c.get("id", "")
        node_list_json = doc_map.get(cid, "")
        if not node_list_json:
            continue
        try:
            raw = _rj.loads(node_list_json) if isinstance(node_list_json, str) else node_list_json
            all_cid_items[cid] = raw
        except Exception:
            pass
    all_items = list({item for items in all_cid_items.values() for item in items if isinstance(item, str) and item})
    path_map = _resolve_node_list_items(all_items, task_id, project_db)

    for c in components:
        cid = c.get("id", "")
        meta = c.get("metadata", {}) or {}
        comm_quality[cid] = float(meta.get("qualityScore", 0) or 0)
        for item in all_cid_items.get(cid, []):
            for resolved in path_map.get(item, []):
                file_to_comms.setdefault(resolved, set()).add(cid)

    if file_to_comms:
        try:
            rel_keys = [
                (_os.path.relpath(fp, project_root) if project_root and _os.path.isabs(fp) else fp).replace('\\', '/')
                for fp in file_to_comms
            ]
            logger.info("[_compute_file_ranks] size_query project_root=%r n_files=%d first_abs=%r first_rel=%r",
                       project_root, len(file_to_comms),
                       next(iter(file_to_comms), '') if file_to_comms else '',
                       rel_keys[0] if rel_keys else '')
            rel_to_size = {}
            for row in project_db.execute(
                "SELECT file_path, size FROM source_files WHERE file_path IN ({})".format(
                    ",".join("?" for _ in rel_keys)
                ), rel_keys
            ).fetchall():
                rel_to_size[row["file_path"]] = row["size"] or 0
            logger.info("[_compute_file_ranks] source_files matched=%d", len(rel_to_size))
            for abs_fp, rel_fp in zip(file_to_comms, rel_keys):
                file_sizes[abs_fp] = rel_to_size.get(rel_fp, 0)
            logger.info("[_compute_file_ranks] file_sizes nonzero=%d",
                       sum(1 for v in file_sizes.values() if v > 0))
        except Exception as e:
            logger.warning("[_compute_file_ranks] size lookup failed: %s", e)

    try:
        for row in project_db.execute(
            "SELECT d.source_file, COUNT(*) as cnt FROM dependencies d "
            "JOIN graph_node g ON g.file_path = d.source_file AND g.task_id = ? "
            "WHERE d.source_file IN ({}) GROUP BY d.source_file".format(
                ",".join("?" for _ in file_to_comms)
            ), (task_id,) + tuple(file_to_comms.keys())
        ).fetchall():
            file_edges[row["source_file"]] = row["cnt"]
    except Exception:
        pass

    from topoone.agent.agent_workflow.path_utils import to_rel
    scored = []
    for fp, comms in file_to_comms.items():
        cross = len(comms)
        edges = file_edges.get(fp, 0)
        size = file_sizes.get(fp, 0)
        max_quality = max((comm_quality.get(c, 0) for c in comms), default=0)
        size_score = (1 if size > 10000 else 0) * 15 + \
                     (1 if size > 50000 else 0) * 15 + \
                     (1 if size > 100000 else 0) * 10
        score = size_score + int(max_quality * 100)
        scored.append({
            "file_path": to_rel(fp, project_root), "score": score, "cross": cross,
            "edges": edges, "size": size, "is_large": 1 if size > 10000 else 0,
            "quality": max_quality, "batch": "",
        })

    scored.sort(key=lambda x: (-x["score"], -x["size"]))

    total = len(scored)
    p0_end = max(1, int(total * 0.30))
    p1_end = max(p0_end + 1, int(total * 0.60))
    while p0_end < total and scored[p0_end]["score"] == scored[p0_end - 1]["score"]:
        p0_end += 1
    while p1_end < total and scored[p1_end]["score"] == scored[p1_end - 1]["score"]:
        p1_end += 1
    for i, item in enumerate(scored):
        if i < p0_end:
            item["batch"] = "P0"
        elif i < p1_end:
            item["batch"] = "P1"
        else:
            item["batch"] = "P2"

    # P3(未包含)：源码中未纳入任何组件分析的文件——仅清单化展示与 agent 按需
    # 补充预摘要（pipeline_run_presummary 传 batches=["P3"]），不参与强制预摘要，
    # 也不计入预摘要进度分母。用于判定组件分析覆盖边界。
    p3_count = 0
    try:
        covered = {it["file_path"] for it in scored}
        # 仅真实源码文件（language 非空且非 directory，剔除 README/目录/include 杂项行）
        for row in project_db.execute(
            "SELECT file_path, COALESCE(size, 0) AS sz FROM source_files "
            "WHERE language IS NOT NULL AND language != '' AND language != 'directory'"
        ).fetchall():
            rel = row["file_path"]
            if rel and rel not in covered:
                scored.append({
                    "file_path": rel, "score": 0, "cross": 0, "edges": 0,
                    "size": row["sz"] or 0, "is_large": 0, "quality": 0,
                    "batch": "P3",
                })
                p3_count += 1
    except Exception as e:
        logger.warning(f"[_compute_file_ranks] P3(未包含) 计算失败: {e}")

    return {
        "files": scored,
        "counts": {"P0": p0_end, "P1": p1_end - p0_end,
                   "P2": total - p1_end, "P3": p3_count},
    }



_batched_files_cache: dict = {}


def _count_batched_source_files(task_id: str, project_db, project_root: str = "") -> int:
    """预摘要覆盖的源码文件数（P0+P1+P2 批次并集）。

    进度分母用它而非图内全部文件：不属于任何 L0 社区的文件不在
    预摘要分析范围内，若计入分母，文件进度永远到不了 100%。
    60s 缓存（流水线期间图静态），避免 3s 轮询端点重复查询。
    """
    import time as _t
    now = _t.monotonic()
    hit = _batched_files_cache.get(task_id)
    if hit and now - hit[1] < 60:
        return hit[0]
    count = 0
    try:
        comps = [{"id": c["id"], "metadata": {"qualityScore": c["qualityScore"]}}
                 for c in unified_l0_components(project_db, task_id)]
        ranks = _compute_file_ranks(task_id, project_db, comps, project_root)
        count = sum(1 for f in ranks.get("files", []) if f.get("batch") in ("P0", "P1", "P2"))
    except Exception:
        count = 0
    _batched_files_cache[task_id] = (count, now)
    return count


# 代码解析产物表：清除这些表后任务可重新执行（状态重置 pending）
_PARSE_CACHE_TABLES = {
    "graph_node", "graph_edge", "graph_doc",
    "community_hierarchy", "community_llm_results",
    "ast_data", "dependencies", "call_chains",
}


def _reset_tasks_to_pending(task_store, project_id: str) -> int:
    """把项目内非 running 任务重置为 pending（清除缓存后开放重新执行）。

    running 任务不动；已是 pending 的跳过。返回重置数量。
    """
    count = 0
    for task in task_store.list_tasks(project_id):
        if task.get("status") in ("done", "error", "cancelled", "modified", "stopped"):
            task_store.update_task_status(task["id"], "pending", progress=0, error="")
            count += 1
    return count


def _with_fixed_report_types(report_types: list) -> list:
    """报告类型补齐固定项：内部依赖分析(dependency) + 内部调用分析(callChain) 始终包含。"""
    rt = list(report_types or [])
    for t in ("dependency", "callChain"):
        if t not in rt:
            rt.append(t)
    return rt




class Shared:
    """register 期绑定的共享上下文（原闭包显式化，MS5-V1）。"""

    def __init__(self, server, multi_db):
        self.server = server
        self.multi_db = multi_db
        self._agent_proxy = None

    def bind_agent_proxy(self):
        """P3e：kb 的 agent 执行移交 agent 服务（HTTP /zmq/agent.*）。"""
        url = os.environ.get("AGENT_API_URL", "").strip()
        if url:
            from topoone.messaging.remote import HttpAgentManager
            self._agent_proxy = HttpAgentManager(url)
            logger.info(f"[analysis] agent RPC → HttpAgentManager ({url})")

    def agent_mgr(self):
        """返回 AgentTaskManager（本地）或远程 Agent 管理器"""
        if self._agent_proxy is not None:
            return self._agent_proxy
        from topoone.agent.agent_workflow.agent_queue import get_global_queue
        return get_global_queue()

    def startup_sweep(self):
        """启动清扫：标记进程重启后残留的 running 任务。"""
        try:
            store = TaskStore(self.multi_db.main_db)
            stale = store._db.execute(
                "SELECT id FROM analysis_tasks WHERE status='running'"
            ).fetchall()
            if stale:
                logger.warning(f"[startup] Found {len(stale)} stale running tasks, marking as error")
                store._db.execute(
                    "UPDATE analysis_tasks SET status='error', error='Process restarted, task interrupted' WHERE status='running'"
                )
                store._db.execute(
                    "UPDATE analysis_task_runs SET status='error', error='Process restarted', finished_at=datetime('now') WHERE status='running'"
                )
                store._db.commit()
        except Exception as e:
            logger.warning(f"[startup] failed to clean stale tasks: {e}")

    def recover_orphans(self):
        """启动时恢复孤儿任务（后端异常终止后残留的 running 状态）。"""
        from topoone.engine.analyst_runner import is_task_executing
        try:
            orphan_store = TaskStore(self.multi_db.main_db)
            orphans = orphan_store._db.execute(
                "SELECT id, name FROM analysis_tasks WHERE status = 'running'"
            ).fetchall()
            recovered = 0
            for row in orphans:
                oid, oname = row[0], row[1]
                if not is_task_executing(oid):
                    logger.warning(f"[startup] Recovering orphan task {oid} ({oname}) -> error")
                    orphan_store.update_task_status(oid, "error", error="Task execution interrupted (backend terminated abnormally)")
                    orphan_store._db.execute(
                        "UPDATE analysis_task_runs SET status='error', error='Execution interrupted', finished_at=datetime('now') WHERE task_id=? AND status='running'",
                        (oid,),
                    )
                    orphan_store._db.commit()
                    recovered += 1
            if recovered:
                logger.info(f"[startup] Recovered {recovered} orphan task(s)")
        except Exception as e:
            logger.error(f"[startup] Orphan recovery failed: {e}")

    def get_project_root(self, pid):
        try:
            root_row = self.multi_db.main_db.execute(
                "SELECT root_path FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            result = root_row["root_path"] if root_row else ""
            return str(result or "").replace('\\', '/')
        except Exception as e:
            logger.warning("[_get_project_root] FAILED pid=%r error=%s", pid, e)
            return ""

    def get_project_summary(self, pid):
        try:
            row = self.multi_db.main_db.execute(
                "SELECT summary FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            return str(row["summary"] or "") if row else ""
        except Exception:
            return ""

    def make_agent_history_cb(self, project_id, project_db, task_id, action):
        from topoone.engine.store.analysis_store import AnalysisStore
        import json as _json

        def _cb(state_dict):
            try:
                s = AnalysisStore(project_db)
                import datetime as _dt

                def _ts(v):
                    try:
                        return _dt.datetime.fromtimestamp(v).isoformat() if v else None
                    except Exception:
                        return None
                steps_str = _json.dumps(state_dict.get("steps", []), ensure_ascii=False)
                s.save_agent_task_history({
                    "project_id": project_id,
                    "task_id": task_id,
                    "agent_id": state_dict["agent_id"],
                    "action": action,
                    "status": state_dict["status"],
                    "steps": steps_str,
                    "message": state_dict.get("message", ""),
                    "error": state_dict.get("error", ""),
                    "created_at": _ts(state_dict.get("created_at")),
                    "finished_at": _ts(state_dict.get("finished_at")),
                })
            except Exception as e:
                logger.warning(f"[AgentHistory] save failed for {state_dict.get('agent_id', '?')}: {e}")
        return _cb

    def save_agent_running_history(self, project_db, pid, tid, agent_id, action):
        """dispatch 后立即写入 running 历史，页面刷新后前端可恢复执行中任务的状态显示。"""
        if not agent_id or not project_db:
            return
        try:
            from topoone.engine.store.analysis_store import AnalysisStore
            import datetime as _dt
            s = AnalysisStore(project_db)
            s.save_agent_task_history({
                "project_id": pid,
                "task_id": tid,
                "agent_id": agent_id,
                "action": action,
                "status": "running",
                "steps": "",
                "message": "",
                "error": "",
                "created_at": _dt.datetime.now().isoformat(),
                "finished_at": None,
            })
        except Exception as e:
            logger.warning(f"[AgentHistory] save running failed for {agent_id}: {e}")


def _ensure_project_db(multi_db, task_id: str):
    """Get the project database for a task, ensuring the DB is initialized."""
    main_db = multi_db.main_db
    row = main_db.fetchone(
        "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,))
    if not row:
        return None
    return multi_db.get_project_db(row["project_id"])


def _ensure_table(db, table_name: str, ddl: str):
    """Create table if it doesn't exist on the given database."""
    try:
        for stmt in ddl.split(";"):
            stmt = stmt.strip()
            if stmt:
                db.execute(stmt)
        db.commit()
    except Exception as e:
        logger.warning(f"[ensure_table] failed to create {table_name}: {e}")
