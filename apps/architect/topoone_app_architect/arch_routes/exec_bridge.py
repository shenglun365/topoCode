"""执行作业桥接泵(exec_bridge)——architect 会话 ↔ runner 实施作业(多实例)。

生命周期 v2(P3 清退旧 jobs 写路径):
- 唯一路径 = arch_tasks 任务模型(propose→confirm→泵); conv.meta.jobs 仅存量只读兼容
- workState 聚合: 存在非终态作业 → 会话 running(双收件人, 输入不锁); 全部终态 → architect
- 纯下行泵: 作业事件(提问/进度/完成/失败)批量落会话消息——**无上行自动转发**
  (裁决#6.1); 用户补充经「继续执行」显式增量回合交回等待中的作业
- 停止: 仅 UI 按钮(REST)调用 stop(); 无自然语言通道(裁决#5)
- 验收简报: done 时自动生成(实际改动 vs 规约边界越界检测 + 验收标准对照),
  消息带 meta {jobId, kind, branch} 供前端渲染验收操作
"""
import asyncio
import json
import logging
import os
import time
import urllib.request
from typing import Any, Dict, List, Optional

from . import store
from .store import states as ST

logger = logging.getLogger(__name__)

RUNNER_BASE = os.environ.get("RUNNER_BASE_URL", "http://127.0.0.1:3458").rstrip("/")
_TERMINAL = ("done", "failed", "stopped", "lost")   # 存量 jobs 账本终态(只读兼容)


