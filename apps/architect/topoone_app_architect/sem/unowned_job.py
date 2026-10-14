"""未归属批量提取作业体(unowned.py §8.2 拆分): 循环批次/force 重建/进度。"""
from __future__ import annotations

import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

_JOB_MAX_BATCHES = 80                # 循环保险丝(清单 cap 500 / 批 10 → ≤50 批)

from .unowned import _UNOWNED_CAP, unowned_files  # noqa: E402  (清单/上限单源)


def _pending_unowned(rid: str, project: Optional[str], force: bool = False) -> List[str]:
    """当前待提取的未归属文件：零资产/仅剩 stale(重提可复活)，
    且排除无独立符号的结构性无产出文件(config 聚合头等)。

    force=True: 含已有资产文件(批量重建语义——与单文件提取的清除重建一致)。"""
    res = unowned_files(rid, project, limit=_UNOWNED_CAP)
    if res.get("error"):
        return []
    if force:
        return [f["path"] for f in (res.get("files") or [])
                if f.get("extractable", True)]
    return [f["path"] for f in (res.get("files") or [])
            if not f.get("activeCount") and f.get("extractable", True)]


def _extract_job_loop(ctx) -> dict:
    """批 1-4 收编：进度走 job 行，取消走 cancelRequested 协作标记。"""
    from .structural_extract import extract_structural
    rid = (ctx.scope or {}).get("root") or ""
    project = (ctx.scope or {}).get("project") or ""
    batch = max(1, int((ctx.scope or {}).get("batch") or 10))
    level = (ctx.scope or {}).get("level") or "implementation"
    tried: set = set()          # 本作业已尝试文件：产出为 0 的文件 assetCount 恒 0，
                                # 不记录会每批重进待提取集 → 死循环(实测 44 批回归)
    force = bool((ctx.scope or {}).get("force"))
    done = saved = batches = 0
    errors: list = []
    for _ in range(_JOB_MAX_BATCHES):
        if ctx.cancelled():
            return {"saved": saved, "errors": errors, "summary": f"已取消({done})"}
        pending = [f for f in _pending_unowned(rid, project, force) if f not in tried]
        if not pending:
            break
        files = pending[:batch]
        tried.update(files)
        ctx.progress(done=done, saved=saved, batch=batches, current=files[0])
        try:
            if force:
                # 重建语义(与单文件提取一致): 先清该批文件已有实现资产与连带逻辑视图
                from .engine import batch_manage
                batch_manage(rid, project, "clear", files=files)
            # 批6：批量提取走结构化(无 LLM)；语义增强用户按需触发
            res = extract_structural(rid, project, files, rev="workspace")
            if (res or {}).get("parseFailures") == len(files):
                errors = (errors or [])[-4:] + [
                    {"files": files, "error": "解析失败(符号库/KB 不可达?)"}]
                break   # 整批全失败 → 停住如实上报
            if isinstance(res, dict) and res.get("error"):
                errors = (errors or [])[-4:] + [
                    {"files": files, "error": str(res.get("error"))[:200]}]
                break           # 范围/符号库类错误：继续批大概率同样失败，停住如实上报
            saved += (res.get("saved") or 0)
        except Exception as e:  # noqa: BLE001 — 作业线程必须吞异常保状态一致
            logger.warning("[unowned] 批量提取作业异常: %s", e, exc_info=True)
            errors = (errors or [])[-4:] + [
                {"files": files, "error": str(e)[:200]}]
            break
        done += len(files)
        batches += 1
        ctx.progress(done=done, saved=saved, batch=batches)
    return {"saved": saved, "errors": errors, "summary": f"完成({done} 文件/{batches} 批)"}


from . import job_runner as _job_runner
_job_runner.register("extract_unowned", _extract_job_loop)
