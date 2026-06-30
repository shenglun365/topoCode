"""
AST Worker — 独立进程执行 6 步分析流水线

启动方式:
    python -m ast_worker --task-id <task_id> --run-id <run_id> --data-dir <path>

被 main.py 在 distributed 模式下作为子进程启动。
完成后直接写入数据库（同一份 DB 文件），主进程通过轮询获知进度。
"""

from __future__ import annotations

import logging
import os
import sys
import time

from logging_config import setup_logging
from config import TOPO_MODE

setup_logging()
logger = logging.getLogger("ast_worker")


class AstProgressDummy:
    """替代 ZMQServer 的进度发布哑元 — 跑在子进程中，不发布到主进程 ZMQ"""
    def publish(self, topic: str, event_type: str, data: dict):
        logger.debug(f"[AstWorker] progress: {topic}.{event_type} {data}")


def main():
    data_dir = None
    task_id = None
    run_id = None

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--task-id" and i + 1 < len(args):
            task_id = args[i + 1]; i += 2
        elif args[i] == "--run-id" and i + 1 < len(args):
            run_id = args[i + 1]; i += 2
        elif args[i] == "--data-dir" and i + 1 < len(args):
            data_dir = args[i + 1]; i += 2
        elif args[i] == "--help":
            print("Usage: python -m ast_worker --task-id X --run-id Y --data-dir PATH")
            return
        else:
            i += 1

    if not task_id or not run_id:
        logger.error("task_id and run_id are required")
        sys.exit(1)
    if not data_dir:
        data_dir = os.environ.get("TOPOCODE_DB_DIR",
                                  os.path.join(os.path.expanduser("~"), ".topocode"))

    logger.info(f"[AstWorker] starting task={task_id} run={run_id} data_dir={data_dir} mode={TOPO_MODE}")

    from messaging.worker_signal import signal_ready, start_heartbeat_thread
    signal_ready()
    start_heartbeat_thread()

    from sqlite_ctx import MultiDBManager
    from analyst_runner import _do_parse

    multi_db = MultiDBManager(data_dir)
    dummy_server = AstProgressDummy()
    start_time = time.time()

    # SIGTERM → 设置停止标志让 _do_parse 优雅退出
    _sigterm_caught = False
    def _handle_sigterm(signum, frame):
        nonlocal _sigterm_caught
        _sigterm_caught = True
        from analyst_runner import set_stop_flag
        set_stop_flag(task_id)
        logger.info(f"[AstWorker] SIGTERM received, stopping task={task_id}")
    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        result = _do_parse(dummy_server, multi_db, task_id, run_id, start_time)
        logger.info(f"[AstWorker] task={task_id} done: {result.get('files_processed', 0)} files")
    except Exception as e:
        if _sigterm_caught:
            logger.info(f"[AstWorker] task={task_id} terminated by SIGTERM")
        else:
            logger.exception(f"[AstWorker] task={task_id} failed: {e}")
        from store.task_store import TaskStore
        ts = TaskStore(multi_db.main_db)
        ts.update_task_status(task_id, "error", error=str(e))
        if run_id:
            ts.finish_run(run_id, "error", str(e))
        sys.exit(1)
    finally:
        multi_db.close_all()

    # 标记完成
    from store.task_store import TaskStore
    ts = TaskStore(multi_db.main_db)
    if result and not result.get("stopped"):
        ts.update_task_status(task_id, "done", progress=100, error="")
        if run_id:
            ts.finish_run(run_id, "done")
    else:
        ts.update_task_status(task_id, "cancelled", error="")
        if run_id:
            ts.finish_run(run_id, "cancelled")

    logger.info(f"[AstWorker] task={task_id} finished")
    sys.exit(0)


if __name__ == "__main__":
    main()
