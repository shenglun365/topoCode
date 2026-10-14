"""异步渲染任务层: 提交即回 jobId, 后台串行队列执行, 持久缓存幂等命中。

需求契约(用户裁决): 后台异步 CLI / 支持缓存 / 不阻塞 / 页面刷新不中断。
- 幂等: job key = sha256(fmt + code) —— 同源文重复提交返回同 jobId;
  done 任务(或持久缓存命中)直接回结果(cached=true), 页面刷新后重提交零成本恢复。
- 不阻塞: POST 立即返回; 渲染在单 worker 线程(PlantUmlCli 自带 JVM 串行锁)。
- 缓存: cache_get/cache_put 由宿主注入(零宿主知识; docs 服务用 SQLite
  plantuml_cache 复用 viewer 缓存), 进程重启后命中免渲染。
- 任务表: 内存 LRU(cap JOB_TABLE_CAP) 仅供 jobId 轮询与去重; error 任务
  可重试(重新入队), done 任务直接命中。
"""

from __future__ import annotations

import hashlib
import queue
import threading
import time
from collections import OrderedDict
from typing import Callable, Optional

JOB_TABLE_CAP = 512
QUEUE_CAP = 128

CacheGet = Callable[[str], Optional[str]]
CachePut = Callable[[str, str, str], None]
RenderFn = Callable[[str, str], bytes]


def render_job_key(code: str, fmt: str) -> str:
    """任务幂等键(与 PlantUmlCli LRU 同构: fmt + \0 + code)。"""
    return hashlib.sha256(f"{fmt}\0{code}".encode("utf-8", errors="replace")).hexdigest()


class RenderJobManager:
    """串行渲染任务管理器。render_fn(code, fmt) -> bytes, 异常即任务失败。"""

    def __init__(self, render_fn: RenderFn,
                 cache_get: Optional[CacheGet] = None,
                 cache_put: Optional[CachePut] = None,
                 queue_cap: int = QUEUE_CAP, table_cap: int = JOB_TABLE_CAP):
        self._render_fn = render_fn
        self._cache_get = cache_get
        self._cache_put = cache_put
        self._q: "queue.Queue[tuple[str, str, str]]" = queue.Queue(maxsize=queue_cap)
        self._lock = threading.Lock()
        self._jobs: "OrderedDict[str, dict]" = OrderedDict()
        self._table_cap = table_cap
        self._pending: set[str] = set()
        self._worker = threading.Thread(target=self._run, daemon=True, name="render-jobs")
        self._worker.start()

    # ── 提交 / 查询 ────────────────────────────────────────────

    def submit(self, code: str, fmt: str = "svg") -> dict:
        """提交渲染。返回 {jobId, status[, cached][, svg|error]}——done/error 时带结果。"""
        key = render_job_key(code, fmt)
        with self._lock:
            job = self._jobs.get(key)
            if job is not None:
                self._jobs.move_to_end(key)
                if job["status"] == "done":
                    return {"jobId": key, "status": "done", "cached": True, "svg": job["svg"]}
                if job["status"] == "error":
                    # 失败任务不幂等占位: 弹出后走重试(重新入队)
                    del self._jobs[key]
                else:
                    return {"jobId": key, "status": job["status"]}
        # 持久缓存命中(锁外 IO)
        if self._cache_get is not None:
            try:
                svg = self._cache_get(key)
            except Exception:
                svg = None
            if svg:
                self._finish(key, "done", svg=svg)
                return {"jobId": key, "status": "done", "cached": True, "svg": svg}
        with self._lock:
            if key in self._pending:
                return {"jobId": key, "status": self._jobs.get(key, {}).get("status", "queued")}
            rec = self._record(key, "queued")
            self._pending.add(key)
        try:
            self._q.put_nowait((key, code, fmt))
        except queue.Full:
            with self._lock:
                self._pending.discard(key)
                self._jobs.pop(key, None)
            raise RuntimeError("render job queue full")
        return {"jobId": key, "status": rec["status"]}

    def status(self, job_id: str) -> dict:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return {"jobId": job_id, "status": "unknown"}
            out = {"jobId": job_id, "status": job["status"]}
            if job["status"] == "done":
                out["svg"] = job["svg"]
            elif job["status"] == "error":
                out["error"] = job["error"]
            return out

    def pending_count(self) -> int:
        return self._q.qsize()

    # ── 内部 ───────────────────────────────────────────────────

    def _record(self, key: str, status: str) -> dict:
        rec = {"jobId": key, "status": status, "svg": None, "error": None, "ts": time.time()}
        self._jobs[key] = rec
        self._jobs.move_to_end(key)
        while len(self._jobs) > self._table_cap:
            self._jobs.popitem(last=False)
        return rec

    def _finish(self, key: str, status: str, svg: Optional[str] = None,
                error: Optional[str] = None) -> None:
        with self._lock:
            rec = self._jobs.get(key)
            if rec is None:
                rec = self._record(key, status)
            rec.update(status=status, svg=svg, error=error)
            self._pending.discard(key)

    def _run(self) -> None:
        while True:
            key, code, fmt = self._q.get()
            try:
                with self._lock:
                    rec = self._jobs.get(key)
                    if rec is not None:
                        rec["status"] = "running"
                data = self._render_fn(code, fmt)
                svg = data.decode("utf-8", errors="replace")
                if self._cache_put is not None:
                    try:
                        self._cache_put(key, code, svg)
                    except Exception:
                        pass  # 缓存写失败不影响任务结果
                self._finish(key, "done", svg=svg)
            except Exception as e:
                self._finish(key, "error", error=str(e))
            finally:
                self._q.task_done()
