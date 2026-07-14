"""
export_service.py — 导出后台线程：JSONL 生成 + MD5 哈希 + zip 打包 + ZMQ 进度
"""
import hashlib
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

EXPORT_DIR_NAME = "exports"
EXPORT_STATUS_PENDING = "pending"
EXPORT_STATUS_RUNNING = "running"
EXPORT_STATUS_DONE = "done"
EXPORT_STATUS_ERROR = "error"

_export_tasks: dict[str, dict] = {}
_export_lock = threading.Lock()


def _md5_file(file_path: str) -> str:
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except (FileNotFoundError, PermissionError, OSError):
        return ""
    return h.hexdigest()


def _make_rel(project_root: str):
    __root = project_root.replace('\\', '/') if project_root else ''
    def _rel(p):
        if not p:
            return p
        if p.startswith("file:"):
            p = p[5:]
        p = p.replace('\\', '/')
        if __root and p.lower().startswith(__root.lower()):
            p = p[len(__root):]
        return p.lstrip("/")
    return _rel


def _export_worker(export_id: str, multi_db, project_id: str, task_ids: Optional[list[str]],
                   publish_fn):
    """后台导出线程"""
    t0 = time.time()
    tmp_dir = None
    try:
        main_db = multi_db.main_db
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        project_root = project.get("root_path", "") or ""
        project_name = project.get("name", project_id)
        _rel = _make_rel(project_root)

        # 创建导出目录（对导入项目 root_path="" 则 fallback 到 data_dir）
        base_export_dir = project_root if project_root else multi_db.data_dir
        exports_dir = os.path.join(base_export_dir, ".topocode", EXPORT_DIR_NAME)
        os.makedirs(exports_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in project_name)
        archive_name = f"export-{safe_name}-{timestamp}.zip"
        archive_path = os.path.join(exports_dir, archive_name)

        # 临时工作目录
        tmp_dir = tempfile.mkdtemp(prefix=f"export_{export_id}_")

        project_db = multi_db.get_project_db(project_id)

        # ── 确定要导出的 task 列表 ──
        if task_ids:
            all_tasks = []
            for tid in task_ids:
                row = main_db.fetchone("SELECT * FROM analysis_tasks WHERE id = ? AND project_id = ?",
                                       (tid, project_id))
                if row:
                    all_tasks.append(row)
        else:
            all_tasks = main_db.fetchall(
                "SELECT * FROM analysis_tasks WHERE project_id = ?", (project_id,)
            )

        if not all_tasks:
            raise ValueError(f"No tasks found for project {project_id}")

        _update_status(export_id, EXPORT_STATUS_RUNNING, 0, f"Exporting {len(all_tasks)} tasks")

        task_id_list = [t["id"] for t in all_tasks]
        # 实际步数: 3(manifest+project.json+source_files) + n*8(task+7table) + 1(更新manifest)
        total_steps = 4 + len(all_tasks) * 8
        step = 0

        def _progress(msg, inc=1):
            nonlocal step
            step += inc
            pct = min(99, int(step / total_steps * 100))
            _update_status(export_id, EXPORT_STATUS_RUNNING, pct, msg)
            publish_fn("export", "export.progress", {
                "exportId": export_id, "progress": pct, "message": msg,
            })

        # ── manifest.json ──
        manifest = {
            "version": "1.0",
            "exportedAt": datetime.now().isoformat(),
            "projectName": project_name,
            "projectId": project_id,
            "taskIds": task_id_list,
            "counts": {},
        }
        _progress("Writing manifest")

        # ── project.json ──
        proj_info = {
            "name": project.get("name"),
            "language": project.get("language"),
            "rootPath": project.get("root_path"),
        }
        with open(os.path.join(tmp_dir, "project.json"), "w", encoding="utf-8") as f:
            json.dump(proj_info, f, ensure_ascii=False)
        _progress("Writing project.json")

        # ── source_files.jsonl (含 MD5) ──
        all_source = project_db.fetchall(
            "SELECT * FROM source_files WHERE language != 'directory'"
        )
        source_count = 0
        with open(os.path.join(tmp_dir, "source_files.jsonl"), "w", encoding="utf-8") as f:
            for row in all_source:
                d = dict(row)
                fp = d.get("file_path", "")
                full_path = os.path.join(project_root, fp) if project_root else fp
                d["md5_hash"] = _md5_file(full_path)
                f.write(json.dumps(d, ensure_ascii=False, default=str) + "\n")
                source_count += 1
        manifest["counts"]["source_files"] = source_count
        _progress(f"source_files ({source_count} rows, with MD5)")

        # 逐 task 导出分析数据
        for tid in task_id_list:
            task_info = next(t for t in all_tasks if t["id"] == tid)
            _write_jsonl(task_id=tid, label="tasks", rows=[dict(task_info)],
                         tmp_dir=tmp_dir, key_fields=["id"])
            _progress(f"task {tid[:8]} config")

            for table, label in [
                ("graph_node", "graph_nodes"),
                ("graph_edge", "graph_edges"),
                ("graph_doc", "communities"),
                ("community_hierarchy", "community_hierarchy"),
                ("community_llm_results", "community_llm_results"),
                ("report_subdocs", "report_subdocs"),
                ("file_summaries", "file_summaries"),
            ]:
                rows = project_db.fetchall(
                    f"SELECT * FROM {table} WHERE task_id = ?", (tid,)
                )
                count = len(rows)
                _write_jsonl(task_id=tid, label=label, rows=[dict(r) for r in rows],
                             tmp_dir=tmp_dir, key_fields=None if label == "communities" else None)
                manifest["counts"].setdefault(label, 0)
                manifest["counts"][label] += count
                _progress(f"{label} ({count} rows)")

        # 重新写入 manifest（含最终计数）
        with open(os.path.join(tmp_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        _progress("Updating manifest")

        # ── 打包 zip ──
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(tmp_dir):
                for fn in files:
                    file_path = os.path.join(root, fn)
                    arcname = os.path.relpath(file_path, tmp_dir)
                    zf.write(file_path, arcname)

        elapsed = time.time() - t0
        _update_status(export_id, EXPORT_STATUS_DONE, 100,
                       f"Export complete: {step} steps, {elapsed:.1f}s",
                       result={"archivePath": archive_path, "size": os.path.getsize(archive_path)})
        publish_fn("export", "export.done", {
            "exportId": export_id,
            "archivePath": archive_path,
            "size": os.path.getsize(archive_path),
        })
        logger.info(f"[Export] {export_id} done: {archive_path} ({elapsed:.1f}s)")

    except Exception as e:
        logger.error(f"[Export] {export_id} failed: {e}", exc_info=True)
        _update_status(export_id, EXPORT_STATUS_ERROR, 0, str(e))
        publish_fn("export", "export.error", {"exportId": export_id, "error": str(e)})
    finally:
        if tmp_dir and os.path.exists(tmp_dir):
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _write_jsonl(task_id: str, label: str, rows: list[dict],
                 tmp_dir: str, key_fields: Optional[list[str]] = None):
    """追加写入 JSONL 文件（per-task 文件）"""
    if not rows:
        return
    filepath = os.path.join(tmp_dir, f"{label}.jsonl")
    with open(filepath, "a", encoding="utf-8") as f:
        for row in rows:
            cleaned = {k: v for k, v in row.items() if v is not None}
            f.write(json.dumps(cleaned, ensure_ascii=False, default=str) + "\n")


def _update_status(export_id: str, status: str, progress: int,
                   message: str = "", result: Optional[dict] = None):
    with _export_lock:
        if export_id in _export_tasks:
            _export_tasks[export_id].update({
                "status": status,
                "progress": progress,
                "message": message,
            })
            if result:
                _export_tasks[export_id]["result"] = result


def start_export(multi_db, project_id: str, task_ids: Optional[list[str]],
                 publish_fn) -> str:
    """启动导出后台任务，返回 export_id"""
    export_id = f"export-{uuid.uuid4().hex[:12]}"
    with _export_lock:
        _export_tasks[export_id] = {
            "id": export_id,
            "status": EXPORT_STATUS_PENDING,
            "progress": 0,
            "message": "Queued",
            "result": None,
        }
    thread = threading.Thread(
        target=_export_worker,
        args=(export_id, multi_db, project_id, task_ids, publish_fn),
        daemon=True,
    )
    thread.start()
    return export_id


def get_export_status(export_id: str) -> Optional[dict]:
    with _export_lock:
        return _export_tasks.get(export_id)


def remove_archive(archive_path: str) -> bool:
    """导出完成后删除 zip 文件"""
    try:
        if os.path.exists(archive_path):
            os.remove(archive_path)
            logger.info(f"[Export] removed archive: {archive_path}")
            return True
    except Exception as e:
        logger.warning(f"[Export] failed to remove archive {archive_path}: {e}")
    return False


def cleanup_old_archives(multi_db, project_id: str, days: int = 7):
    """删除指定项目 exports/ 目录下 N 天前的旧 zip 文件"""
    try:
        project = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (project_id,)
        )
        if not project:
            return
        project_root = project.get("root_path", "") or ""
        base_dir = project_root if project_root else multi_db.data_dir
        exports_dir = os.path.join(base_dir, ".topocode", EXPORT_DIR_NAME)
        if not os.path.isdir(exports_dir):
            return
        now = time.time()
        cutoff = now - days * 86400
        removed = 0
        for fname in os.listdir(exports_dir):
            if not fname.endswith(".zip"):
                continue
            fpath = os.path.join(exports_dir, fname)
            if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                try:
                    os.remove(fpath)
                    removed += 1
                except Exception:
                    pass
        if removed:
            logger.info(f"[Export] cleaned {removed} old archives from {exports_dir}")
    except Exception as e:
        logger.warning(f"[Export] cleanup_old_archives error: {e}")
