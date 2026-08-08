"""Execution / plan / task routes (sqlite-backed) — 阶段 4: 原子 commitBatch。

契约见 docs/architect/api-execution.md。
POST /exec 为原子 commitBatch(经 store.run_atomic, WriteQueue 单事务)：
合成/接收方案 → 生成任务树 → 建确认方案 → 创建执行任务 → 绑定需求 execId。
"""
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store

router = APIRouter()

BASELINE_COMMIT = "1a2b3c4d5e6f"


# ── 纯函数: 合成方案 / 生成任务树 ──────────────────────────────

def _assemble_change_items(reqs):
    changes = []
    seen = set()
    for r in reqs:
        for c in (r.get("analysis") or {}).get("changes") or []:
            key = c.get("resource")
            if key and key not in seen:
                seen.add(key)
                changes.append(c)
    return changes


def _build_plan(reqs, req_ids, provided=None):
    now = _ts()
    if provided and provided.get("id"):
        base = dict(provided)
        base["id"] = provided["id"]
        base["reqIds"] = req_ids
        base["baseCommit"] = base.get("baseCommit") or BASELINE_COMMIT
        base.setdefault("status", "draft")
        base.setdefault("updatedAt", now)
        return base
    title = reqs[0]["title"] if reqs else "批次执行方案"
    base_commit = reqs[0].get("analysis", {}).get("implementationPath") and BASELINE_COMMIT or BASELINE_COMMIT
    affected = []
    for r in reqs:
        for a in (r.get("analysis") or {}).get("assetScope") or []:
            if a.get("assetId") not in affected:
                affected.append(a["assetId"])
    grade = "S" if len(affected) <= 1 else ("M" if len(affected) <= 3 else "L")
    return {
        "id": store.next_id("plan"), "reqIds": req_ids, "title": f"需求批次: {title}",
        "approach": "基于需求概要设计的执行步骤拆分, 按任务树分步实现并验收。",
        "changes": _assemble_change_items(reqs),
        "impact": {
            "affected": affected, "grade": grade,
            "basis": "由各需求的资产范围聚合", "risks": ["涉及跨模块改动, 需关注回归"],
        },
        "status": "draft", "taskPlanId": None, "baseCommit": base_commit,
        "updatedAt": now,
    }


def _build_task_tree(plan, reqs):
    """需求 analysis.steps[] → TaskNode 树(对齐前端 execution-batch.buildTaskTree)。"""
    plan_id = plan.get("taskPlanId") or store.next_id("tp")
    plan["taskPlanId"] = plan_id
    children = []
    total = 0
    for r in reqs:
        steps = (r.get("analysis") or {}).get("steps") or []
        for s in steps:
            est = s.get("estMin", 30)
            total += est
            children.append({
                "id": store.next_id("task"), "title": s.get("title", "实现任务"),
                "kind": "task", "status": "pending", "estMin": est,
                "context": s.get("context") or [f"需求: {r['id']}"],
                "files": s.get("files") or [],
            })
    if not children:
        total = 90
        children.append({"id": store.next_id("task"), "title": "梳理现状与边界", "kind": "task",
                         "status": "pending", "estMin": 30, "context": [], "files": []})
        children.append({"id": store.next_id("task"), "title": "实现核心逻辑", "kind": "task",
                         "status": "pending", "estMin": 60, "context": [], "files": []})
    return {
        "id": plan_id, "title": plan.get("title", "任务方案"), "kind": "epic",
        "status": "pending", "estMin": total,
        "context": ["需求: " + "/".join(reqs[0]["id"] if reqs else "")],
        "files": [], "children": children,
    }


# ── Plans ─────────────────────────────────────────────────────

@router.get("/plans")
async def list_plans():
    return ok(store.PlansStore.all())


@router.post("/plans")
async def create_plan(request: Request):
    body = await request.json()
    reqs = [store.RequirementsStore.get(i) for i in body.get("reqIds", [])]
    reqs = [r for r in reqs if r]
    plan = _build_plan(reqs, body.get("reqIds", []), provided=body.get("plan"))
    store.PlansStore.create(plan)
    return ok(store.PlansStore.get(plan["id"]))


@router.patch("/plans/{plan_id}")
async def patch_plan(plan_id: str, request: Request):
    body = await request.json()
    row = store.PlansStore.update(plan_id, {**body, "updatedAt": _ts()})
    if not row:
        return err(404, "Plan not found")
    return ok(row)


