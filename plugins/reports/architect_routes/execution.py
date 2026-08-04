"""Execution / plan / task routes."""
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err

router = APIRouter()

TASKS = []
PLANS = []
BASELINE_COMMIT = "1a2b3c4d5e6f"


@router.get("/plans")
async def list_plans():
    return ok(PLANS)


@router.post("/plans")
async def create_plan(request: Request):
    body = await request.json()
    plan = {
        "id": _id("plan"), "reqIds": body.get("reqIds", []),
        "title": body.get("title", ""), "approach": body.get("approach", ""),
        "changes": body.get("changes", []),
        "impact": body.get("impact", {"affected": [], "grade": "low", "basis": "", "risks": []}),
        "status": "draft", "taskPlanId": None, "baseCommit": BASELINE_COMMIT,
        "updatedAt": _ts(),
    }
    PLANS.append(plan)
    return ok(plan)


@router.patch("/plans/{plan_id}")
async def patch_plan(plan_id: str, request: Request):
    body = await request.json()
    for p in PLANS:
        if p["id"] == plan_id:
            p.update(body)
            p["updatedAt"] = _ts()
            return ok(p)
    return err(404, "Plan not found")


@router.get("/plans/{plan_id}/task-tree")
async def get_task_tree(plan_id: str):
    return ok({
        "id": _id("tp"), "title": "任务方案", "kind": "epic",
        "status": "pending", "estMin": 300, "context": [], "files": [],
        "children": [
            {"id": _id("task"), "title": "梳理现状与边界", "kind": "task", "status": "pending", "estMin": 30, "context": [], "files": ["app/order.go"]},
            {"id": _id("task"), "title": "实现核心逻辑", "kind": "task", "status": "pending", "estMin": 120, "context": [], "files": ["app/order.go"]},
            {"id": _id("task"), "title": "单元测试", "kind": "task", "status": "pending", "estMin": 60, "context": [], "files": []},
        ],
    })


@router.get("/exec")
async def list_execution_tasks():
    return ok(TASKS)


@router.post("/exec")
async def create_execution_task(request: Request):
    body = await request.json()
    task = {
        "id": _id("ex"), "planId": body.get("planId", ""),
        "adapter": body.get("adapter", "opencode"), "model": body.get("model"),
        "reqIds": body.get("reqIds", []), "connectivity": "ok",
        "status": "running", "sessionIds": [], "baseCommit": BASELINE_COMMIT,
        "runCount": 1, "createdAt": _ts(), "updatedAt": _ts(),
        "endedAt": None, "error": None, "treeRevision": 0,
        "stats": {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0},
        "amendments": [],
    }
    TASKS.append(task)
    return ok(task)


@router.patch("/exec/{task_id}")
async def patch_execution_task(task_id: str, request: Request):
    body = await request.json()
    for t in TASKS:
        if t["id"] == task_id:
            t.update(body)
            t["updatedAt"] = _ts()
            return ok(t)
    return err(404, "Task not found")


@router.post("/exec/{task_id}/stop")
async def stop_execution_task(task_id: str):
    for t in TASKS:
        if t["id"] == task_id:
            t["status"] = "stopped"
            t["endedAt"] = _ts()
            t["updatedAt"] = _ts()
            return ok(t)
    return err(404, "Task not found")
