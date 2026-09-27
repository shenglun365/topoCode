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

# cv-266 上下文组装(历史脉络/MCP 接线/工具告知)——proxy_ctx 单源, 再导出保住
# 既有测试接缝(proxy._merge_mcp_servers 等)
from .proxy_ctx import (  # noqa: E402
    _HISTORY_CAP_DEFAULT, _history_brief, _merge_mcp_servers, _mcp_tools_brief)

# conv_id -> {job_id, executor_type}（活跃直通会话; 进程级, 与 _TASK_PUMPS 同策略）
_PROXY_JOBS: Dict[str, Dict[str, str]] = {}

# runner 作业终态(snapshot.status 口径, 与 pumps.run_event_pump 一致)
_JOB_TERMINAL = ("done", "failed", "stopped")


def proxy_state(conv_id: str) -> Dict[str, Any]:
    """直通会话状态(cv-275): FE 持久状态条数据源(REST 查询, 刷新安全)。

    {active, jobId, sessionRef, executorType}——active=有活跃直通作业
    (内存句柄; 后端重启后句柄清空但会话行 sessionRef 仍可复活)。"""
    entry = _PROXY_JOBS.get(conv_id) or {}
    from ... import store as _st
    row = _st.ConversationsStore.get(conv_id) or {}
    return {"active": bool(entry),
            "jobId": entry.get("job_id") or "",
            "executorType": entry.get("executor_type") or "",
            "sessionRef": row.get("sessionRef") or ""}


def proxy_stop(conv_id: str) -> Dict[str, Any]:
    """停止直通执行器(cv-273/275): 按作业状态分型——

    running → /abort(暂停语义: 中止本轮, 会话保留, 发消息即恢复);
    空闲(waiting_input) → /finish(结束会话: 下条消息开启全新会话)。
    会话行 sessionRef 恒保留(finish 亦不清——用户可随时复活续上下文)。"""
    entry = _PROXY_JOBS.get(conv_id)
    if not entry:
        return {"ok": False, "error": "无进行中的直通会话"}
    job_id = entry["job_id"]
    from . import exec_bridge as eb
    snap = eb._runner(f"/api/implement/{job_id}", None, 12.0) or {}
    running = (snap.get("status") or "") not in ("waiting_input", "done",
                                                 "failed", "stopped")
    action = "abort" if running else "finish"
    r = eb._runner(f"/api/implement/{job_id}/{action}", {}, 12.0)
    if r is None:
        return {"ok": False, "error": "runner 不可达(:3458)", "job_id": job_id}
    if r.get("ok") is False:
        return {"ok": False, "error": r.get("error") or f"{action} 调用失败",
                "job_id": job_id}
    return {"ok": True, "job_id": job_id, "action": action,
            "summary": ("已暂停——会话保留，发消息即恢复" if running
                        else "已结束直通会话——下条消息将开启全新会话")}


def proxy_enabled(conv: Optional[dict]) -> bool:
    """quick 挡 = coding 执行器模式(直通对话)。"""
    return str((conv or {}).get("analysisMode") or "") == "quick"


def proxy_job_of(conv_id: str) -> Optional[Dict[str, str]]:
    return _PROXY_JOBS.get(conv_id)


# 直通正文卡节流落库间隔: 执行器流式 text 增量原位更新(单卡生长, cv-263——
# 此前 text 只累积不落库, 3.5 分钟执行期 UI 零反馈, 终态一次性 flush)。
_PROXY_FLUSH_MS = 400


