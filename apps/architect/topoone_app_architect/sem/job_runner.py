"""语义作业统一调度器（批1-3/1-4）。

收编三套 daemon（sync-extract / unowned-extract / enhance-desc）的进程内
_jobs dict 状态：作业行持久化于 arch_semantic_jobs（项目库），handler 协作式
取消（cancelRequested 轮询）+ 进度落库（浮窗/轮询可见）；进程重启后 running→lost
如实对账（本进程 _local_running 不含即非本进程作业）。

并发模型（需求 2-B/D12）：结构化类并行（Semaphore 4）、LLM 类全局串行
（Semaphore 1，成本闸门）；排队 = handler 线程阻塞在信号量（量小可接受）。
幂等：同项目同 kind 活跃作业存在时 start 回执 already_running。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from ..store.jobs import SemanticJobsStore, _now

logger = logging.getLogger(__name__)

_SEM_STRUCT = threading.Semaphore(4)   # 结构化类(无 LLM 成本)并行上限
_SEM_LLM = threading.Semaphore(1)      # LLM 类全局串行(成本闸门)

_BOOT_AT = time.time() * 1000          # 进程启动时间(对账分界：早于此的 running=遗留)

_handlers: Dict[str, Callable[["JobCtx"], dict]] = {}
_local_running: set = set()            # 本进程在跑的 job id（恢复对账分界）
_recovered: set = set()                # 已惰性对账过的 pid
_lock = threading.Lock()


def register(kind: str, fn: Callable[["JobCtx"], dict]) -> None:
    """注册作业执行体（kind → handler）。"""
    _handlers[kind] = fn


class JobCtx:
    """handler 执行上下文：进度落库 + 协作取消检查。"""

    def __init__(self, job: dict):
        self.job = job
        self._cancelled = False

    @property
    def pid(self) -> str:
        return self.job.get("projectId") or ""

    @property
    def scope(self) -> dict:
        return self.job.get("scope") or {}

    def cancelled(self) -> bool:
        if self._cancelled:
            return True
        try:
            row = SemanticJobsStore.get(self.job["id"])
            if row and row.get("cancelRequested"):
                self._cancelled = True
        except Exception:
            pass
        return self._cancelled

    def progress(self, *, total: Optional[int] = None, done: Optional[int] = None,
                 current: str = "", batch: Optional[int] = None,
                 saved: Optional[int] = None, stage: Optional[int] = None) -> None:
        """增量合并进度并落库（失败吞掉——进度丢失不致死）。"""
        try:
            row = SemanticJobsStore.get(self.job["id"])
            cur = dict((row or {}).get("progress") or {})
            if total is not None:
                cur["total"] = total
            if done is not None:
                cur["done"] = done
            if saved is not None:
                cur["saved"] = saved
            if batch is not None:
                cur["batch"] = batch
            if stage is not None:
                cur["stage"] = stage
            if current:
                cur["current"] = current
            SemanticJobsStore.update(self.job["id"], {"progress": cur})
        except Exception:
            pass


def start_job(pid: str, kind: str, scope: Optional[dict] = None, *,
              llm: bool = False, stages: Optional[list] = None,
              created_by: str = "") -> dict:
    """提交作业：幂等（同 pid+kind 活跃即回执）→ 建行 → 分派线程。"""
    if not pid:
        return {"started": False, "reason": "invalid_project"}
    if kind not in _handlers:
        return {"started": False, "reason": "unknown_kind"}
    recover(pid)
    active = SemanticJobsStore.active(pid, kind)
    if active:
        return {"started": False, "reason": "already_running", "job": active[0]}
    job = SemanticJobsStore.create(pid, kind, scope, llm=llm,
                                   stages=stages, created_by=created_by)
    threading.Thread(target=_run_job, args=(job["id"],),
                     daemon=True, name=f"job-{kind}-{job['id']}").start()
    logger.info("[job-runner] 作业提交: pid=%s kind=%s id=%s", pid, kind, job["id"])
    return {"started": True, "job": job}


def _run_job(job_id: str) -> None:
    job = SemanticJobsStore.get(job_id)
    if not job:
        return
    sem = _SEM_LLM if job.get("llm") else _SEM_STRUCT
    acquired = sem.acquire(timeout=600)   # 排队上限 10min，超时如实失败
    if not acquired:
        SemanticJobsStore.finish(job_id, state="failed",
                                 result={"summary": "排队超时(10min)"})
        return
    try:
        job = SemanticJobsStore.get(job_id) or job
        if job.get("state") == "cancelled":
            return
        # 置 running：否则 state 恒 queued 直到终态（任务中心全程显示「排队中」，
        # 完成直接跳完成；重启对账 running→lost 也无从生效）——实测缺口 2026-09-30
        SemanticJobsStore.update(job_id, {"state": "running", "startedAt": _now()})
        job = SemanticJobsStore.get(job_id) or job
        handler = _handlers.get(job.get("kind") or "")
        if handler is None:
            SemanticJobsStore.finish(job_id, state="failed",
                                     result={"summary": f"无执行体: {job.get('kind')}"})
            return
        with _lock:
            _local_running.add(job_id)
        try:
            result = handler(JobCtx(job)) or {}
            row = SemanticJobsStore.get(job_id) or {}
            if row.get("state") == "cancelled":   # handler 内已终态(取消)——不覆盖
                return
            ok_flag = not result.get("error")
            SemanticJobsStore.finish(
                job_id, state="done" if ok_flag else "failed", result=result,
                progress=(SemanticJobsStore.get(job_id) or {}).get("progress") or {})
            logger.info("[job-runner] 作业完成: id=%s kind=%s state=%s",
                        job_id, job.get("kind"), "done" if ok_flag else "failed")
        except Exception as e:  # noqa: BLE001 — 作业线程必须吞异常保状态一致
            logger.warning("[job-runner] 作业异常(%s): %s", job_id, e, exc_info=True)
            SemanticJobsStore.finish(job_id, state="failed",
                                     result={"summary": str(e)[:300]})
        finally:
            # 提取类作业完成后失效 compare 派生缓存：否则重比命中旧结果（提取前口径），
            # pending 不消失 → 用户重复点击重复提交作业（交互提取闭环实测问题 2026-09-30）
            try:
                from .compare import invalidate_compare_cache
                invalidate_compare_cache(job.get("projectId") or "")
            except Exception:
                pass
            with _lock:
                _local_running.discard(job_id)
    finally:
        sem.release()


def cancel_job(pid: str, job_id: str) -> dict:
    """请求取消（协作式：handler 轮询 cancelRequested 退出）。"""
    job = SemanticJobsStore.get(job_id)
    if not job or job.get("projectId") != pid:
        return {"cancelled": False}
    if job.get("state") not in ("queued", "running"):
        return {"cancelled": False, "reason": "not_active"}
    SemanticJobsStore.request_cancel(job_id)
    # queued 且尚未起跑（线程阻塞在信号量）→ 起跑时见 cancelled 即退出；
    # 这里对 queued 直接终态（还没执行无协作点）。
    if job.get("state") == "queued" and job_id not in _local_running:
        SemanticJobsStore.finish(job_id, state="cancelled",
                                 result={"summary": "取消(未开始)"})
    return {"cancelled": True}


def list_jobs(pid: str, state: str = "", limit: int = 50) -> List[dict]:
    recover(pid)
    return SemanticJobsStore.list(pid, state=state, limit=limit)


def active_job(pid: str, kind: str) -> Optional[dict]:
    return (SemanticJobsStore.active(pid, kind) or [None])[0]


def recover(pid: str) -> None:
    """惰性对账（每项目一次）：running 且非本进程在跑 → lost（重启失忆如实呈现）。"""
    with _lock:
        if pid in _recovered:
            return
        _recovered.add(pid)
    try:
        for row in SemanticJobsStore.active(pid):
            # 分界：本进程起跑的 job(running 且 started_at >= 进程启动)不动；
            # 早于进程启动的 running = 重启遗留 → lost。
            if row["id"] in _local_running:
                continue
            if (row.get("state") == "running"
                    and (row.get("startedAt") or 0) >= _BOOT_AT):
                continue
            SemanticJobsStore.finish(row["id"], state="lost",
                                     result={"summary": "进程重启，作业中断"})
    except Exception as e:  # noqa: BLE001
        logger.warning("[job-runner] 对账失败(pid=%s): %s", pid, e)
