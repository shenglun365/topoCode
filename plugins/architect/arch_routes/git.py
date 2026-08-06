"""Git domain routes — 服务端模拟仓库操作(全量)。

契约见 docs/architect/api-execution.md。真实 git 操作在独立进程;
此处返回确定性的模拟结果, 便于前端全链路联调。
"""
import re
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store

router = APIRouter()

BASELINE_COMMIT = "1a2b3c4d5e6f"
BRANCH = "main"
LOG_ENTRIES = [
    {"oid": "8f4a2e1c", "subject": "feat: 订单结算接入库存预占", "author": "dev", "date": "2026-07-28 14:02"},
    {"oid": "3c1b90a7", "subject": "fix: 支付回调幂等修正", "author": "dev", "date": "2026-07-26 09:41"},
    {"oid": BASELINE_COMMIT, "subject": "feat: 引入订单服务骨架", "author": "dev", "date": "2026-07-20 11:12"},
]

_WORKING_TREE = {
    "app/order.go": "package order\n// 订单核心逻辑(工作区未提交修改)\n",
    "app/payment.go": "package payment\n// 支付回调幂等处理\n",
    "app/inventory.go": "package inventory\n// 库存预占/扣减\n",
}


def _status():
    return {
        "branch": BRANCH, "ahead": 0, "behind": 0, "dirty": True,
        "uncommitted": ["app/order.go"], "staged": [], "baseline": BASELINE_COMMIT,
    }


@router.get("/git/status")
async def git_status():
    return ok(_status())


@router.get("/git/log")
async def git_log(limit: int = 10):
    return ok({"branch": BRANCH, "entries": LOG_ENTRIES[:limit], "baseline": BASELINE_COMMIT})


@router.get("/git/head")
async def git_head():
    return ok({"oid": "8f4a2e1c", "subject": "feat: 订单结算接入库存预占", "branch": BRANCH})


@router.get("/git/working-tree")
async def git_working_tree():
    return ok({"files": [{"path": k, "staged": k in ("app/order.go",), "content": v} for k, v in _WORKING_TREE.items()]})


@router.post("/git/checkout")
async def git_checkout(request: Request):
    body = await request.json()
    ref = body.get("ref") or "main"
    return ok({"branch": ref, "oid": "8f4a2e1c", "clean": True})


@router.post("/git/reset")
async def git_reset(request: Request):
    body = await request.json()
    mode = body.get("mode") or "hard"
    target = body.get("target") or BASELINE_COMMIT
    return ok({"mode": mode, "target": target, "status": _status(), "reset": True})


@router.post("/git/commit")
async def git_commit(request: Request):
    body = await request.json()
    msg = body.get("message") or "chore: 更新"
    return ok({"oid": "a7c9e2f1", "subject": msg, "branch": BRANCH, "status": _status()})


@router.post("/git/push")
async def git_push(request: Request):
    return ok({"branch": BRANCH, "pushed": True, "remote": "origin"})


@router.get("/git/diff")
async def git_diff(request: Request):
    body = {}
    return ok({"files": [
        {"path": "app/order.go", "additions": 12, "deletions": 2,
         "diff": "--- a/app/order.go\n+++ b/app/order.go\n@@ -1,3 +1,13 @@\n package order\n+// 工作区未提交修改\n"},
    ]})