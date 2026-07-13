"""
import_service.py — 导入后台线程：JSONL 解析 → 写入/恢复 + 数据重映射 + ZMQ 进度

两种模式:
  - "share" (默认): 写入当前项目，保留原始 task_id（仅冲突时重映射）
  - "restore": 校验 projectId 一致后覆盖原项目，保留 task_id 和原始状态
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

IMPORT_MODE_SHARE = "share"
IMPORT_MODE_RESTORE = "restore"

_import_tasks: dict[str, dict] = {}
_import_lock = threading.Lock()


def _clear_project_analysis_data(project_db, table_names: list[str]):
    """清空项目库中指定的分析数据表（用于 restore 覆盖模式）"""
    for table in table_names:
        try:
            project_db.execute(f"DELETE FROM {table}")
        except Exception:
            pass
    project_db.commit()


def _import_worker(import_id: str, multi_db, archive_path: str, publish_fn,
                   import_mode: str = IMPORT_MODE_SHARE,
                   target_project_id: str = "",
                   cleanup_archive: bool = False):
    """后台导入线程"""
    t0 = time.time()
    tmp_dir = None
    try:
        main_db = multi_db.main_db

        if not target_project_id:
            raise ValueError("Must specify target project ID")

        _update_status(import_id, IMPORT_STATUS_RUNNING, 0, "Extracting archive")

        # ── 解压 ──
        tmp_dir = tempfile.mkdtemp(prefix=f"import_{import_id}_")
        with zipfile.ZipFile(archive_path, "r") as zf:
            zf.extractall(tmp_dir)

        # ── 验证 manifest ──
        manifest_path = os.path.join(tmp_dir, "manifest.json")
        if not os.path.exists(manifest_path):
            raise ValueError("Archive missing manifest.json")
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
        logger.info(f"[Import] manifest: {json.dumps(manifest, ensure_ascii=False)[:200]}")

        # ── 读取 project.json ──
        proj_path = os.path.join(tmp_dir, "project.json")
        proj_info = {}
        if os.path.exists(proj_path):
            with open(proj_path, "r", encoding="utf-8") as f:
                proj_info = json.load(f)

        original_project_id = manifest.get("projectId", "")
        original_root = proj_info.get("rootPath", "") or ""
        import_name = proj_info.get("name", manifest.get("projectName", "Imported Project"))
        import_language = proj_info.get("language", "Unknown")
        now = datetime.now().isoformat()
        is_restore = import_mode == IMPORT_MODE_RESTORE

        # ── projectId 校验 ──
        if is_restore:
            if original_project_id != target_project_id:
                raise ValueError(
                    f"Archive project ID ({original_project_id}) "
                    f"does not match target project ID ({target_project_id}), rejecting import"
                )

        # ── 获取目标项目 ──
        existing_project = main_db.fetchone(
            "SELECT * FROM projects WHERE id = ?", (target_project_id,)
        )
        if not existing_project:
            raise ValueError(f"Target project not found: {target_project_id}")

        project_id = existing_project["id"]
        base_name = existing_project["name"]
        logger.info(f"[Import] {import_mode} mode: writing to project {project_id} ({base_name})")
        _update_status(import_id, IMPORT_STATUS_RUNNING, 5,
                       f"{'Overwriting' if is_restore else 'Writing to'} existing project {base_name}")

        # ── 清空旧的分析数据 ──
        clear_tables = [
            "source_files", "graph_node", "graph_edge", "graph_doc",
            "community_hierarchy", "community_llm_results", "report_subdocs",
            "file_summaries", "file_hashes",
        ]
        project_db = multi_db.get_project_db(project_id)
        multi_db._migrate_project_db(project_db)
        _clear_project_analysis_data(project_db, clear_tables)

        # 删除旧的任务记录
        old_tasks = main_db.fetchall(
            "SELECT id FROM analysis_tasks WHERE project_id = ?", (project_id,)
        )
        for ot in old_tasks:
            main_db.delete("analysis_tasks", "id = ?", (ot["id"],))

        # ── 读取 JSONL 配置 ──
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

        # ── 读取 tasks.jsonl，确定 task_id 映射 ──
        task_map = {}
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

                    # restore 模式：保留原始 task_id
                    # share 模式：保留原始 task_id，但检查是否与全局已有任务冲突
                    new_id = old_id
                    if not is_restore:
                        existing = main_db.fetchone(
                            "SELECT id FROM analysis_tasks WHERE id = ?", (old_id,)
                        )
                        if existing:
                            new_id = f"task-{uuid.uuid4().hex[:12]}"
                            logger.info(f"[Import] task_id conflict: {old_id} -> {new_id}")

                    if new_id != old_id:
                        task_map[old_id] = new_id

                    old_task["id"] = new_id
                    old_task["project_id"] = project_id
                    if not is_restore:
                        old_task["status"] = "done"
                    if "created_at" not in old_task:
                        old_task["created_at"] = now
                    if "updated_at" not in old_task:
                        old_task["updated_at"] = now
                    imported_tasks.append(old_task)

        if not imported_tasks:
            raise ValueError("Archive has no task data (tasks.jsonl is empty)")

        _update_status(import_id, IMPORT_STATUS_RUNNING, 15, f"About to import {len(imported_tasks)} tasks")

        # ── 写入 tasks ──
        for task in imported_tasks:
            main_db.insert("analysis_tasks", task)
        logger.info(f"[Import] imported {len(imported_tasks)} tasks")

        # ── 统计总步骤 ──
        total_steps = 1 + len(jsonl_files)
        step = 1
        _update_status(import_id, IMPORT_STATUS_RUNNING, 20, "Importing analysis data")

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
                    # task_id 冲突重映射（task_map 有值才替换）
                    if "task_id" in row and row["task_id"] in task_map:
                        row["task_id"] = task_map[row["task_id"]]
                    # 设置 project_id
                    if "project_id" in row:
                        row["project_id"] = project_id
                    # md5_hash 只在 source_files.jsonl 中存在（用于 file_hashes），
                    # source_files 表本身没有此列，移除避免 INSERT 失败
                    if table == "source_files" and "md5_hash" in row:
                        del row["md5_hash"]
                    # report_subdocs 中概览文档 id 为 overall-{task_id}，task_id 重映射后需同步更新
                    if task_map and table == "report_subdocs" and "id" in row:
                        for old_tid, new_tid in task_map.items():
                            if row["id"].startswith(f"overall-{old_tid}"):
                                row["id"] = f"overall-{new_tid}"
                                break
                    # graph_edge INCLUDE 边的 source_id/target_id 为 file:/abs/path 格式，
                    # 去掉 file: 前缀和原项目根路径转成相对路径，避免空项目导入后因 project_root=""
                    # 导致 community_data._rel 无法归一化匹配 graph_doc.node_list
                    if table == "graph_edge" and row.get("kind") == "imports":
                        for col in ("source_id", "target_id"):
                            val = row.get(col, "")
                            if val.startswith("file:") and original_root:
                                val = val[5:]
                                if val.lower().startswith(original_root.lower()):
                                    val = val[len(original_root):]
                                row[col] = val.lstrip("/")
                    # graph_doc.node_list/edge_list 同样归一化，否则运行时 _rel 产生绝对路径 key，
                    # 与 graph_edge 归一化后的相对路径不匹配，跨社区边全部丢失
                    if table == "graph_doc":
                        _orig_lower = original_root.lower()
                        def _norm_path(pv):
                            if not pv or not pv.startswith("file:") or not original_root:
                                return pv
                            pv = pv[5:]
                            if pv.lower().startswith(_orig_lower):
                                pv = pv[len(original_root):]
                            return pv.lstrip("/")
                        for jcol in ("node_list", "edge_list"):
                            raw = row.get(jcol, "")
                            if not raw:
                                continue
                            try:
                                data = json.loads(raw) if isinstance(raw, str) else raw
                            except Exception:
                                continue
                            if not isinstance(data, list):
                                continue
                            changed = False
                            for item in data:
                                if jcol == "node_list":
                                    if isinstance(item, str):
                                        nv = _norm_path(item)
                                        if nv != item:
                                            data[data.index(item)] = nv
                                            changed = True
                                    elif isinstance(item, dict):
                                        oid = item.get("id", "")
                                        nid = _norm_path(oid)
                                        if nid != oid:
                                            item["id"] = nid
                                            changed = True
                                else:
                                    if isinstance(item, dict):
                                        for ecol in ("source", "target"):
                                            ov = item.get(ecol, "")
                                            nv = _norm_path(ov)
                                            if nv != ov:
                                                item[ecol] = nv
                                                changed = True
                                    elif isinstance(item, (list, tuple)) and len(item) >= 2:
                                        for eidx in range(2):
                                            ov = item[eidx]
                                            if isinstance(ov, str):
                                                nv = _norm_path(ov)
                                                if nv != ov:
                                                    item[eidx] = nv
                                                    changed = True
                            if changed:
                                row[jcol] = json.dumps(data, ensure_ascii=False)
                    rows.append(row)

            if not rows:
                step += 1
                continue

            if rows:
                _bulk_insert(project_db, table, rows)

            total_rows += len(rows)
            pct = 20 + int(step / total_steps * 70)
            _update_status(import_id, IMPORT_STATUS_RUNNING, pct,
                           f"Imported {label} ({len(rows)} rows)")
            publish_fn("import", "import.progress", {
                "importId": import_id,
                "progress": pct,
                "message": f"Imported {label} ({len(rows)} rows)",
            })
            step += 1

        # ── file_hashes 表 ──
        _update_status(import_id, IMPORT_STATUS_RUNNING, 93, "Writing file hash index")
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
        _update_status(import_id, IMPORT_STATUS_RUNNING, 96, "Updating project info")
        try:
            cnt_row = project_db.fetchone(
                "SELECT COUNT(*) AS cnt FROM source_files WHERE language != 'directory'"
            )
            file_count = cnt_row["cnt"] if cnt_row else 0
        except Exception:
            file_count = 0
        main_db.update("projects", {
            "file_count": file_count,
            "language": import_language,
            "status": "synced",
            "updated_at": datetime.now().isoformat(),
        }, "id = ?", (project_id,))

        elapsed = time.time() - t0
        _update_status(import_id, IMPORT_STATUS_DONE, 100,
                       f"Import complete: {total_rows} rows, {elapsed:.1f}s",
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
        # 清理上传的临时 copy（HTTP 上传路径传 cleanup_archive=True）
        if cleanup_archive and archive_path and os.path.exists(archive_path):
            try:
                os.remove(archive_path)
                logger.info(f"[Import] cleaned up archive: {archive_path}")
            except Exception as e:
                logger.warning(f"[Import] failed to clean up archive: {e}")


def _bulk_insert(project_db, table: str, rows: list[dict]):
    """通用批量插入，自动推断列名（收集所有行的列名并集）"""
    if not rows:
        return
    col_names = list({k for row in rows for k in row.keys()})
    placeholders = ",".join(["?"] * len(col_names))
    cols = ",".join(f'"{c}"' for c in col_names)
    sql = f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({placeholders})"
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        params = [tuple(r.get(c) for c in col_names) for r in batch]
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


def start_import(multi_db, archive_path: str, publish_fn,
                 import_mode: str = IMPORT_MODE_SHARE,
                 target_project_id: str = "",
                 cleanup_archive: bool = False) -> str:
    """启动导入后台任务，返回 import_id

    import_mode:
      - "share" (默认): 写入 target_project_id 项目，保留原始 task_id（仅冲突时重映射）
      - "restore": 校验 target_project_id 与导入包一致后覆盖

    target_project_id: 写入目标的项目 ID（share/restore 都需要）
    cleanup_archive: 导入完成后是否删除源 zip（HTTP 上传路径使用）
    """
    if not os.path.exists(archive_path):
        raise FileNotFoundError(f"Archive not found: {archive_path}")
    if import_mode not in (IMPORT_MODE_SHARE, IMPORT_MODE_RESTORE):
        raise ValueError(f"Invalid import_mode: {import_mode}")

    import_id = f"import-{uuid.uuid4().hex[:12]}"
    with _import_lock:
        _import_tasks[import_id] = {
            "id": import_id,
            "status": IMPORT_STATUS_PENDING,
            "progress": 0,
            "message": "Queued",
            "result": None,
        }
    thread = threading.Thread(
        target=_import_worker,
        args=(import_id, multi_db, archive_path, publish_fn, import_mode,
              target_project_id, cleanup_archive),
        daemon=True,
    )
    thread.start()
    return import_id


def get_import_status(import_id: str) -> Optional[dict]:
    with _import_lock:
        return _import_tasks.get(import_id)