def _make_handlers(conv_id: str, job_id: str, etype: str):
    """泵回调组(独立函数以便特征测试直接驱动): (on_event, on_snapshot, on_lost)。

    cv-263 流式可见性: text 事件增量落单卡(kind=proxy, jobId 定位)——首段
    land, 后续原位 UPDATE + SSE 通知(task_status 单卡先例), UI 同一条消息
    持续生长; 终态/输入等待时收尾余量+状态后缀。"""
    import time as _time
    from ...agent.collab import cards as _cards
    from . import exec_bridge as eb

    buf: Dict[str, Any] = {"text": "", "row": None, "at": 0.0}
    meta = {"kind": "proxy", "jobId": job_id}

    def _persist(text: str) -> None:
        """正文单卡 upsert: 首段 land 建卡, 后续原位 UPDATE + SSE 通知。"""
        if not text:
            return
        if buf["row"] is None:
            buf["row"] = eb._append(conv_id, "assistant", text,
                                    msg_meta=dict(meta), agent=etype)
            return
        try:
            row = _store_update(conv_id, meta, text)
            if row:
                _cards.emit(conv_id, str(row.get("id") or ""),
                            agent=etype, kind="proxy")
        except Exception:  # noqa: BLE001 — 更新失败回落重落新卡
            buf["row"] = eb._append(conv_id, "assistant", text,
                                    msg_meta=dict(meta), agent=etype)

    def _store_update(cid: str, m: dict, text: str) -> dict | None:
        from ... import store as _st
        return _st.ConversationsStore.update_message_by_meta(
            cid, m, {"content": text})

    def _flush(suffix: str = "") -> None:
        # 重置非删键(cv-264): pop 后键缺失, 迟到/重放的 text 事件在
        # buf["text"] 读取处 KeyError → 泵崩死 → 后续输出全部黑洞。
        text = (buf.get("text") or "").strip()
        buf["text"] = ""
        _persist((text + ("\n\n" + suffix if suffix else "")).strip()
                 if (text or suffix) else "")
        buf["row"] = None   # 回合结束, 下轮执行器输出重新建卡

    def on_event(ev: dict) -> None:
        kind = ev.get("kind") or ""
        if kind == "text":
            # cv-271: 不设上限——缓冲即交付物, 截断=数据丢失(cv-266 实证
            # 头部 6000 字符被挤掉); 失控保护归 runner loopguard(按输出/
            # 工具频次熔断), architect 侧不再二次截断
            buf["text"] = (buf.get("text") or "") + str(ev.get("text") or "")
            # cv-273: 过程流同步(0.5s 节流)——控制条活动文本预览(此前 text
            # 只进卡片缓冲, 过程流 lastText 恒空=预览死面, cv-266 实证)
            from . import process_stream as _ps
            prog = _ps.apply_event(_ps.proxy_progress(conv_id), ev)
            if prog is not None:
                _ps.proxy_store(conv_id, prog)
                _ps.publish(conv_id, f"proxy:{conv_id}", prog,
                            throttle=_ps.sse_throttle("text"), jobId=job_id)
            now = _time.monotonic() * 1000
            if now - buf["at"] >= _PROXY_FLUSH_MS:
                buf["at"] = now
                _persist(buf["text"])
        elif kind == "turn_done":
            # cv-267 对话回合制: 正常收束(非终态, 作业保活——续话直达原生会话)
            _flush("✅ 本轮回答已结束——继续对话将直接送达执行器。")
            # cv-270 折叠快照: toolCount=本轮环长, 过程态清空(下一轮从零);
            # 快照经 SSE 交 FE 折叠显示("本轮共 N 次工具调用")
            from . import process_stream as _ps
            _ps.proxy_turn_done(conv_id)
            snap = _ps.proxy_fold_snapshot(conv_id)   # 含 turnCount(本轮累计)
            _ps.publish(conv_id, f"proxy:{conv_id}", snap, jobId=job_id)
        elif kind == "input_required":
            _flush("⏸ 执行器有事项需要你确认——直接回复即可。")
        elif kind in ("tool", "usage", "progress"):
            # cv-268 过程感知单源: 落内存环形(瞬态) + SSE progress
            # (conversationId 键无 taskId → FE 分流到消息区过程条)
            from . import process_stream as _ps
            prog = _ps.apply_event(_ps.proxy_progress(conv_id), ev)
            if prog is not None:
                _ps.proxy_store(conv_id, prog)
                _ps.publish(conv_id, f"proxy:{conv_id}", prog,
                            throttle=_ps.sse_throttle(kind), jobId=job_id)
        elif kind == "notice":
            logger.info("[proxy] %s notice: %s", job_id, str(ev.get("text") or "")[:120])
        elif kind in ("done", "failed", "aborted"):
            _flush("✅ 本轮完成。" if kind == "done"
                   else ("🛑 已停止本轮执行（会话保留——发消息即可继续）。"
                         if kind == "aborted" else f"⚠️ 本轮结束({kind})。"))
            _PROXY_JOBS.pop(conv_id, None)
            from . import process_stream as _ps
            _ps.proxy_finish(conv_id)
            suffix = ("会话已结束——继续对话将开启新的执行器会话。"
                      if kind in ("done", "aborted") else "可重试或改走任务链路。")
            eb._append(conv_id, "assistant", suffix,
                       msg_meta={"kind": "proxy"}, agent=etype)

    def on_lost(reason: str) -> None:
        _PROXY_JOBS.pop(conv_id, None)
        from . import process_stream as _ps
        _ps.proxy_finish(conv_id)
        eb._append(conv_id, "assistant",
                   f"⚠️ 直通会话与 runner 失去联系({reason})。",
                   msg_meta={"kind": "proxy"}, agent=etype)

    def on_snapshot(snap: dict) -> None:
        # 校准快照: 回写执行器原生会话 id(断线重挂/审计用); 变化时持久化到
        # 会话行(cv-273 复活链——作业终态后, 下条消息带 sessionRef 复活同会话)
        sid = str((snap or {}).get("sessionId") or "").strip()
        entry = _PROXY_JOBS.get(conv_id)
        if sid and entry and entry.get("job_id") == job_id:
            if entry.get("session_ref") != sid:
                entry["session_ref"] = sid
                try:
                    from ... import store as _st
                    _st.ConversationsStore.update(conv_id, {"sessionRef": sid})
                except Exception as e:  # noqa: BLE001
                    logger.warning("[proxy] sessionRef 持久化失败 conv=%s: %s",
                                   conv_id, e)

    return on_event, on_snapshot, on_lost, _flush


