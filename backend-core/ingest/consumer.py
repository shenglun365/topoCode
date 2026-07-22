"""
ingest/consumer.py — 后台线程消费 ingest 目录中的 JSON 文件

架构：
  解除了 async 事件循环的阻塞 — 在独立线程中轮询，避免阻塞 IPC 请求处理。

  项目列表缓存（60s TTL），避免每轮全表扫描主库。
"""
import json
import logging
import os
import threading
import time
import uuid
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_DISPATCH: dict[str, Callable] = {}


def register_handler(_type: str, handler: Callable):
    """注册 _type 对应的 DB 写入处理函数。handler(data: dict) → None（抛异常表示失败）"""
    _DISPATCH[_type] = handler


def get_handler(_type: str) -> Optional[Callable]:
    return _DISPATCH.get(_type)


def consume_one(ingest_dir: str, fname: str) -> bool:
    """
    消费单个 ingest 文件：
    1. 读 JSON
    2. 按 _type 分发给注册的 handler
    3. 成功则删除文件

    Returns:
        True 消费成功（文件已删除）, False 跳过（下次重试）
    """
    fpath = os.path.join(ingest_dir, fname)
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        logger.warning(f"[ingest] read failed {fname}: {e}")
        return False

    _type = data.get("_type", "")
    handler = get_handler(_type)
    if not handler:
        logger.warning(f"[ingest] unknown _type '{_type}' in {fname}, removing")
        try:
            os.remove(fpath)
        except Exception:
            pass
        return True

    try:
        handler(data)
        os.remove(fpath)
        return True
    except Exception as e:
        logger.warning(f"[ingest] handler failed for {fname}: {e}")
        return False


class IngestConsumer:
    """
    后台线程 ingest 消费者。

    - 在独立线程中轮询，不阻塞 async 事件循环
    - 项目列表缓存（60s TTL），避免每轮查主库
    """

    def __init__(self, multi_db, interval: float = 2.0):
        self._multi_db = multi_db
        self._interval = interval

        # 项目列表缓存
        self._project_cache: dict[str, str] = {}   # pid → root_path
        self._cache_updated: float = 0
        self._cache_ttl: float = 60.0

        self._running = False
        self._thread: Optional[threading.Thread] = None

    def _refresh_project_cache(self):
        """刷新项目列表缓存（TTL 控制）"""
        now = time.time()
        if now - self._cache_updated < self._cache_ttl:
            return
        try:
            rows = self._multi_db.main_db.fetchall(
                "SELECT id, root_path FROM projects "
                "WHERE root_path IS NOT NULL AND root_path != ''"
            )
            self._project_cache = {r["id"]: r["root_path"] for r in rows}
            self._cache_updated = now
            logger.debug(f"[IngestConsumer] refreshed project cache: {len(self._project_cache)} projects")
        except Exception as e:
            logger.warning(f"[IngestConsumer] refresh project cache failed: {e}")

    def _run(self):
        """后台线程主循环"""
        logger.info("[IngestConsumer] background thread started")
        while self._running:
            try:
                self._refresh_project_cache()
                for pid, root in self._project_cache.items():
                    if not root:
                        continue
                    ingest_dir = os.path.join(root, ".topocode", "ingest")
                    if not os.path.isdir(ingest_dir):
                        continue
                    try:
                        files = sorted(
                            f for f in os.listdir(ingest_dir)
                            if f.endswith(".json") and not f.endswith(".tmp")
                        )
                    except OSError:
                        continue
                    for fname in files:
                        if not consume_one(ingest_dir, fname):
                            break
            except Exception as e:
                logger.error(f"[IngestConsumer] loop error: {e}")
            time.sleep(self._interval)
        logger.info("[IngestConsumer] background thread stopped")

    def start(self):
        """启动后台消费线程"""
        if self._thread and self._thread.is_alive():
            logger.warning("[IngestConsumer] already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="ingest-consumer",
        )
        self._thread.start()
        logger.info("[IngestConsumer] started")

    def stop(self):
        """停止消费线程"""
        self._running = False

    def join(self, timeout: float = 5.0):
        """等待线程结束"""
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)


