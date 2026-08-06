"""Architecture change / staging / compliance / spec routes (sqlite-backed).

阶段 3/4 收尾: spec 落 `arch_specs`, staging scan 落 `arch_staging_scans`,
baseline handshake 落 `arch_projects` 或内存态(阶段保持)。
"""
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err
from . import store

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
    now = _ts()
    entry = {
        "id": store.next_id("inc"),
        "scope": "递归执行 batch (增量扫描)",
        "grade": "M",
        "files": ["app/domain.go"],
        "edgesChanged": 2,
        "reExplained": ["comm-order"],
        "boundaryChanged": [],
        "createdAt": now,
    }
    store.StagingScansStore.create(entry)
    return ok({
        "scope": {"filesChanged": ["app/domain.go"], "added": 1, "modified": 2, "deleted": 0, "deletedHighRisk": False},
        "grade": "M", "gradeBasis": "增量扫描完成", "gradeAction": "无",
        "affectedComponents": ["order-service"],
        "layers": {
            "file": {"reParsed": 1, "reusedByHash": 0, "edgesChanged": 2},
            "community": {"refined": 1, "dirty": 0, "action": "无变化"},
            "semantic": {"reExplained": 1, "dirty": 0, "inherited": 0},
        },
        "log": entry,
    })


@router.get("/arch/staging/log")
async def get_staging_log():
    return ok(store.StagingScansStore.all())


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


def _load_spec():
    db = store._db()
    row = db.fetchone("SELECT * FROM arch_specs WHERE version = 'v1.0'")
    if not row:
        return None
    return {
        "version": row["version"],
        "overrides": store._loads(row["overrides"], []),
        "explicitRules": store._loads(row["explicit_rules"], []),
        "derivedRules": store._loads(row["derived_rules"], []),
        "changelog": store._loads(row["changelog"], []),
        "updatedAt": row["updated_at"],
    }


def _default_spec():
    return {
        "version": "v1.0", "overrides": [],
        "explicitRules": [
            {"id": "rule-1", "text": "所有服务间调用必须通过接口层", "level": "blocker", "source": "explicit"},
            {"id": "rule-2", "text": "领域事件使用 Outbox 模式", "level": "major", "source": "explicit"},
        ],
        "derivedRules": [],
        "changelog": [{"version": "v1.0", "date": _ts(), "note": "初始规约", "confirmedBy": "admin"}],
    }


@router.get("/spec")
async def get_spec():
    row = _load_spec()
    return ok(row or _default_spec())


@router.post("/spec/confirm")
async def confirm_spec():
    spec = _load_spec() or _default_spec()
    db = store._db()
    db.execute(
        "INSERT INTO arch_specs (version, overrides, explicit_rules, derived_rules, changelog, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(version) DO UPDATE SET overrides = excluded.overrides, "
        "explicit_rules = excluded.explicit_rules, derived_rules = excluded.derived_rules, "
        "changelog = excluded.changelog, updated_at = excluded.updated_at",
        (
            spec["version"],
            store._dumps(spec["overrides"]),
            store._dumps(spec["explicitRules"]),
            store._dumps(spec["derivedRules"]),
            store._dumps(spec["changelog"]),
            _ts(),
        ),
    )
    db.commit()
    return ok({"confirmed": True, "version": "v1.0"})