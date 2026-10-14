"""一键基线刷新编排（数据主权批E2）。

kind=baseline_refresh：collect_graph(采集+分组, 公共服务管线) →
component_name(命名, LLM 失败容错) 三步串行——FE「更新基线」单端点入口，
任务中心单作业可见全进度。子步骤复用各自 handler(独立容错, 步骤失败即停)。
"""
from __future__ import annotations

import logging

from . import job_runner
from .job_runner import JobCtx

logger = logging.getLogger(__name__)


class _SubCtx:
    """子步骤上下文：pid/scope 透传, progress/cancelled 代理父作业(阶段前缀)。"""

    def __init__(self, parent: JobCtx, pid: str, scope: dict, stage: str):
        self._parent = parent
        self._pid = pid
        self._scope = scope
        self._stage = stage

    pid = property(lambda self: self._pid)
    scope = property(lambda self: self._scope)
    job = property(lambda self: {"id": self._parent.job.get("id"),
                                 "projectId": self._pid})

    def cancelled(self):
        return self._parent.cancelled()

    def progress(self, **kw):
        cur = kw.get("current") or ""
        kw["current"] = f"[{self._stage}] {cur}"[:120]
        self._parent.progress(**kw)


def _job_baseline_refresh(ctx: JobCtx) -> dict:
    from . import component_naming, graph_collect
    from .. import store as _store_mod

    pid = ctx.pid
    scope = dict(ctx.scope or {})
    out: dict = {"steps": {}}

    ctx.progress(total=2, done=0, current="[采集] 语义管线(解析→符号→关系→社区→分组)")
    r1 = graph_collect._job_collect_graph(_SubCtx(ctx, pid, scope, "采集"))
    out["steps"]["collect"] = r1
    if r1.get("error"):
        out["error"] = f"采集失败: {r1['error']}"
        return out

    ctx.progress(total=2, done=1, current="[命名] KB llm 通道")
    try:
        r3 = component_naming._job_component_name(_SubCtx(ctx, pid, {}, "命名"))
        out["steps"]["naming"] = r3
        if r3.get("error"):
            out["warning"] = f"命名失败: {r3['error']}"
    except Exception as e:  # noqa: BLE001
        out["steps"]["naming"] = {"error": str(e)}
        out["warning"] = f"命名异常: {e}"

    ctx.progress(total=2, done=2, current="完成")
    out["rev"] = (r1 or {}).get("rev") or ""
    out["head"] = (r1 or {}).get("head") or ""
    # W5 轻事实层(2610-B1): 尾步挂测试文件模式扫描(纯文件名 glob, 成本极低;
    # 失败容错不影响基线刷新)。D-8: 覆盖率不采(未来 CI/CD 整合供数)。
    try:
        from .test_reach import record_test_scan
        root = str((scope or {}).get("root") or "")
        if not root:
            _p = _store_mod.ProjectsStore.get(pid) or {}
            root = str(_p.get("rootPath") or _p.get("root_path") or "")
        out["steps"]["testScan"] = record_test_scan(pid, root)
    except Exception as e:  # noqa: BLE001
        out["steps"]["testScan"] = {"error": str(e)}
    logger.info("[baseline-refresh] 完成: %s", {k: (v or {}).get("error") or "ok"
                                                for k, v in out["steps"].items()})
    return out


job_runner.register("baseline_refresh", _job_baseline_refresh)  # noqa: E305
