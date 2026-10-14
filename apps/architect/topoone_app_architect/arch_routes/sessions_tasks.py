"""v2 会话任务 REST 簇(MS4-W4 自 sessions.py 尾段切出; 路径前缀不变 /api/architect)。

12 条 /tasks/* 路由 + /units 读侧——纯 dispatch/exec_bridge 转发, 与会话中心解耦。
"""
import asyncio

import fastapi
from fastapi import APIRouter, Request

from ..common import ok, err
from .. import store
from .sessions import _tasks_of_conv  # noqa: F401,E402 — 会话中心内部 helper(读侧共享)

router = APIRouter()

# ── v2 统一会话: coding subagent 任务 REST(轻门禁/投递/停止) ──

@router.post("/requirements/{req_id}/execute-now")
async def requirement_execute_now(req_id: str, request: Request):
    """立即执行(cv-281): 需求最新版→单任务直发(免 GU 计划/确认门)。

    body: {convId, executorType?}; 逻辑单源=dispatch.execute_requirement_now
    (propose_task→confirm_task 复用, 规约全文 confirm 时自动随注入)。"""
    from ..agent.execution import dispatch as _dispatch
    body = await request.json()
    conv_id = str((body or {}).get("convId") or "")
    if not conv_id:
        return err(400, "convId 必填")
    res = await asyncio.to_thread(
        _dispatch.execute_requirement_now, conv_id, req_id,
        str((body or {}).get("executorType") or ""))
    if not res.get("ok"):
        return err(400, str(res.get("error") or "execute-failed"))
    return ok(res)


@router.post("/tasks/{task_id}/gate-answer")
async def task_gate_answer(task_id: str, request: Request):
    """脏区问询确定性消费(cv-282): 单源=gate_ask.resolve_dirty_gate。"""
    from ..agent.execution import gate_ask as _gate
    body = await request.json()
    res = await asyncio.to_thread(
        _gate.resolve_dirty_gate, task_id,
        str((body or {}).get("choiceText") or ""))
    if not res.get("ok") and res.get("error") in ("task-not-waiting",
                                                  "unknown-choice"):
        return err(400, str(res.get("error")))
    return ok(res)

@router.post("/tasks/{task_id}/merge")
async def task_merge(task_id: str, request: Request):
    """确认合并(本地 PR 语义, 环节十五): 门禁通过后执行合并, 任务记 merged 终态。

    body: {mode?: "ff"(默认, 仅快进) | "no-ff"(强制合并提交, 冲突中止回显)}。"""
    from ..agent.execution import exec_bridge
    try:
        body = await request.json()
    except Exception:
        body = {}
    mode = "no-ff" if str((body or {}).get("mode") or "") == "no-ff" else "ff"
    res = await asyncio.to_thread(exec_bridge.merge_branch, task_id, mode)
    if not res.get("ok"):
        return err(int(res.get("code") or 400), res.get("error") or "merge-failed")
    # 流程相位重算: merged = 回执已消化(reviewing 出口; force 解除粘滞)
    try:
        _t = res.get("task") or {}
        _cid = _t.get("conversationId") or ""
        if _cid:
            from ..agent.governance import flow as _flow
            await asyncio.to_thread(lambda: _flow.recompute(_cid, trigger="task-merge", force=True))
    except Exception:  # noqa: BLE001
        pass
    return ok(res)


@router.get("/tasks/{task_id}/merge-precheck")
async def task_merge_precheck(task_id: str):
    """合并入口检查(环节十五): 主目录推进/任务分支内容/是否可直并。"""
    from ..agent.execution import exec_bridge
    res = await asyncio.to_thread(exec_bridge.merge_precheck, task_id)
    if not res.get("ok"):
        return err(int(res.get("code") or 400), res.get("error") or "precheck-failed")
    return ok(res)