@router.post("/plans/{plan_id}/confirm")
async def confirm_plan(plan_id: str):
    plan = store.PlansStore.get(plan_id)
    if not plan:
        return err(404, "Plan not found")
    plan["taskPlanId"] = plan.get("taskPlanId") or store.next_id("tp")
    plan["status"] = "confirmed"
    plan["updatedAt"] = _ts()
    store.PlansStore.update(plan_id, plan)
    # 需求 → planned
    for rid in plan.get("reqIds") or []:
        store.RequirementsStore.update(rid, {"status": "planned", "planId": plan_id, "updatedAt": _ts()})
    return ok(store.PlansStore.get(plan_id))


@router.post("/plans/{plan_id}/release")
async def release_plan(plan_id: str):
    plan = store.PlansStore.get(plan_id)
    if not plan:
        return err(404, "Plan not found")
    plan["status"] = "draft"
    plan["updatedAt"] = _ts()
    store.PlansStore.update(plan_id, plan)
    for rid in plan.get("reqIds") or []:
        store.RequirementsStore.update(rid, {"status": "analyzed", "planId": None, "updatedAt": _ts()})
    return ok(store.PlansStore.get(plan_id))


# ── Task tree ─────────────────────────────────────────────────

@router.get("/plans/{plan_id}/task-tree")
async def get_task_tree(plan_id: str):
    tree = store.TaskTreesStore.get_by_plan(plan_id)
    if tree:
        return ok(tree["root"])
    return ok(store._loads("[]") and {
        "id": store.next_id("tp"), "title": "任务方案", "kind": "epic",
        "status": "pending", "estMin": 300, "context": [], "files": [],
        "children": [
            {"id": store.next_id("task"), "title": "梳理现状与边界", "kind": "task", "status": "pending", "estMin": 30, "context": [], "files": ["app/order.go"]},
            {"id": store.next_id("task"), "title": "实现核心逻辑", "kind": "task", "status": "pending", "estMin": 120, "context": [], "files": ["app/order.go"]},
            {"id": store.next_id("task"), "title": "单元测试", "kind": "task", "status": "pending", "estMin": 60, "context": [], "files": []},
        ],
    })


# ── Execution tasks ───────────────────────────────────────────

@router.get("/exec")
async def list_execution_tasks():
    return ok(store.ExecutionTasksStore.all())


@router.get("/exec/{task_id}")
async def get_execution_task(task_id: str):
    row = store.ExecutionTasksStore.get(task_id)
    if not row:
        return err(404, "Task not found")
    return ok(row)


