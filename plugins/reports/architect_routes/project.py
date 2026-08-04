"""Project, baseline, snapshot routes."""
from typing import Optional
from fastapi import APIRouter, Request
import common as reports_common
from .common import _ts, _id, ok, err, build_architecture_model

router = APIRouter()

BASELINE_COMMIT = "1a2b3c4d5e6f"

PROJECT_INFO = {
    "id": "proj-order",
    "name": "订单服务系统",
    "desc": "需求驱动 + 架构驱动示例：下单 → 库存预扣 → 支付 → 事件最终一致 → 超时关单",
    "rootPath": "/home/dev/topo-projects/order-service",
    "kbRoot": "/home/dev/topo-storage/worktrees/baseline",
    "branch": "main",
    "baselineId": "baseline_id = N",
    "baselineCommit": BASELINE_COMMIT,
    "createdAt": _ts() - 86400000 * 3,
    "active": True,
    "config": {"estMinMin": 60, "estMinMax": 480, "acceptanceMax": 4, "p0SubsetMax": 5},
    "mode": "existing",
    "productForm": "io",
}


@router.get("/project/bound")
async def get_bound_project(root: Optional[str] = None):
    return ok(PROJECT_INFO)


@router.post("/project/bound")
async def create_greenfield_project(request: Request):
    """Create a greenfield project."""
    body = await request.json()
    now = _ts()
    project = {
        "id": f"proj-{now:x}",
        "name": body.get("name", "新项目"),
        "desc": body.get("desc", ""),
        "rootPath": body.get("execRoot", ""),
        "kbRoot": body.get("kbRoot", ""),
        "branch": "main",
        "baselineId": None,
        "baselineCommit": "",
        "createdAt": now,
        "active": True,
        "config": {"estMinMin": 15, "estMinMax": 240, "acceptanceMax": 6, "p0SubsetMax": 4},
        "mode": "greenfield",
        "scaffold": {
            "language": body.get("language", ""),
            "framework": body.get("framework"),
            "moduleLayout": body.get("moduleLayout", "mono"),
        },
        "productForm": body.get("productForm"),
    }
    return ok(project)


@router.get("/project/status")
async def get_project_status():
    return ok({
        "baseline": {
            "id": "baseline_id = N",
            "version": "v0.0.1",
            "commit": BASELINE_COMMIT,
            "manifestHash": "sha256:9f7...c21",
            "createdAt": _ts() - 86400000 * 3,
        },
        "head": {"commit": "a1b2c3d4e5f6", "branch": "main", "ahead": 6},
        "diff": {
            "filesChanged": 5,
            "added": 2,
            "modified": 3,
            "deleted": 0,
            "deletedHighRisk": False,
            "files": [
                "order-service/order.go", "order-service/service.go",
                "order-service/close.go", "outbox-service/relay.go",
                "tests/integration_test.go",
            ],
        },
        "lastRebaseline": None,
    })


@router.get("/project/snapshots")
async def get_snapshots():
    now = _ts()
    model = build_architecture_model()
    return ok([
        {"id": "snap-v0", "name": "基线快照", "version": "v0",
         "createdAt": now - 86400000 * 3, "model": model},
        {"id": "snap-v1", "name": "当前快照", "version": "v1",
         "createdAt": now, "model": model},
    ])


@router.get("/project/baseline/meta")
async def get_baseline_meta():
    return ok({
        "gitTag": "v1.0.0-order-service", "branch": "main",
        "gitDate": _ts() - 86400000 * 3, "analyzedAt": _ts() - 86400000 * 3,
        "archVersion": "v1", "commit": BASELINE_COMMIT,
        "desc": "订单领域服务（示例）",
    })


@router.get("/project/baseline/dirty")
async def get_baseline_dirty():
    return ok({"dirty": True})


@router.post("/project/baseline/sync")
async def sync_baseline(request: Request):
    body = await request.json()
    return ok({
        "success": True, "commit": body.get("commit", BASELINE_COMMIT),
        "baselineId": "baseline_id = N+1",
    })


@router.patch("/project/config")
async def update_project_config(request: Request):
    patch = await request.json()
    PROJECT_INFO["config"].update(patch)
    return ok(PROJECT_INFO)