@router.post("/tasks/{task_id}/cleanup")
async def task_cleanup(task_id: str, request: Request):
    """T5 终态任务对账清理: runner finish(释放执行器资源/可选删 worktree)。

    body: {keepWorktree?: bool=true}; 幂等——runner 作业不存在也视为清毕。"""
    from ..agent.execution import exec_bridge
    keep = True
    try:
        body = await request.json()
        keep = bool((body or {}).get("keepWorktree", True))
    except Exception:  # noqa: BLE001
        pass
    task = await asyncio.to_thread(store.TasksStore.get, task_id)
    if not task:
        return err(404, "task-not-found")
    if (task.get("status") or "") not in ("done", "failed", "cancelled"):
        return err(400, "仅终态任务可清理(先停止)")
    job_id = task.get("runnerJobId") or ""
    if job_id:
        await asyncio.to_thread(
            exec_bridge._runner, f"/api/implement/{job_id}/finish",
            {"keepWorktree": keep}, timeout=30.0)
    return ok({"taskId": task_id, "cleaned": True, "keptWorktree": keep})


@router.post("/tasks/{task_id}/ignore")
async def task_ignore(task_id: str):
    """主动忽略(2026-09-20 裁决: 默认保存/对话更新/主动忽略): 仅 saved 态。"""
    res = await asyncio.to_thread(exec_bridge.ignore_task, task_id)
    if not res.get("ok"):
        return err(res.get("code") or 400, str(res.get("error") or "忽略失败"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/confirm")
async def task_confirm(task_id: str, request: Request):
    """确认任务卡 → 拉起 runner(轻门禁唯一入口)。

    body 可选 executorType: 覆盖任务执行器(确认时换引擎, 优先级低于专用端点)。"""
    from ..agent.execution import exec_bridge
    etype = ""
    try:
        body = await request.json()
        etype = str((body or {}).get("executorType") or "")
    except Exception:  # noqa: BLE001
        pass
    if etype:
        await asyncio.to_thread(exec_bridge.task_set_executor, task_id, etype)
    res = await asyncio.to_thread(exec_bridge.confirm_task, task_id)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "confirm-failed"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/dismiss")
async def task_dismiss(task_id: str):
    """回执已阅(dismiss, reviewing 消化出口): 仅 done 态; 不改终态, 留痕。

    与 ignore 语义区分: ignore=saved 卡不执行; dismiss=done 回执已阅
    (不合并/不建下张卡的用户显式消化)。"""
    from ..agent.execution.dispatch import dismiss_task
    res = await asyncio.to_thread(dismiss_task, task_id)
    if not res.get("ok"):
        return err(int(res.get("code") or 400), str(res.get("error") or "dismiss-failed"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/milestones")
async def task_set_milestones(task_id: str, request: Request):
    """设定关键节点(遗留#2): body {milestones: [{id,title,doneWhen?}]};
    仅未开始任务可改(运行中指令已固化)。任务行优先于规约快照同名声明。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    from ..agent.execution.dispatch import task_set_milestones as _set
    task = await asyncio.to_thread(_set, task_id,
                                   (body or {}).get("milestones"))
    if not task:
        return err(404, "任务不存在或已开始(仅未开始任务可改关键节点)")
    return ok({"task": task})


@router.post("/tasks/{task_id}/readback")
async def task_set_readback(task_id: str, request: Request):
    """设定解读回环开关(D4): body {on: bool}; 仅未开始任务可改。

    显式值覆盖挡位默认(high-stakes 开/其余关); 运行中指令已固化不可改。"""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    from ..agent.execution.dispatch import task_set_readback as _set
    task = await asyncio.to_thread(_set, task_id, bool((body or {}).get("on")))
    if not task:
        return err(404, "任务不存在或已开始(仅未开始任务可改解读回环开关)")
    return ok({"task": task})


@router.post("/tasks/{task_id}/executor")
async def task_set_executor(task_id: str, request: Request):
    """设定任务执行器(待确认态切换; cline/opencode/codex)。"""
    from ..agent.execution import exec_bridge
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    etype = str((body or {}).get("executorType") or "").strip()
    from ..agent.execution.capabilities import is_valid_type, executor_types
    if not is_valid_type(etype):        # B1 单源: 双命名空间归一判断
        return err(400, "executorType 取值: " + "/".join(executor_types()))
    task = await asyncio.to_thread(exec_bridge.task_set_executor, task_id, etype)
    if not task:
        return err(404, "任务不存在或已不可切换")
    return ok({"task": task})


@router.post("/tasks/{task_id}/verify-config")
async def task_verify_config(task_id: str, request: Request):
    """设定任务验收门禁配置(待确认态; V1 发现链 P0 显式来源)。

    body: {verifyConfig: {maxAttempts?, autoRepair?, timeoutMul?, build?, test?}}"""
    from ..agent.execution import exec_bridge
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    cfg = (body or {}).get("verifyConfig")
    if not isinstance(cfg, dict):
        return err(400, "verifyConfig 必须为对象")
    task = await asyncio.to_thread(exec_bridge.task_set_verify_config,
                                   task_id, cfg)
    if task is None:
        return err(400, "任务不存在或已不可修改(仅待确认态可改)")
    return ok({"task": task})


@router.post("/tasks/{task_id}/cancel")
async def task_cancel(task_id: str, request: Request):
    """取消(待确认)/停止(执行中)任务; 保留 worktree/分支。"""
    from ..agent.execution import exec_bridge
    reason = ""
    try:
        body = await request.json()
        reason = str((body or {}).get("reason") or "")
    except Exception:  # noqa: BLE001
        pass
    res = await asyncio.to_thread(exec_bridge.task_stop, task_id, reason)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "stop-failed"))
    return ok({"task": res.get("task")})


@router.post("/tasks/{task_id}/input")
async def task_input(task_id: str, request: Request):
    """向任务转达用户回复(waiting_input 立即; running 排队续跑)。"""
    from ..agent.execution import exec_bridge
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return err(400, "invalid-json")
    text = str((body or {}).get("text") or "").strip()
    if not text:
        return err(400, "text 为空")
    res = await asyncio.to_thread(exec_bridge.task_input, task_id, text)
    if not res.get("ok"):
        return err(400, str(res.get("error") or "input-failed"))
    # R4 回声: requestId 全链路关联(主流已落 task_input_echo 持久回执)
    return ok({"queued": bool(res.get("queued")),
               "requestId": res.get("requestId") or ""})


@router.get("/tasks")
async def tasks_of(conv_id: str = fastapi.Query("", alias="convId")):
    """会话任务清单(倒序)。?convId= 会话 id。"""
    if not conv_id:
        return err(400, "convId 必填")
    conv = store.ConversationsStore.get(conv_id)
    if not conv:
        return err(404, "会话不存在")
    return ok({"tasks": _tasks_of_conv(conv)})


@router.get("/units")
async def units_of(conv_id: str = fastapi.Query("", alias="convId"),
                   type: str = fastapi.Query("", alias="type"),
                   q: str = fastapi.Query("", alias="q"),
                   scope: str = fastapi.Query("", alias="scope"),
                   limit: int = fastapi.Query(100, alias="limit")):
    """会话知识单元清单(存储归一: 回执/分析/产物/错误等, 检索面读侧)。

    ?convId= 会话 id; 缺省时跨会话列示:
      - scope=all: 跨全库(主库+各项目库)汇总 —— 会话中心左栏知识资产统一视图,
        条目携带 conversationId 供前端标注/联动来源会话;
      - 其余: 按请求项目上下文路由读。
    """
    cap = max(1, min(limit, 200))
    if conv_id:
        conv = store.ConversationsStore.get(conv_id)
        if not conv:
            return err(404, "会话不存在")
        if q.strip():
            rows = store.ContextUnitsStore.search(q.strip(), type_=type or None,
                                                  conversation_id=conv_id,
                                                  limit=cap)
        else:
            rows = store.ContextUnitsStore.all(conversation_id=conv_id, type_=type or None,
                                               limit=cap)
    elif scope == "all":
        rows = store.ContextUnitsStore.all_across(type_=type or None,
                                                  q=q.strip() or None, limit=cap)
    else:
        if q.strip():
            rows = store.ContextUnitsStore.search(q.strip(), type_=type or None, limit=cap)
        else:
            rows = store.ContextUnitsStore.all(type_=type or None, limit=cap)
        # scan 归并路径未整体重排 → 按 createdAt 重排后截断
        rows = sorted(rows, key=lambda r: (r.get("createdAt") is None, r.get("createdAt") or 0),
                      reverse=True)[:cap]
    return ok({"units": rows})


@router.delete("/units/{unit_id}")
async def unit_remove(unit_id: str):
    """删除会话知识单元(误沉淀/过期清理)。"""
    removed = await asyncio.to_thread(store.ContextUnitsStore.delete, unit_id)
    if not removed:
        return err(404, "单元不存在")
    return ok({"deleted": True, "id": unit_id})
