"""「校验并提取」= 变化量校验(extract-plan) + 快照批量提取作业(sync-extract)。

全量语义下的增量口径(用户确认的产品定义)：
- 待提取 = git 变更(新增∪修改) ∪ 从未提取(符号全集中零资产) ∪ 仅剩 stale 资产文件；
  排除无独立符号文件(结构性无产出)；
- 删除文件只失效不提取(校验阶段的 reconcile 已按哈希口径标记)；
- 执行按启动时的清单快照迭代(所见即所得；作业中产生的新变更下次同步)。

作业复用 unowned 批量提取的成熟模式：单飞/每批 N/固定清单/可停止/进度轮询；
并与 unowned 作业互斥(同项目同时至多一个提取循环)。
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional, Set

from .paths import _norm_path, project_id_for, resolve_root

logger = logging.getLogger(__name__)

_SYNC_CAP = 2000              # 快照清单上限(超大仓库防雪崩；超出部分下次同步)
_SYNC_MAX_BATCHES = 400       # 循环保险丝(2000/批10 → 理论 ≤200 批)

_jobs: Dict[str, dict] = {}   # pid → 作业状态(进程内，不落库)
_jobs_lock = threading.Lock()


def _delta(root: str, project: Optional[str], *, run_reconcile: bool) -> dict:
    """变化量核心口径(计划与快照共用，避免双算)。

    返回 {added, modified, deleted, neverExtracted, staleOnly, toExtract,
          invalidated, files(全量清单 cap), truncated, symbolSource}。
    run_reconcile=True 时先按哈希口径 reconcile(校验阶段标准化 stale 标记)。
    """
    pid = project_id_for(root, project)
    invalidated: List[str] = []
    if run_reconcile:
        try:
            from .engine import reconcile_semantic
            invalidated = (reconcile_semantic(root, project) or {}).get("invalidated") or []
        except Exception as e:
            logger.warning("[sync-extract] reconcile 失败(继续按 git 口径计算): %s", e)

    changed: Dict[str, List[str]] = {}
    try:
        from .engine import changed_files
        changed = changed_files(root, project) or {}
    except Exception as e:
        logger.warning("[sync-extract] changed_files 失败: %s", e)
    changed_set = (set(changed.get("added") or []) | set(changed.get("modified") or []))

    # 符号全集 + 可提取预判(与 unowned 同口径)
    from .symbols import open_symbol_conn, close_symbol_conn
    from .unowned import _EXTRACTABLE_KINDS
    conn, src = open_symbol_conn(root, project)
    if conn is None:
        return {"error": f"符号库不可用(source={src})：请先建立代码图谱索引"}
    try:
        kinds_by_file: Dict[str, Set[str]] = {}
        for fp, k in conn.execute(
                "SELECT file_path, kind FROM nodes WHERE kind NOT IN ('file','import')"):
            nf = _norm_path(fp or "")
            if nf:
                kinds_by_file.setdefault(nf, set()).add((k or "").lower())
    finally:
        close_symbol_conn(conn)
    symbol_files = set(kinds_by_file)
    extractable = {f for f in symbol_files
                   if kinds_by_file.get(f, set()) & _EXTRACTABLE_KINDS}

    # 资产锚点索引(首锚点)：任一资产文件 / active 资产文件
    any_asset: Set[str] = set()
    active_asset: Set[str] = set()
    try:
        from .. import store
        for a in (store.SemanticAssetsStore.all_status(pid, limit=20000) or []):
            if (a.get("status") or "active") == "deleted":
                continue
            for r in (a.get("astRefs") or [])[:1]:
                f = _norm_path(r.get("file") or "")
                if f:
                    any_asset.add(f)
                    if (a.get("status") or "active") == "active":
                        active_asset.add(f)
    except Exception as e:
        logger.warning("[sync-extract] 资产锚点索引失败: %s", e)

    never = {f for f in symbol_files if f not in any_asset}
    stale_only = {f for f in symbol_files if f in any_asset and f not in active_asset}
    full = (changed_set | never | stale_only) & extractable
    files = sorted(full)[:_SYNC_CAP]
    return {
        "added": len((set(changed.get("added") or []) & symbol_files)),
        "modified": len((set(changed.get("modified") or []) & symbol_files)),
        "deleted": len(changed.get("deleted") or []),
        "neverExtracted": len(never & extractable),
        "staleOnly": len(stale_only & extractable),
        "toExtract": len(full),
        "invalidated": len(invalidated),
        "files": files,
        "truncated": len(full) > len(files),
        "symbolSource": src,
    }


def extract_plan(root: Optional[str], project: Optional[str]) -> dict:
    """校验阶段：reconcile 标准化 stale + 变化量统计与样本清单。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"error": "项目根未解析"}
    plan = _delta(rid, project, run_reconcile=True)
    if plan.get("error"):
        return plan
    out = dict(plan)
    out["files"] = plan["files"][:20]        # 展示用样本
    out["batchesEstimate"] = (plan["toExtract"] + 9) // 10
    return out