def _start_pump(conv_id: str, job_id: str, etype: str) -> None:
    """直通事件泵(薄壳): 回调组(_make_handlers)+事件循环挂载; 终态清句柄。"""
    from ...agent.execution import pumps as _pumps
    from . import exec_bridge as eb
    on_event, on_snapshot, on_lost, _flush = _make_handlers(
        conv_id, job_id, etype)

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

    收口纪律(cv-259): 本回合必须恒发 WS done 终止帧——proxy 只落库不收口时,
    前端 chatStream promise 永挂 busy=true, SSE conv-message 被无限 defer
    (消息只能整页刷新可见)且输入框锁死。row 回执→done(content+messageId);
    无回执(纯转发)→done(cardClosed) 清本地占位泡。
    """
    from . import exec_bridge as eb
    from .dispatch import _dirty_worktree

    conv_id, conv = gate["conv_id"], gate["conv"]

    async def _send_done(row: Optional[dict] = None) -> None:
        try:
            if row:
                await send({"type": "done", "conversationId": conv_id,
                            "content": str(row.get("content") or ""),
                            "messageId": str(row.get("id") or ""),
                            "meta": {"kind": "proxy"}})
            else:
                await send({"type": "done", "conversationId": conv_id,
                            "content": "", "cardClosed": True})
        except Exception:  # noqa: BLE001 — 收口失败不吞落库事实(SSE 通道兜底)
            logger.exception("[proxy] done 收口失败 conv=%s", conv_id)

    ex = executor
    if not ex:
        row = eb._append(conv_id, "assistant",
                         "⚠️ 未配置可用执行器(coding 执行器模式需要至少一个已启用的"
                         "执行器)——请在执行器配置中启用后重试，或切回 architect 模式。",
                         msg_meta={"kind": "proxy"})
        await _send_done(row)
        return True

    text = str(gate.get("question") or "").strip()
    if not text:
        await _send_done()
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
            # cv-266: 转达语境摘要(既有 digest 载荷)随 /input 携带, 与任务链同语义
            _digest = str(data.get("digest") or "").strip()
            _fwd = text if not _digest else (
                f"{text}\n\n【用户转达的语境摘要】\n{_digest}")
            r = eb._runner(f"/api/implement/{job['job_id']}/input",
                           {"text": _fwd, "steer": True}, timeout=_t)
            if r is None:
                row = eb._append(conv_id, "assistant",
                                 "⚠️ 转发失败: runner 不可达(:3458)。",
                                 msg_meta={"kind": "proxy"}, agent=_agent)
                await _send_done(row)
            elif r.get("ok") is False:
                row = eb._append(conv_id, "assistant",
                                 f"⚠️ 转发失败: {r.get('error') or '未知错误'}。",
                                 msg_meta={"kind": "proxy"}, agent=_agent)
                await _send_done(row)
            else:
                await _send_done()   # 纯转发静默成功: 收口清占位泡, 产出经泵+SSE 呈现
            return True

    # 首次启动: 隔离决策(cv-202 同口径: 会话隔离开关) + 脏工作区处置
    worktree = bool((conv or {}).get("isolated"))
    dirty_note = ""
    dirty_warn = ""
    if not worktree and root and _dirty_worktree(root):
        # cv-269 软化(用户实证 cv-264 自干扰死锁: 架构注入文件自身弄脏工作区
        # → 下轮被拒): 直通=chat 角色(用户逐轮在环, 三原则不强硬保底)——
        # 警告+边界提醒后继续; 任务链 dispatch 硬闸不变(自治执行仍防互踩)
        dirty_note = ("【工作区提示】当前工作区存在未提交变更（可能来自其它开发进程）。"
                      "不要回滚、提交(stash/checkout/clean/commit)或清理任何与本次诉求"
                      "无关的变更；你的修改应聚焦本次诉求涉及的范围。")
        # cv-270: 警告并入直通回执(不再独立落卡——信息流污染实证 cv-266)
        dirty_warn = ("\n⚠️ 工作区有未提交变更（可能来自其它开发进程）——"
                      "执行器被要求不动无关变更；如需完全隔离，请开启会话隔离开关。")

    from .context_pack import build_context_pack, render_context_pack_md
    pack = build_context_pack({}, conv, root)
    # cv-266: 历史脉络默认注入(确定性拼接, 容量执行器 config 可调, 0=关)
    # + 用户"语境摘要"转达(digest 既有载荷, 此前在直通分支被丢弃)
    parts = [text]
    digest = str(data.get("digest") or "").strip()
    if digest:
        parts.append(f"【用户转达的语境摘要】\n{digest}")
    hist_cap = ecfg.get("historyContextChars")
    hist_cap = hist_cap if isinstance(hist_cap, int) and hist_cap >= 0 \
        else _HISTORY_CAP_DEFAULT
    brief = (_history_brief(conv_id, hist_cap,
                            exclude_msg_ids={str(gate.get("last_user_msg_id") or "")})
             if hist_cap else "")
    if brief:
        parts.append(brief)
    if dirty_note:
        parts.append(dirty_note)
    parts.append(render_context_pack_md(pack))
    instruction = "\n\n".join(p for p in parts if p.strip()).strip()
    mcp = _merge_mcp_servers(ecfg, etype)
    if mcp is not None:
        payload_mcp = mcp
    payload: Dict[str, Any] = {
        "root": root, "projectId": (conv or {}).get("projectId") or "",
        "branchName": f"proxy/{int(time.time() * 1000) % 10 ** 10}",
        "boundaries": {"files": [], "components": [], "readOnly": False},
        "worktree": worktree,
        "instruction": instruction,
        "executorType": etype,
        "executorConfig": ecfg,
        # cv-267 直通=对话回合制: 执行器原生多回合自管上下文, runner 不拼任务
        # 协作协议/不跑验收门; 无标记收束=turn_done(作业保活, 续话复用原生会话)
        "sessionRole": "chat",
        # cv-273 复活链: 会话行持久化的执行器原生会话 id → 新 job 复活同会话
        **({"sessionRef": str((conv or {}).get("sessionRef") or "")}
           if (conv or {}).get("sessionRef") else {}),
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
    # cv-266/cv-269: MCP 工具告知并入 instruction(此前独立落盘
    # TOPO-CONTEXT-TOOLS.md 会弄脏融合模式工作区 → 脏区门禁自干扰死锁);
    # codex 无 MCP 面 → 不告知不虚报
    tools_brief = _mcp_tools_brief(conv_id, mcp)
    if tools_brief:
        parts.insert(-1, tools_brief.strip())   # 契约段之前
        instruction = "\n\n".join(p for p in parts if p.strip()).strip()
        payload["instruction"] = instruction    # payload 已装配, 同步回写
    if workspace_files:
        payload["workspaceFiles"] = workspace_files
    if mcp is not None:
        payload["mcp_servers"] = payload_mcp
    if model:
        payload["model"] = model

    sr = eb._client().start_implement(payload, 20.0)
    if not sr.ok:
        row = eb._append(conv_id, "assistant",
                         f"⚠️ 直通启动失败: {sr.error or 'runner 服务不可达(:3458)'}",
                         msg_meta={"kind": "proxy"})
        await _send_done(row)
        return True

    _PROXY_JOBS[conv_id] = {"job_id": sr.job_id, "executor_type": etype}
    _start_pump(conv_id, sr.job_id, etype)
    row = eb._append(conv_id, "assistant",
                     f"🔗 已直通执行器 `{etype}`(job `{sr.job_id}`，"
                     f"{'隔离 worktree' if worktree else '融合模式'})"
                     "——本轮起你的消息直接发给执行器，architect 仅做通道。"
                     + dirty_warn,
                     msg_meta={"kind": "proxy"}, agent=etype)
    await _send_done(row)
    return True



def _timeout_of(ecfg: dict) -> float:
    v = (ecfg or {}).get("turnTimeout")
    return float(v) if isinstance(v, (int, float)) and v > 0 else 12.0
