"""范围提取作业（交互提取闭环需求）：files/comm 范围 LLM 提取的任务化封装。

三个交互入口共用（基线对比「提取并重新对比」/ 语义列表按组件提取 / 按文件提取）：
弹窗确认范围 → 本作业后台执行（进度在任务中心）→ 完成经失效总线刷新。
"""
from __future__ import annotations

from typing import List

from . import job_runner


def _job_extract_scope(ctx) -> dict:
    """extract_scope 作业执行体：scope = {root, project, scopeType(files|comm),
    key(组件id), files[], kinds[], level, modelId}。

    按 2 文件/批调 engine.extract_scope 并逐批推进进度——整体一次调用会让作业
    长时间停在 0%（running 无中间态，任务中心观感为「等待后直接完成」）。"""
    from .engine import extract_scope
    from .paths import resolve_root
    sc = ctx.scope or {}
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败"}
    files: List[str] = list(sc.get("files") or [])
    if not files:
        return {"saved": 0, "summary": "无可提取文件"}
    total = len(files)
    ctx.progress(total=total, done=0)
    saved_total = 0
    BATCH = 2   # 取消响应粒度：批内 LLM 调用不可中断，批越小停止越快
    for i in range(0, total, BATCH):
        if ctx.cancelled():
            return {"saved": saved_total,
                    "summary": f"已取消({min(i, total)}/{total})"}
        batch = files[i:i + BATCH]
        r = extract_scope(
            rid, sc.get("project"),
            scope_type=sc.get("scopeType") or "files",
            scope_key=sc.get("key") or "",
            files=batch,
            kinds=sc.get("kinds") or None,
            model_id=sc.get("modelId"),
            level=sc.get("level") or "implementation",
        )
        if r.get("error"):
            return {"error": r["error"], "saved": saved_total}
        saved_total += r.get("count") or len(r.get("assets") or [])
        ctx.progress(total=total, done=min(i + BATCH, total), saved=saved_total,
                     current=batch[-1])
    return {"saved": saved_total,
            "summary": f"范围提取 {saved_total} 条资产 / {total} 文件"}


job_runner.register("extract_scope", _job_extract_scope)


def start_extract_scope(root: str, project: str, scope: dict, *,
                        kinds: List[str] = None, level: str = "implementation",
                        model_id: str = "") -> dict:
    """提交范围提取作业（幂等：同类活跃回执 already_running）。"""
    from .paths import project_id_for, resolve_root
    rid = (resolve_root(root, project) or "").strip()
    if not rid:
        return {"started": False, "reason": "invalid_root"}
    return job_runner.start_job(
        project_id_for(rid, project), "extract_scope",
        scope={"root": rid, "project": project, **(scope or {}),
               "kinds": list(kinds or []), "level": level,
               "modelId": model_id or ""},
        llm=True)
