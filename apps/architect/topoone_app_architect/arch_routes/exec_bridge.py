"""执行作业桥接泵(exec_bridge)——architect 会话 ↔ runner 实施作业(多实例)。

生命周期重构 v2:
- 多作业: 会话可并行多个外调作业; 账本 jobs[](conv.meta) 为唯一终态真相,
  runner _JOBS 仅运行态(重启即失 → lost 对账)
- workState 聚合: 存在非终态作业 → 会话 running(输入锁定); 全部终态 → architect
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
POLL_INTERVAL = 2.5
_MAX_CONSECUTIVE_ERR = 5
_TERMINAL = ("done", "failed", "stopped", "lost")

# conv_id → {jobId → pump task} 注册表(进程内; 断电由 lost 对账兜底)
_PUMPS: Dict[str, Dict[str, asyncio.Task]] = {}


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


def is_running(conv_id: str) -> bool:
    return bool([j for j in jobs_of(conv_id) if (j.get("status") or "") not in _TERMINAL])


def waiting_job(conv_id: str) -> Optional[dict]:
    """最近一个 waiting_input 作业(「继续执行」的交回目标)。"""
    for j in reversed(jobs_of(conv_id)):
        if j.get("status") == "waiting_input":
            return j
    return None


# ── 会话消息 ──

def _append(conv_id: str, role: str, content: str, msg_meta: Optional[dict] = None,
            project_id: str = "") -> None:
    payload = {
        "id": store.next_id("m"), "conversationId": conv_id, "role": role,
        "time": _ts(), "content": content, "projectId": project_id,
    }
    if msg_meta:
        payload["meta"] = json.dumps(msg_meta, ensure_ascii=False)
    store.ConversationsStore.append_message(payload)
    try:
        store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
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


# ── 互斥引擎(裁决#1/#2/#9: 声明边界 + 组件 KB 口径 + 冲突拒绝) ──

def _resolve_boundary_files(rid: str, root: str, project: Optional[str]) -> List[str]:
    """规约边界 → 文件/目录前缀集合(文件级统一口径; 组件经 KB 解析为文件集)。"""
    from .req_agent import parse_scope_files
    snap = (store.RequirementsStore.spec_active(rid or "") or {}).get("snapshot") or {}
    scope = snap.get("allowedScope") or []
    files = set(parse_scope_files(scope))
    comps = [str(x).strip()[5:] for x in scope
             if str(x or "").strip().startswith("comp:")]
    if comps:
        try:
            from .sem.engine import _component_file_map
            cfm = _component_file_map(root or "", project)
            for cid in comps:
                for f in cfm.get(cid) or []:
                    files.add(str(f).lstrip("./").rstrip("/"))
        except Exception as e:  # noqa: BLE001
            logger.debug("[exec-bridge] 组件边界解析失败: %s", e)
    return sorted(files)


def _check_mutex(conv: dict, root: str, boundary_files: List[str]) -> Optional[str]:
    """交托互斥校验: 与全局运行中作业的文件边界求交; readOnly 豁免。

    返回 None=通过; 冲突时返回说明文本。声明级互斥(越界写靠验收简报事后检测,
    裁决#2)。
    """
    running = _runner("/api/implement/running", timeout=8.0)
    if not running or not running.get("ok"):
        return None           # runner 不可达 → 无法校验(不阻塞, 风险自担)
    for j in running.get("jobs") or []:
        jb = j.get("boundaries") or {}
        if jb.get("readOnly"):
            continue
        if (j.get("root") or "") != (root or ""):
            continue           # 跨项目天然隔离
        theirs = set(str(x).lstrip("./").rstrip("/") for x in (jb.get("files") or []))
        clash = _files_intersect(boundary_files, theirs)
        if clash:
            return (f"操作边界冲突：与运行中作业 `{j.get('jobId')}`(分支 `{j.get('branch')}`)"
                    f" 的范围重叠于 {', '.join(clash[:5])}。"
                    "请等待其完成/停止，或修订规约边界后重试。")
    return None


def _files_intersect(a: List[str], b: List[str]) -> List[str]:
    """文件/目录前缀集合求交(目录前缀视为覆盖其下所有文件)。"""
    out = []
    for x in a:
        for y in list(b):
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                if x not in out:
                    out.append(x)
                break
    return out


# ── 生命周期 ──

def start_implement(conv: dict, instruction: str, executor_hint: Optional[dict] = None,
                    branch_name: str = "", spec_ver: int = 0) -> Any:
    """确认执行 → runner 建作业 + 账本登记 + 泵启动 + workState→running。"""
    from .execution import conv_root_project
    conv_id = conv["id"]
    if is_running(conv_id):
        return ("当前会话已有作业执行中（输入锁定）。请在会话信息面板停止作业，"
                "或等待回合结束后再启动新作业。")
    root, project = conv_root_project(conv)
    if not root:
        return "无法解析项目根(会话未绑定项目/需求)，无法启动作业。"
    rid = (conv.get("reqId") or "")
    branch = (branch_name or "").strip() or f"exec/{(rid or conv_id).replace('RQ-', 'rq').lower()}-{_ts() % 100000}"
    # 交托互斥校验(声明边界 × 全局运行作业)
    boundary_files = _resolve_boundary_files(rid, root, project)
    conflict = _check_mutex(conv, root, boundary_files)
    if conflict:
        return f"⛔ {conflict}"
    payload = {"root": root, "instruction": instruction, "branchName": branch,
               "boundaries": {"files": boundary_files, "components": [],
                              "readOnly": False}}
    for k_src, k_dst in (("model", "model"), ("basePort", "basePort"),
                         ("autoStart", "autoStart"), ("baseUrl", "baseUrl")):
        if executor_hint and executor_hint.get(k_src) not in (None, ""):
            payload[k_dst] = executor_hint[k_src]
    # 执行器分发(多类型 coding agent 适配): 角色 executorId → runner 选 TurnAdapter
    if executor_hint and executor_hint.get("executorId"):
        payload["executorId"] = executor_hint["executorId"]
        payload["executorType"] = executor_hint.get("executorType") or ""
        payload["executorConfig"] = executor_hint.get("executorConfig") or {}
    res = _runner("/api/implement", payload, timeout=20.0)
    if not res or not res.get("ok"):
        err = (res or {}).get("error") or "runner 服务不可达(:3458)"
        return (f"❌ 实施作业启动失败：{err}\n"
                "请检查 runner 服务与执行器(系统管理→执行器探活)后重试「执行方案」。")
    job_id = res["jobId"]
    _job_upsert(conv_id, {
        "jobId": job_id, "branch": res.get("branch") or branch,
        "worktree": res.get("worktree") or "", "specVer": spec_ver,
        "reqId": rid, "status": "running", "startedAt": _ts(),
        "changedFiles": [], "failReason": "", "lastAgentNote": "", "lastAgentTs": 0,
    })
    _start_pump(conv_id, job_id, rid)
    return (f"🚀 实施作业已启动\n"
            f"- 作业 `{job_id}`　规约 v{spec_ver or '?'}　分支 `{branch}`\n"
            f"- 交付：开发 + 单元测试 + 整体编译验收\n"
            f"- **会话输入已锁定**(作业执行中)；agent 提问/完成/报错时自动恢复对话。\n"
            f"- 需要 agent 继续时：回合结束后回复补充内容，发送「继续执行」转达。\n"
            f"- 停止作业请用会话信息面板的「停止作业」按钮。")


def job_input(conv_id: str, job_id: str, text: str) -> Dict[str, Any]:
    """增量回合: 用户补充打包交回等待中的作业(opencode session 多轮保持)。"""
    res = _runner(f"/api/implement/{job_id}/input", {"text": text[:12000]}, 15.0)
    if res and res.get("ok"):
        # 泵在 waiting_input 期间持续轮询(仅终态退出)——无需重启
        _job_upsert(conv_id, {"jobId": job_id, "status": "running"})
        return {"ok": True}
    return {"ok": False, "error": (res or {}).get("error") or "runner 不可达"}


def stop(conv_id: str, reason: str = "") -> str:
    """UI 停止按钮(REST): 结束全部运行中作业(保留 worktree/分支)。"""
    jobs = [j for j in jobs_of(conv_id) if (j.get("status") or "") not in _TERMINAL]
    if not jobs:
        return "当前会话没有运行中的作业。"
    for j in jobs:
        _runner(f"/api/implement/{j['jobId']}/finish", {"keepWorktree": True}, timeout=30.0)
        _job_upsert(conv_id, {"jobId": j["jobId"], "status": "stopped",
                              "endedAt": _ts()})
    _cancel_pumps(conv_id)
    _aggregate_work_state(conv_id)
    return (f"🛑 已停止 {len(jobs)} 个作业。分支与改动已保留，"
            "可「查看差异」检视，或「执行方案」按当前规约重新执行。")


def diff_text(conv_id: str) -> str:
    """「查看差异」(自然语言/UI 按钮共用): 最近作业相对基线的 diff 摘要。"""
    jobs = jobs_of(conv_id)
    if not jobs:
        return "暂无作业记录。发送「执行方案」启动。"
    j = jobs[-1]
    d = _runner(f"/api/implement/{j['jobId']}/diff", timeout=30.0)
    if not (d or {}).get("ok"):
        return (f"作业 `{j['jobId']}`(分支 `{j.get('branch')}`)差异不可得"
                "(作业已从 runner 内存清除)。账本记录的改动文件：\n"
                + "\n".join(f"- `{f}`" for f in (j.get("changedFiles") or [])[:20]))
    files = "\n".join(f"- `{f}`" for f in (d.get("changedFiles") or [])[:30]) or "- (无)"
    return (f"**分支 `{j.get('branch')}` 相对基线的差异**"
            f"(+{d.get('addLines', 0)}/-{d.get('delLines', 0)} 行)\n{files}")


def reconcile_lost(conv_id: str) -> None:
    """lost 对账: 账本中非终态作业逐个查询 runner, 404 → lost(兜底重建路径)。"""
    changed = False
    for j in [x for x in jobs_of(conv_id) if (x.get("status") or "") not in _TERMINAL]:
        snap = _runner(f"/api/implement/{j['jobId']}?since=0", timeout=6.0)
        if snap is None:
            _job_upsert(conv_id, {"jobId": j["jobId"], "status": "lost",
                                  "endedAt": _ts(),
                                  "failReason": "runner 重启/作业句柄丢失"})
            changed = True
        elif snap.get("ok"):
            st = snap.get("status") or ""
            if st in _TERMINAL:
                _job_upsert(conv_id, {"jobId": j["jobId"], "status": st, "endedAt": _ts()})
                changed = True
    if changed:
        _aggregate_work_state(conv_id)
        _append(conv_id, "assistant",
                "⚠️ 作业状态对账完成(部分作业因服务重启丢失句柄→lost)。"
                "「执行方案」重试将自动附带前情简报。")


# ── 泵(纯下行) ──

def _start_pump(conv_id: str, job_id: str, rid: str) -> None:
    tasks = _PUMPS.setdefault(conv_id, {})
    old = tasks.get(job_id)
    if old and not old.done():
        return
    tasks[job_id] = asyncio.create_task(_pump(conv_id, job_id, rid))


def _cancel_pumps(conv_id: str) -> None:
    for t in _PUMPS.pop(conv_id, {}).values():
        t.cancel()


async def _pump(conv_id: str, job_id: str, rid: str) -> None:
    """下行事件 → 会话消息; 终态落账本 + workState 聚合 + 验收简报。"""
    logger.info("[exec-bridge] pump start conv=%s job=%s", conv_id, job_id)
    errs = 0
    last_seq = 0
    try:
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            snap = await asyncio.to_thread(
                _runner, f"/api/implement/{job_id}?since={last_seq}", None, 12.0)
            if snap is None:
                errs += 1
                if errs >= _MAX_CONSECUTIVE_ERR:
                    _job_upsert(conv_id, {"jobId": job_id, "status": "lost",
                                          "endedAt": _ts(),
                                          "failReason": "runner 连续不可达"})
                    _append(conv_id, "assistant",
                            "⚠️ 与作业失去联系(runner 不可达)——已记为 lost。"
                            "「执行方案」重试会自动附上前情简报。")
                    return
                continue
            errs = 0
            if not snap.get("ok"):
                # 作业不在 runner(404) → lost
                _job_upsert(conv_id, {"jobId": job_id, "status": "lost",
                                      "endedAt": _ts(), "failReason": "作业句柄丢失(runner 重启?)"})
                _append(conv_id, "assistant",
                        "⚠️ 作业句柄已丢失(runner 重启)——已记为 lost。"
                        "「执行方案」重试将自动附前情简报。")
                return
            pid = (store.ConversationsStore.get(conv_id) or {}).get("projectId") or ""
            for ev in snap.get("events") or []:
                last_seq = max(last_seq, ev.get("seq", 0))
                kind = ev.get("kind") or ""
                if kind in ("user_input", "session_ready"):
                    continue
                text = (ev.get("text") or "").strip()
                if kind == "input_required":
                    clean = text.replace("[[NEED_INPUT]]", "").strip() or "(等待你的输入)"
                    _append(conv_id, "assistant",
                            f"⏸ **执行工程师需要你的输入**（作业 `{job_id[:12]}…`）\n\n{clean}\n\n"
                            "回复补充内容后发送「**继续执行**」转达；停止请用会话信息面板按钮。",
                            msg_meta={"jobId": job_id, "kind": "job_input"})
                    _job_upsert(conv_id, {"jobId": job_id, "status": "waiting_input",
                                          "lastAgentNote": clean[:500], "lastAgentTs": _ts()})
                elif kind == "done":
                    clean = text.replace("[[IMPLEMENT_DONE]]", "").strip()
                    changed = ev.get("changedFiles") or []
                    _job_upsert(conv_id, {"jobId": job_id, "status": "done",
                                          "endedAt": _ts(), "changedFiles": changed,
                                          "lastAgentNote": clean[:500], "lastAgentTs": _ts()})
                    brief = _acceptance_brief(conv_id, rid, changed)
                    files = ("\n".join(f"- `{f}`" for f in changed[:20])
                             if changed else "- (无变更文件)")
                    _append(conv_id, "assistant",
                            f"✅ **作业完成**（分支 `{(jobs_of(conv_id)[-1] or {}).get('branch', '')}`）\n\n"
                            f"{clean}\n\n**变更文件**：\n{files}\n\n---\n**验收简报**\n{brief}\n\n"
                            "请验收：点本消息下方「验收」查看差异并判定；"
                            "通过=需求标记已完成；需返工=回复意见后「继续执行」或调整规约。",
                            msg_meta={"jobId": job_id, "kind": "job_done",
                                      "branch": (jobs_of(conv_id)[-1] or {}).get("branch", "")})
                elif kind == "failed":
                    _job_upsert(conv_id, {"jobId": job_id, "status": "failed",
                                          "endedAt": _ts(), "failReason": text[:400],
                                          "lastAgentTs": _ts()})
                    _append(conv_id, "assistant",
                            f"❌ 执行作业失败：{text}\n分支已保留。"
                            "排查后「执行方案」重试(自动附前情简报)。",
                            msg_meta={"jobId": job_id, "kind": "job_failed"})
                elif kind in ("aborted", "finished"):
                    _append(conv_id, "assistant", f"ℹ️ {text}")
                elif text:
                    _append(conv_id, "assistant", text,
                            msg_meta={"jobId": job_id, "kind": "job_progress"})
                    _job_upsert(conv_id, {"jobId": job_id, "lastAgentTs": _ts()})
            status = snap.get("status") or ""
            if status in _TERMINAL:
                _job_upsert(conv_id, {"jobId": job_id, "status": status,
                                      "endedAt": _ts()})
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[exec-bridge] pump crashed conv=%s job=%s: %s", conv_id, job_id, e)