def _runner(path: str, payload: Optional[dict] = None, timeout: float = 12.0) -> Optional[dict]:
    try:
        if payload is None:
            req = urllib.request.Request(f"{RUNNER_BASE}{path}")
        else:
            req = urllib.request.Request(
                f"{RUNNER_BASE}{path}", data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:  # noqa: BLE001
        logger.debug("[exec-bridge] runner %s failed: %s", path, e)
        return None


def _ts() -> int:
    return int(time.time() * 1000)


def _meta_of(conv_id: str) -> dict:
    conv = store.ConversationsStore.get(conv_id) or {}
    meta = conv.get("meta")
    if isinstance(meta, dict):
        return meta
    try:
        return json.loads(meta or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _save_meta(conv_id: str, meta: dict) -> None:
    import copy
    fresh = _meta_of(conv_id)
    fresh.update({k: v for k, v in meta.items() if not k.startswith("_")})
    store.ConversationsStore.update(conv_id, {"meta": json.dumps(fresh, ensure_ascii=False)})


# ── 账本(jobs[]) ──

def jobs_of(conv_id: str) -> List[dict]:
    j = _meta_of(conv_id).get("jobs")
    return j if isinstance(j, list) else []


def _job_upsert(conv_id: str, job: dict) -> None:
    meta = _meta_of(conv_id)
    jobs = meta.get("jobs") if isinstance(meta.get("jobs"), list) else []
    for i, e in enumerate(jobs):
        if e.get("jobId") == job.get("jobId"):
            jobs[i] = {**e, **job}
            break
    else:
        jobs.append(job)
    meta["jobs"] = jobs[-20:]          # 账本留最近 20 条
    _save_meta(conv_id, meta)
    _aggregate_work_state(conv_id)


def _aggregate_work_state(conv_id: str) -> None:
    """workState 聚合: 非终态作业存在 ⇔ running。"""
    live = [j for j in jobs_of(conv_id) if (j.get("status") or "") not in _TERMINAL]
    try:
        store.ConversationsStore.set_work_state(conv_id, "running" if live else "architect")
    except Exception:  # noqa: BLE001
        pass
def _meta_dict_of(conv: dict) -> dict:
    meta = (conv or {}).get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            meta = {}
    return meta or {}
# ── 会话消息 ──

def _append(conv_id: str, role: str, content: str, msg_meta: Optional[dict] = None,
            project_id: str = "", agent: str = "") -> None:
    """委托 collab.cards.land(卡片落流唯一出口, cv-175 规范化)。"""
    from ..agent.collab import cards as _cards
    meta = dict(msg_meta or {})
    _cards.land(conv_id, content, kind=meta.pop("kind", None), role=role,
                project_id=project_id, agent=agent, **meta)

def _acceptance_brief(conv_id: str, rid: str, changed_files: List[str]) -> str:
    """验收简报: 实际改动 vs 规约边界(越界检测) + 验收标准静态对照。

    architect 辅助判定材料——完成与否由用户判定(裁决#3)。
    """
    from .req_agent import parse_scope_files
    active = store.RequirementsStore.spec_active(rid or "") or {}
    snap = active.get("snapshot") or {}
    scope_files = parse_scope_files(snap.get("allowedScope") or [])
    out_lines = []
    if scope_files:
        overrun = [f for f in changed_files
                   if not any(f.startswith(p) for p in scope_files)]
        if overrun:
            out_lines.append("**⚠️ 越界改动**(超出规约允许范围，请核查)：\n"
                             + "\n".join(f"- `{f}`" for f in overrun[:15]))
        else:
            out_lines.append(f"✅ 边界符合：{len(changed_files)} 个改动文件均在允许范围内")
    else:
        out_lines.append("ℹ️ 规约未声明可解析边界，无法做越界检测")
    acc = snap.get("acceptance") or []
    if acc:
        out_lines.append("**验收标准对照**(静态，逐条人工确认)：\n"
                         + "\n".join(f"- [ ] {a}" for a in acc[:12]))
    return "\n\n".join(out_lines)


# ── 互斥引擎(裁决#1/#2/#9) — 实现迁至 agent.governance.boundary(P2), 薄委托 ──

def _resolve_boundary_files(rid: str, root: str, project: Optional[str]) -> List[str]:
    from ..agent.governance.boundary import resolve_boundary_files
    return resolve_boundary_files(rid, root, project)


def _check_mutex(conv: dict, root: str, boundary_files: List[str]) -> Optional[str]:
    from ..agent.governance.boundary import check_mutex
    return check_mutex(conv, root, boundary_files, runner=_runner)


def _files_intersect(a: List[str], b: List[str]) -> List[str]:
    from ..agent.governance.boundary import files_intersect
    return files_intersect(a, b)
def stop(conv_id: str, reason: str = "") -> str:
    """UI 停止按钮(REST): 结束全部运行中作业(保留 worktree/分支)。"""
    jobs = [j for j in jobs_of(conv_id) if (j.get("status") or "") not in _TERMINAL]
    if not jobs:
        return "当前会话没有运行中的作业。"
    for j in jobs:
        _runner(f"/api/implement/{j['jobId']}/finish", {"keepWorktree": True}, timeout=30.0)
        _job_upsert(conv_id, {"jobId": j["jobId"], "status": "stopped",
                              "endedAt": _ts()})
    _aggregate_work_state(conv_id)
    return (f"🛑 已停止 {len(jobs)} 个作业。分支与改动已保留，"
            "可「查看差异」检视，或 `/执行` 按当前规约重新执行。")
_WS_IDLE_SEC = 10.0        # 订阅空闲窗口(超时→snapshot 校准一轮, 保留 lost/终态判定)
_WS_RETRY_GAP = 4          # 订阅失败后的重试间隔(轮询轮)
# ══════════════════════════════════════════════════════════════════
# v2 统一会话: coding subagent 任务模型(arch_tasks)
# 设计: 任务回执以消息(agent=executor_type)落统一流, 本节只管生命周期。
# 轻门禁: pending_confirm(任务卡确认) → running → waiting_input → 终态。
# 解耦: 本层不感知 executor 内部(TurnAdapter 协议隔离), agent 标注 =
# task.executorType(architect 泵统一写)。
# ══════════════════════════════════════════════════════════════════

_TASK_TERMINAL = ("done", "failed", "cancelled")
_TASK_ACTIVE = (ST.TASK_PENDING_CONFIRM, "running", ST.TASK_WAITING_INPUT)


def _last_failed_branch(conv_id: str) -> str:
    """取会话最近一次失败任务的分支(跨主库+项目库扫描——任务库路由存在
    读写分裂隐患, 与 recover_sweep 同法兜住; 路由统一另行排查)。"""
    try:
        from .store.base import _db, _scan_dbs
        seen = []
        for db in [_db(), *_scan_dbs()]:
            try:
                rows = db.fetchall(
                    "SELECT id, branch, created_at FROM arch_tasks "
                    "WHERE conversation_id = ? AND status = 'failed' "
                    "AND branch LIKE 'task/%' ORDER BY created_at DESC",
                    (conv_id,))
                seen.extend(rows or [])
            except Exception:  # noqa: BLE001
                continue
        seen.sort(key=lambda r: r.get("created_at") or 0, reverse=True)
        for r in seen:
            return str(r.get("branch") or "")
    except Exception:  # noqa: BLE001
        pass
    return ""


def propose_task(conv: dict, title: str, instruction: str,
                 executor_hint: Optional[dict] = None) -> dict:
    """轻门禁入口: 建任务(pending_confirm) + 任务卡消息落统一流。

    由 LLM 工具 task.propose / architect 编排调用; 用户确认(REST/卡片按钮)
    后 confirm_task 真正拉起 runner。"""
    conv_id = conv["id"]
    _pid = (conv or {}).get("projectId") or (conv or {}).get("project_id") or ""
    # 执行器选定单源(显式 hint > 会话绑定 > 注册表默认); 不再字面回落 opencode(cv-153 教训)
    from .agent_executors import normalize_executor_type, default_executor
    etype = normalize_executor_type((executor_hint or {}).get("executorType") or "")
    if not etype:
        _bound = executor_hint_by_id(str((conv or {}).get("executorId") or ""), conv) or {}
        etype = normalize_executor_type(_bound.get("executorType") or "")
    if not etype:
        etype = normalize_executor_type((default_executor() or {}).get("type") or "")
    if not etype:
        return {"ok": False,
                "error": "无可用执行器：注册表无启用项且未指定执行器类型——"
                         "请在「执行器配置」启用至少一个执行器后在对话中指定(如 @cline)。"}
    _eid = ((executor_hint or {}).get("executorId") or ""
            or (conv or {}).get("executorId") or "")
    if not _eid:
        # 类型/配置须同源(cv-158 实证: 默认执行器只给了 type 没带 id → confirm 时
        # 无 executorConfig 可查, sidecar 收到空 model 被拒)——eid 取同一注册项
        _def = default_executor() or {}
        _eid = str(_def.get("id") or "")
    # 续跑衔接(cv-177): 会话存在失败任务且其分支仍在 → 新任务复用该分支,
    # runner 检出已有分支承接上次进度(终态自动 commit 已保全)——重跑不再从零开始。
    resume_branch = _last_failed_branch(conv_id)
    _rid = (conv or {}).get("reqId") or ""
    _spec_ver = 0
    if _rid:
        _active = store.RequirementsStore.spec_active(_rid) or {}
        _spec_ver = int(_active.get("ver") or 0)
    task = store.TasksStore.create({
        "conversationId": conv_id,
        "projectId": _pid,
        "reqId": _rid,
        "title": (title or "").strip()[:120] or "实施任务",
        "instruction": instruction,
        "status": ST.TASK_PENDING_CONFIRM,
        "executorType": etype,
        "executorId": _eid,
        "specVer": _spec_ver,
        **({"branch": resume_branch} if resume_branch else {}),
    })
    # 错误契约(docs/architect/error-contract.md): 成功形状显式 ok=True
    # (失败形状 {"ok": False, "error"}; store 行为规范列, ok 仅回执层)
    task = {**task, "ok": True}
    _resume_note = (f"\n\n> 🔁 续跑：将承接上次失败任务的进度分支 `{resume_branch}`"
                     "（进度已自动保全）" if resume_branch else "")
    _append(conv_id, "assistant",
            f"📋 **任务待确认**\n\n**{task['title']}**\n执行器 `{etype}`\n\n"
            + instruction[:2000]
            + "\n\n---\n确认后开始执行; 可取消或要求 architect 调整。" + _resume_note,
            msg_meta={"kind": "task_card", "taskId": task["id"]},
            project_id=_pid)
    _publish_task(conv_id, task)
    return task


def confirm_task(task_id: str) -> dict:
    """用户确认任务卡 → runner 建作业 + 泵启动(pending_confirm→running)。"""
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found"}
    if (task.get("status") or "") != ST.TASK_PENDING_CONFIRM:
        return {"ok": False, "error": f"task-status={task.get('status')}"}
    conv = store.ConversationsStore.get(task["conversationId"])
    if not conv:
        return {"ok": False, "error": "conv-not-found"}
    from .execution import conv_root_project
    conv_id = conv["id"]
    # 同会话活跃任务互斥(一次一个 subagent 回合); 命中先惰性自愈——
    # 服务重启可能留下僵尸 running(泵丢失), 核对 runner 实际态后再裁决
    other = next((t for t in store.TasksStore.of_conv(conv_id)
                  if t["id"] != task_id and t.get("status") in ("running", ST.TASK_WAITING_INPUT)), None)
    if other:
        try:
            recover_conv_tasks(conv_id)
        except Exception:  # noqa: BLE001
            pass
        other = next((t for t in store.TasksStore.of_conv(conv_id)
                      if t["id"] != task_id and t.get("status") in ("running", ST.TASK_WAITING_INPUT)), None)
    if other:
        return {"ok": False,
                "error": f"另一任务执行中({other['title']}), 停止或等待其结束"}
    # 执行器选定单源(hint > 任务卡 > 注册表默认); 不再字面回落 opencode——
    # 解析不到 → 任务显式 failed(用户要求: 指定失败必须明确返回, 禁止降级)。
    # 先于项目根解析: 缺执行器是更前置的错误, 优先显式暴露。
    from .agent_executors import normalize_executor_type, default_executor
    hint = executor_hint_by_id(task.get("executorId") or "", conv) or {}
    _etype = normalize_executor_type(hint.get("executorType")
                                     or task.get("executorType") or "")
    if not _etype:
        _etype = normalize_executor_type((default_executor() or {}).get("type") or "")
    if not hint and not (task.get("executorId") or ""):
        # 配置同源兜底(cv-158): 任务只有类型没有 id(默认执行器早期版本只写 type)
        # → 取注册表默认项的完整配置(/models/provider/key), 否则 sidecar 收到空 model
        hint = executor_hint_by_id(str((default_executor() or {}).get("id") or ""), conv) or {}
        _etype = _etype or normalize_executor_type(hint.get("executorType") or "")
    if not _etype:
        err = ("无可用执行器：任务未绑定执行器且注册表无默认项——"
               "请在任务卡上选择执行器或在「执行器配置」设置默认。")
        store.TasksStore.finish(task_id, "failed", err)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
        return {"ok": False, "error": err}
    root, project = conv_root_project(conv)
    if not root:
        store.TasksStore.update(task_id, {"status": "failed",
                                          "result_md": "无法解析项目根(会话未绑定项目)"})
        return {"ok": False, "error": "no-project-root"}
    rid = task.get("reqId") or ""
    branch = f"task/{task_id.replace('task-', '')}"
    boundary_files = _resolve_boundary_files(rid, root, project)
    conflict = _check_mutex(conv, root, boundary_files)
    if conflict:
        store.TasksStore.finish(task_id, "failed", f"边界冲突: {conflict}")
        return {"ok": False, "error": conflict}
    payload = {"root": root, "instruction": _task_instruction(task, _task_chain_brief(conv_id, task_id)),
               "branchName": branch, "projectId": project,
               "boundaries": {"files": boundary_files, "components": [],
                              "readOnly": False}}
    # hint 已含注册表默认兜底(上方选定单源)——此处不得按空 executorId 重查覆盖
    for k in ("model", "basePort", "autoStart", "baseUrl"):
        v = hint.get(k)
        if v not in (None, ""):
            payload[k] = v
    if hint.get("executorId"):
        payload["executorId"] = hint["executorId"]
        payload["executorConfig"] = hint.get("executorConfig") or {}
    if _etype:
        payload["executorType"] = _etype   # 引擎选择以 task 为准(无注册表也可指定)
    # 回合超时配置下发(执行器注册表 config → runner 看门狗参数)
    _cfg = hint.get("executorConfig") or {}
    for k in ("turnTimeout", "stallSec"):
        v = _cfg.get(k)
        if isinstance(v, (int, float)) and v > 0:
            payload[k] = float(v)
    # 复活执行器原生会话(跨回合连续性): task 行持 sessionRef
    if task.get("sessionRef"):
        payload["sessionRef"] = task["sessionRef"]
    # P5: 规约/规则/agent 配置落盘 worktree（per-executor 路径映射）
    workspace_files = _build_workspace_files(_etype or "", _cfg, task)
    if workspace_files:
        payload["workspaceFiles"] = workspace_files

    res = _runner("/api/implement", payload, timeout=20.0)
    if not res or not res.get("ok"):
        err = (res or {}).get("error") or "runner 服务不可达(:3458)"
        store.TasksStore.finish(task_id, "failed", err)
        return {"ok": False, "error": err}
    store.TasksStore.update(task_id, {
        "status": "running", "runner_job_id": res["jobId"],
        "worktree": res.get("worktree") or "", "branch": res.get("branch") or branch,
        "session_ref": res.get("sessionId") or ""})
    try:
        store.ConversationsStore.set_work_state(conv_id, "running")
    except Exception:  # noqa: BLE001
        pass
    agent = task.get("executorType") or _etype
    pid = (conv or {}).get("projectId") or ""
    _append(conv_id, "user",
            f"🚀 **{task['title']}** 启动（`{res['jobId']}` 分支 `{branch}`）",
            msg_meta={"kind": "task_start", "taskId": task_id}, project_id=pid)
    _start_task_pump(conv_id, task_id, res["jobId"], rid, agent)
    t = store.TasksStore.get(task_id) or {}
    _publish_task(conv_id, t)
    return {"ok": True, "task": t}


def task_set_executor(task_id: str, executor_type: str) -> Optional[dict]:
    """设定任务执行器(别名归一: cline→cline-sdk)。仅 pending_confirm 可换——
    运行中引擎已固化(换=新任务); 返回更新后任务行(不可换返回 None)。"""
    from .agent_executors import normalize_executor_type
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") != ST.TASK_PENDING_CONFIRM:
        return None
    etype = normalize_executor_type(executor_type)
    if etype not in ("cline-sdk", "opencode", "codex-server"):
        return None
    return store.TasksStore.update(task_id, {"executor_type": etype})


def task_input(task_id: str, text: str) -> Dict[str, Any]:
    """用户回复 → 转达 subagent(waiting_input 立即; running 排队续跑)。

    审批指令: `/approve {requestId}` | `/deny {requestId} [理由]` →
    转发 runner approval 端点(越界确认桥), 不作为回合输入。
    """
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") not in (ST.TASK_WAITING_INPUT, "running"):
        return {"ok": False, "error": "task-not-active"}
    stripped = (text or "").strip()
    approve = stripped.startswith("/approve ")
    deny = stripped.startswith("/deny ")
    if approve or deny:
        parts = stripped.split(None, 2)
        request_id = parts[1].strip() if len(parts) > 1 else ""
        if not request_id:
            return {"ok": False, "error": "缺少 requestId（用法: /approve {id} 或 /deny {id} [理由]）"}
        reason = parts[2].strip() if len(parts) > 2 else ""
        job_id = str(task.get("runnerJobId") or "")
        res = _runner(f"/api/implement/{job_id}/approval",
                      {"requestId": request_id,
                       "approved": approve,
                       "reason": reason or ("approved" if approve else "rejected by user")},
                      15.0)
        if res and res.get("ok"):
            conv_id = task.get("conversationId") or ""
            _append(conv_id, "assistant",
                    f"{'✅ 已批准' if approve else '🚫 已拒绝'} 工具调用 `{request_id}`。",
                    msg_meta={"kind": "task_approval_done", "taskId": task_id},
                    project_id=(store.ConversationsStore.get(conv_id) or {}).get("projectId") or "")
            return {"ok": True, "approval": True}
        return {"ok": False, "error": (res or {}).get("error") or "审批转发失败"}
    res = _runner(f"/api/implement/{task.get('runnerJobId')}/input",
                  {"text": stripped[:12000],
                   # P4: running 态优先 steer 直达（cline pending 优先投递）；
                   # runner 侧不支持的执行器自动回退排队
                   **({"steer": True} if (task.get("status") or "") == "running" else {})},
                  15.0)
    if res and res.get("ok"):
        if (task.get("status") or "") == ST.TASK_WAITING_INPUT:
            store.TasksStore.update(task_id, {"status": "running"})
            t = store.TasksStore.get(task_id) or {}
            _publish_task(task["conversationId"], t)
        return {"ok": True, "queued": bool(res.get("queued"))}
    return {"ok": False, "error": (res or {}).get("error") or "runner 不可达"}


def task_stop(task_id: str, reason: str = "") -> Dict[str, Any]:
    """停止任务(保留 worktree/分支)。"""
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") in _TASK_TERMINAL:
        return {"ok": False, "error": "task-not-active"}
    if (task.get("status") or "") == ST.TASK_PENDING_CONFIRM:
        store.TasksStore.finish(task_id, "cancelled", reason or "用户取消")
        t = store.TasksStore.get(task_id) or {}
        _publish_task(task["conversationId"], t)
        return {"ok": True, "task": t}
    _runner(f"/api/implement/{task.get('runnerJobId')}/finish",
            {"keepWorktree": True}, timeout=30.0)
    store.TasksStore.finish(task_id, "cancelled", reason or "用户停止")
    for fut in (_TASK_PUMPS.pop(task["conversationId"], None) or {}).values():
        fut.cancel()
    _task_reaggregate_work_state(task["conversationId"])
    t = store.TasksStore.get(task_id) or {}
    _publish_task(task["conversationId"], t)
    return {"ok": True, "task": t}


def active_task_of(conv_id: str) -> Optional[dict]:
    """最新活跃任务(running/waiting_input 优先, 次 pending_confirm); 无则 None。"""
    ts = store.TasksStore.of_conv(conv_id)
    for t in reversed(ts):
        if (t.get("status") or "") in ("running", ST.TASK_WAITING_INPUT):
            return t
    for t in reversed(ts):
        if (t.get("status") or "") == ST.TASK_PENDING_CONFIRM:
            return t
    return None


def _publish_task(conv_id: str, task: dict) -> None:
    """任务状态变更 → SSE 单通道广播(前端 TaskCard/过滤器响应)。"""
    try:
        from ..agent.collab.sse import emit
        emit("task", conv_id, task=task)
    except Exception:  # noqa: BLE001
        pass


def _task_reaggregate_work_state(conv_id: str) -> None:
    """任务终态后: 无其它活跃任务 → workState 回 architect 相位。"""
    try:
        if not active_task_of(conv_id):
            store.ConversationsStore.set_work_state(conv_id, "architect")
    except Exception:  # noqa: BLE001
        pass


# ── 任务泵: 事件 → 统一流(agent 标注) ──

_TASK_PUMPS: Dict[str, dict] = {}   # conv_id -> {job_id: asyncio.Task}
_MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_main_loop(loop) -> None:
    """服务启动时捕获主事件循环: REST to_thread 工作线程内启动泵须调度回这里
    (工作线程无循环, create_task 必炸——cv-153 泵从未启动的真根因)。"""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _start_task_pump(conv_id: str, task_id: str, job_id: str, rid: str,
                     agent: str) -> None:
    jobs = _TASK_PUMPS.setdefault(conv_id, {})
    old = jobs.get(job_id)
    if old and not old.done():
        return
    coro = _task_pump(conv_id, task_id, job_id, rid, agent)
    try:
        loop = asyncio.get_running_loop()
        jobs[job_id] = loop.create_task(coro)
    except RuntimeError:
        # 工作线程(REST to_thread 等): 调度回主事件循环
        if _MAIN_LOOP is not None and _MAIN_LOOP.is_running():
            jobs[job_id] = asyncio.run_coroutine_threadsafe(coro, _MAIN_LOOP)
        else:
            coro.close()   # 无循环可挂(测试/关停): 丢弃并告警, 不让协程泄漏
            logger.warning("[exec-bridge] 无事件循环可挂任务泵 conv=%s job=%s",
                           conv_id, job_id)


_SWEEP_TASK: Optional[asyncio.Task] = None


def start_recover_sweep(interval: float = 45.0) -> None:
    """C 定时对账: 主循环周期任务——扫描默认库+全部项目库的假 running 任务。

    恢复触发不再依赖用户交互(GET messages/handle_chat); 服务重启后
    由本循环自动收敛。重复调用幂等(任务存活即跳过)。"""
    global _SWEEP_TASK
    if _SWEEP_TASK and not _SWEEP_TASK.done():
        return

    async def _loop() -> None:
        while True:
            try:
                n = await asyncio.to_thread(recover_sweep)
                if n:
                    logger.info("[exec-bridge] sweep 收尾任务数=%s", n)
            except Exception as e:  # noqa: BLE001
                logger.warning("[exec-bridge] sweep 异常: %s", e)
            await asyncio.sleep(interval)

    _SWEEP_TASK = asyncio.create_task(_loop())


def recover_sweep() -> int:
    """扫默认库+全部项目库(目录发现 {data}/architect/{pid}/arch.db)中
    存在 running/waiting_input 任务的会话 → recover_conv_tasks。
    返回收尾任务数(重挂泵不计)。"""
    import sqlite3
    from ..arch_routes import ctx as _ctx
    data_dir = _ctx.data_dir()
    db_paths = [os.path.join(data_dir, "architect.db")]
    proj_root = os.path.join(data_dir, "architect")
    if os.path.isdir(proj_root):
        for pid in sorted(os.listdir(proj_root)):
            dbp = os.path.join(proj_root, pid, "arch.db")
            if os.path.isfile(dbp):
                db_paths.append(dbp)
    conv_ids: list = []
    for dbp in db_paths:
        if not os.path.isfile(dbp):
            continue
        try:
            con = sqlite3.connect(f"file:{dbp}?mode=ro", uri=True)
            try:
                rows = con.execute(
                    "SELECT DISTINCT conversation_id FROM arch_tasks "
                    "WHERE status IN ('running','waiting_input')").fetchall()
                conv_ids += [r[0] for r in rows if r[0]]
            finally:
                con.close()
        except Exception:  # noqa: BLE001
            continue
    total = 0
    for conv_id in dict.fromkeys(conv_ids):
        try:
            rec = recover_conv_tasks(conv_id)
            total += int((rec or {}).get("finished") or 0)
        except Exception:  # noqa: BLE001
            logger.warning("[exec-bridge] sweep 恢复失败 conv=%s", conv_id)
    return total


def recover_conv_tasks(conv_id: str) -> dict:
    """P1 泵恢复(惰性): 会话交互前核对 running/waiting_input 任务与 runner 实际态。

    服务重启会丢内存泵(_TASK_PUMPS)与 runner 作业(_JOBS 同为内存态)——runner
    侧已终态的任务被卡 running(互斥锁死会话、无结果回执; cv-153 实证)。
    - runner 终态(done/failed) → 重放终态事件(回执+result_md+work_state 聚合)
    - 仍在执行 → 返回 repump 清单(调用方须在事件循环内 _start_task_pump;
      本函数可能跑在工作线程, 不能 create_task)
    - runner 报作业不存在 → 显式 failed(不臆测不悬置)
    - runner 不可达 → 跳过(可能在重启, 下次交互再试)
    返回 {"finished": 收尾数, "repump": [(task_id, job_id, rid, agent), ...]}。
    """
    out = {"finished": 0, "repump": []}
    for t in store.TasksStore.of_conv(conv_id):
        if (t.get("status") or "") not in ("running", ST.TASK_WAITING_INPUT):
            continue
        job_id = t.get("runnerJobId") or ""
        if not job_id:
            continue
        res = _runner(f"/api/implement/{job_id}", timeout=8.0)
        if not res or not res.get("ok"):
            if res and "作业不存在" in str(res.get("error") or ""):
                err = "runner 作业已丢失(执行器服务重启)——无法续跑, 请重新发起任务。"
                _handle_task_event({"kind": "failed", "text": err},
                                   _task_ctx(conv_id, t["id"], job_id,
                                             t.get("reqId") or "",
                                             t.get("executorType") or ""))
                out["finished"] += 1
            continue
        evs = res.get("events") or []
        last_term = None
        for ev in evs:
            if (ev.get("kind") or "") in ("done", "failed", "input_required"):
                last_term = ev
        if last_term and (last_term.get("kind") in ("done", "failed")):
            _handle_task_event(last_term,
                               _task_ctx(conv_id, t["id"], job_id,
                                         t.get("reqId") or "",
                                         t.get("executorType") or ""))
            out["finished"] += 1
        else:
            # 仍在执行或等待输入: 交还调用方在事件循环内重挂泵
            out["repump"].append((t["id"], job_id, t.get("reqId") or "",
                                  t.get("executorType") or ""))
    return out


def _task_ctx(conv_id: str, task_id: str, job_id: str, rid: str, agent: str) -> dict:
    conv = store.ConversationsStore.get(conv_id) or {}
    return {"convId": conv_id, "taskId": task_id, "jobId": job_id, "rid": rid,
            "pid": conv.get("projectId") or "", "agent": agent}


_PROGRESS_SSE_LAST: dict = {}   # task_id → 上次 SSE progress 发送时刻(文本节流)


def _publish_progress(conv_id: str, task_id: str, prog: dict,
                      throttle: float = 0.0) -> None:
    """任务进度实时推送（WS/SSE 单一出口）。

    throttle>0 时按 task 节流(准流式: 文本片段高频, 0.5s 一拍足够"内容在动";
    工具/终态事件不节流保证不丢关键帧)。"""
    if throttle > 0:
        now = time.time()
        if now - _PROGRESS_SSE_LAST.get(task_id, 0.0) < throttle:
            return
        _PROGRESS_SSE_LAST[task_id] = now
    try:
        from ..agent.collab.sse import emit
        emit("progress", conv_id, taskId=task_id, **{"at": _ts(), **prog})
    except Exception:  # noqa: BLE001
        pass


def _build_workspace_files(executor_type: str, executor_cfg: dict, task: dict) -> list:
    """P5: 执行器约定文件组装（cline→.cline/rules|agents, opencode/codex→AGENTS.md）。

    数据源（后续接 KB 语义资产的扩展点）:
    - task.rulesMd        任务级规约文本
    - cfg.rulesMd         执行器级规约文本
    - cfg.teams.agents    cline teams 成员配置([{name, content}])
    """
    files: list = []
    rules_parts = []
    for src in (task.get("rulesMd"), (executor_cfg or {}).get("rulesMd")):
        if isinstance(src, str) and src.strip():
            rules_parts.append(src.strip())
    if rules_parts:
        content = "\n\n".join(rules_parts)
        if executor_type == "cline-sdk":
            files.append({"path": ".cline/rules/000-guide.md", "content": content})
        else:
            files.append({"path": "AGENTS.md", "content": content})
    if executor_type == "cline-sdk":
        teams = (executor_cfg or {}).get("teams") or {}
        for a in (teams.get("agents") if isinstance(teams, dict) else []) or []:
            if isinstance(a, dict) and str(a.get("name") or "").strip() \
                    and isinstance(a.get("content"), str):
                name = "".join(c for c in str(a["name"]) if c.isalnum() or c in "-_")
                if name:
                    files.append({"path": f".cline/agents/{name}.md",
                                  "content": str(a["content"])})
    return files


def _handle_task_event(ev: dict, ctx: dict) -> None:
    """v2: runner 事件 → 任务生命周期 + 统一流消息(agent=executor)。

    (P3 起为唯一任务事件路径; 旧 jobs 泵已清退):
    - 无子会话: 全部落主流, agent=ctx.agent;
    - input_required: 消息 + task waiting_input(无熔断计数——统一流天然往返);
    - progress: task.progress + SSE progress(不落消息);
    - done/failed: 终态 + result_md。
    """
    conv_id, task_id, job_id = ctx["convId"], ctx["taskId"], ctx["jobId"]
    pid, agent = ctx["pid"], ctx["agent"]
    kind = ev.get("kind") or ""
    if kind in ("user_input", "session_ready"):
        return
    text = (ev.get("text") or "").strip()
    task = store.TasksStore.get(task_id) or {}
    title = task.get("title") or "任务"
    if kind == "input_required":
        clean = text.replace("[[NEED_INPUT]]", "").strip() or "(等待你的输入)"
        _append(conv_id, "assistant",
                f"⏸ **{agent} 需要你的输入**（任务「{title}」）\n\n{clean}\n\n"
                "直接回复即转达; 也可 @architect 讨论。",
                msg_meta={"kind": "task_input", "taskId": task_id},
                project_id=pid, agent=agent)
        store.TasksStore.update(task_id, {"status": ST.TASK_WAITING_INPUT})
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
    elif kind == "done":
        clean = text.replace("[[IMPLEMENT_DONE]]", "").strip()
        changed = ev.get("changedFiles") or []
        brief = _acceptance_brief(conv_id, ctx["rid"], changed)
        files = ("\n".join(f"- `{f}`" for f in changed[:20])
                 if changed else "- (无变更文件)")
        branch = (store.TasksStore.get(task_id) or {}).get("branch") or ""
        _append(conv_id, "assistant",
                f"✅ **任务完成**「{title}」（分支 `{branch}`）\n\n{clean}\n\n"
                f"**变更文件**：\n{files}\n\n---\n**验收简报**\n{brief}",
                msg_meta={"kind": "task_done", "taskId": task_id, "branch": branch},
                project_id=pid, agent=agent)
        store.TasksStore.finish(task_id, "done", clean[:2000])
        _task_reaggregate_work_state(conv_id)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
    elif kind == "failed":
        _append(conv_id, "assistant",
                f"❌ **任务失败**「{title}」：{text}\n分支已保留, 可重新发起。",
                msg_meta={"kind": "task_failed", "taskId": task_id},
                project_id=pid, agent=agent)
        store.TasksStore.finish(task_id, "failed", text[:2000])
        _task_reaggregate_work_state(conv_id)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})
    elif kind == "progress":
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev,
                "toolCount": int(ev.get("toolCount") or 0),
                "msgCount": int(ev.get("msgCount") or 0), "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
        _publish_progress(conv_id, task_id, prog)
    elif kind == "text":
        # 准流式执行预览: 滚动文本尾(600 字符)+节流 SSE(0.5s), 不落消息(防刷屏)。
        # UI 过程面板随 progress 事件实时变化, 终态回执仍走 done/failed。
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev,
                "lastText": ((prev.get("lastText") or "") + text)[-600:], "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
        _publish_progress(conv_id, task_id, prog, throttle=0.5)
    elif kind == "tool":
        # 工具轨迹: process 环形尾(30 条)随 SSE 全量下发, TaskCard 渲染过程流
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        name = str(ev.get("toolName") or text or "")
        trail = [*(((prev.get("process") or []))), {"at": _ts(), "s": f"▸ {name}"}][-30:]
        prog = {**prev, "lastTool": name, "process": trail, "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
        _publish_progress(conv_id, task_id, prog)
    elif kind == "usage":
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev,
                "inputTokens": int(ev.get("inputTokens") or 0),
                "outputTokens": int(ev.get("outputTokens") or 0), "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
    elif kind == "approval_request":
        # 越界审批桥: 落可操作消息(meta 携 jobId/requestId), 前端渲染批准/拒绝
        tool_name = str(ev.get("toolName") or "工具")
        req_id = str(ev.get("requestId") or "")
        _append(conv_id, "assistant",
                f"🔐 **{agent} 请求确认**（任务「{title}」）\n\n"
                f"工具 `{tool_name}` 请求执行，等待你的批准。\n\n"
                f"批准：回复 /approve {req_id}；拒绝：回复 /deny {req_id}。",
                msg_meta={"kind": "task_approval", "taskId": task_id,
                          "approvalJobId": job_id, "approvalRequestId": req_id},
                project_id=pid, agent=agent)
    elif kind == "team":
        # P5: 团队进度 → 进度预览（不落消息，防刷屏）
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev, "lastTeam": text[:120], "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
        _publish_progress(conv_id, task_id, {"lastTeam": text[:120]})
    elif kind == "mcp":
        # P5: MCP 注入结果 → 进度（失败轻提示落进度，不阻断）
        prev = (store.TasksStore.get(task_id) or {}).get("progress") or {}
        prog = {**prev, "lastMcp": f"{ev.get('server')}:{'ok' if ev.get('ok') else 'failed'}",
                "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
    elif kind in ("notice", "turn_outcome"):
        # notice: 进展噪声(mistake_limit 由 failed 收口); turn_outcome: 标记已承载
        return
    elif kind in ("aborted", "finished"):
        _append(conv_id, "assistant", f"ℹ️ {text}", project_id=pid, agent=agent)
    elif text:
        _append(conv_id, "assistant", text,
                msg_meta={"kind": "task_progress", "taskId": task_id},
                project_id=pid, agent=agent)


async def _task_pump(conv_id: str, task_id: str, job_id: str, rid: str,
                     agent: str) -> None:
    """任务泵: 骨架委托 agent.execution.pumps(唯一实现), 事件走 task 路径。"""
    from ..agent.execution import pumps as _pumps
    logger.info("[exec-bridge] task-pump start conv=%s task=%s job=%s",
                conv_id, task_id, job_id)

    def on_event(ev: dict) -> None:
        _handle_task_event(ev, _task_ctx(conv_id, task_id, job_id, rid, agent))

    def on_snapshot(snap: dict) -> None:
        sid = (snap.get("sessionId") or "").strip()
        if sid:
            t = store.TasksStore.get(task_id) or {}
            if (t.get("sessionRef") or "") != sid:
                try:
                    store.TasksStore.update(task_id, {"session_ref": sid})
                except Exception:  # noqa: BLE001
                    pass

    def on_lost(reason: str) -> None:
        store.TasksStore.finish(task_id, "failed", reason)
        title = (store.TasksStore.get(task_id) or {}).get("title", "")
        _append(conv_id, "assistant",
                f"⚠️ 任务「{title}」与 runner 失去联系({reason}), 已记为失败。",
                msg_meta={"kind": "task_failed", "taskId": task_id},
                agent=agent)
        _publish_task(conv_id, store.TasksStore.get(task_id) or {})

    def on_finished(status: str) -> None:
        # runner 侧终态兜底(事件流已落终态时为 no-op; stopped→cancelled 语义)
        t = store.TasksStore.get(task_id) or {}
        if (t.get("status") or "") not in _TASK_TERMINAL:
            store.TasksStore.finish(
                task_id, "cancelled" if status == "stopped" else status)
            _publish_task(conv_id, store.TasksStore.get(task_id) or {})

    await _pumps.run_event_pump(
        base=RUNNER_BASE, job_id=job_id, runner=_runner,
        on_event=on_event, on_snapshot=on_snapshot,
        on_lost=on_lost, on_finished=on_finished)


def _task_instruction(task: dict, prior_brief: str = "") -> str:
    """任务指令组装(P4 委托 planning.task_plan, 原文迁入保真)。"""
    from ..agent.planning.task_plan import assemble_task_instruction
    return assemble_task_instruction(task, prior_brief)


def _meta_get(conv: dict) -> dict:
    import json as _json
    meta = (conv or {}).get("meta")
    if isinstance(meta, dict):
        return meta          # row_to_api 已解析
    try:
        return _json.loads(meta or "{}")
    except Exception:  # noqa: BLE001
        return {}


def _meta_set(conv_id: str, meta: dict) -> None:
    import json as _json
    store.ConversationsStore.update(conv_id, {"meta": _json.dumps(meta, ensure_ascii=False)})


def _spec_updated_at(rid: str) -> int:
    return int((store.RequirementsStore.get(rid) or {}).get("updatedAt") or 0)



def _task_chain_brief(conv_id: str, current_task_id: str) -> str:
    """前情链: 同会话最近 ≤3 条终态任务的结果摘要(自动注入新任务指令)。

    任务链上下文延续——执行器不重走已完成的探索/改动; 纯确定性组装,
    不调 LLM、不弹 UI、不依赖 architect 自觉。"""
    rows = [t for t in store.TasksStore.of_conv(conv_id)
            if t.get("id") != current_task_id
            and (t.get("status") or "") in ("done", "failed", "cancelled")]
    if not rows:
        return ""
    lines = []
    for t in rows[::-1][:3]:               # 最近在前
        status = t.get("status") or ""
        result = str(t.get("resultMd") or t.get("result_md")
                     or "").strip().replace("\n", " ")
        if len(result) > 240:
            result = result[:240].rstrip() + "…"
        if not result:
            continue
        icon = "✅" if status == "done" else "⚠️"
        lines.append(f"- {icon}「{(t.get('title') or '')[:40]}」({status}): {result}")
    if not lines:
        return ""
    return "\n".join(lines)[:1000]




def executor_hint_by_id(executor_id: str, conv: Optional[dict] = None) -> Optional[dict]:
    """执行器 id → 注册表配置提示(model/端口/超时等)——v2 任务模型用。

    原 websocket._executor_hint 泛化: 按 task.executorId 直查注册表;
    无绑定 → None(缺省 opencode)。
    """
    eid = (executor_id or "").strip()
    if not eid:
        return None
    conv_model = ((conv or {}).get("executorModel") or "").strip()
    try:
        from .agent_executors import load_executors, _default_sidecar_path
        for e in load_executors():
            if (e.get("id") or "") == eid:
                cfg = e.get("config") or {}
                model_names = [str(m.get("name") or m.get("model") or "")
                               for m in (cfg.get("models") or [])
                               if (m.get("name") or m.get("model"))]
                # 模型选择链对齐(turn_adapter._resolve_model 同序):
                # 会话绑定 > 注册表顶层默认(model_id) > models[0] > cfg.model。
                # 教训(cv-163/166): 各层各自兜底 → 实际执行模型与 UI 展示不一致。
                model = (conv_model
                         or (cfg.get("model_id") or "")
                         or (model_names[0] if model_names else "")
                         or cfg.get("model") or "")
                return {"executorId": eid,
                        "executorType": e.get("type") or "",
                        "executorConfig": {
                            "model": cfg.get("model") or "",
                            "base_port": cfg.get("base_port"),
                            "auto_start": cfg.get("auto_start"),
                            "base_url": cfg.get("base_url") or cfg.get("serve_url") or "",
                            "opencode_bin": cfg.get("opencode_bin") or "",
                            "node_bin": cfg.get("node_bin") or "",
                            "sidecar_script": cfg.get("sidecar_script")
                                or _default_sidecar_path(),
                            "provider_id": cfg.get("provider_id") or "",
                            "model_id": cfg.get("model_id") or "",
                            "api_key": cfg.get("api_key") or "",
                            "max_iterations": cfg.get("max_iterations"),
                            "arch_url": cfg.get("arch_url") or "",
                            "codex_bin": cfg.get("codex_bin") or "",
                            "codex_home": cfg.get("codex_home") or "",
                            "approval_policy": cfg.get("approval_policy") or "",
                            "sandbox_mode": cfg.get("sandbox_mode") or "",
                            "turnTimeout": cfg.get("turnTimeout"),
                            "stallSec": cfg.get("stallSec"),
                            # cv-158 修复: models/permission/mcp_servers 曾被丢弃——
                            # cline 按作业换模(_resolve_model)与 opencode MCP 全依赖它们
                            "models": cfg.get("models") or [],
                            "permission": cfg.get("permission") or "",
                            "rulesMd": cfg.get("rulesMd") or "",
                            "mcp_servers": cfg.get("mcp_servers") or {},
                        },
                        "model": model,
                        "basePort": cfg.get("base_port"),
                        "autoStart": cfg.get("auto_start"),
                        "baseUrl": cfg.get("base_url") or cfg.get("serve_url") or ""}
    except Exception:  # noqa: BLE001
        pass
    return None
