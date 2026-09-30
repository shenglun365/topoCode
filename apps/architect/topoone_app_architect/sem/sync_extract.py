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
from typing import Dict, List, Optional, Set

from .paths import _norm_path, project_id_for, resolve_root

logger = logging.getLogger(__name__)

_SYNC_CAP = 2000              # 快照清单上限(超大仓库防雪崩；超出部分下次同步)


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


def _snapshot_loop(ctx) -> dict:
    """逐文件推进(LLM 在环后单文件 1~3 分钟，原批口径 10 文件/更会让进度
    长时间凝固在 done=0)。每文件 done+1/saved 即时落库(浮窗/轮询可见)，
    单文件异常不拖累整批；连续 ≥5 个文件系统性同错(范围/符号库类)熔断。
    批 1-4 收编：进度走 job 行(原进程内 dict)，取消走 cancelRequested 协作标记。
    """
    from . import job_runner
    from .engine import extract_scope
    snapshot = list((ctx.scope or {}).get("files") or [])
    level = (ctx.scope or {}).get("level") or "implementation"
    rid = (ctx.scope or {}).get("root") or ""
    project = (ctx.scope or {}).get("project") or ""
    total = len(snapshot)
    done = saved = 0
    consecutive_errors = 0
    errors: list = []
    for f in snapshot:
        if ctx.cancelled():
            return {"saved": saved, "summary": f"已取消({done}/{total})"}
        ctx.progress(total=total, done=done, saved=saved, current=f)
        try:
            res = extract_scope(rid, project, "files", "", files=[f], level=level)
            if isinstance(res, dict) and res.get("error"):
                consecutive_errors += 1
                errors = (errors or [])[-4:] + [
                    {"files": [f], "error": str(res.get("error"))[:200]}]
                if consecutive_errors >= 5:
                    return {"saved": saved, "error": f"连续 {consecutive_errors} 文件同错，熔断",
                            "errors": errors, "summary": f"熔断({done}/{total})"}
            else:
                consecutive_errors = 0
                saved += (res.get("count") or 0)
        except Exception as e:  # noqa: BLE001 — 作业线程必须吞异常保状态一致
            logger.warning("[sync-extract] 作业异常(%s): %s", f, e, exc_info=True)
            consecutive_errors += 1
            errors = (errors or [])[-4:] + [
                {"files": [f], "error": str(e)[:200]}]
            if consecutive_errors >= 5:
                return {"saved": saved, "error": f"连续 {consecutive_errors} 文件同错，熔断",
                        "errors": errors, "summary": f"熔断({done}/{total})"}
        finally:
            done += 1
            ctx.progress(total=total, done=done, saved=saved)
    return {"saved": saved, "errors": errors, "summary": f"完成({done}/{total})"}


from . import job_runner as _job_runner
_job_runner.register("extract_delta", _snapshot_loop)


def sync_extract_start(root: Optional[str], project: Optional[str],
                       batch: int = 10, level: str = "implementation") -> dict:
    """启动快照批量提取作业(批 1-4 收编：job 行持久化 + 统一调度器分派)。

    清单在启动时一次计算(快照)，作业内不再重算。与 unowned 批量作业互斥
    (同项目同时至多一个提取循环，沿用原互斥语义)。
    """
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    pid = project_id_for(root, project)
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
    if not snapshot:
        return {"started": False, "reason": "nothing_to_extract", "total": 0}
    from . import job_runner
    r = job_runner.start_job(
        pid, "extract_delta",
        scope={"type": "project", "files": snapshot, "level": level,
               "root": rid, "project": project, "batch": max(1, batch)},
        llm=True)   # 提取环后含 LLM 单文件解析 → 计入 LLM 闸门
    if r.get("started"):
        logger.info("[sync-extract] 作业启动: pid=%s total=%d batch=%d",
                    pid, len(snapshot), batch)
        return {"started": True, "total": len(snapshot),
                "jobId": (r.get("job") or {}).get("id") or ""}
    if r.get("reason") == "already_running":
        return {"started": False, "reason": "already_running"}
    return {"started": False, "reason": r.get("reason") or "unknown"}


def sync_extract_status(root: Optional[str], project: Optional[str]) -> dict:
    """作业进度轮询(批 1-4：读 job 行映射旧响应形状，FE 兼容)。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"running": False}
    pid = project_id_for(root, project)
    from . import job_runner
    job = job_runner.active_job(pid, "extract_delta")
    if not job:
        return {"running": False}
    p = job.get("progress") or {}
    result = job.get("result") or {}
    return {
        "running": job.get("state") == "running",
        "total": p.get("total") or 0, "done": p.get("done") or 0,
        "saved": p.get("saved") or 0, "batches": 0,
        "errors": result.get("errors") or [],
        "stopped": job.get("state") == "cancelled",
        "startedAt": job.get("startedAt") or 0,
        "finishedAt": job.get("finishedAt") or 0,
        "level": (job.get("scope") or {}).get("level") or "implementation",
        "batch": (job.get("scope") or {}).get("batch") or 10,
        "current": p.get("current") or "",
        "jobId": job.get("id") or "", "jobState": job.get("state") or "",
    }


def sync_extract_stop(root: Optional[str], project: Optional[str]) -> dict:
    """请求停止作业(协作式取消；已落库资产保留)。"""
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"stopped": False}
    pid = project_id_for(root, project)
    from . import job_runner
    job = job_runner.active_job(pid, "extract_delta")
    if not job:
        return {"stopped": False}
    r = job_runner.cancel_job(pid, job["id"])
    return {"stopped": bool(r.get("cancelled"))}