def setup_handlers(multi_db):
    """注册所有 ingest 类型对应的 DB 写入 handler。在 main.py 启动时调用一次。"""

    from store.analysis_store import AnalysisStore
    from store.task_store import TaskStore
    import time as _time

    def _get_project_db(data):
        pid = data.get("project_id")
        if not pid:
            raise ValueError(f"Missing project_id in ingest data: {data.get('_type')}")
        return pid, multi_db.get_project_db(pid)

    def _handle_community_result(data):
        pid, pdb = _get_project_db(data)
        store = AnalysisStore(pdb)
        logger.info(f"[ingest consumer] writing community_result: {data.get('comm_id', '?')} status={data.get('status','?')}")
        store.bulk_insert_llm_results([{
            "task_id": data["task_id"],
            "edge_type": data["edge_type"],
            "comm_lv": data["comm_lv"],
            "comm_id": data["comm_id"],
            "name": data.get("name", ""),
            "summary": data.get("summary", ""),
            "model_id": data.get("model_id", ""),
            "template_id": data.get("template_id", ""),
            "component_type": data.get("component_type", "community"),
            "status": data.get("status", "completed"),
        }])

    def _handle_subdoc(data):
        pid, pdb = _get_project_db(data)
        tid = data["task_id"]
        et = data.get("edge_type", "CALL")
        logger.info(f"[ingest consumer] writing subdoc: {data.get('doc_id', '?')}")
        cid = data.get("comm_id")
        doc_id = data["doc_id"]
        now = data.get("created_at", _time.strftime('%Y-%m-%d %H:%M:%S'))

        if tid and et:
            if cid:
                pdb.execute(
                    "DELETE FROM report_subdocs WHERE task_id=? AND edge_type=? AND comm_id=? AND id!=?",
                    (tid, et, cid, doc_id)
                )
            else:
                pdb.execute(
                    "DELETE FROM report_subdocs WHERE task_id=? AND edge_type=? AND comm_id IS NULL AND id!=?",
                    (tid, et, doc_id)
                )

        pdb.execute(
            "INSERT OR REPLACE INTO report_subdocs (id, task_id, edge_type, comm_id, title, content, template_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, tid, et, cid, data["title"], data["content"], data.get("template_id"), now, now)
        )
        pdb.conn.commit()
        # 更新 doc_project_map 映射
        try:
            multi_db.main_db.execute(
                "INSERT OR REPLACE INTO doc_project_map (doc_id, project_id, task_id) VALUES (?, ?, ?)",
                (doc_id, pid, tid),
            )
        except Exception:
            pass

    def _handle_file_summary(data):
        pid, pdb = _get_project_db(data)
        fp = data["file_path"]
        logger.info(f"[ingest consumer] writing file_summary: {fp[:60]}")
        summary = data["summary"][:2000]
        sid = uuid.uuid4().hex[:16]

        pdb.execute(
            "DELETE FROM file_summaries WHERE project_id=? AND file_path=?",
            (pid, fp)
        )
        pdb.execute(
            "INSERT INTO file_summaries (id, project_id, task_id, file_path, summary, summary_len, source, updated_at) VALUES (?, ?, ?, ?, ?, ?, 'llm', datetime('now'))",
            (sid, pid, data.get("task_id", ""), fp, summary, len(summary))
        )
        pdb.conn.commit()

    register_handler("community_result", _handle_community_result)
    register_handler("subdoc", _handle_subdoc)
    register_handler("file_summary", _handle_file_summary)


try:
    import asyncio
    _async_sleep = asyncio.sleep
except ImportError:
    import time as _time
    async def _async_sleep(sec):
        _time.sleep(sec)
