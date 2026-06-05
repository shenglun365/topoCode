import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def save_overall_doc(multi_db, task_id: str, title: str, content: str) -> dict:
    main_db = multi_db.main_db
    task = main_db.fetchone(
        "SELECT project_id FROM analysis_tasks WHERE id = ?",
        (task_id,)
    )
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    project_id = task["project_id"]
    project_db = multi_db.get_project_db(project_id)

    # 清理旧版随机 ID 的 overall 文档（过渡期兼容）
    project_db.execute(
        "DELETE FROM report_subdocs WHERE task_id=? AND comm_id='overall' AND id NOT LIKE ?",
        (task_id, 'overall-%')
    )

    # 使用稳定 ID，支持持久化 web 链接
    doc_id = f"overall-{task_id}"
    now = datetime.now().isoformat()
    project_db.execute(
        "INSERT OR REPLACE INTO report_subdocs (id, task_id, edge_type, comm_id, title, content, created_at, updated_at) VALUES (?, ?, '', 'overall', ?, ?, ?, ?)",
        (doc_id, task_id, title, content, now, now)
    )

    project_db.commit()
    logger.info(f"[saveOverallDoc] saved doc={doc_id} for task={task_id}")

    return {"id": doc_id, "title": title, "content": content, "createdAt": now}
