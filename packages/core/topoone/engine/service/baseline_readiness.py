"""基线就绪编排 — 无状态幂等(baseline.readiness / baseline.ensureReady)。

设计纪律(与 api_cold_start 的"一次性自举"不同, 本模块是可重复调用的稳态接口):
- **无状态**: 就绪状态实时从 projects / analysis_tasks / view_mounts 三表推导,
  不持久化任何编排状态 — 不存在与源表漂移的第二事实源。
- **幂等**: ensureReady 只执行"下一个缺失步骤"; 任务进行中重复调用不产生
  重复任务(与 tasks_crud 的重名拦截口径一致)。
- **不越权**: 仅在**零挂载**时以 origin='auto' 自动挂载最新 done 任务;
  任何 manual 挂载(用户显式操作)永不自动替换 — 遵守 view_service
  "切换一律显式挂载"哲学。

状态机(推导而非存储; 2026-10 KB 去基线化裁决——挂载/基线对齐语义退役,
KB = 自由分析研究引擎):
    no_project → importing → no_analysis → analyzing → ready
    ready = 存在 done 任务(不再要求 view_mounts 挂载; unmounted 态消亡)

fast 任务类型语义(analysis_tasks.type):
- full : 6 步静态管线 + AI 项目摘要(report_service)
- fast : 6 步静态管线 + 组件快速命名(agent 工具调用式, 见
  engine/component_naming_fast.py), 跳过 AI 项目摘要。
  二者静态产物(graph_node/graph_edge/社区)完全同构, fast 供
  architect 消费快速就绪; 后续可用 full 重跑升级为详细通道产物。
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# 就绪状态顺序(仅用于文档/断言, 推导不依赖顺序; unmounted 已随挂载编排退役)
STATES = ("no_project", "importing", "no_analysis", "analyzing", "ready")

_ACTIVE_TASK_STATUS = ("pending", "queued", "running")

# ensure 通道建任务的 report_types —— 单源语义对齐 workbench
# TaskCreateForm.FIXED_REPORT_TYPES(手动建任务恒含这两项)。
# analyst_runner._step5_detect_communities 以此为门: 缺失则
# INCLUDE/CALL/UNIFIED 三线社区全部跳过, 图谱有节点无社区,
# fast-naming 无社区可命名而静默空转(实测 85 文件 1 秒假 done)。
ENSURE_REPORT_TYPES = ["dependency", "callChain"]


def _project_by_root(main_db, root: str) -> Optional[dict]:
    """root 反查项目。三锚点匹配(精确优先)：
    - root_path：static 模式即原始目录; git 模式是镜像 worktree(原始根不在此列)
    - local_repo_path / remote_url：git-local 导入记录的克隆源(=用户原始根)
    缺后两个锚点时 ensureReady 二次调用会误判 no_project → 重复建项。"""
    if not root:
        return None
    abs_root = os.path.abspath(root)
    try:
        row = main_db.fetchone(
            "SELECT id, name, root_path, status FROM projects "
            "WHERE root_path = ? OR local_repo_path = ? OR remote_url = ? "
            "ORDER BY CASE WHEN root_path = ? THEN 0 ELSE 1 END LIMIT 1",
            (abs_root, abs_root, abs_root, abs_root))
        return dict(row) if row else None
    except Exception:
        return None


def _resolve_project(main_db, project_id: str = "", root: str = "") -> Optional[dict]:
    """project_id 优先, 否则按 root_path 反查(与 architect symbols._resolve_core_pid 同口径)。"""
    if project_id:
        row = main_db.fetchone(
            "SELECT id, name, root_path, status FROM projects WHERE id = ?",
            (project_id,))
        if row:
            return dict(row)
    return _project_by_root(main_db, root)


def _latest_task(main_db, pid: str, statuses: tuple) -> Optional[dict]:
    if not statuses:
        return None
    ph = ",".join("?" for _ in statuses)
    try:
        row = main_db.fetchone(
            f"SELECT id, name, type, status, created_at FROM analysis_tasks "
            f"WHERE project_id = ? AND status IN ({ph}) "
            f"ORDER BY created_at DESC LIMIT 1",
            (pid, *statuses))
        return dict(row) if row else None
    except Exception:
        return None


def _importing(main_db, root: str) -> bool:
    """project.import 后台作业进行中(注册表内 running/starting 且无项目行)。"""
    try:
        from topoone.engine.service.project import _IMPORT_JOBS
    except Exception:
        return False
    if _project_by_root(main_db, root):
        return False
    return any((j or {}).get("status") in ("starting", "running")
               for j in _IMPORT_JOBS.values())


def derive_readiness(multi_db, project_id: str = "", root: str = "") -> dict:
    """从既有三表推导就绪状态(只读, 无副作用)。"""
    main_db = multi_db.main_db
    proj = _resolve_project(main_db, project_id, root)
    if not proj:
        state = "importing" if _importing(main_db, root) else "no_project"
        return {"state": state, "projectId": "", "root": root or ""}

    pid = proj["id"]
    active = _latest_task(main_db, pid, _ACTIVE_TASK_STATUS)
    if active:
        return {"state": "analyzing", "projectId": pid, "taskId": active["id"],
                "taskName": active.get("name") or "", "taskType": active.get("type") or "",
                "taskStatus": active.get("status") or "", "root": proj["root_path"]}

    done = _latest_task(main_db, pid, ("done",))
    if not done:
        return {"state": "no_analysis", "projectId": pid, "root": proj["root_path"]}

    out = {"projectId": pid, "taskId": done["id"], "taskName": done.get("name") or "",
           "taskType": done.get("type") or "", "root": proj["root_path"]}
    # 去基线化: done 即 ready(挂载不再是就绪前置); mountedTaskIds 字段保留
    # 向后兼容(消费方 BaselineInitCard/语义资产只读 taskId/mountedTaskIds)。
    out["state"] = "ready"
    out["mountedTaskIds"] = [done["id"]]
    return out


def ensure_ready(server, multi_db, project_id: str = "", root: str = "",
                 task_type: str = "fast", init_git: bool = False) -> dict:
    """执行下一个缺失步骤并返回最新就绪状态。

    task_type 仅在需要新建任务时生效(full/fast); 已有任务/挂载不受影响。
    init_git: 工作目录非 git 仓库时授权 TopoCode 自动初始化
    (FE 冷启动按钮点击即授权; 与 workbench 导入对话框勾选同语义)。
    """
    main_db = multi_db.main_db
    state = derive_readiness(multi_db, project_id, root)

    if state["state"] in ("ready", "analyzing", "importing"):
        return state  # 稳态/进行中 — 幂等返回

    if state["state"] == "no_project":
        if not root:
            raise ValueError("no_project 状态必须提供 root 才能建项")
        # import_project 是 register_project_methods 闭包内的注册函数,
        # 非模块级 —— 经 server.methods 注册表调用(延迟 from-import 必 ImportError)。
        handler = (getattr(server, "methods", {}) or {}).get("project.import")
        if not handler:
            raise ValueError("project.import 未注册, 无法自动建项")
        res = handler(path=root, mode="git-local", init_git=bool(init_git))
        logger.info("[baseline.ensureReady] project.import started: %s", res)
        return derive_readiness(multi_db, "", root)

    if state["state"] == "no_analysis":
        from topoone.engine.store.task_store import TaskStore
        pid = state["projectId"]
        name = f"ensure-{task_type}"
        store = TaskStore(main_db)
        task = store.create_task({
            "project_id": pid, "type": task_type, "name": name,
            "report_types": list(ENSURE_REPORT_TYPES),
        })
        # 复用 analysis.runTask 的入队语义(运行记录 + 后台执行)
        from topoone.engine.analyst_runner import enqueue_analysis_task
        import asyncio
        import time as _time
        run = store.create_run(task["id"], {})
        store.update_task_status(task["id"], "running", progress=0, error="")
        start = _time.time()
        asyncio.create_task(
            enqueue_analysis_task(server, multi_db, task["id"], run["id"], start))
        logger.info("[baseline.ensureReady] task=%s (%s) enqueued", task["id"], task_type)
        return derive_readiness(multi_db, pid)

    return state  # pragma: no cover — 状态机已穷举(挂载步随去基线化退役)



def register_baseline_readiness_methods(server, multi_db) -> None:
    @server.register("baseline.readiness")
    def baseline_readiness(projectId=None, project_id=None, root=None):
        return derive_readiness(multi_db, project_id or projectId, root or "")

    @server.register("baseline.ensureReady")
    async def baseline_ensure_ready(projectId=None, project_id=None, root=None,
                                    taskType=None, task_type=None,
                                    initGit=None, init_git=None):
        return ensure_ready(server, multi_db, project_id or projectId, root or "",
                            (taskType or task_type or "fast"),
                            init_git=bool(initGit or init_git))
