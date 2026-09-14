"""Cline v2 执行器内省路由 — 会话转写/用量/检查点/换模/审批（透传 runner）。

架构会话 ↔ runner 实施作业的 cline 专有内省面。全部经 RunnerClient 透传到
runner /api/implement/{jobId}/*；非 cline 执行器由 runner 端明确报"不支持"。
UI 消费面：SessionsPage 转写/检查点回滚/用量 chip/会话内换模/越界审批对话框。
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from ..agent.execution.runner_client import RunnerClient
from .exec_bridge import _runner
from .common import err, ok

logger = logging.getLogger(__name__)
router = APIRouter()

_client = RunnerClient(_runner)


@router.get("/exec/{job_id}/messages")
async def exec_messages(job_id: str, display: bool = True):
    res = _client.messages(job_id, display=display)
    return ok(res) if res.get("ok") else err(400, res.get("error") or "runner 不可达")


@router.get("/exec/{job_id}/usage")
async def exec_usage(job_id: str):
    res = _client.usage(job_id)
    return ok(res) if res.get("ok") else err(400, res.get("error") or "runner 不可达")


@router.get("/exec/{job_id}/checkpoints")
async def exec_checkpoints(job_id: str, runCount: int = 1):
    res = _client.checkpoints(job_id, run_count=runCount)
    return ok(res) if res.get("ok") else err(400, res.get("error") or "runner 不可达")


@router.post("/exec/{job_id}/restore")
async def exec_restore(job_id: str, request: Request):
    body = await request.json()
    run_count = int(body.get("runCount") or 0)
    if run_count <= 0:
        return err(400, "runCount 非法")
    res = _client.restore(job_id, run_count, body.get("options") or None)
    return ok(res) if res.get("ok") else err(400, res.get("error") or "runner 不可达")


@router.post("/exec/{job_id}/model")
async def exec_model(job_id: str, request: Request):
    body = await request.json()
    model_id = str(body.get("modelId") or "").strip()
    if not model_id:
        return err(400, "modelId 为空")
    res = _client.update_model(job_id, model_id)
    return ok(res) if res.get("ok") else err(400, res.get("error") or "换模失败")


@router.post("/exec/{job_id}/approval")
async def exec_approval(job_id: str, request: Request):
    body = await request.json()
    request_id = str(body.get("requestId") or "").strip()
    if not request_id:
        return err(400, "requestId 为空")
    res = _client.approval(job_id, request_id,
                           body.get("approved") is True,
                           str(body.get("reason") or ""))
    return ok(res) if res.get("ok") else err(400, res.get("error") or "审批转发失败")


@router.get("/exec/{job_id}/pending")
async def exec_pending(job_id: str):
    """挂起提示清单（steer/queue 排队面）。"""
    res = _client.pending(job_id)
    return ok(res) if res.get("ok") else err(400, res.get("error") or "runner 不可达")


@router.post("/exec/{job_id}/proceed")
async def exec_proceed(job_id: str, request: Request):
    """长命令放行（dev server/watch 阻塞时后台继续）。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        body = {}
    res = _client.proceed(job_id, str(body.get("toolCallId") or ""))
    return ok(res) if res.get("ok") else err(400, res.get("error") or "runner 不可达")
