"""Execution / plan / task routes (sqlite-backed) — 阶段 4: 原子 commitBatch。

契约见 docs/architect/api-execution.md。
POST /exec 为原子 commitBatch(经 store.run_atomic, WriteQueue 单事务)：
合成/接收方案 → 生成任务树 → 建确认方案 → 创建执行任务 → 绑定需求 execId。
"""
import logging
import os
import threading
from typing import Optional
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store
from .agent_roles import role_model_id

router = APIRouter()
logger = logging.getLogger(__name__)


def _auto_acceptance_after_runner_done(task: dict, reqs: list,
                                       root: str, project: str) -> None:
    """M3-6: runner 完成（verify 触发）→ 自动局部验收(trigger=runner_done)。

    后台线程运行(严 profile 提取可含 LLM，耗时)；条目转 verifying，
    通过/打回判定仍唯一归设计者（保真纪律）；异常仅记日志不阻断主流程。
    """
    from . import acceptance as _acc
    from .semantic_assets import project_id_for
    try:
        pid = project_id_for(root, project)
        req_ids = {r.get("id") for r in reqs if r.get("id")}
        pkg_ids = []
        for pkg in store.ContractPackageStore.list(pid):
            if pkg.get("status") not in ("created", "injected"):
                continue
            linked = [iid for iid in (pkg.get("itemIds") or [])
                      if (store.ContractItemStore.get(iid, pid) or {}).get("reqId") in req_ids]
            if linked:
                pkg_ids.append(pkg["id"])
        for pkg_id in pkg_ids:
            try:
                _acc.run_acceptance(pid, root, project or "", pkg_id,
                                    trigger_type="runner_done",
                                    ref=task.get("id") or "",
                                    base_commit=task.get("baseCommit") or "")
                logger.info("[exec] runner_done 自动验收: task=%s pkg=%s",
                            task.get("id"), pkg_id)
            except Exception as e:
                logger.warning("[exec] 自动验收失败 pkg=%s: %s", pkg_id, e)
    except Exception as e:
        logger.warning("[exec] 自动验收触发异常: %s", e)


def _real_base_commit(root: Optional[str] = None) -> str:
    """工程目录真实 git HEAD(基线提交)；非 git/无 HEAD → 空串(调用方兜底)。"""
    if not root:
        return ""
    try:
        from . import arch_git
        return (arch_git.head_commit(root) or "").strip()
    except Exception:
        return ""


def _resolve_root_project(reqs, body):
    """解析 SE 探查所需的 root(源码根)/project(项目 id)。

    优先 body（前端显式传入）；缺省经请求级项目上下文 + arch_projects 解析。
    """
    root = body.get("root")
    project = body.get("project")
    if not project:
        try:
            from . import ctx
            project = ctx.get_project()
        except Exception:
            project = None
    if not root and project:
        try:
            proj = store.ProjectsStore.get(project) or {}
            root = proj.get("rootPath") or proj.get("kbRoot") or ""
        except Exception:
            root = ""
    return root, project


# ── 纯函数: 合成方案 / 生成任务树 ──────────────────────────────

def _assemble_change_items(reqs):
    changes = []
    seen = set()
    for r in reqs:
        sem_ids = [a.get("assetId") for a in (r.get("analysis") or {}).get("assetScope") or []
                   if str(a.get("assetId") or "").startswith("sa-")]
        for c in (r.get("analysis") or {}).get("changes") or []:
            key = c.get("resource")
            if key and key not in seen:
                seen.add(key)
                if sem_ids:
                    c["semanticAssetIds"] = list(dict.fromkeys((c.get("semanticAssetIds") or []) + sem_ids))
                changes.append(c)
    return changes


