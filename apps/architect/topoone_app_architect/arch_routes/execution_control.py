"""执行详情窗 REST(cv-285): 双源(taskId|jobId)统一详情 + 单一控制面。

逻辑单源=agent.execution.exec_control(方案甲: 任务行与直通作业同窗体,
控制无并行通道)。"""
import asyncio

from fastapi import APIRouter, Request

from ..common import ok, err

router = APIRouter()


@router.get("/execution/detail")
async def execution_detail(convId: str = "",
                           taskId: str = "",
                           jobId: str = ""):
    """执行详情(统一视图模型): ?taskId= 任务源 / ?jobId= 直通源。"""
    from ..agent.execution import exec_control as _ec
    if not convId or not (taskId or jobId):
        return err(400, "convId 与 taskId|jobId 必填其一")
    res = await asyncio.to_thread(
        _ec.execution_detail, convId, taskId, jobId)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "detail-failed"))
    return ok(res)


@router.post("/execution/control")
async def execution_control(request: Request):
    """作业控制单一控制面: {convId, action: pause|resume|stop|input,
    taskId?|jobId?, text?(input)}——pause=abort 保会话/stop=finish 保留
    worktree/resume·input=转达(任务源走 task_input 单源)。"""
    from ..agent.execution import exec_control as _ec
    body = await request.json()
    conv_id = str((body or {}).get("convId") or "")
    action = str((body or {}).get("action") or "")
    if not conv_id or not action:
        return err(400, "convId 与 action 必填")
    res = await asyncio.to_thread(
        _ec.control_execution, conv_id, action,
        str((body or {}).get("taskId") or ""),
        str((body or {}).get("jobId") or ""),
        str((body or {}).get("text") or ""))
    if not res.get("ok") and res.get("error") in (
            "task-not-found", "no-target", "unknown-action:"
            + action, "text-empty", "task-not-running"):
        return err(400, str(res.get("error")))
    return ok(res)
