"""范围提取作业（交互提取闭环需求）：files/comm 范围 LLM 提取的任务化封装。

三个交互入口共用（基线对比「提取并重新对比」/ 语义列表按组件提取 / 按文件提取）：
弹窗确认范围 → 本作业后台执行（进度在任务中心）→ 完成经失效总线刷新。
"""
from __future__ import annotations

from typing import List

from . import job_runner


def _job_extract_scope(ctx) -> dict:
    """extract_scope 作业执行体：scope = {root, project, scopeType(files|comm),
    key(组件id), files[], kinds[], level, modelId}。执行体同步调 engine.extract_scope。"""
    from .engine import extract_scope
    from .paths import resolve_root
    sc = ctx.scope or {}
    rid = (resolve_root(sc.get("root") or "", sc.get("project")) or "").strip()
    if not rid:
        return {"error": "项目 root 解析失败"}
    files: List[str] = list(sc.get("files") or [])
    ctx.progress(total=max(len(files), 1), done=0)
    r = extract_scope(
        rid, sc.get("project"),
        scope_type=sc.get("scopeType") or "files",
        scope_key=sc.get("key") or "",
        files=files or None,
        kinds=sc.get("kinds") or None,
        model_id=sc.get("modelId"),
        level=sc.get("level") or "implementation",
    )
    if r.get("error"):
        return {"error": r["error"], "saved": 0}
    n = r.get("count") or len(r.get("assets") or [])
    ctx.progress(total=max(len(files), 1), done=max(len(files), 1), saved=n)
    return {"saved": n,
            "summary": f"范围提取 {n} 条资产 / {len(files)} 文件"}


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