def _build_plan(reqs, req_ids, provided=None, base_commit: str = ""):
    now = _ts()
    # 基线提交：真实 git HEAD(由调用方解析)；缺失则空(前端/校验按未定基线处理)。
    bc = (base_commit or "").strip()
    if provided and provided.get("id"):
        base = dict(provided)
        base["id"] = provided["id"]
        base["reqIds"] = req_ids
        base["baseCommit"] = (base.get("baseCommit") or bc or "").strip()
        base.setdefault("status", "draft")
        base.setdefault("updatedAt", now)
        return base
    title = reqs[0]["title"] if reqs else "批次执行方案"
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
        "status": "draft", "taskPlanId": None, "baseCommit": bc,
        "updatedAt": now,
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
    root, _project = _resolve_root_project(reqs, body)
    plan = _build_plan(reqs, body.get("reqIds", []), provided=body.get("plan"),
                       base_commit=_real_base_commit(root))
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
    # 无任务树(SE 树未生成/旧计划)→ 返回空树骨架(不伪造假任务/假文件)。
    return ok({
        "id": store.next_id("tp"), "title": "任务方案", "kind": "epic",
        "status": "pending", "estMin": 0, "context": [], "files": [],
        "dependsOn": [], "children": [],
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

    from . import tagent_se
    se_root, se_project = _resolve_root_project(reqs, body)
    # 基线提交取工程目录真实 git HEAD(非 git → 空，按未定基线处理，不再用假常量)。
    plan = _build_plan(reqs, req_ids, provided=body.get("plan"),
                       base_commit=_real_base_commit(se_root))
    plan["status"] = "confirmed"

    # SE 大脑生成任务树（显式 depends_on），替换机械 steps→树。
    # 在原子写之前调用（LLM 异步，不可持有 DB 事务）；失败明确报错，不伪造。
    root, problems = await tagent_se.build_task_tree_se(
        reqs, root=se_root, project=se_project,
        model_id=(body.get("modelId") or ""))
    if root is None:
        return err(502, "SE 任务树生成失败: " + "; ".join(problems or ["LLM 未产出任务树"]))
    root["id"] = store.next_id("tp")
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
        ("INSERT INTO arch_execution_tasks (id, plan_id, adapter, model, req_ids, connectivity, status, session_ids, base_commit, run_count, tree_revision, test_ids, amendments, stats, instance_id, task_branch, branch_mode, conversation_id, created_at, updated_at)"
         " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
         (exec_id, plan_id, body.get("adapter", "opencode"), body.get("model"),
          store._dumps(req_ids), "ok", "created", store._dumps([]), plan["baseCommit"],
          1, 0, store._dumps(body.get("testIds", [])), store._dumps([]),
          store._dumps({"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0}),
          instance_id, task_branch, branch_mode, (body.get("conversationId") or "").strip(), now, now)),
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


# ── Subagent 指派(P3.2: 经 agent-bus broker 交接) ────────────────────

def assign_requirement(req_id: str, target: str, exec_id: str = "",
                       tool: str = "", params: Optional[dict] = None):
    """把需求指派给 subagent：runner(内部执行任务) / mcp(外部 MCP 工具)。

    成功: 向 broker 发布 execution.handoff → 需求 status→executing + 持久化 assignedTo
    (broker 分发循环按 dst 路由: runner→architect /exec/{id}/run, mcp→MCP 工具调用)。
    返回 (req, None)；失败 (None, (http_code, msg))。
    """
    req = store.RequirementsStore.get(req_id)
    if not req:
        return None, (404, "需求不存在")
    target = (target or "").strip().lower()
    if target not in ("runner", "mcp"):
        return None, (400, "target 必须为 runner 或 mcp")
    exec_id = (exec_id or "").strip()
    tool = (tool or "").strip()
    if target == "runner":
        exec_id = exec_id or (req.get("execId") or "").strip()
        if not exec_id:
            return None, (400, "指派 runner 需要 execId(执行任务)")
        if not store.ExecutionTasksStore.get(exec_id):
            return None, (400, f"执行任务 {exec_id} 不存在")
        assigned = "runner"
    else:
        if not tool:
            return None, (400, "指派 mcp 需要 tool(MCP 工具名)")
        assigned = f"mcp:{tool}"
    from .bus_client import get_bus
    pub = get_bus().publish("architect", target, "execution.handoff", {
        "reqId": req_id, "execId": exec_id, "tool": tool,
        "params": params or {}, "assignedTo": assigned,
    })
    if pub is None:
        return None, (503, "agent-bus broker 不可达，无法发布交接消息")
    store.RequirementsStore.update(req_id, {
        "status": "executing", "assignedTo": assigned,
        "execId": exec_id or req.get("execId"), "updatedAt": _ts(),
    })
    return store.RequirementsStore.get(req_id), None


@router.post("/requirements/{req_id}/assign")
async def assign_requirement_endpoint(req_id: str, request: Request):
    """P3.2: 需求指派 subagent(runner/mcp) → bus handoff → 状态→executing。"""
    body = await request.json()
    row, e = assign_requirement(
        req_id, body.get("target") or "", exec_id=body.get("execId") or "",
        tool=body.get("tool") or "", params=body.get("params") or {})
    if not row:
        code, msg = e
        return err(code, msg)
    return ok(row)


@router.post("/exec/{task_id}/run")
async def run_execution_task(task_id: str):
    """把已确认的任务树提交给 runner 执行(SE.execute → on_submit → runner)。

    从 DB 还原用户确认的树 → CodingTaskTree，构建 SE(on_submit=提交 runner)，
    `se.execute` 取 tree_id 落库(runnerTreeId)，再触发非阻塞 run。
    前端凭返回的 treeId 直连 runner WS `/api/trees/{treeId}/events` 渲染进度。
    """
    import asyncio

    from . import tagent_se
    from .kb_gateway import get_gateway
    from .runner_gateway import get_runner

    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    tree_row = store.TaskTreesStore.get_by_plan(task["planId"])
    if not tree_row or not tree_row.get("root"):
        return err(409, "任务树不存在")

    coding_tree = tagent_se.frontend_tree_to_coding(tree_row["root"])
    problems = coding_tree.validate()
    if problems:
        return err(500, "任务树非法: " + "; ".join(problems))

    # 执行器选择贯通：任务级 adapter 盖到无显式选择的叶节点
    # （节点级 executor_id 优先；adapter 空/未注册 → 用池默认）
    adapter = (task.get("adapter") or "").strip()
    if adapter:
        def _stamp(node) -> None:
            if not node.executor_id and not node.is_container():
                node.executor_id = adapter
            for c in node.children:
                _stamp(c)
        for r in coding_tree.roots:
            _stamp(r)

    reqs = [store.RequirementsStore.get(i) for i in task.get("reqIds") or []]
    reqs = [r for r in reqs if r]
    root, project = _resolve_root_project(reqs, {})
    context = tagent_se.make_se_context(reqs, root, project, task)

    se = tagent_se.build_architect_se(
        get_gateway(), root=root, project=project,
        project_root=root or "",
        on_submit=tagent_se.make_runner_on_submit(),
    )
    runner = get_runner()
    tree_id = await asyncio.to_thread(se.execute, coding_tree, context)
    if not tree_id:
        return err(502, "runner 不可达, 任务树提交失败")

    # ── S2 任务分支协议 ──────────────────────────────────────
    # dispatch 前：工程目录切任务分支（脏区拒绝）；树完成监视（done→commit+push 镜像）。
    # root 不可解析（无绑定项目/降级环境）→ 跳过分支协议，保持旧行为。
    branch_note = ""
    project_row = None
    if root and os.path.isdir(root):
        try:
            from . import project as project_routes
            from . import branch_service
            project_row = project_routes._resolve_project(root, project) or {}
            task_branch = (task.get("taskBranch") or "").strip()
            if (task.get("branchMode") or "auto") == "auto" and task_branch:
                prep = await asyncio.to_thread(
                    branch_service.prepare_task_branch,
                    root, task_branch, task.get("baseCommit") or "")
                if not prep.get("ok"):
                    return err(409, f"任务分支准备失败: {prep.get('reason')}")
                branch_note = task_branch
        except Exception as e:  # noqa: BLE001
            logger.warning("[exec] 任务分支准备异常 exec=%s: %s", task_id, e)

    store.ExecutionTasksStore.update(task_id, {
        "runnerTreeId": tree_id, "status": "running",
        "runCount": (task.get("runCount") or 0) + 1, "updatedAt": _ts(),
    })
    progress = await asyncio.to_thread(runner.run, tree_id)

    if project_row is not None:
        try:
            from . import branch_service
            branch_service.watch_and_land(
                store.ExecutionTasksStore.get(task_id) or task,
                project_row, root or "", tree_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("[exec] 分支落地监视启动失败 exec=%s: %s", task_id, e)

    return ok({"treeId": tree_id, "progress": progress, "taskBranch": branch_note})


@router.post("/exec/{task_id}/rejudge")
async def rejudge_execution_task(task_id: str):
    """stale 重判：SE 基于当前源码重判依赖，返回更新后的树(供用户再确认)。

    runner 检出 blocked_stale → 前端调本端点 → SE 重判 → 落 pending 树(供 confirm)
    + 返回前端树。跨进程：旧树从 runner 拉取并注入 SE。
    """
    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    tree_id = task.get("runnerTreeId")
    if not tree_id:
        return err(409, "无 runner 任务树(未提交执行)")

    from . import tagent_se
    from .kb_gateway import get_gateway
    from .runner_gateway import get_runner

    runner = get_runner()
    got = runner.get_tree(tree_id)
    if not got or "tree" not in got:
        return err(502, "runner 不可达")
    runner_tree = got["tree"]  # {roots: [...]} (snake_case)
    stale_ids = tagent_se.stale_node_ids(runner_tree)
    if not stale_ids:
        return err(409, "无失效(stale)节点")

    reqs = [store.RequirementsStore.get(i) for i in task.get("reqIds") or []]
    reqs = [r for r in reqs if r]
    root, project = _resolve_root_project(reqs, {})
    se = tagent_se.build_architect_se(
        get_gateway(), root=root, project=project, project_root=root or "",
        model_id=role_model_id("verify"))
    tagent_se.seed_runner_tree(se, tree_id, runner_tree)
    result = await se.rejudge(tree_id, stale_ids, tagent_se._req_text(reqs))
    if result.tree is None:
        return err(502, "重判失败: " + "; ".join(result.problems or ["LLM 未产出树"]))

    new_tree_dict = result.tree.to_dict()
    new_tree_fe = tagent_se._tree_to_frontend(result.tree)
    store.ExecutionTasksStore.update(task_id, {
        "pendingRejudge": {"tree": new_tree_dict, "staleIds": stale_ids, "treeId": tree_id},
        "status": "blocked", "updatedAt": _ts(),
    })
    return ok({"treeId": tree_id, "staleIds": stale_ids, "newTree": new_tree_fe})


@router.post("/exec/{task_id}/rejudge/confirm")
async def confirm_rejudge(task_id: str):
    """确认重判：PUT 新树 + rejudge(刷新哈希基线) + run，继续执行。"""
    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    pending = task.get("pendingRejudge")
    if not pending or not pending.get("tree"):
        return err(409, "无待确认的重判")

    from .runner_gateway import get_runner
    runner = get_runner()
    tree_id = pending.get("treeId") or task.get("runnerTreeId")
    stale_ids = pending.get("staleIds") or []
    ok_update = runner.update_tree(tree_id, pending["tree"])
    ok_rejudge = runner.rejudge(tree_id, stale_ids)
    if not (ok_update and ok_rejudge):
        return err(502, "重判确认失败(runner)")

    store.ExecutionTasksStore.update(task_id, {
        "pendingRejudge": None, "status": "running", "updatedAt": _ts(),
    })
    progress = runner.run(tree_id)
    return ok({"treeId": tree_id, "progress": progress})


@router.post("/exec/{task_id}/verify")
async def verify_execution_task(task_id: str):
    """验证：SE 基于已变更文件 agentic 复查(不跑测试)，返回验证报告。

    返回 {passed, issues[], unmetRequirements[], report}；不通过可 retry/skip 后重跑。
    """
    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    tree_id = task.get("runnerTreeId")
    if not tree_id:
        return err(409, "无 runner 任务树(未提交执行)")

    from . import tagent_se
    from .kb_gateway import get_gateway
    from .runner_gateway import get_runner

    runner = get_runner()
    got = runner.get_tree(tree_id)
    if not got or "tree" not in got:
        return err(502, "runner 不可达")

    reqs = [store.RequirementsStore.get(i) for i in task.get("reqIds") or []]
    reqs = [r for r in reqs if r]
    root, project = _resolve_root_project(reqs, {})
    se = tagent_se.build_architect_se(
        get_gateway(), root=root, project=project, project_root=root or "",
        model_id=role_model_id("verify"))
    tagent_se.seed_runner_tree(se, tree_id, got["tree"])
    result = await se.verify(tree_id, tagent_se._req_text(reqs))
    # M3-6: runner 完成信号 → 自动触发局部验收(后台；判定仍归设计者)
    if root:
        threading.Thread(
            target=_auto_acceptance_after_runner_done,
            args=(task, reqs, root, project), daemon=True,
        ).start()
    return ok({
        "treeId": tree_id,
        "passed": result.passed,
        "issues": result.issues,
        "unmetRequirements": result.unmet,
        "report": result.report,
    })


@router.post("/exec/{task_id}/run-tests")
async def run_execution_tests(task_id: str, request: Request):
    """闭环(B3)：真实 subprocess 执行任务关联单测(testIds)，记录结果并汇总。

    root 经 body 传入(前端当前项目)；缺省尝试从需求/项目解析。
    无关联单测 → ran:0(明确，不伪造)。结果回写各单测 lastResult/status。
    """
    import asyncio
    task = store.ExecutionTasksStore.get(task_id)
    if not task:
        return err(404, "Task not found")
    test_ids = task.get("testIds") or []
    try:
        body = await request.json()
    except Exception:
        body = {}
    root = (body.get("root") or "").strip()
    if not root:
        reqs = [store.RequirementsStore.get(i) for i in task.get("reqIds") or []]
        reqs = [r for r in reqs if r]
        root, _project = _resolve_root_project(reqs, {})
        root = root or ""

    if not test_ids:
        return ok({"ran": 0, "passed": 0, "failed": 0, "allPassed": True,
                   "results": [], "note": "任务未关联单测", "at": _ts()})

    from .test_runner import run_test_script
    results = []
    passed = failed = 0
    for tid in test_ids:
        test = store.UnitTestsStore.get(tid)
        if not test:
            results.append({"testId": tid, "status": "error",
                            "lastResult": {"passed": 0, "failed": 1, "error": "test not found", "at": _ts()}})
            failed += 1
            continue
        raw = await asyncio.to_thread(run_test_script, test.get("scriptPath") or "", root)
        last_result = {**raw, "at": _ts()}
        status = "passed" if raw.get("failed", 0) == 0 and raw.get("passed", 0) > 0 else "failed"
        store.UnitTestsStore.update(tid, {"status": status, "lastResult": last_result, "updatedAt": _ts()})
        results.append({"testId": tid, "status": status, "lastResult": last_result})
        if status == "passed":
            passed += 1
        else:
            failed += 1
    return ok({"ran": len(results), "passed": passed, "failed": failed,
               "allPassed": failed == 0, "results": results, "at": _ts()})


@router.patch("/exec/{task_id}")
async def patch_execution_task(task_id: str, request: Request):
    body = await request.json()
    row = store.ExecutionTasksStore.update(task_id, {**body, "updatedAt": _ts()})
    if not row:
        return err(404, "Task not found")
    if str(body.get("status") or "") in ("done", "failed", "stopped"):
        from . import context_registry
        context_registry.write_exec_report(task_id, str(body["status"]))
    return ok(row)


@router.post("/exec/{task_id}/stop")
async def stop_execution_task(task_id: str):
    row = store.ExecutionTasksStore.update(task_id, {
        "status": "stopped", "endedAt": _ts(), "updatedAt": _ts(),
    })
    if not row:
        return err(404, "Task not found")
    from . import context_registry
    context_registry.write_exec_report(task_id, "stopped")
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
    from . import context_registry
    context_registry.write_exec_report(task_id, "done")
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