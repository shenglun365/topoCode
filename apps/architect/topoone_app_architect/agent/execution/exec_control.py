"""执行详情与作业控制(cv-285): 双源(taskId|jobId)统一视图模型 + 单一控制面。

方案甲(用户裁决): 任务行与直通作业 → 同一窗体数据形状(ExecutionDetail);
控制(pause/resume/stop/input)单端点分发——pause=abort 本轮保会话 /
resume=继续(转达) / stop=finish 保留 worktree / input=信息补充与问询回答。
全程复用既有 runner 端点与 exec_bridge.task_input 单源, 无并行控制通道。
"""
from __future__ import annotations

from typing import Any, Dict

from ... import store
from ...store import states as ST

ACTIONS = ("pause", "resume", "stop", "input")

_JOB_ALIVE = ("running", "waiting_input")

# 用户语义终态: 转达/重试不复活(与泵终态守卫同词汇)
_USER_TERMINAL = ("cancelled", "ignored")


def _task_resume_or_input(task: Dict[str, Any], task_id: str,
                          text: str) -> Dict[str, Any]:
    """转达/继续执行按任务状态分型(cv-285c 用户实证: failed 卡转达被
    task-not-active 静默拒绝)。

    running/waiting_input → task_input 单源转达(现状);
    saved → confirm 直接开始;
    failed → 附【用户补充】翻回 saved + confirm 重跑(失败分支续跑 cv-177
    ——重跑不再从零开始), 补充文本随指令下发;
    cancelled/ignored → 明确拒绝(用户语义终态不复活)。"""
    from . import exec_bridge as eb
    st = str(task.get("status") or "")
    if st in _USER_TERMINAL:
        return {"ok": False, "error": "task-terminal"}
    if st in _JOB_ALIVE:
        res = eb.task_input(task_id, text)
        return {"ok": bool(res.get("ok")), "queued": bool(res.get("queued"))}
    if st == ST.TASK_SAVED:
        res = _confirm_saved(task_id)
        return {"ok": bool(res.get("ok")), "retried": True,
                "error": str(res.get("error") or "")}
    if st == "failed":
        instr = str(task.get("instruction") or "")
        supplement = f"\n\n【用户补充(失败重试)】{text}"
        store.TasksStore.update(task_id, {
            "instruction": (instr + supplement)[:8000],
            "status": ST.TASK_SAVED})
        res = _confirm_saved(task_id)
        out = {"ok": bool(res.get("ok")), "retried": True,
               "error": str(res.get("error") or "")}
        if res.get("gateAsk"):
            out["gateAsk"] = res["gateAsk"]   # 脏区问询态透传(卡已落流)
        return out
    return {"ok": False, "error": f"task-status={st}"}


def _confirm_saved(task_id: str) -> Dict[str, Any]:
    """saved → confirm_task(dispatch 单源, 锁内重读)。"""
    from . import dispatch as _dispatch
    return _dispatch.confirm_task(task_id)


def _runner_status(job_id: str) -> Dict[str, Any]:
    """runner 作业快照(活跃度真相源; 失联→空)。"""
    from . import exec_bridge as eb
    if not job_id:
        return {}
    try:
        snap = eb._client().snapshot(job_id)
        if snap and snap.ok:
            return {"runnerStatus": str(snap.status or ""),
                    "sessionId": str(snap.session_id or "")}
    except Exception:  # noqa: BLE001 — 详情快照失败不阻断
        pass
    return {}


