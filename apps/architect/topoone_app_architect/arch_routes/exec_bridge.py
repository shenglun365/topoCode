"""执行作业桥接泵(exec_bridge)——architect 会话 ↔ runner 实施作业(多实例)。

生命周期重构 v2:
- 多作业: 会话可并行多个外调作业; 账本 jobs[](conv.meta) 为唯一终态真相,
  runner _JOBS 仅运行态(重启即失 → lost 对账)
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


def _meta_dict_of(conv: dict) -> dict:
    meta = (conv or {}).get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except (TypeError, ValueError):
            meta = {}
    return meta or {}


def _subsession_history_brief(sub_id: str, budget: int = 3000) -> str:
    """architect 代持(S4): 执行器无原生会话保持(session_ref 空)时,
    把子会话历史要点注入新作业 instruction——等效会话连续性。

    取最近 8 条消息(用户补充/agent 产出尾部), 每条截断, 总预算受控。
    """
    try:
        msgs = store.ConversationsStore.messages(sub_id, limit=200)[-8:]
    except Exception:  # noqa: BLE001
        return ""
    lines = []
    used = 0
    for m in reversed(msgs):                      # 近者优先
        role = "用户补充" if (m.get("role") or "") == "user" else "执行产出"
        c = (m.get("content") or "").strip()
        if not c or c.startswith("🚀"):
            continue
        frag = c[:400]
        if used + len(frag) > budget:
            frag = frag[: max(0, budget - used)]
        if not frag:
            break
        lines.append(f"[{role}] {frag}")
        used += len(frag)
        if used >= budget:
            break
    if not lines:
        return ""
    lines.reverse()
    return ("【会话历史简报(architect 代持——执行器无原生会话保持, 供你恢复上下文)】\n"
            + "\n".join(lines))


def _ensure_active_coding_session(conv: dict) -> str:
    """确保主会话有活跃 coding 子会话(无→新建; 指向失效→重建)。

    子会话 = 作业宿主(coding 自持上下文容器): 新建即清空上下文,
    切换/复活靠 session_ref。库路由与主会话同项目库。
    """
    conv_id = (conv or {}).get("id") or ""
    meta = _meta_dict_of(conv)
    active = meta.get("activeCodingSession") or ""
    if active:
        sub = store.ConversationsStore.get(active)
        if sub and (sub.get("parentConvId") or "") == conv_id \
                and (sub.get("status") or "active") == "active":
            return active
    pid = (conv or {}).get("projectId") or ""
    from . import ctx as _ctx
    tok = _ctx.set_project(pid) if pid else None
    try:
        sub = store.ConversationsStore.create({
            "kind": "coding", "projectId": pid,
            "reqId": (conv or {}).get("reqId") or "",
            "title": "coding 子会话",
            "executorId": (conv or {}).get("executorId") or "",
            "parentConvId": conv_id,
            "roles": ["architect"],
            "meta": {"createdFrom": conv_id, "createdAtTs": _ts()},
        })
    finally:
        if tok is not None:
            _ctx.reset_project(tok)
    meta["activeCodingSession"] = sub["id"]
    store.ConversationsStore.update(conv_id, {"meta": meta})
    return sub["id"]


def active_job(conv_id: str) -> Optional[dict]:
    """最近活跃作业(waiting_input|running)——coding 收件人定向投递目标。"""
    for j in reversed(jobs_of(conv_id)):
        if (j.get("status") or "") in ("waiting_input", "running"):
            return j
    return None


def running_role(conv_id: str) -> Optional[dict]:
    """running 归属推导: 活跃作业 → {role:'coding', executorId}; 无 → None(architect)。"""
    j = active_job(conv_id)
    if not j:
        return None
    return {"role": "coding", "executorId": j.get("executorId") or "opencode",
            "jobId": j.get("jobId") or "", "status": j.get("status") or ""}


def deliver_to_coding(conv_id: str, text: str) -> Dict[str, Any]:
    """双收件人: coding 方向定向投递。
    等待中(waiting_input)→立即转达开新回合; 回合执行中→runner 侧排队,
    回合结束自动续跑; 终态/无作业→错误提示。"""
    j = active_job(conv_id)
    if not j:
        return {"ok": False, "error": "no-active-job"}
    return job_input(conv_id, j["jobId"], text)


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


def _append_sub(parent_conv_id: str, sub_id: str, role: str, content: str,
                msg_meta: Optional[dict] = None, project_id: str = "") -> None:
    """子会话消息写入 + 主会话未读计数 bump(用户在 architect 视图时经
    Coding 入口 badge 感知, 不向主信息流双落全文——避免两种信息流混淆)。"""
    _append(sub_id, role, content, msg_meta=msg_meta, project_id=project_id)
    try:
        meta = _meta_dict_of(store.ConversationsStore.get(parent_conv_id) or {})
        meta["subUnread"] = int(meta.get("subUnread") or 0) + 1
        store.ConversationsStore.update(parent_conv_id, {"meta": meta})
        from . import ws_events
        ws_events.publish({"type": "sub-unread", "conversationId": parent_conv_id,
                           "count": meta["subUnread"]})
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
    """`/执行` → runner 建作业 + 账本登记 + 泵启动 + workState→running。"""
    from .execution import conv_root_project
    conv_id = conv["id"]
    if is_running(conv_id):
        return ("当前会话已有作业执行中(同一时间一个作业)。请在会话信息面板停止作业，"
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
               "projectId": project,
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
    # S3 子会话宿主: 作业挂活跃 coding 子会话(sessionRef 复活执行器原生会话)
    sub_id = _ensure_active_coding_session(store.ConversationsStore.get(conv_id) or conv)
    sub_row = store.ConversationsStore.get(sub_id) or {}
    if sub_row.get("sessionRef"):
        payload["sessionRef"] = sub_row["sessionRef"]
    else:
        # S4 代持: 无原生会话可复活(无状态执行器/会话丢失) → 子会话历史注入
        brief = _subsession_history_brief(sub_id)
        if brief:
            payload["instruction"] = brief + "\n\n---\n\n" + payload["instruction"]

    # S4 回合超时配置下发(执行器注册表 config → runner 看门狗参数)
    _cfg = (executor_hint or {}).get("executorConfig") or {}
    for k in ("turnTimeout", "stallSec"):
        v = _cfg.get(k)
        if isinstance(v, (int, float)) and v > 0:
            payload[k] = float(v)

    res = _runner("/api/implement", payload, timeout=20.0)
    if not res or not res.get("ok"):
        err = (res or {}).get("error") or "runner 服务不可达(:3458)"
        return (f"❌ 实施作业启动失败：{err}\n"
                "请检查 runner 服务与执行器(系统管理→执行器探活)后重试 `/执行`。")
    job_id = res["jobId"]
    _job_upsert(conv_id, {
        "jobId": job_id, "branch": res.get("branch") or branch,
        "worktree": res.get("worktree") or "", "specVer": spec_ver,
        "reqId": rid, "status": "running", "startedAt": _ts(),
        "executorId": (executor_hint or {}).get("executorId") or "",
        "subSessionId": sub_id,
        "changedFiles": [], "failReason": "", "lastAgentNote": "", "lastAgentTs": 0,
    })
    _pid = (conv or {}).get("projectId") or ""
    _append(sub_id, "user",
            f"🚀 作业启动（`{job_id}` 规约 v{spec_ver or '?'} 分支 `{branch}`）\n\n"
            + str(payload.get("instruction") or instruction)[:4000],
            msg_meta={"jobId": job_id, "kind": "job_start"}, project_id=_pid)
    _start_pump(conv_id, job_id, rid)
    return (f"🚀 实施作业已启动\n"
            f"- 作业 `{job_id}`　规约 v{spec_ver or '?'}　分支 `{branch}`\n"
            f"- 交付：开发 + 单元测试 + 整体编译验收\n"
            f"- 对话不受锁定：输入框可切换收件人（architect 继续分析 / coding 转达作业）。\n"
            f"- 发给 coding 的补充：等待中→立即转达；执行回合中→自动排队续跑。\n"
            f"- 停止作业请用会话信息面板的「停止作业」按钮。")


def job_input(conv_id: str, job_id: str, text: str) -> Dict[str, Any]:
    """增量回合: 用户补充打包交回等待中的作业(opencode session 多轮保持)。"""
    res = _runner(f"/api/implement/{job_id}/input", {"text": text[:12000]}, 15.0)
    if res and res.get("ok"):
        # 泵在 waiting_input 期间持续轮询(仅终态退出)——无需重启
        _job_upsert(conv_id, {"jobId": job_id, "status": "running"})
        return {"ok": True, "queued": bool(res.get("queued"))}
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
            "可「查看差异」检视，或 `/执行` 按当前规约重新执行。")


def diff_text(conv_id: str) -> str:
    """「查看差异」(自然语言/UI 按钮共用): 最近作业相对基线的 diff 摘要。"""
    jobs = jobs_of(conv_id)
    if not jobs:
        return "暂无作业记录。发送 `/执行` 启动。"
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
                "`/执行` 重试将自动附带前情简报。")


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


def _pump_ctx(conv_id: str, job_id: str, rid: str) -> dict:
    """泵上下文: 子会话宿主/库路由等每轮可刷新的派生量。"""
    pid = (store.ConversationsStore.get(conv_id) or {}).get("projectId") or ""
    sub_id = ""
    jb = next((j for j in jobs_of(conv_id) if j.get("jobId") == job_id), None)
    if jb and jb.get("subSessionId"):
        sub_id = jb["subSessionId"]
    return {"convId": conv_id, "jobId": job_id, "rid": rid, "pid": pid,
            "subId": sub_id, "target": sub_id or conv_id}


def _handle_pump_event(ev: dict, ctx: dict) -> None:
    """单事件 → 会话消息/账本(WS 推送与轮询校准共用)。"""
    conv_id, job_id = ctx["convId"], ctx["jobId"]
    sub_id, target, pid = ctx["subId"], ctx["target"], ctx["pid"]
    kind = ev.get("kind") or ""
    if kind in ("user_input", "session_ready"):
        return
    text = (ev.get("text") or "").strip()
    if kind == "input_required":
        clean = text.replace("[[NEED_INPUT]]", "").strip() or "(等待你的输入)"
        # 信息流分离(裁决): 等待输入只落 coding 子会话全文——主会话不双落,
        # 由未读 badge + 作业状态 chip(等待回复)提示, 点 Coding 角色切子会话流。
        if sub_id:
            _append_sub(conv_id, sub_id, "assistant",
                        f"⏸ **执行工程师需要你的输入**\n\n{clean}",
                        msg_meta={"jobId": job_id, "kind": "job_input_sub"}, project_id=pid)
        else:
            _append(conv_id, "assistant",
                    f"⏸ **执行工程师需要你的输入**（作业 `{job_id[:12]}…`）\n\n{clean}\n\n"
                    "回复补充内容后以 coding 收件人发送(或 `/继续`)转达；停止请用会话信息面板按钮。",
                    msg_meta={"jobId": job_id, "kind": "job_input"}, project_id=pid)
        _job_upsert(conv_id, {"jobId": job_id, "status": "waiting_input",
                              "lastAgentNote": clean[:500], "lastAgentTs": _ts()})
    elif kind == "done":
        clean = text.replace("[[IMPLEMENT_DONE]]", "").strip()
        changed = ev.get("changedFiles") or []
        _job_upsert(conv_id, {"jobId": job_id, "status": "done",
                              "endedAt": _ts(), "changedFiles": changed,
                              "lastAgentNote": clean[:500], "lastAgentTs": _ts()})
        brief = _acceptance_brief(conv_id, ctx["rid"], changed)
        files = ("\n".join(f"- `{f}`" for f in changed[:20])
                 if changed else "- (无变更文件)")
        _append(conv_id, "assistant",
                f"✅ **作业完成**（分支 `{(jobs_of(conv_id)[-1] or {}).get('branch', '')}`）\n\n"
                f"{clean}\n\n**变更文件**：\n{files}\n\n---\n**验收简报**\n{brief}\n\n"
                "请验收：点本消息下方「验收」查看差异并判定；"
                "通过=需求标记已完成；需返工=回复意见后「继续执行」或调整规约。",
                msg_meta={"jobId": job_id, "kind": "job_done",
                          "branch": (jobs_of(conv_id)[-1] or {}).get("branch", "")})
        if sub_id:
            _append_sub(conv_id, sub_id, "assistant",
                        f"✅ **作业完成**（分支 `{(jobs_of(conv_id)[-1] or {}).get('branch', '')}`）\n\n{clean}",
                        msg_meta={"jobId": job_id, "kind": "job_done_sub"}, project_id=pid)
    elif kind == "failed":
        _job_upsert(conv_id, {"jobId": job_id, "status": "failed",
                              "endedAt": _ts(), "failReason": text[:400],
                              "lastAgentTs": _ts()})
        _append(conv_id, "assistant",
                f"❌ 执行作业失败：{text}\n分支已保留。"
                "排查后 `/执行` 重试(自动附前情简报)。",
                msg_meta={"jobId": job_id, "kind": "job_failed"})
        if sub_id:
            _append_sub(conv_id, sub_id, "assistant",
                        f"❌ 执行作业失败：{text}",
                        msg_meta={"jobId": job_id, "kind": "job_failed_sub"}, project_id=pid)
    elif kind == "progress":
        # 执行进展(工具调用计数): 不落消息(防刷屏)——账本留痕 + SSE 实时推
        # 前端(主视图 ▶ chip 与 coding 视图进展行共享)。
        prog = {"toolCount": int(ev.get("toolCount") or 0),
                "msgCount": int(ev.get("msgCount") or 0),
                "at": _ts()}
        _job_upsert(conv_id, {"jobId": job_id, "progress": prog,
                              "lastAgentTs": _ts()})
        try:
            from . import ws_events
            ws_events.publish({"type": "job-progress", "conversationId": conv_id,
                               "subConversationId": sub_id, "jobId": job_id, **prog})
        except Exception:  # noqa: BLE001
            pass
    elif kind in ("aborted", "finished"):
        _append(conv_id, "assistant", f"ℹ️ {text}")
    elif text:
        if sub_id:
            _append_sub(conv_id, sub_id, "assistant", text,
                        msg_meta={"jobId": job_id, "kind": "job_progress"}, project_id=pid)
        else:
            _append(target, "assistant", text,
                    msg_meta={"jobId": job_id, "kind": "job_progress"}, project_id=pid)
        _job_upsert(conv_id, {"jobId": job_id, "lastAgentTs": _ts()})


async def _ws_connect(job_id: str, since: int):
    """连接 runner 作业事件实时订阅面(失败返回 None——泵降级轮询)。"""
    try:
        import websockets
        url = (RUNNER_BASE.replace("https://", "wss://").replace("http://", "ws://")
               + f"/api/implement/{job_id}/events?since={since}")
        return await asyncio.wait_for(
            websockets.connect(url, open_timeout=3.0, max_size=4 * 1024 * 1024), 4.0)
    except Exception:  # noqa: BLE001
        return None


_WS_IDLE_SEC = 10.0        # 订阅空闲窗口(超时→snapshot 校准一轮, 保留 lost/终态判定)
_WS_RETRY_GAP = 4          # 订阅失败后的重试间隔(轮询轮)


async def _pump(conv_id: str, job_id: str, rid: str) -> None:
    """上行通道(执行器能力自适应): WS 实时订阅优先, 轮询校准兜底。

    - 订阅模式: runner 事件即产即推(opencode SSE/codex notifications 等实时
      执行器端到端即时; 轮询型执行器仍按其已知时点推送);
    - 校准/降级: 订阅不可达或空闲超时 → snapshot 轮询(补漏事件+终态确认+
      连续不可达 lost 判定), 与订阅共用事件处理(seq 去重)。
    - 事件粒度: 回合级(input_required/done/failed/progress)。流式 token 扩展
      预留: runner 侧 adapter 逐段 emit("text") → WS 即推 → _handle_pump_event
      原生落 job_progress 消息, 本层与架构零改动(见 runner implement.emit
      与 turn_adapter._sse_loop 注释)。
    """
    logger.info("[exec-bridge] pump start conv=%s job=%s", conv_id, job_id)
    errs = 0
    last_seq = 0
    ws = None
    ws_gap = 0
    try:
        while True:
            # ① 实时订阅优先
            if ws is None and ws_gap <= 0:
                ws = await _ws_connect(job_id, last_seq)
                if ws is None:
                    ws_gap = _WS_RETRY_GAP
                    await asyncio.sleep(POLL_INTERVAL)
            if ws is not None:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=_WS_IDLE_SEC)
                    ev = json.loads(raw)
                    if int(ev.get("seq") or 0) <= last_seq:
                        continue
                    last_seq = int(ev.get("seq") or 0)
                    _handle_pump_event(ev, _pump_ctx(conv_id, job_id, rid))
                    if ev.get("kind") in ("done", "failed"):
                        return
                    continue
                except Exception:  # noqa: BLE001
                    try:
                        await ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ws = None
                    ws_gap = 1     # 空闲超时/断流 → 校准一轮后再重连
            else:
                ws_gap = max(0, ws_gap - 1)
                await asyncio.sleep(POLL_INTERVAL)

            # ② snapshot 校准(订阅空闲/降级共用): 补漏 + 终态确认 + lost
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
                            "`/执行` 重试会自动附上前情简报。")
                    return
                continue
            errs = 0
            if not snap.get("ok"):
                _job_upsert(conv_id, {"jobId": job_id, "status": "lost",
                                      "endedAt": _ts(), "failReason": "作业句柄丢失(runner 重启?)"})
                _append(conv_id, "assistant",
                        "⚠️ 作业句柄已丢失(runner 重启)——已记为 lost。"
                        "`/执行` 重试将自动附前情简报。")
                return
            ctx = _pump_ctx(conv_id, job_id, rid)
            sub_id = ctx["subId"]
            sid = (snap.get("sessionId") or "").strip()
            if sid and sub_id:
                try:
                    sub_row = store.ConversationsStore.get(sub_id) or {}
                    if (sub_row.get("sessionRef") or "") != sid:
                        store.ConversationsStore.update(sub_id, {"sessionRef": sid})
                except Exception:  # noqa: BLE001
                    pass
            for ev in snap.get("events") or []:
                if int(ev.get("seq") or 0) <= last_seq:
                    continue
                last_seq = max(last_seq, int(ev.get("seq") or 0))
                _handle_pump_event(ev, ctx)
            status = snap.get("status") or ""
            if status in _TERMINAL:
                _job_upsert(conv_id, {"jobId": job_id, "status": status,
                                      "endedAt": _ts()})
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[exec-bridge] pump crashed conv=%s job=%s: %s", conv_id, job_id, e)


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
    task = store.TasksStore.create({
        "conversationId": conv_id,
        "projectId": _pid,
        "reqId": (conv or {}).get("reqId") or "",
        "title": (title or "").strip()[:120] or "实施任务",
        "instruction": instruction,
        "status": "pending_confirm",
        "executorType": etype,
        "executorId": (executor_hint or {}).get("executorId") or "",
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
    payload = {"root": root, "instruction": _task_instruction(task),
               "branchName": branch, "projectId": project,
               "boundaries": {"files": boundary_files, "components": [],
                              "readOnly": False}}
    hint = executor_hint_by_id(task.get("executorId") or "", conv) or {}
    for k in ("model", "basePort", "autoStart", "baseUrl"):
        v = hint.get(k)
        if v not in (None, ""):
            payload[k] = v
    if hint.get("executorId"):
        payload["executorId"] = hint["executorId"]
        payload["executorType"] = hint.get("executorType") or task.get("executorType") or "opencode"
        payload["executorConfig"] = hint.get("executorConfig") or {}
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
    _cancel_pumps(task["conversationId"])
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

    与旧 _handle_pump_event 并存(P2 清退旧路径); 差异:
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
    """任务泵: 复用 WS 订阅+轮询校准骨架(与 _pump 同构, 事件走 task 路径)。"""
    logger.info("[exec-bridge] task-pump start conv=%s task=%s job=%s",
                conv_id, task_id, job_id)
    errs = 0
    last_seq = 0
    ws = None
    ws_gap = 0
    try:
        while True:
            if ws is None and ws_gap <= 0:
                ws = await _ws_connect(job_id, last_seq)
                if ws is None:
                    ws_gap = _WS_RETRY_GAP
                    await asyncio.sleep(POLL_INTERVAL)
            if ws is not None:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=_WS_IDLE_SEC)
                    ev = json.loads(raw)
                    if int(ev.get("seq") or 0) <= last_seq:
                        continue
                    last_seq = int(ev.get("seq") or 0)
                    _handle_task_event(ev, _task_ctx(conv_id, task_id, job_id, rid, agent))
                    if ev.get("kind") in ("done", "failed"):
                        return
                    continue
                except Exception:  # noqa: BLE001
                    try:
                        await ws.close()
                    except Exception:  # noqa: BLE001
                        pass
                    ws = None
                    ws_gap = 1
            else:
                ws_gap = max(0, ws_gap - 1)
                await asyncio.sleep(POLL_INTERVAL)

            snap = await asyncio.to_thread(
                _runner, f"/api/implement/{job_id}?since={last_seq}", None, 12.0)
            if snap is None:
                errs += 1
                if errs >= _MAX_CONSECUTIVE_ERR:
                    store.TasksStore.finish(task_id, "failed", "runner 连续不可达")
                    _append(conv_id, "assistant",
                            f"⚠️ 任务「{(store.TasksStore.get(task_id) or {}).get('title', '')}」"
                            "与 runner 失去联系, 已记为失败。",
                            msg_meta={"kind": "task_failed", "taskId": task_id},
                            agent=agent)
                    _publish_task(conv_id, store.TasksStore.get(task_id) or {})
                    return
                continue
            errs = 0
            if not snap.get("ok"):
                store.TasksStore.finish(task_id, "failed", "作业句柄丢失(runner 重启?)")
                _publish_task(conv_id, store.TasksStore.get(task_id) or {})
                return
            ctx = _task_ctx(conv_id, task_id, job_id, rid, agent)
            sid = (snap.get("sessionId") or "").strip()
            if sid and (store.TasksStore.get(task_id) or {}).get("sessionRef") != sid:
                try:
                    store.TasksStore.update(task_id, {"session_ref": sid})
                except Exception:  # noqa: BLE001
                    pass
            for ev in snap.get("events") or []:
                if int(ev.get("seq") or 0) <= last_seq:
                    continue
                last_seq = max(last_seq, int(ev.get("seq") or 0))
                _handle_task_event(ev, ctx)
            if (snap.get("status") or "") in ("done", "failed", "stopped"):
                # runner 终态(含 stopped→cancelled 语义); 事件流已落终态, 兜底校准
                st = snap.get("status") or ""
                t = store.TasksStore.get(task_id) or {}
                if (t.get("status") or "") not in _TASK_TERMINAL:
                    store.TasksStore.finish(
                        task_id, "cancelled" if st == "stopped" else st)
                    _publish_task(conv_id, store.TasksStore.get(task_id) or {})
                return
    except asyncio.CancelledError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("[exec-bridge] task-pump crashed conv=%s task=%s: %s",
                       conv_id, task_id, e)
def _task_instruction(task: dict, prior_brief: str = "") -> str:
    """任务指令组装: task.instruction(architect 整理) 为正文 + 绑定需求规约
    补充(边界/验收) + 工作环境/DoD 系统段(确定性注入, 不依赖 LLM)。

    prior_brief: 前情简报(重试时注入)。
    """
    rid = task.get("reqId") or ""
    r = store.RequirementsStore.get(rid) or {} if rid else {}
    active = store.RequirementsStore.spec_active(rid) or {} if rid else {}
    a = (active.get("snapshot") or {}) if rid else {}
    if not a and rid:
        a = r.get("analysis") or {}
    parts = [f"# 实施任务：{task.get('title') or '任务'}"
             + (f"（{rid} · 规约 v{active.get('ver') or '?'}）" if rid else "")]
    body = str(task.get("instruction") or "").strip()
    if prior_brief:
        parts.append("## 前情简报(上次作业)\n" + prior_brief)
    # 方案兜底: designMd 未细化时用需求正文(requirementMd/desc)——agent 永远拿到实质任务,
    # 不允许"只有标题+DoD"的空指令把作业打成 NEED_INPUT 空转(cv-140 教训)。
    if body:
        parts.append("## 任务上下文（architect 整理, 遵循执行）\n" + body)
    desc_text = str(a.get("desc") or r.get("desc") or "").strip()
    if body and not (a.get("designMd") or a.get("implementationPath")):
        pass   # 正文已给——不做空方案警告
    elif not (a.get("designMd") or a.get("implementationPath")):
        if desc_text:
            parts.append(
                "> ⚠️ 本规约未细化实现方案(仅需求正文)。请基于以下需求描述自行设计并实施,"
                "不确定处一次性集中提问, 不要每步暂停。\n\n## 需求描述\n" + desc_text)
        else:
            parts.append("> ⚠️ 本规约既无实现方案也无需求正文——若你无法从任务上下文推断目标, "
                         "请立即 [[NEED_INPUT]] 报告\"规约为空\", 不要猜测实施。")
    if a.get("functionalScope"):
        parts.append("## 需求目标\n" + "\n".join(f"- {x}" for x in a["functionalScope"]))
    parts.append(
        "## 工作环境(重要, 先读)\n"
        "- 你在项目源码仓库的**隔离 worktree 分支**执行, pwd 即源码树根——"
        "先浏览仓库(README/构建文件/目录结构)理解项目, 再动手。\n"
        "- 交付物一律**写入源码树**(新文件/修改/文档, git 分支内); "
        "**不要写系统路径**(/etc /usr /opt 等运行时部署位置)——环境搭建与部署"
        "由用户手工执行, 你提供文件与部署说明即可。\n"
        "- 环境类问题(sudo/依赖/编译工具)先自主查证仓库与 README; "
        "只对**需求歧义**集中一次性提问, 不要为环境搭建反复提问。")
    if a.get("designMd") or a.get("implementationPath"):
        parts.append("## 实现方案(遵循执行)\n"
                     + str(a.get("designMd") or a.get("implementationPath")))
    if a.get("allowedScope"):
        scope_lines = [str(x) for x in a["allowedScope"]]
        abs_paths = [s for s in scope_lines if s.strip().startswith("/")]
        if abs_paths:
            parts.append(
                "## 允许增删改\n" + "\n".join(f"- {x}" for x in scope_lines)
                + "\n> 注: 其中以 `/` 开头的是**运行时部署路径**(用户环境的目标位置)"
                "——请在源码树中创建对应文件(或等价物)并附部署说明, "
                "不要尝试直接写这些系统路径。")
        else:
            parts.append("## 允许增删改\n" + "\n".join(f"- {x}" for x in scope_lines))
    if a.get("forbiddenScope"):
        parts.append("## 一定不能动\n" + "\n".join(f"- {x}" for x in a["forbiddenScope"]))
    if a.get("acceptance"):
        parts.append("## 验收标准\n" + "\n".join(f"- {x}" for x in a["acceptance"]))
    parts.append(
        "## 交付定义(DoD)\n"
        "1. 按方案完成代码实现；\n"
        "2. 为新增/变更逻辑编写并运行单元测试(全部通过)；\n"
        "3. 完成整体编译/构建验证(项目可编译、无链接错误)；\n"
        "4. 全部完成后输出 [[IMPLEMENT_DONE]] 与摘要(变更文件/单测结果/编译结果/遗留项)；"
        "任一环节需要用户操作、确认、澄清或补充信息时，输出 [[NEED_INPUT]] 与具体问题后结束回合等待。")
    return "\n\n".join(parts)


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



def _prior_job_brief(conv: dict) -> str:
    """前情简报: 最近一条非完成作业的失败原因/实际改动/结论(重试上下文延续)。"""
    jobs = _meta_get(conv).get("jobs") or []
    for j in reversed(jobs):
        if (j.get("status") or "") not in ("done",):
            lines = []
            if j.get("failReason"):
                lines.append(f"- 上次结果: {str(j['failReason'])[:200]}")
            if j.get("changedFiles"):
                lines.append("- 已改动文件: " + ", ".join(j["changedFiles"][:12]))
            if j.get("lastAgentNote"):
                lines.append(f"- agent 结论: {str(j['lastAgentNote'])[:300]}")
            if lines:
                lines.append("- 请基于以上前情继续/修正，避免重复已完成的工作")
                return "\n".join(lines)
        break
    return ""




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