def _snapshot_loop(pid: str, rid: str, project: Optional[str],
                   snapshot: List[str], batch: int, level: str) -> None:
    job = _jobs.get(pid) or {}
    try:
        from .engine import extract_scope
        step = max(1, batch)
        for i in range(0, len(snapshot), step):
            if job.get("stop"):
                job["stopped"] = True
                break
            if i >= _SYNC_MAX_BATCHES * step:
                break
            files = snapshot[i:i + step]
            try:
                res = extract_scope(rid, project, "files", "", files=files, level=level)
                if isinstance(res, dict) and res.get("error"):
                    job["errors"] = (job.get("errors") or [])[-4:] + [
                        {"files": files, "error": str(res.get("error"))[:200]}]
                    break        # 范围/符号库类错误：继续批大概率同样失败，如实上报
                job["saved"] = job.get("saved", 0) + (res.get("count") or 0)
            except Exception as e:  # noqa: BLE001 — 作业线程必须吞异常保状态一致
                logger.warning("[sync-extract] 作业异常: %s", e, exc_info=True)
                job["errors"] = (job.get("errors") or [])[-4:] + [
                    {"files": files, "error": str(e)[:200]}]
                break
            job["done"] = job.get("done", 0) + len(files)
            job["batches"] = job.get("batches", 0) + 1
    finally:
        job["running"] = False
        job["finishedAt"] = time.time()


def _job_public(job: dict) -> dict:
    return {k: job.get(k) for k in
            ("running", "total", "done", "saved", "batches", "errors", "stopped",
             "startedAt", "finishedAt", "level", "batch")}


def sync_extract_start(root: Optional[str], project: Optional[str],
                       batch: int = 10, level: str = "implementation") -> dict:
    """启动快照批量提取作业。清单在启动时一次计算(快照)，作业内不再重算。

    与 unowned 批量作业互斥(同项目同时至多一个提取循环)。
    """
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    pid = project_id_for(root, project)
    with _jobs_lock:
        job = _jobs.get(pid)
        if job and job.get("running"):
            return {"started": False, "reason": "already_running",
                    "progress": _job_public(job)}
    try:
        from .unowned import unowned_extract_status
        if (unowned_extract_status(root, project) or {}).get("running"):
            return {"started": False, "reason": "unowned_running"}
    except Exception:
        pass
    # 快照(不再 reconcile——校验阶段已跑；两次会重复失效+双份 git diff)
    snap = _delta(rid, project, run_reconcile=False)
    if snap.get("error"):
        return {"started": False, "reason": "plan_error", "message": snap["error"]}
    snapshot = snap.get("files") or []
    with _jobs_lock:
        job = _jobs.get(pid)
        if job and job.get("running"):
            return {"started": False, "reason": "already_running",
                    "progress": _job_public(job)}
        if not snapshot:
            return {"started": False, "reason": "nothing_to_extract", "total": 0}
        _jobs[pid] = {"running": True, "total": len(snapshot), "done": 0, "saved": 0,
                      "batches": 0, "errors": [], "stopped": False,
                      "startedAt": time.time(), "level": level, "batch": batch}
    threading.Thread(target=_snapshot_loop,
                     args=(pid, rid, project, snapshot, max(1, batch), level),
                     daemon=True, name=f"sync-extract-{pid}").start()
    logger.info("[sync-extract] 作业启动: pid=%s total=%d batch=%d",
                pid, len(snapshot), batch)
    return {"started": True, "total": len(snapshot)}


def sync_extract_status(root: Optional[str], project: Optional[str]) -> dict:
    """作业进度轮询(无作业/已完成 → running=False 携带末次统计)。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"running": False}
    pid = project_id_for(root, project)
    with _jobs_lock:
        job = _jobs.get(pid)
        if not job:
            return {"running": False}
        return _job_public(job)


def sync_extract_stop(root: Optional[str], project: Optional[str]) -> dict:
    """请求停止作业(当前批完成后退出；已落库资产保留)。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"stopped": False}
    pid = project_id_for(root, project)
    with _jobs_lock:
        job = _jobs.get(pid)
        if job and job.get("running"):
            job["stop"] = True
            return {"stopped": True}
    return {"stopped": False}
