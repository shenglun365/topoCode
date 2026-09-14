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
    # 库路由: 未显式给项目 → 从会话行取(消息必须与会话同库, 防主库孤儿)
    if not project_id:
        try:
            project_id = (store.ConversationsStore.get(conv_id) or {}).get("projectId") or ""
        except Exception:  # noqa: BLE001
            pass
    payload = {
        "id": store.next_id("m"), "conversationId": conv_id, "role": role,
        "time": _ts(), "content": content, "projectId": project_id,
        "agent": agent or "",
    }
    if msg_meta:
        payload["meta"] = json.dumps(msg_meta, ensure_ascii=False)
    store.ConversationsStore.append_message(payload)
    try:
        store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
    except Exception:  # noqa: BLE001
        pass
    # 实时推送: 前端(SSE)收到后按会话刷新。
    try:
        from . import ws_events
        ws_events.publish({"type": "conv-message", "conversationId": conv_id,
                           "msgId": payload["id"], "agent": agent or "",
                           "kind": (msg_meta or {}).get("kind", "")})
    except Exception:  # noqa: BLE001
        pass
# ── 边界/验收简报 ──

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
_TASK_ACTIVE = ("pending_confirm", "running", "waiting_input")


def propose_task(conv: dict, title: str, instruction: str,
                 executor_hint: Optional[dict] = None) -> dict:
    """轻门禁入口: 建任务(pending_confirm) + 任务卡消息落统一流。

    由 LLM 工具 task.propose / architect 编排调用; 用户确认(REST/卡片按钮)
    后 confirm_task 真正拉起 runner。"""
    conv_id = conv["id"]
    _pid = (conv or {}).get("projectId") or (conv or {}).get("project_id") or ""
    etype = (executor_hint or {}).get("executorType") or "opencode"
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
        "status": "pending_confirm",
        "executorType": etype,
        "executorId": (executor_hint or {}).get("executorId") or "",
        "specVer": _spec_ver,
    })
    _append(conv_id, "assistant",
            f"📋 **任务待确认**\n\n**{task['title']}**\n执行器 `{etype}`\n\n"
            + instruction[:2000]
            + "\n\n---\n确认后开始执行; 可取消或要求 architect 调整。",
            msg_meta={"kind": "task_card", "taskId": task["id"]},
            project_id=_pid)
    _publish_task(conv_id, task)
    return task


def confirm_task(task_id: str) -> dict:
    """用户确认任务卡 → runner 建作业 + 泵启动(pending_confirm→running)。"""
    task = store.TasksStore.get(task_id)
    if not task:
        return {"ok": False, "error": "task-not-found"}
    if (task.get("status") or "") != "pending_confirm":
        return {"ok": False, "error": f"task-status={task.get('status')}"}
    conv = store.ConversationsStore.get(task["conversationId"])
    if not conv:
        return {"ok": False, "error": "conv-not-found"}
    from .execution import conv_root_project
    conv_id = conv["id"]
    # 同会话活跃任务互斥(一次一个 subagent 回合)
    other = next((t for t in store.TasksStore.of_conv(conv_id)
                  if t["id"] != task_id and t.get("status") in ("running", "waiting_input")), None)
    if other:
        return {"ok": False,
                "error": f"另一任务执行中({other['title']}), 停止或等待其结束"}
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
    hint = executor_hint_by_id(task.get("executorId") or "", conv) or {}
    for k in ("model", "basePort", "autoStart", "baseUrl"):
        v = hint.get(k)
        if v not in (None, ""):
            payload[k] = v
    _etype = hint.get("executorType") or task.get("executorType") or "opencode"
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
    agent = task.get("executorType") or "opencode"
    pid = (conv or {}).get("projectId") or ""
    _append(conv_id, "user",
            f"🚀 **{task['title']}** 启动（`{res['jobId']}` 分支 `{branch}`）",
            msg_meta={"kind": "task_start", "taskId": task_id}, project_id=pid)
    _start_task_pump(conv_id, task_id, res["jobId"], rid, agent)
    t = store.TasksStore.get(task_id) or {}
    _publish_task(conv_id, t)
    return {"ok": True, "task": t}