@router.post("/exec")
async def create_execution_task(request: Request):
    """原子 commitBatch: 方案+任务树+执行任务+需求绑定 同事务。
    每步失败整体回滚。返回 { plan, exec }。"""
    body = await request.json()
    req_ids = list(dict.fromkeys(body.get("reqIds", [])))
    reqs = [store.RequirementsStore.get(i) for i in req_ids]
    reqs = [r for r in reqs if r]

    plan = _build_plan(reqs, req_ids, provided=body.get("plan"))
    plan["status"] = "confirmed"
    root = _build_task_tree(plan, reqs)
    plan["taskPlanId"] = root["id"]

    now = _ts()
    exec_id = store.next_id("ex")
    plan_id = plan["id"]
    tree_id = store.next_id("tree")
    branch_mode = (body.get("branchMode") or "auto").strip().lower()
    if branch_mode not in ("auto", "manual"):
        branch_mode = "auto"
    task_branch = (body.get("taskBranch") or "").strip()
    if branch_mode == "auto" or not task_branch:
        task_branch = f"arch/{exec_id}"
        branch_mode = "auto"
    instance_id = (body.get("instanceId") or "").strip()

    # 收集需求字段更新(exec_id/plan_id/status→planned)
    statements = [
        ("INSERT INTO arch_plans (id, req_ids, title, approach, changes, impact, status, task_plan_id, base_commit, updated_at)"
         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
         (plan_id, store._dumps(req_ids), plan["title"], plan["approach"],
          store._dumps(plan["changes"]), store._dumps(plan["impact"]),
          "confirmed", plan["taskPlanId"], plan["baseCommit"], now)),
        ("INSERT INTO arch_task_trees (id, plan_id, root, revision, history, updated_at)"
         " VALUES (?, ?, ?, 1, ?, ?)",
         (tree_id, plan_id, store._dumps(root), store._dumps([]), now)),
        ("INSERT INTO arch_execution_tasks (id, plan_id, adapter, model, req_ids, connectivity, status, session_ids, base_commit, run_count, tree_revision, test_ids, amendments, stats, instance_id, task_branch, branch_mode, created_at, updated_at)"
         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
         (exec_id, plan_id, body.get("adapter", "opencode"), body.get("model"),
          store._dumps(req_ids), "ok", "created", store._dumps([]), plan["baseCommit"],
          1, 0, store._dumps(body.get("testIds", [])), store._dumps([]),
          store._dumps({"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0}),
          instance_id, task_branch, branch_mode, now, now)),
    ]
    for r in reqs:
        statements.append(
            ("UPDATE arch_requirements SET plan_id = ?, exec_id = ?, status = 'planned', updated_at = ? WHERE id = ?",
             (plan_id, exec_id, now, r["id"]))
        )

    store.run_atomic(statements)

    plan_out = store.PlansStore.get(plan_id)
    exec_out = store.ExecutionTasksStore.get(exec_id)
    return ok({"plan": plan_out, "exec": exec_out})


@router.patch("/exec/{task_id}")
async def patch_execution_task(task_id: str, request: Request):
    body = await request.json()
    row = store.ExecutionTasksStore.update(task_id, {**body, "updatedAt": _ts()})
    if not row:
        return err(404, "Task not found")
    return ok(row)


@router.post("/exec/{task_id}/stop")
async def stop_execution_task(task_id: str):
    row = store.ExecutionTasksStore.update(task_id, {
        "status": "stopped", "endedAt": _ts(), "updatedAt": _ts(),
    })
    if not row:
        return err(404, "Task not found")
    return ok(row)


@router.post("/exec/{task_id}/accept")
async def accept_execution_task(task_id: str):
    """验收通过(事务): 任务 done + 需求 done。"""
    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    now = _ts()
    statements = [
        ("UPDATE arch_execution_tasks SET status = 'done', ended_at = ?, updated_at = ? WHERE id = ?",
         (now, now, task_id)),
    ]
    for rid in task.get("reqIds") or []:
        statements.append(
            ("UPDATE arch_requirements SET status = 'done', updated_at = ? WHERE id = ?",
             (now, rid))
        )
    store.run_atomic(statements)
    return ok(store.ExecutionTasksStore.get(task_id))


@router.post("/exec/{task_id}/amendments")
async def add_amendment(task_id: str, request: Request):
    """追加需求: 挂到任务树末尾 + 累计 estMin + 需求 executing + 任务 running。"""
    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    body = await request.json()
    now = _ts()
    analysis = body.get("analysis") or {}
    amendments = list(task.get("amendments") or [])
    amended = {
        "id": store.next_id("am"),
        "title": body.get("title", "追加需求"),
        "desc": body.get("desc", ""),
        "scope": body.get("scope", []),
        "analysis": analysis,
        "design": body.get("design"),
        "status": "executing",
        "updatedAt": now,
    }
    amendments.append(amended)

    plan = store.PlansStore.get(task["planId"])
    tree = store.TaskTreesStore.get_by_plan(task["planId"]) if plan else None
    est = (analysis.get("feasibility") or {}).get("estMin", 30)

    statements = [
        ("UPDATE arch_execution_tasks SET amendments = ?, status = 'running', updated_at = ? WHERE id = ?",
         (store._dumps(amendments), now, task_id)),
    ]
    if tree:
        root = tree["root"]
        root.setdefault("estMin", 0)
        root["estMin"] += est
        root.setdefault("children", []).append({
            "id": store.next_id("task"), "title": amended["title"], "kind": "task",
            "status": "pending", "estMin": est,
            "context": [f"追加需求: {amended['title']}"], "files": [],
        })
        statements.append(
            ("UPDATE arch_task_trees SET root = ?, updated_at = ? WHERE id = ?",
             (store._dumps(root), now, tree["id"]))
        )

    # 追加需求落库为新需求(可独立追踪)
    statements.append(
        ("INSERT INTO arch_requirements (id, kind, tier, location, status, title, priority, desc, acceptance, analysis, plan_id, exec_id, updated_at)"
         " VALUES (?, 'user-story', 'analyzed', 'pool', 'executing', ?, 'P2', ?, ?, ?, ?, ?, ?)",
         (amended["id"], amended["title"], amended["desc"], store._dumps([]),
          store._dumps(analysis), task["planId"], task_id, now))
    )

    store.run_atomic(statements)
    return ok({"amended": amended, "exec": store.ExecutionTasksStore.get(task_id)})