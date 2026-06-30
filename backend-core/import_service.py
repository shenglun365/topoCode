"""
import_service.py — 导入后台线程：JSONL 解析 → 新项目创建 + 数据重映射 + ZMQ 进度
"""
import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

IMPORT_STATUS_PENDING = "pending"
IMPORT_STATUS_RUNNING = "running"
IMPORT_STATUS_DONE = "done"
IMPORT_STATUS_ERROR = "error"

_import_tasks: dict[str, dict] = {}
_import_lock = threading.Lock()


def _import_worker(import_id: str, multi_db, archive_path: str, publish_fn):
    """后台导入线程 — 只允许创建新项目"""
    t0 = time.time()
    tmp_dir = None
    try:
        main_db = multi_db.main_db

        _update_status(import_id, IMPORT_STATUS_RUNNING, 0, "解压导入包")

        # ── 解压 ──
        tmp_dir = tempfile.mkdtemp(prefix=f"import_{import_id}_")
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(tmp_dir)

        # ── 验证 manifest ──
        manifest_path = os.path.join(tmp_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise ValueError("导入包缺少 manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        logger.info(f"[Import] manifest: {json.dumps(manifest, ensure_ascii=False)[:200]}")

        # ── 读取 project.json ──
        proj_path = os.path.join(tmp_dir, "project.json")
        proj_info = {}
        if os.path.exists(proj_path):
            with open(proj_path, "r", encoding="utf-8") as f:
                proj_info = json.load(f)

        import_name = proj_info.get("name", manifest.get("projectName", "Imported Project"))
        import_language = proj_info.get("language", "Unknown")

        # ── 创建新项目（同名自动加后缀） ──
        project_id = f"proj-{uuid.uuid4().hex[:8]}"
        base_name = import_name
        suffix = 1
        while main_db.fetchone("SELECT id FROM projects WHERE name = ?", (base_name,)):
            base_name = f"{import_name}-{suffix}"
            suffix += 1

        now = datetime.now().isoformat()
        main_db.insert("projects", {
            "id": project_id,
            "name": base_name,
            "root_path": "",
            "language": import_language,
            "file_count": 0,
            "status": "synced",
            "needs_resync": 1,
            "has_file_changes": 0,
            "is_sample": 0,
            "created_at": now,
            "updated_at": now,
        })
        logger.info(f"[Import] created project {project_id} ({base_name})")

        _update_status(import_id, IMPORT_STATUS_RUNNING, 10, "创建项目库")

        # ── 创建项目 DB ──
        project_db = multi_db.init_project_db(project_id)
        multi_db._migrate_project_db(project_db)

        # ── 读取 JSONL，统计行数 ──
        jsonl_files = {
            "source_files": {"table": "source_files", "cols": None},
            "graph_nodes": {"table": "graph_node", "cols": None},
            "graph_edges": {"table": "graph_edge", "cols": None},
            "communities": {"table": "graph_doc", "cols": None},
            "community_hierarchy": {"table": "community_hierarchy", "cols": None},
            "community_llm_results": {"table": "community_llm_results", "cols": None},
            "report_subdocs": {"table": "report_subdocs", "cols": None},
            "file_summaries": {"table": "file_summaries", "cols": None},
        }

        # ── 读取 tasks.jsonl，重映射 task_id ──
        task_map = {}  # old_task_id → new_task_id
        imported_tasks = []
        tasks_path = os.path.join(tmp_dir, "tasks.jsonl")
        if os.path.exists(tasks_path):
            with open(tasks_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    old_task = json.loads(line)
                    old_id = old_task.get("id", "")
                    new_id = f"task-{uuid.uuid4().hex[:12]}"
                    task_map[old_id] = new_id
                    old_task["id"] = new_id
                    old_task["project_id"] = project_id
                    old_task["status"] = "done"
                    if "created_at" not in old_task:
                        old_task["created_at"] = now
                    if "updated_at" not in old_task:
                        old_task["updated_at"] = now
                    imported_tasks.append(old_task)

        if not imported_tasks:
            raise ValueError("导入包中没有任务数据 (tasks.jsonl 为空)")

        _update_status(import_id, IMPORT_STATUS_RUNNING, 15, f"即将导入 {len(imported_tasks)} 个任务")

        # ── 写入 tasks ──
        for task in imported_tasks:
            main_db.insert("analysis_tasks", task)
        logger.info(f"[Import] imported {len(imported_tasks)} tasks")

        # ── 统计总步骤 ──
        total_steps = 1 + len(jsonl_files)
        step = 1
        _update_status(import_id, IMPORT_STATUS_RUNNING, 20, "导入分析数据")

        # ── 逐类型导入到 project DB ──
        total_rows = 0
        for label, cfg in jsonl_files.items():
            filepath = os.path.join(tmp_dir, f"{label}.jsonl")
            if not os.path.exists(filepath):
                step += 1
                continue
            table = cfg["table"]
            rows = []
            with open(filepath, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    # 重映射 task_id
                    if "task_id" in row:
                        old_tid = row["task_id"]
                        row["task_id"] = task_map.get(old_tid, old_tid)
                    # 清理 project_id 字段
                    if "project_id" in row:
                        row["project_id"] = project_id
                    rows.append(row)

            if not rows:
                step += 1
                continue

            # 批量插入
            if rows:
                _bulk_insert(project_db, table, rows)

            total_rows += len(rows)
            pct = 20 + int(step / total_steps * 70)
            _update_status(import_id, IMPORT_STATUS_RUNNING, pct,
                           f"已导入 {label} ({len(rows)} 条)")
            publish_fn("import", "import.progress", {
                "importId": import_id,
                "progress": pct,
                "message": f"已导入 {label} ({len(rows)} 条)",
            })
            step += 1

        # ── file_hashes 表 ──
        _update_status(import_id, IMPORT_STATUS_RUNNING, 93, "写入文件哈希索引")
        _ensure_file_hashes_table(project_db)
        source_path = os.path.join(tmp_dir, "source_files.jsonl")
        if os.path.exists(source_path):
            hash_rows = []
            with open(source_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    row = json.loads(line)
                    fp = row.get("file_path", "")
                    md5 = row.get("md5_hash", "")
                    if fp and md5:
                        hash_rows.append((fp, md5))
            if hash_rows:
                project_db.executemany(
                    "INSERT OR REPLACE INTO file_hashes (file_path, md5_hash, updated_at) VALUES (?, ?, datetime('now'))",
                    hash_rows,
                )
                project_db.conn.commit()
            logger.info(f"[Import] wrote {len(hash_rows)} file hashes")

        # ── 更新 project 统计 ──
        _update_status(import_id, IMPORT_STATUS_RUNNING, 96, "更新项目信息")
        source_count = main_db.fetchone(
            "SELECT COUNT(*) AS cnt FROM source_files WHERE project_id = ? AND language != 'directory'",
            (project_id,)
        ) if False else 0  # source_files 在 project DB, 不通过 main_db
        # 用 project DB 统计
        try:
            cnt_row = project_db.fetchone(
                "SELECT COUNT(*) AS cnt FROM source_files WHERE language != 'directory'"
            )
            file_count = cnt_row["cnt"] if cnt_row else 0
        except Exception:
            file_count = 0
        main_db.update("projects", {
            "file_count": file_count,
            "status": "synced",
            "updated_at": datetime.now().isoformat(),
        }, "id = ?", (project_id,))

        elapsed = time.time() - t0
        _update_status(import_id, IMPORT_STATUS_DONE, 100,
                       f"导入完成，共 {total_rows} 条数据，耗时 {elapsed:.1f}s",
                       result={
                           "projectId": project_id,
                           "projectName": base_name,
                           "taskCount": len(imported_tasks),
                           "totalRows": total_rows,
                       })
        publish_fn("import", "import.done", {
            "importId": import_id,
            "projectId": project_id,
            "projectName": base_name,
        })
        logger.info(f"[Import] {import_id} done: {project_id} ({elapsed:.1f}s)")

    except Exception as e:
        logger.error(f"[Import] {import_id} failed: {e}", exc_info=True)
        _update_status(import_id, IMPORT_STATUS_ERROR, 0, str(e))
        publish_fn("import", "import.error", {"importId": import_id, "error": str(e)})
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _bulk_insert(project_db, table: str, rows: list[dict]):
    """通用批量插入，自动推断列名"""
    if not rows:
        return
    col_names = list(rows[0].keys())
    placeholders = ",".join(["?"] * len(col_names))
    cols = ",".join(f'"{c}"' for c in col_names)
    sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        params = [tuple(r.get(c, "") for c in col_names) for r in batch]
        project_db.executemany(sql, params)
    project_db.conn.commit()


def _ensure_file_hashes_table(project_db):
    try:
        project_db.execute("""
            CREATE TABLE IF NOT EXISTS file_hashes (
                file_path TEXT PRIMARY KEY,
                md5_hash TEXT NOT NULL,
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        project_db.conn.commit()
    except Exception:
        pass


def _update_status(import_id: str, status: str, progress: int,
                   message: str = "", result: Optional[dict] = None):
    with _import_lock:
        if import_id in _import_tasks:
            _import_tasks[import_id].update({
                "status": status,
                "progress": progress,
                "message": message,
            })
            if result:
                _import_tasks[import_id]["result"] = result


def start_import(multi_db, archive_path: str, publish_fn) -> str:
    """启动导入后台任务，返回 import_id"""
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    import_id = f"import-{uuid.uuid4().hex[:12]}"
    with _import_lock:
        _import_tasks[import_id] = {
            "id": import_id,
            "status": IMPORT_STATUS_PENDING,
            "progress": 0,
            "message": "排队中",
            "result": None,
        }
    thread = threading.Thread(
        target=_import_worker,
        args=(import_id, multi_db, archive_path, publish_fn),
        daemon=True,
    )
    thread.start()
    return import_id


def get_import_status(import_id: str) -> Optional[dict]:
    with _import_lock:
        return _import_tasks.get(import_id)