def task_set_executor(task_id: str, executor_type: str) -> Optional[dict]:
    """设定任务执行器(cline/opencode/codex)。仅 pending_confirm 可换——
    运行中引擎已固化(换=新任务); 返回更新后任务行(不可换返回 None)。"""
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") != "pending_confirm":
        return None
    if executor_type not in ("cline", "opencode", "codex"):
        return None
    return store.TasksStore.update(task_id, {"executor_type": executor_type})


def task_input(task_id: str, text: str) -> Dict[str, Any]:
    """用户回复 → 转达 subagent(waiting_input 立即; running 排队续跑)。"""
    task = store.TasksStore.get(task_id)
    if not task or (task.get("status") or "") not in ("waiting_input", "running"):
        return {"ok": False, "error": "task-not-active"}
    res = _runner(f"/api/implement/{task.get('runnerJobId')}/input",
                  {"text": text[:12000]}, 15.0)
    if res and res.get("ok"):
        if (task.get("status") or "") == "waiting_input":
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
    if (task.get("status") or "") == "pending_confirm":
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
        if (t.get("status") or "") in ("running", "waiting_input"):
            return t
    for t in reversed(ts):
        if (t.get("status") or "") == "pending_confirm":
            return t
    return None


def _publish_task(conv_id: str, task: dict) -> None:
    """任务状态变更 → SSE 单通道广播(前端 TaskCard/过滤器响应)。"""
    try:
        from . import ws_events
        ws_events.publish({"type": "task", "conversationId": conv_id,
                           "task": task})
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


def _start_task_pump(conv_id: str, task_id: str, job_id: str, rid: str,
                     agent: str) -> None:
    jobs = _TASK_PUMPS.setdefault(conv_id, {})
    old = jobs.get(job_id)
    if old and not old.done():
        return
    jobs[job_id] = asyncio.create_task(
        _task_pump(conv_id, task_id, job_id, rid, agent))


def _task_ctx(conv_id: str, task_id: str, job_id: str, rid: str, agent: str) -> dict:
    conv = store.ConversationsStore.get(conv_id) or {}
    return {"convId": conv_id, "taskId": task_id, "jobId": job_id, "rid": rid,
            "pid": conv.get("projectId") or "", "agent": agent}


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
        store.TasksStore.update(task_id, {"status": "waiting_input"})
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
        prog = {"toolCount": int(ev.get("toolCount") or 0),
                "msgCount": int(ev.get("msgCount") or 0), "at": _ts()}
        store.TasksStore.set_progress(task_id, prog)
        try:
            from . import ws_events
            ws_events.publish({"type": "progress", "conversationId": conv_id,
                               "taskId": task_id, **prog})
        except Exception:  # noqa: BLE001
            pass
    elif kind in ("aborted", "finished"):
        _append(conv_id, "assistant", f"ℹ️ {text}", project_id=pid, agent=agent)
    elif text:
        _append(conv_id, "assistant", text,
                msg_meta={"kind": "task_progress", "taskId": task_id},
                project_id=pid, agent=agent)


async def _task_pump(conv_id: str, task_id: str, job_id: str, rid: str,
                     agent: str) -> None:
    """任务泵: 骨架委托 agent.execution.pumps(唯一实现), 事件走 task 路径。"""
    from .agent.execution import pumps as _pumps
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
                model = (conv_model
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
                        },
                        "model": model,
                        "basePort": cfg.get("base_port"),
                        "autoStart": cfg.get("auto_start"),
                        "baseUrl": cfg.get("base_url") or cfg.get("serve_url") or ""}
    except Exception:  # noqa: BLE001
        pass
    return None
