"""
TaskStore — 主库 CRUD 操作

管理 analysis_tasks, analysis_task_runs, analysis_reports, task_config_history
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from .connection import SQLiteContext


class TaskStore:
    """主库任务相关表的 CRUD 封装"""

    def __init__(self, main_db: SQLiteContext):
        self._db = main_db

    # ==================== analysis_tasks ====================

    def create_task(self, task: dict) -> dict:
        """创建新任务"""
        task_id = task.get("id") or str(uuid.uuid4())
        db = self._db.conn
        db.execute("""
            INSERT INTO analysis_tasks (
                id, project_id, type, name, status, progress, total, current,
                scopes, extensions, exclude_dirs, report_types,
                pattern_type, pattern, config_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            task_id,
            task["project_id"],
            task.get("type", "full"),
            task["name"],
            "pending",
            0, 100, 0,
            json.dumps(task.get("scopes", [])),
            json.dumps(task.get("extensions", [])),
            json.dumps(task.get("exclude_dirs", [])),
            json.dumps(task.get("report_types", [])),
            task.get("pattern_type"),
            task.get("pattern"),
            1,
        ))
        self._db.commit()
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取单个任务（JSON 字段已解析）"""
        row = self._db.execute(
            "SELECT * FROM analysis_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        return self._parse_task_row(dict(row))

    def list_tasks(self, project_id: str) -> list[dict]:
        """按项目查询任务列表（含运行统计）"""
        rows = self._db.execute("""
            SELECT t.*,
                   COALESCE(r.run_count, 0) AS run_count,
                   r.last_run_status,
                   r.last_run_number
            FROM analysis_tasks t
            LEFT JOIN (
                SELECT task_id,
                       COUNT(*) AS run_count,
                       MAX(run_number) AS last_run_number,
                       (SELECT status FROM analysis_task_runs r2
                        WHERE r2.task_id = r1.task_id
                        ORDER BY run_number DESC LIMIT 1) AS last_run_status
                FROM analysis_task_runs r1
                GROUP BY task_id
            ) r ON t.id = r.task_id
            WHERE t.project_id = ?
            ORDER BY t.created_at DESC
        """, (project_id,)).fetchall()
        return [self._parse_task_row(dict(r)) for r in rows]

    def update_task_status(self, task_id: str, status: str,
                           progress: int = None, current: int = None,
                           error: str = None):
        """更新任务状态"""
        sets = ["status = ?", "updated_at = datetime('now')"]
        params = [status]
        if progress is not None:
            sets.append("progress = ?")
            params.append(progress)
        if current is not None:
            sets.append("current = ?")
            params.append(current)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        params.append(task_id)
        self._db.execute(
            f"UPDATE analysis_tasks SET {', '.join(sets)} WHERE id = ?",
            params,
        )

    def update_task_config(self, task_id: str, config: dict) -> dict:
        """
        更新任务配置（保存历史 + 版本号++）

        Returns:
            更新后的任务记录
        """
        old_task = self.get_task(task_id)
        if not old_task:
            raise ValueError(f"Task {task_id} not found")
        if old_task["status"] == "running":
            raise RuntimeError("Cannot update config of running task")

        # 保存旧配置到历史
        self._save_config_history(task_id, old_task)

        # 构建更新
        sets = []
        params = []
        field_map = {
            "name": "name", "scopes": "scopes", "extensions": "extensions",
            "exclude_dirs": "exclude_dirs", "report_types": "report_types",
            "pattern_type": "pattern_type", "pattern": "pattern",
        }
        for key, col in field_map.items():
            if key in config:
                val = config[key]
                if isinstance(val, list):
                    val = json.dumps(val)
                sets.append(f"{col} = ?")
                params.append(val)

        sets.append("config_version = config_version + 1")
        sets.append("status = 'pending'")
        sets.append("updated_at = datetime('now')")
        params.append(task_id)

        self._db.execute(
            f"UPDATE analysis_tasks SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        return self.get_task(task_id)

    def delete_task(self, task_id: str) -> int:
        """删除任务（CASCADE 删除 runs/reports/history）"""
        cur = self._db.execute(
            "DELETE FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        return cur.rowcount

    def update_task_meta(self, task_id: str, **kwargs) -> dict:
        """更新任务的元数据 (favorite/pinned/tags)"""
        allowed = {"favorite", "pinned", "tags"}
        sets = []
        params = []
        for k, v in kwargs.items():
            if k in allowed:
                if k == "tags" and isinstance(v, list):
                    v = json.dumps(v)
                sets.append(f"{k} = ?")
                params.append(v)
        if not sets:
            return self.get_task(task_id)
        sets.append("updated_at = datetime('now')")
        params.append(task_id)
        self._db.execute(
            f"UPDATE analysis_tasks SET {', '.join(sets)} WHERE id = ?",
            params,
        )
        return self.get_task(task_id)

    # ==================== analysis_task_runs ====================

    def create_run(self, task_id: str, config_snapshot: dict) -> dict:
        """创建运行记录"""
        run_id = str(uuid.uuid4())
        run_number = self._next_run_number(task_id)

        db = self._db.conn
        db.execute("""
            INSERT INTO analysis_task_runs (
                id, task_id, run_number, status, total,
                snapshot_scope, snapshot_scopes, snapshot_extensions,
                snapshot_exclude_dirs, snapshot_report_types
            ) VALUES (?, ?, ?, 'running', 100, ?, ?, ?, ?, ?)
        """, (
            run_id, task_id, run_number,
            config_snapshot.get("scope"),
            json.dumps(config_snapshot.get("scopes", [])),
            json.dumps(config_snapshot.get("extensions", [])),
            json.dumps(config_snapshot.get("exclude_dirs", [])),
            json.dumps(config_snapshot.get("report_types", [])),
        ))

        # 更新任务的 last_run_id
        self._db.execute(
            "UPDATE analysis_tasks SET last_run_id = ? WHERE id = ?",
            (run_id, task_id),
        )
        self._db.commit()

        return {
            "id": run_id,
            "task_id": task_id,
            "run_number": run_number,
            "status": "running",
        }

    def _next_run_number(self, task_id: str) -> int:
        row = self._db.execute(
            "SELECT COALESCE(MAX(run_number), 0) + 1 AS next_num "
            "FROM analysis_task_runs WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return row["next_num"]

    def get_task_runs(self, task_id: str) -> list[dict]:
        """获取任务的运行历史"""
        rows = self._db.execute(
            "SELECT * FROM analysis_task_runs "
            "WHERE task_id = ? ORDER BY run_number DESC",
            (task_id,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for key in ("snapshot_scopes", "snapshot_extensions",
                        "snapshot_exclude_dirs", "snapshot_report_types"):
                if d.get(key):
                    d[key] = json.loads(d[key])
            result.append(d)
        return result

    def update_run_progress(self, run_id: str, progress: int, current: int):
        self._db.execute("""
            UPDATE analysis_task_runs
            SET progress = ?, current = ?
            WHERE id = ?
        """, (progress, current, run_id))

    def finish_run(self, run_id: str, status: str, error: str = None):
        """完成运行记录"""
        sets = ["status = ?", "finished_at = datetime('now')"]
        params = [status]
        if error:
            sets.append("error = ?")
            params.append(error)
        # 计算耗时
        self._db.execute(f"""
            UPDATE analysis_task_runs
            SET {', '.join(sets)},
                duration_ms = CAST(
                    (julianday(datetime('now')) - julianday(started_at)) * 86400000
                    AS INTEGER)
            WHERE id = ?
        """, params + [run_id])

    # ==================== analysis_reports ====================

    def upsert_report(self, report: dict):
        """插入/覆盖分析报告（同 task_id 只保留一份，按 task_id 删除旧报告）"""
        report_id = report.get("id") or str(uuid.uuid4())
        # 先删除该任务的所有旧报告（task_id 有 UNIQUE 约束）
        self._db.execute(
            "DELETE FROM analysis_reports WHERE task_id = ?",
            (report["task_id"],),
        )
        self._db.execute("""
            INSERT INTO analysis_reports (
                id, task_id, run_id,
                total_ast_nodes, total_symbols,
                total_call_edges, total_dep_edges, total_communities,
                language_stats, files_processed, skipped_files,
                best_call_community_id, best_dep_community_id,
                logs, summary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            report_id, report["task_id"], report["run_id"],
            report.get("total_ast_nodes", 0),
            report.get("total_symbols", 0),
            report.get("total_call_edges", 0),
            report.get("total_dep_edges", 0),
            report.get("total_communities", 0),
            json.dumps(report.get("language_stats", {})),
            report.get("files_processed", 0),
            report.get("skipped_files", 0),
            report.get("best_call_community_id"),
            report.get("best_dep_community_id"),
            json.dumps(report.get("logs", [])),
            report.get("summary"),
        ))

    def get_results(self, task_id: str, run_id: str = None) -> dict:
        """
        获取分析结果

        查询优先级: run_id → task.last_run_id → task_id (最新)
        """
        if run_id is None:
            task = self.get_task(task_id)
            if task and task.get("last_run_id"):
                run_id = task["last_run_id"]

        if run_id:
            row = self._db.execute(
                "SELECT * FROM analysis_reports WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT * FROM analysis_reports WHERE task_id = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (task_id,),
            ).fetchone()

        if not row:
            return {
                "ast": None, "callChain": None,
                "dependencies": None, "dataflow": None,
            }
        d = dict(row)
        if d.get("language_stats"):
            d["language_stats"] = json.loads(d["language_stats"])
        if d.get("logs"):
            d["logs"] = json.loads(d["logs"])
        return d

    def get_task_logs(self, task_id: str, run_id: str = None) -> dict:
        """获取运行日志"""
        results = self.get_results(task_id, run_id)
        return {
            "logs": results.get("logs", []),
            "completed": True,
        }

    # ==================== task_config_history ====================

    def _save_config_history(self, task_id: str, task: dict):
        hist_id = f"hist-{uuid.uuid4().hex[:12]}"

        def _to_json(val):
            if isinstance(val, list):
                return json.dumps(val)
            return val

        self._db.execute("""
            INSERT INTO task_config_history (
                id, task_id, config_version, name,
                scope, scopes, extensions, exclude_dirs,
                report_types, pattern_type, pattern
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            hist_id, task_id, task.get("config_version", 1),
            task.get("name"), task.get("scope"),
            _to_json(task.get("scopes")),
            _to_json(task.get("extensions")),
            _to_json(task.get("exclude_dirs")),
            _to_json(task.get("report_types")),
            task.get("pattern_type"), task.get("pattern"),
        ))

    # ==================== 辅助方法 ====================

    @staticmethod
    def _parse_task_row(d: dict) -> dict:
        """解析任务行，JSON 字段反序列化"""
        for key in ("tags", "scopes", "extensions", "exclude_dirs",
                     "report_types", "result_data"):
            if d.get(key) and isinstance(d[key], str):
                try:
                    d[key] = json.loads(d[key])
                except (json.JSONDecodeError, TypeError):
                    pass
        return d
