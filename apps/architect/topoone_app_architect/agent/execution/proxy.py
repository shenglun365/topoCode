"""coding 直通通道代理(quick 挡语义升级, 用户裁决 2026-09-26)。

会话切至 quick(coding 执行器模式)后，对话回合**绕过需求/任务体系**直接与
执行器会话——architect 仅做通道代理 + 上下文装配(定位裁决: 主 agent 职责
白名单之「执行编排/信息交互」，不越位做需求收敛)。

复用面(零新建管道): runner implement 会话 API(input/abort/events)、
run_event_pump 通用泵、P2 上下文包契约、_build_workspace_files(AGENTS.md
映射下发)、脏工作区门禁(_dirty_worktree)。

边界: 直通模式下验收/需求卡/台账不强制(用户裁决)；脏工作区首次启动仍显式
拒绝(并行进程保护，续话 /input 不重复检测)。
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

logger = logging.getLogger("arch_routes.exec_bridge")

# conv_id -> {job_id, executor_type}（活跃直通会话; 进程级, 与 _TASK_PUMPS 同策略）
_PROXY_JOBS: Dict[str, Dict[str, str]] = {}

# runner 作业终态(snapshot.status 口径, 与 pumps.run_event_pump 一致)
_JOB_TERMINAL = ("done", "failed", "stopped")


def proxy_enabled(conv: Optional[dict]) -> bool:
    """quick 挡 = coding 执行器模式(直通对话)。"""
    return str((conv or {}).get("analysisMode") or "") == "quick"


def proxy_job_of(conv_id: str) -> Optional[Dict[str, str]]:
    return _PROXY_JOBS.get(conv_id)


def _start_pump(conv_id: str, job_id: str, etype: str) -> None:
    """直通事件泵(薄壳): 事件→会话 assistant 消息; 终态清 _PROXY_JOBS。"""
    from ...agent.execution import pumps as _pumps
    from . import exec_bridge as eb

    buf: Dict[str, Any] = {"text": ""}

    def _flush(suffix: str = "") -> None:
        text = (buf.pop("text", "") or "").strip()
        if text or suffix:
            eb._append(conv_id, "assistant",
                       (text + ("\n\n" + suffix if suffix else "")).strip(),
                       msg_meta={"kind": "proxy"},
                       agent=etype)

    def on_event(ev: dict) -> None:
        kind = ev.get("kind") or ""
        if kind == "text":
            buf["text"] = (buf["text"] + str(ev.get("text") or ""))[-6000:]
        elif kind == "input_required":
            _flush("⏸ 执行器等待你的输入——直接回复即可(继续直通)。")
        elif kind == "notice":
            logger.info("[proxy] %s notice: %s", job_id, str(ev.get("text") or "")[:120])
        elif kind in ("done", "failed", "aborted"):
            _flush("✅ 本轮完成。" if kind == "done"
                   else f"⚠️ 本轮结束({kind})。")
            _PROXY_JOBS.pop(conv_id, None)
            suffix = ("会话已结束——继续对话将开启新的执行器会话。"
                      if kind in ("done", "aborted") else "可重试或改走任务链路。")
            eb._append(conv_id, "assistant", suffix,
                       msg_meta={"kind": "proxy"}, agent=etype)

    def on_lost(reason: str) -> None:
        _PROXY_JOBS.pop(conv_id, None)
        eb._append(conv_id, "assistant",
                   f"⚠️ 直通会话与 runner 失去联系({reason})。",
                   msg_meta={"kind": "proxy"}, agent=etype)

    def on_snapshot(snap: dict) -> None:
        # 校准快照: 回写执行器原生会话 id(断线重挂/审计用)
        sid = str((snap or {}).get("sessionId") or "").strip()
        entry = _PROXY_JOBS.get(conv_id)
        if sid and entry and entry.get("job_id") == job_id:
            entry["session_ref"] = sid

    async def _pump():
        try:
            await _pumps.run_event_pump(
                base=eb.RUNNER_BASE, job_id=job_id, runner=eb._runner,
                on_event=on_event, on_snapshot=on_snapshot, on_lost=on_lost)
        except Exception as e:  # noqa: BLE001 — 泵异常退出必须清句柄(cv-259:
            # 缺 on_snapshot 直接 TypeError, 事件全丢且死 job 永久占住直通会话)。
            # 正常返回必经终态/lost 回调(各自已清), 不在此弹出——句柄存续=活跃会话。
            logger.exception("[proxy] 事件泵异常退出 conv=%s job=%s", conv_id, job_id)
            _flush(f"⚠️ 直通事件泵异常退出({e})——继续对话将开启新的执行器会话。")
            entry = _PROXY_JOBS.get(conv_id)
            if entry and entry.get("job_id") == job_id:
                _PROXY_JOBS.pop(conv_id, None)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_pump())
    except RuntimeError:
        if eb._MAIN_LOOP is not None and eb._MAIN_LOOP.is_running():
            asyncio.run_coroutine_threadsafe(_pump(), eb._MAIN_LOOP)
        else:
            logger.warning("[proxy] 无事件循环可挂泵 conv=%s job=%s", conv_id, job_id)


async def proxy_turn(data: dict, gate: dict, send, *, root: str,
                     project: str, executor: Dict[str, Any]) -> bool:
    """quick 挡回合直通。返回 True=本回合已收束(不再进 architect 管线)。

    - 活跃直通会话 → /input 直发(纯转发, 纯代理)
    - 无会话 → 轻量 start_session(无需求卡/任务卡; 注入上下文包+工作区约定
      文件; 脏工作区门禁显式拒绝——并行进程保护)
    - 未配置执行器 → 显式报错(不强硬保底到 architect 管线)

    R1 合规: root/executor 由 orchestrator 例外层解析注入, 本模块不依赖 arch_routes。
    """
    from . import exec_bridge as eb
    from .dispatch import _dirty_worktree

    conv_id, conv = gate["conv_id"], gate["conv"]
    ex = executor
    if not ex:
        eb._append(conv_id, "assistant",
                   "⚠️ 未配置可用执行器(coding 执行器模式需要至少一个已启用的"
                   "执行器)——请在执行器配置中启用后重试，或切回 architect 模式。",
                   msg_meta={"kind": "proxy"})
        return True

    text = str(gate.get("question") or "").strip()
    if not text:
        return True

    # 执行器配置单源(经 exec_bridge hint 解析链, 与任务卡派发同构; cv-259:
    # 只发 executorType 不发 executorConfig → runner 空 models 报"未配置模型")
    hint: Dict[str, Any] = {}
    try:
        hint = eb.executor_hint_by_id(str(ex.get("id") or ""), conv) or {}
    except Exception:  # noqa: BLE001
        hint = {}
    etype = str(hint.get("executorType") or ex.get("type") or "")
    ecfg: Dict[str, Any] = hint.get("executorConfig") or (ex.get("config") or {})
    if hint:
        model = str(hint.get("model") or "").strip()
    else:
        # 兜底链与 executor_hint_by_id/_resolve_model 同序: 会话绑定 > model_id > models[0]
        names = [str(m.get("name") or m.get("model") or "")
                 for m in (ecfg.get("models") or [])
                 if (m.get("name") or m.get("model"))]
        model = (str((conv or {}).get("executorModel") or "").strip()
                 or str(ecfg.get("model_id") or "").strip()
                 or (names[0] if names else "")
                 or str(ecfg.get("model") or ""))

    job = _PROXY_JOBS.get(conv_id)
    if job:
        _t = _timeout_of(ecfg)
        _agent = job.get("executor_type") or etype
        snap = eb._runner(f"/api/implement/{job['job_id']}", None, _t)
        if snap is None:
            # runner 失联: 清死句柄(cv-259 盲发 /input 石沉大海的根治), 落入新开
            _PROXY_JOBS.pop(conv_id, None)
            eb._append(conv_id, "assistant",
                       "⚠️ 直通会话与 runner 失联(:3458)——本条消息将尝试开启新的执行器会话。",
                       msg_meta={"kind": "proxy"}, agent=_agent)
        elif str(snap.get("status") or "") in _JOB_TERMINAL:
            _PROXY_JOBS.pop(conv_id, None)   # 终态 → 开启新的直通会话
        else:
            r = eb._runner(f"/api/implement/{job['job_id']}/input",
                           {"text": text}, timeout=_t)
            if r is None:
                eb._append(conv_id, "assistant",
                           "⚠️ 转发失败: runner 不可达(:3458)。",
                           msg_meta={"kind": "proxy"}, agent=_agent)
            elif r.get("ok") is False:
                eb._append(conv_id, "assistant",
                           f"⚠️ 转发失败: {r.get('error') or '未知错误'}。",
                           msg_meta={"kind": "proxy"}, agent=_agent)
            return True

    # 首次启动: 隔离决策(cv-202 同口径: 会话隔离开关) + 脏工作区门禁
    worktree = bool((conv or {}).get("isolated"))
    if not worktree and root and _dirty_worktree(root):
        eb._append(conv_id, "assistant",
                   "⚠️ 工作区有未提交变更(可能来自其它开发进程)——直通执行器已拒绝"
                   "就地启动，避免互踩。请先处理变更，或开启会话隔离开关。",
                   msg_meta={"kind": "proxy"})
        return True

    from .context_pack import build_context_pack, render_context_pack_md
    pack = build_context_pack({}, conv, root)
    instruction = (text + "\n\n" + render_context_pack_md(pack)).strip()
    payload: Dict[str, Any] = {
        "root": root, "projectId": (conv or {}).get("projectId") or "",
        "branchName": f"proxy/{int(time.time() * 1000) % 10 ** 10}",
        "boundaries": {"files": [], "components": [], "readOnly": False},
        "worktree": worktree,
        "instruction": instruction,
        "executorType": etype,
        "executorConfig": ecfg,
    }
    if hint.get("executorId"):
        payload["executorId"] = hint["executorId"]
    for k in ("basePort", "autoStart", "baseUrl"):
        v = hint.get(k)
        if v not in (None, ""):
            payload[k] = v
    for k in ("turnTimeout", "stallSec"):
        v = ecfg.get(k)
        if isinstance(v, (int, float)) and v > 0:
            payload[k] = float(v)
    workspace_files = eb._build_workspace_files(etype, ecfg, {})
    if workspace_files:
        payload["workspaceFiles"] = workspace_files
    if model:
        payload["model"] = model

    sr = eb._client().start_implement(payload, 20.0)
    if not sr.ok:
        eb._append(conv_id, "assistant",
                   f"⚠️ 直通启动失败: {sr.error or 'runner 服务不可达(:3458)'}",
                   msg_meta={"kind": "proxy"})
        return True

    _PROXY_JOBS[conv_id] = {"job_id": sr.job_id, "executor_type": etype}
    _start_pump(conv_id, sr.job_id, etype)
    eb._append(conv_id, "assistant",
               f"🔗 已直通执行器 `{etype}`(job `{sr.job_id}`，"
               f"{'隔离 worktree' if worktree else '就地模式'})"
               "——本轮起你的消息直接发给执行器，architect 仅做通道。",
               msg_meta={"kind": "proxy"}, agent=etype)
    return True


def _timeout_of(ecfg: dict) -> float:
    v = (ecfg or {}).get("turnTimeout")
    return float(v) if isinstance(v, (int, float)) and v > 0 else 12.0
