import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def save_overall_doc(multi_db, task_id: str, title: str, content: str) -> dict:
    main_db = multi_db.main_db
    task = main_db.fetchone(
        "SELECT project_id, root_path FROM analysis_tasks t JOIN projects p ON p.id=t.project_id WHERE t.id = ?",
        (task_id,)
    )
    if not task:
        raise ValueError(f"Task not found: {task_id}")

    project_id = task["project_id"]
    project_root = task["root_path"]

    # 通过 ingest 异步写入，避免 pipeline 运行期间直接写 DB
    doc_id = f"overall-{task_id}"
    from ingest import write_ingest
    write_ingest(project_root, "subdoc", {
        "task_id": task_id,
        "project_id": project_id,
        "edge_type": "",
        "comm_id": "overall",
        "doc_id": doc_id,
        "title": title,
        "content": content,
        "template_id": "",
        "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    })

    logger.info(f"[saveOverallDoc] ingested doc={doc_id} for task={task_id}")

    return {"id": doc_id, "title": title, "content": content, "createdAt": datetime.now().isoformat()}
