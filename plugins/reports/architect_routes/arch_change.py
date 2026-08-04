"""Architecture change / staging / compliance / spec routes."""
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err

router = APIRouter()

BASELINE_COMMIT = "1a2b3c4d5e6f"


@router.post("/arch/change")
async def compute_arch_change(request: Request):
    body = await request.json()
    return ok({
        "baseline": {"version": "v1", "commit": BASELINE_COMMIT, "branch": "main", "analyzedAt": _ts(), "gitDate": _ts()},
        "files": {"added": 2, "modified": 4, "deleted": 0},
        "nodes": [
            {"id": "c-order", "name": "订单服务", "kind": "component", "change": "modified", "file": "app/order.go"},
            {"id": "c-outbox", "name": "Outbox 服务", "kind": "infra", "change": "added", "file": "app/outbox.go"},
        ],
        "relations": [{"id": "c-order~c-outbox", "kind": "depends", "change": "added", "file": "app/order.go"}],
        "leafComponents": body.get("stagingAffected", []),
        "diagrams": {
            "structure": "graph TD; A[订单服务] --> B[库存服务]; A --> C[支付服务];",
            "dependency": "graph LR; A[order] --> B[inventory]; A --> C[payment];",
            "calls": "sequenceDiagram; order->>inventory: 预扣库存;",
        },
        "codeChanges": [
            {"id": "node-c-order", "category": "structure", "file": "app/order.go", "symbol": "Order", "change": "modified", "title": "订单服务重构", "summary": "新增 Outbox 依赖", "before": ["func (o *Order) Create() {", "    // old logic"], "after": ["func (o *Order) Create() {", "    // new logic with outbox"]},
        ],
    })


@router.get("/arch/staging")
async def get_staging():
    return ok({
        "scope": {"filesChanged": ["app/domain.go"], "added": 1, "modified": 2, "deleted": 0, "deletedHighRisk": False},
        "grade": "M", "gradeBasis": "模块边界变更，涉及 2 个组件",
        "gradeAction": "新增 Outbox 服务组件，需规约确认",
        "affectedComponents": ["order-service"],
        "layers": {
            "file": {"reParsed": 1, "reusedByHash": 0, "edgesChanged": 2},
            "community": {"refined": 1, "dirty": 0, "action": "社区结构调整"},
            "semantic": {"reExplained": 1, "dirty": 0, "inherited": 0},
        },
    })


@router.post("/arch/staging/scan")
async def run_staging_scan():
    return ok({
        "scope": {"filesChanged": ["app/domain.go"], "added": 1, "modified": 2, "deleted": 0, "deletedHighRisk": False},
        "grade": "M", "gradeBasis": "增量扫描完成", "gradeAction": "无",
        "affectedComponents": ["order-service"],
        "layers": {
            "file": {"reParsed": 1, "reusedByHash": 0, "edgesChanged": 2},
            "community": {"refined": 1, "dirty": 0, "action": "无变化"},
            "semantic": {"reExplained": 1, "dirty": 0, "inherited": 0},
        },
        "log": {"id": _id("inc"), "time": _ts(), "scope": "递归执行 batch (增量扫描)", "grade": "M", "files": [], "edgesChanged": 2, "reExplained": ["comm-order"], "boundaryChanged": []},
    })


@router.get("/arch/staging/log")
async def get_staging_log():
    return ok([
        {"id": _id("inc"), "time": _ts(), "scope": "增量扫描", "grade": "M", "files": ["app/domain.go"], "edgesChanged": 2, "reExplained": ["comm-order"], "boundaryChanged": []},
    ])


@router.get("/arch/staging/compliance")
async def get_staging_compliance():
    return ok([
        {"id": "ck-1", "name": "组件边界未破坏", "kind": "boundary", "pass": True, "level": "blocker", "detail": "所有组件保持在原有边界内", "scope": "order-service"},
        {"id": "ck-2", "name": "规约一致性检查", "kind": "spec", "pass": True, "level": "major", "detail": "无规约违反", "scope": "all"},
    ])


@router.post("/arch/staging/gates")
async def set_staging_gate(request: Request):
    body = await request.json()
    return ok({"key": body.get("key"), "value": body.get("value"), "ok": True})


@router.post("/arch/baseline/verify")
async def verify_baseline():
    return ok({"verify": "ok - 所有检查通过", "verifyOk": True, "baselineId": "baseline_id = N+1"})


@router.post("/arch/baseline/commit")
async def commit_baseline():
    return ok({"commitResult": "原子写入成功", "committedId": "N+1 (v1.0.0)"})


@router.get("/spec")
async def get_spec():
    return ok({
        "version": "v1.0", "overrides": [],
        "explicitRules": [
            {"id": "rule-1", "text": "所有服务间调用必须通过接口层", "level": "blocker", "source": "explicit"},
            {"id": "rule-2", "text": "领域事件使用 Outbox 模式", "level": "major", "source": "explicit"},
        ],
        "derivedRules": [],
        "changelog": [{"version": "v1.0", "date": _ts(), "note": "初始规约", "confirmedBy": "admin"}],
    })


@router.post("/spec/confirm")
async def confirm_spec():
    return ok({"confirmed": True, "version": "v1.0"})


@router.get("/git/status")
async def git_status():
    return ok({
        "branch": "main", "ahead": 6, "dirty": True,
        "files": ["order-service/order.go", "order-service/service.go"],
    })