def execution_detail(conv_id: str, task_id: str = "",
                     job_id: str = "") -> Dict[str, Any]:
    """双源统一视图模型: 任务行字段 / 直通作业快照 → 同一窗体形状。

    任务源: 任务行全量(instruction/resultMd/specVer/branch/workspace/progress)
    + runner 活跃快照(runnerStatus); 直通源: meta 快照 + 会话复活键。"""
    out: Dict[str, Any] = {"ok": True, "source": "", "convId": conv_id,
                           "status": "", "taskId": task_id or "",
                           "jobId": job_id or ""}
    if task_id:
        task = store.TasksStore.get(task_id) or {}
        if not task:
            return {"ok": False, "error": "task-not-found"}
        out.update({
            "source": "task",
            "title": str(task.get("title") or ""),
            "status": str(task.get("status") or ""),
            "instruction": str(task.get("instruction") or ""),
            "resultMd": str(task.get("resultMd") or ""),
            "specVer": int(task.get("specVer") or 0),
            "executorType": str(task.get("executor_type") or ""),
            "branch": str(task.get("branch") or ""),
            "workspace": str(task.get("workspace") or ""),
            "progress": task.get("progress") or {},
            "jobId": str(task.get("runnerJobId") or ""),
            "reqId": str(task.get("reqId") or ""),
        })
        if out["jobId"] and out["status"] in _JOB_ALIVE:
            out.update(_runner_status(out["jobId"]))
        return out
    if job_id:
        from . import proxy
        entry = proxy.proxy_job_of(conv_id) or {}
        row = store.ConversationsStore.get(conv_id) or {}
        out.update({
            "source": "job",
            "title": "编码执行器会话",
            "status": "running" if entry else "ended",
            "executorType": str(entry.get("executor_type")
                                or row.get("lastExecutor") or ""),
            "workspace": "worktree" if bool(row.get("isolated")) else "inplace",
            "sessionRef": str(row.get("sessionRef") or ""),
        })
        out.update(_runner_status(job_id))
        return out
    return {"ok": False, "error": "no-target"}


def control_execution(conv_id: str, action: str,
                      task_id: str = "", job_id: str = "",
                      text: str = "") -> Dict[str, Any]:
    """单一控制面: pause/resume/stop/input——按源分发到既有单源通道。"""
    if action not in ACTIONS:
        return {"ok": False, "error": f"unknown-action:{action}"}
    from . import exec_bridge as eb
    if task_id:
        task = store.TasksStore.get(task_id) or {}
        if not task:
            return {"ok": False, "error": "task-not-found"}
        job = str(task.get("runnerJobId") or "")
        if action == "pause":
            if not job or (task.get("status") or "") not in _JOB_ALIVE:
                return {"ok": False, "error": "task-not-running"}
            r = eb._runner(f"/api/implement/{job}/abort", {}, 12.0)
            return {"ok": bool(r and r.get("ok")), "action": action}
        if action == "resume":
            return _task_resume_or_input(task, task_id, text.strip() or "继续")
        if action == "input":
            if not text.strip():
                return {"ok": False, "error": "text-empty"}
            return _task_resume_or_input(task, task_id, text.strip())
        # stop: 结束作业(保留 worktree/分支) + 任务终态
        if job:
            r = eb._runner(f"/api/implement/{job}/finish",
                           {"keepWorktree": True}, 12.0)
            if r is None:
                return {"ok": False, "error": "runner-unreachable"}
        store.TasksStore.finish(task_id, ST.TASK_CANCELLED,
                                "用户在执行详情窗中停止。")
        return {"ok": True, "action": action}
    if job_id:
        from . import proxy as _px
        from . import process_stream as _ps
        if action == "pause":
            r = eb._runner(f"/api/implement/{job_id}/abort", {}, 12.0)
            ok_ = bool(r and r.get("ok"))
            if ok_:
                _px._set_job_card_state(conv_id, "idle")
            return {"ok": ok_, "action": action}
        if action in ("resume", "input"):
            if not text.strip():
                return {"ok": False, "error": "text-empty"}
            r = eb._runner(f"/api/implement/{job_id}/input",
                           {"text": text.strip(), "steer": True}, 12.0)
            ok_ = bool(r and r.get("ok") is not False)
            if ok_:
                _px._set_job_card_state(conv_id, "running")
            return {"ok": ok_, "action": "input"}
        # stop: 结束直通会话(下条消息开启新会话; sessionRef 保留可复活)
        r = eb._runner(f"/api/implement/{job_id}/finish",
                       {"keepWorktree": True}, 12.0)
        if r is None:
            return {"ok": False, "error": "runner-unreachable"}
        _px._PROXY_JOBS.pop(conv_id, None)
        _ps.proxy_finish(conv_id)
        _px._set_job_card_state(conv_id, "ended")
        return {"ok": True, "action": action}
    return {"ok": False, "error": "no-target"}
