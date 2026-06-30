"""
verify_service.py — 导入后文件比对：MD5 逐文件校验
"""
import hashlib
import logging
import os
import threading
import time
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

VERIFY_STATUS_RUNNING = "running"
VERIFY_STATUS_DONE = "done"
VERIFY_STATUS_ERROR = "error"

_verify_tasks: dict[str, dict] = {}
_verify_lock = threading.Lock()


def _md5(file_path: str) -> str:
    h = hashlib.md5()
    try:
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (FileNotFoundError, PermissionError, OSError):
        return None


def _verify_worker(verify_id: str, multi_db, project_id: str, publish_fn):
    t0 = time.time()
    try:
        main_db = multi_db.main_db
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        project_root = project.get("root_path", "") or ""
        project_db = multi_db.get_project_db(project_id)

        # 确保 file_hashes 表存在
        try:
            project_db.execute("""
                CREATE TABLE IF NOT EXISTS file_hashes (
                    file_path TEXT PRIMARY KEY,
                    md5_hash TEXT NOT NULL,
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
        except Exception:
            pass

        hash_rows = project_db.fetchall("SELECT file_path, md5_hash FROM file_hashes")
        if not hash_rows:
            _update_status(verify_id, VERIFY_STATUS_DONE, 100,
                           "无文件哈希记录", result={
                               "total": 0, "matched": 0, "mismatch": 0,
                               "missing": 0, "matchRate": 0, "details": [],
                           })
            return

        total = len(hash_rows)
        matched = 0
        mismatch = 0
        missing = 0
        details = []

        for i, row in enumerate(hash_rows):
            fp = row["file_path"]
            expected_hash = row["md5_hash"]
            full_path = os.path.join(project_root, fp) if project_root else fp

            status = "missing"
            actual_hash = None
            if os.path.isfile(full_path):
                actual_hash = _md5(full_path)
                if actual_hash is None:
                    status = "missing"
                    missing += 1
                elif actual_hash == expected_hash:
                    status = "matched"
                    matched += 1
                else:
                    status = "mismatch"
                    mismatch += 1
            else:
                missing += 1

            details.append({
                "filePath": fp,
                "status": status,
                "expectedHash": expected_hash,
                "actualHash": actual_hash or "",
            })

            if (i + 1) % 50 == 0 or i == total - 1:
                pct = int((i + 1) / total * 100)
                _update_status(verify_id, VERIFY_STATUS_RUNNING, pct,
                               f"校验中 {i + 1}/{total}")

        match_rate = round(matched / total * 100, 1) if total > 0 else 0
        result = {
            "total": total,
            "matched": matched,
            "mismatch": mismatch,
            "missing": missing,
            "matchRate": match_rate,
            "details": details,
        }

        elapsed = time.time() - t0
        _update_status(verify_id, VERIFY_STATUS_DONE, 100,
                       f"比对完成，匹配率 {match_rate}%，耗时 {elapsed:.1f}s",
                       result=result)
        publish_fn("verify", "verify.done", {
            "verifyId": verify_id,
            "projectId": project_id,
            "matchRate": match_rate,
        })
        logger.info(f"[Verify] {verify_id} done: {project_id} match_rate={match_rate}% ({elapsed:.1f}s)")

    except Exception as e:
        logger.error(f"[Verify] {verify_id} failed: {e}", exc_info=True)
        _update_status(verify_id, VERIFY_STATUS_ERROR, 0, str(e))
        publish_fn("verify", "verify.error", {"verifyId": verify_id, "error": str(e)})


def _update_status(verify_id: str, status: str, progress: int,
                   message: str = "", result: Optional[dict] = None):
    with _verify_lock:
        if verify_id in _verify_tasks:
            _verify_tasks[verify_id].update({
                "status": status,
                "progress": progress,
                "message": message,
            })
            if result:
                _verify_tasks[verify_id]["result"] = result


def start_verify(multi_db, project_id: str, publish_fn) -> str:
    """启动文件比对后台任务，返回 verify_id"""
    verify_id = f"verify-{uuid.uuid4().hex[:12]}"
    with _verify_lock:
        _verify_tasks[verify_id] = {
            "id": verify_id,
            "status": VERIFY_STATUS_RUNNING,
            "progress": 0,
            "message": "排队中",
            "result": None,
        }
    thread = threading.Thread(
        target=_verify_worker,
        args=(verify_id, multi_db, project_id, publish_fn),
        daemon=True,
    )
    thread.start()
    return verify_id


def get_verify_status(verify_id: str) -> Optional[dict]:
    with _verify_lock:
        return _verify_tasks.get(verify_id)
