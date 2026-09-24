"""回合编排器(agent 内核入口) — KB 对话回合全管道。

P2 自 websocket._handle_kb_chat 机械迁入(逐字节保真, 仅接缝替换):
  gate(会话闸门, agent.perception.gate) → route(收件人路由, agent.perception.router)
  → context(消息装配, agent.turns.context) → 执行(工具循环, agent.turns.chat)
  → land(落库 + 终态事件, agent.turns.chat)。

M1 拆分(整体设计 §8.2): 阶段函数迁 agent.turns/*, 本文件保留入口编排
(gate/route/直通指令)并 re-export 阶段函数(五段结构守卫与既有引用兼容)。
websocket.py 仅保留 WS 适配器(事件形状契约冻结, CONV-04)。
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Awaitable, Callable, Optional

from .perception.gate import bind_session
from .perception.router import decide as _route_decide
from .turns.base import SendFn, _TurnIO

# ── 阶段函数 re-export(M1 拆分自本文件; 外部 orch._xxx 引用与五段结构守卫兼容) ──
from .turns.chat import (_chat_land, _chat_max_tokens, _iter_llm_events,
                         _LiveForward, _model_health_hint, _post_turn_land,
                         _req_chat_stream, _run_llm_tool_loop, _run_tool_with_progress,
                         _sync_with_tools)
from .turns.context import _build_chat_messages, _chat_context

logger = logging.getLogger(__name__)


# P2/P3: 会话 agent 的 ctx.* + probe.run/评估/提炼工具注册(幂等; P4 起延迟到首回合)
def _register_session_tools() -> None:
    from ..arch_routes import context_registry as _context_registry
    _context_registry.register_chat_tools()
    _context_registry.register_probe_tool()
    from ..arch_routes import evaluator as _evaluator
    _evaluator.register_evaluator_tools()
    from ..arch_routes import capability_mining as _cap_mining
    _cap_mining.register_mining_tools()


async def _confirm_focus_task(conv: dict, send: SendFn, store,
                              user_msg_id: str, task_id: str,
                              executor: str = "", label: str = "") -> None:
    """焦点动作执行器(批戊): 就近确认焦点帧指代的任务卡(替代 run_confirm 全量
    扫描/多卡逐张提示——指代由焦点帧给出, 与卡片按钮同门禁链)。"""
    from ..arch_routes import exec_bridge as _eb
    conv_id = conv["id"]
    executor = (executor or "").strip()

    async def _done(content: str) -> None:
        msg_id = store.next_id("m")
        await send({"type": "chat_start", "conversationId": conv_id,
                    "requestId": "", "userMessageId": user_msg_id})
        await send({"type": "done", "conversationId": conv_id,
                    "content": content, "messageId": msg_id})

    if executor:
        t2 = await asyncio.to_thread(_eb.task_set_executor, task_id, executor)
        if not t2:
            await _done(f"⚠️ 执行器 `{executor}` 不可用（不在注册表或类型不支持）。")
            return
    res = await asyncio.to_thread(_eb.confirm_task, task_id)
    if res.get("ok"):
        t = res.get("task") or {}
        await _done(f"🚀 已确认任务「{t.get('title')}」（执行器 "
                    f"`{t.get('executorType')}`）——开始执行，进展将在本会话同步。")
    else:
        await _done(f"⚠️ {res.get('error') or '确认失败'}")


async def _retry_focus_task(conv: dict, send: SendFn, store,
                            user_msg_id: str, task_id: str) -> None:
    """焦点动作执行器(批戊): 重发失败步骤(retry_failed 指代落地)。"""
    from ..arch_routes.common import _ts
    from .planning.task_plan import retry_failed_step
    conv_id = conv["id"]
    res = await asyncio.to_thread(retry_failed_step, conv, task_id)
    content = (f"🔁 {res.get('receipt')}" if res.get("ok")
               else f"⚠️ {res.get('receipt') or '重发失败'}")
    msg_id = store.next_id("m")
    await send({"type": "chat_start", "conversationId": conv_id,
                "requestId": "", "userMessageId": user_msg_id})
    await send({"type": "done", "conversationId": conv_id,
                "content": content, "messageId": msg_id})


async def _run_direct_command(cmd: str, conv: dict, send: SendFn, store,
                              user_msg_id: str, executor: str = "",
                              skip_plan: bool = False) -> None:
    """会话指令直通(v2): /提取需求 → 历史提取需求卡; /执行 → ready 规约建任务卡。
    @执行器 前缀显式指定执行器; 回执落库+done 事件与常规回合同形;
    specReady meta 供前端渲染[一键建卡]动作。"""
    from .perception import commands as _cmds
    from ..arch_routes.common import _ts
    conv_id = conv["id"]
    # cv-197: 直通链可含 LLM 拆步(最长 LLM_SYNC_TIMEOUT=300s)——零反馈即
    # 「卡死」观感; 状态事件 + 首尾日志补齐可观测性。
    logger.info("[direct-cmd] %s conv=%s 开始 (skip_plan=%s)", cmd, conv_id, skip_plan)
    try:
        await send({"type": "status", "phase": "direct_cmd", "cmd": cmd})
    except Exception:  # noqa: BLE001
        pass
    # cv-199: 直通链内含 LLM 长调用(拆步/提取, 上限 TOPO_TIMEOUT_LLM_CALL=300s)
    # ——相位回调线程安全桥接 send, 前端 busyLabel 实时透出("正在生成任务计划…")
    _loop = asyncio.get_running_loop()

    def _on_phase(phase: str) -> None:
        _labels = {"plan": "正在生成任务计划（拆步编排，最长可达数分钟）…",
                   "extract": "正在从对话历史提取需求…",
                   "card": "正在创建任务卡…",
                   # cv-205: 去 worktree 措辞——执行形态由启动状态卡标注
                   # (就地缺省; 隔离仅在会话开关显式开启时)
                   "start": "正在启动任务（执行器拉起）…"}
        try:
            asyncio.run_coroutine_threadsafe(
                send({"type": "status", "phase": f"cmd_{phase}",
                      "label": _labels.get(phase, phase)}), _loop)
        except Exception:  # noqa: BLE001
            pass

    meta = None
    if cmd == "提取需求":
        # cv-204 探活根修: 直通链内含 CallTurn LLM 同步调用(上限 300s)+git/DB
        # 同步操作——事件循环上直跑会饿死 /health(supervisor 5×(5+2)s 判挂死
        # kill, cv-201 实证)→ 与 run_confirm(:50) 同规 to_thread。
        res = await asyncio.to_thread(_cmds.run_extract_req, conv, on_phase=_on_phase)
        logger.info("[direct-cmd] 提取需求 conv=%s 完成 ok=%s", conv_id, res.get("ok"))
        if not res.get("ok"):
            content = f"⚠️ {res.get('receipt') or res.get('error') or '提取失败'}"
        else:
            content = res.get("receipt") or "需求卡已提取。"
    elif cmd == "执行":
        # cv-200: 按钮合成路径建卡即启动(「运行」=直接开跑)
        # cv-204: 同上 to_thread——LLM 拆步/建卡/git 链不得阻塞事件循环
        res = await asyncio.to_thread(
            _cmds.run_execute, conv, executor_id=executor,
            skip_plan=skip_plan, on_phase=_on_phase,
            auto_start=skip_plan)
        logger.info("[direct-cmd] 执行 conv=%s 完成 ok=%s", conv_id, res.get("ok"))
        if not res.get("ok"):
            content = f"⚠️ {res.get('receipt') or '建卡失败'}"
        else:
            t = res.get("task") or {}
            etag = f"（执行器 `{t.get('executorType')}`{('·' + executor) if executor else ''}）"
            if (t.get("status") or "") == "running":
                content = (f"🚀 任务已启动：**{t.get('title')}**{etag}——"
                           "进展与提问会进入本会话, 直接回复即可转达。")
            else:
                content = (f"📋 已从规约创建任务卡：**{t.get('title')}**{etag}（待确认）——"
                           "在卡片上确认后 coding subagent 开始执行。")
            # 任务卡本体已由 propose_task 落流(带确认按钮); 此处仅回执指针(不落库)
            msg_id = store.next_id("m")
            await send({"type": "chat_start", "conversationId": conv_id,
                        "requestId": "", "userMessageId": user_msg_id})
            await send({"type": "done", "conversationId": conv_id,
                        "content": content, "messageId": msg_id})
            return
    else:
        return
    msg_id = store.next_id("m")
    row = {"id": msg_id, "conversationId": conv_id, "role": "assistant",
           "time": _ts(), "content": content}
    if meta:
        row["meta"] = json.dumps(meta, ensure_ascii=False)
    store.ConversationsStore.append_message(row)
    try:
        store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
    except Exception:  # noqa: BLE001
        pass
    await send({"type": "chat_start", "conversationId": conv_id,
                "requestId": "", "userMessageId": user_msg_id})
    done_ev = {"type": "done", "conversationId": conv_id,
               "content": content, "messageId": msg_id}
    if meta:
        done_ev["meta"] = meta
    await send(done_ev)


async def _phase_hard_gate(gate: dict, send: SendFn, store) -> bool:
    """管线阶段①.5 相位硬闸(G1: 闸门之后/路由之前, 先于直通指令)。

    仅 interrupted 拦下发类意图(词表单源 flow.evaluate_guards); 命中 → 直通
    回执(零 LLM)。开关 flow_guards_enabled(缺省启用)。其余相位全软(note/hint)。
    """
    from .compensation.overrides import override_enabled, read_overrides
    phase = str((gate.get("conv") or {}).get("flowState") or "")
    if not phase:
        return False
    try:
        if not override_enabled(read_overrides(store.CollabConfigStore.get),
                                "flow_guards_enabled"):
            return False
    except Exception:  # noqa: BLE001 — 开关读取失败保持守卫启用
        pass
    from .governance.flow import evaluate_guards, land_phase_reply
    reply = evaluate_guards(phase, str(gate.get("question") or ""))
    if reply is None:
        return False
    conv_id = gate["conv_id"]
    msg_id = await asyncio.to_thread(land_phase_reply, conv_id, reply)
    await send({"type": "chat_start", "conversationId": conv_id,
                "requestId": "", "userMessageId": gate.get("last_user_msg_id") or ""})
    await send({"type": "chunk", "requestId": "", "delta": reply})
    await send({"type": "done", "conversationId": conv_id,
                "content": reply, "messageId": msg_id})
    return True


async def handle_chat(data: dict, send: SendFn) -> None:
    """自由对话回合(B3 五段管线编排): 闸门 → 路由 → 上下文 → 执行 → 落库。

    每段为独立函数(_chat_gate/_chat_route/_chat_context/_run_llm_tool_loop/
    _chat_land), 本体只做请求解析与段间接线(行为等价重构, 无新抽象层)。
    """
    from ..arch_routes import req_agent
    from ..arch_routes import store
    from ..arch_routes.common import _ts

    now = _ts()
    # ---- 请求解析(段间共享的入口事实) ----
    history = data.get("messages") or []
    if not history and data.get("content"):
        history = [{"role": "user", "content": data.get("content", "")}]
    model_id = data.get("modelId") or data.get("model") or ""
    root = (data.get("root") or "").strip()
    project = (data.get("project") or "").strip()
    diagram_skill = bool(data.get("diagramSkill") or data.get("diagram_skill"))
    skill_scenarios = data.get("skillScenarios") or []
    if not isinstance(skill_scenarios, list):
        skill_scenarios = []
    skill_scenarios = [str(s) for s in skill_scenarios]

    # ---- ① 闸门: 绑定/归档闸/自愈/需求回填 + 用户消息落库 ----
    gate = await _chat_gate(data, send, now)
    if gate is None:
        return
    conv_id, conv = gate["conv_id"], gate["conv"]
    # cv-221: chat_start 即时发送(原惰性=首工具/首 token 才发)——长 LLM 回合
    # 此前全程零帧, 且 SSE 卡片通知可先于 WS chat_start 处理, 会话守卫丢刷新
    # → 卡片回合实时不可见(只能整页刷新)。前端依赖早绑定会话 id。
    io = _TurnIO(send, conv_id, gate["last_user_msg_id"])
    await io.ensure_chat_start()

    # ---- ①.5 相位硬闸(G1 裁决: 闸门之后/路由之前, 先于直通指令) ----
    if await _phase_hard_gate(gate, send, store):
        return

    # ---- ② 路由: transfer 收尾 / 直通指令 / 文字确认(命中即收束) ----
    handled, decision = await _chat_route(data, gate, send)
    if handled:
        return
    assign_contract = decision.contract or None

    # ③.5-前半 目标理解 GU plan(批丁前置于装配): profile → 决策表 → tools 限定。
    # 人格=能力文档 posture 静态单源(GU-3); 指引=决策表动态生成(教学=决策);
    # 确定性层(指令直通/相位硬闸)在其之前不变(防守线①)。
    gu_plan = None
    gu_allowed = None
    gu_focus = None
    if decision.action == "chat":
        from .governance.focus import build_focus
        from .turns.goal import plan_goal_directive
        gu_focus = await asyncio.to_thread(
            build_focus, conv_id, None,
            cached_phase=str(conv.get("flowState") or ""))
        gu_plan = await asyncio.to_thread(
            plan_goal_directive, str(gate.get("question") or ""),
            conv, None, history, gu_focus)
        gu_allowed = _resolve_gu_allowed(gu_plan)

    # ---- ③ 上下文: 角色模型路由 + 懒探测 + 挡位 + 消息装配 ----
    eff_model, msgs, gear = _chat_context(data, gate, skill_scenarios, history,
                                          model_id, assign_contract,
                                          gu_allowed=gu_allowed)
    # ③.5-后半: 回合指引注入(msgs[1])
    if gu_plan:
        from .turns.goal import inject_goal_directive
        inject_goal_directive(msgs, gu_plan)
    _record_prompt_sections(msgs, gear, gu_plan, gu_allowed)

    # ---- ④ 执行: 连续多轮流式(A 管线: 抽至 _run_llm_tool_loop) ----
    tools_used: set = set()
    tool_errors: dict = {}
    loop = await _run_llm_tool_loop(io, conv_id, msgs, root, project,
                                    eff_model, model_id, tools_used, tool_errors,
                                    max_tool_rounds=gear.tool_rounds,
                                    allowed_tools=gu_allowed)

    # ---- ⑤⑥ 落库 + 终态事件(正常 done / 错误 turnError) ----
    await _chat_land(io, msgs, gate, conv, loop, eff_model, model_id,
                     root, project, tools_used, tool_errors,
                     allowed_tools=gu_allowed,
                     gu_action=str((gu_plan or {}).get("action") or ""))

    # ⑤.5 GU 确定性问询卡(cv-247 源②③): clarify-first(策略问题集)/
    # present-options(候选)落 choices 卡——正文之后落流(阅读序), 同
    # fingerprint 原位更新(多回合澄清单锚位, 不刷屏)。模型围栏源(①)
    # 已在 _post_turn_land 落流。交互卡非实体写卡, 不经验权(执法点管
    # 「写实体权力」)。
    gu_choices = (gu_plan or {}).get("choices")
    if gu_choices:
        try:
            from .collab.cards import land_choices
            await asyncio.to_thread(
                land_choices, conv_id, gu_choices,
                fingerprint=str((gu_plan or {}).get("choicesFingerprint") or ""),
                gu_action=str((gu_plan or {}).get("action") or ""))
        except Exception as e:  # noqa: BLE001
            logger.warning("[orch] GU 问询卡落流失败 conv=%s: %s", conv_id, e)


def _resolve_gu_allowed(plan: Optional[dict]) -> Optional[set]:
    """GU 路线 → 具体工具名单(批丁): toolClasses.read ∪ rule.tools(fnmatch)。

    tools=None(规则未配置/passthrough/GU 故障)→ 不限面;
    tools=[](显式只读, 如 present-options/ask-one-question)→ 仅读类面——
    两者语义不同, 判别用 is None(零发版容错: 名单对注册表取交集)。
    """
    if not plan or plan.get("tools") is None:
        return None
    import fnmatch as _fm
    try:
        from ..arch_routes import req_agent as _ra
        names = set(_ra._ARCH_TOOLS)
    except Exception:  # noqa: BLE001
        return None
    from .governance.flow_policy import load_flow_policy
    try:
        pol = load_flow_policy()
    except Exception:  # noqa: BLE001
        return None
    read_pats = (((pol or {}).get("goal") or {}).get("toolClasses")
                 or {}).get("read") or []
    allowed = {n for n in names
               if any(_fm.fnmatch(n, p) for p in read_pats)}
    allowed |= {n for n in names
                if any(_fm.fnmatch(n, p) for p in (plan.get("tools") or []))}
    return allowed or None


def _record_prompt_sections(msgs: list, gear, plan: Optional[dict],
                            gu_allowed: Optional[set]) -> None:
    """A 测量面(批丁): 每回合提示分层字数遥测——供「哪层重→哪层失遵」
    数据闭环(关联台账 A4 遵从率)。只观测, 永不抛出。"""
    try:
        from .reflection import dataset as _ds
        sys_base = len(str((msgs[0] or {}).get("content") or "")) if msgs else 0
        sys_inj = sum(len(str(m.get("content") or "")) for m in msgs[1:]
                      if m.get("role") == "system")
        hist = sum(len(str(m.get("content") or "")) for m in msgs[1:]
                   if m.get("role") != "system")
        _ds.record("prompt_sections", systemBase=sys_base,
                   systemInjections=sys_inj, history=hist,
                   tier=int(getattr(gear, "tier", 1) or 1),
                   toolSurface=str(getattr(gear, "tool_surface", "full") or ""),
                   guAction=str((plan or {}).get("action") or ""),
                   guTools=len(gu_allowed or ()))
    except Exception:  # noqa: BLE001 — 遥测不碍主链
        pass


async def _chat_gate(data: dict, send: SendFn, now: int) -> Optional[dict]:
    """管线阶段① 会话闸门(行为等价抽取自 handle_chat)。

    绑定/归档闸/自愈/需求回填(感知层) + P1 泵恢复(惰性) + 用户消息落单流。
    失败已回错误事件 → None; 成功 → {conv_id, conv, question, last_user_msg_id}。
    """
    from ..arch_routes import req_agent
    from ..arch_routes import store
    from ..arch_routes.common import _ts

    _register_session_tools()
    history = data.get("messages") or []
    # 请求级项目上下文(项目库路由；WS 无 HTTP 查询串，按消息载荷设置)
    from ..arch_routes import ctx as _ctx
    from ..arch_routes.project import _resolve_project as _rp
    try:
        _proj = _rp((data.get("root") or "").strip(),
                    (data.get("project") or "").strip())
        if _proj and _proj.get("id"):
            _ctx.set_project(_proj["id"])
    except Exception:
        pass
    # 请求级需求上下文(供 plan agent「定稿」工具定位当前会话需求)
    try:
        _ctx.set_req(data.get("reqId") or "")
    except Exception:
        pass
    binding = bind_session(data, store, _ctx, store.next_id)
    if binding.error_event is not None:
        await send(binding.error_event)
        return None
    conv_id = binding.conv_id
    conv = binding.conv
    # P1 泵恢复(惰性): 服务重启丢内存泵/runner 作业 → 打开会话时核对收尾,
    # 终态任务补回执落库(否则互斥锁死会话且无结果; cv-153 实证)
    try:
        if any((t.get("status") or "") in ("running", "waiting_input")
               for t in store.TasksStore.of_conv(conv_id)):
            from ..arch_routes import exec_bridge as _eb
            _rec = await asyncio.to_thread(_eb.recover_conv_tasks, conv_id)
            for _tid, _jid, _rid2, _ag in (_rec or {}).get("repump", []):
                _eb._start_task_pump(conv_id, _tid, _jid, _rid2, _ag)
    except Exception as _rec_err:  # noqa: BLE001
        logger.warning("[kb-chat] 任务泵恢复失败 conv=%s: %s", conv_id, _rec_err)
    user_msgs = [m for m in history if m.get("role") == "user" and (m.get("content") or "").strip()]
    # v2 统一会话: 所有 user 消息落单流(agent=''); subagent 回复由泵以
    # agent=executor_type 标注落库。无信息流分离, 无命令符号。
    question = (user_msgs[-1].get("content", "") if user_msgs else "").strip()
    last_user_msg_id = ""
    for m in user_msgs[-1:]:
        last_user_msg_id = store.next_id("m")
        row = {"id": last_user_msg_id, "conversationId": conv_id,
               "role": "user", "time": now, "content": m.get("content", "")}
        # cv-197: 按钮触发的合成消息(/执行 等)落库带标记, 前端不回显
        # (标记常量登记于 collab.cards.MSG_FLAG_SYNTHETIC, 审计 D3)
        if data.get("synthetic"):
            from .collab.cards import MSG_FLAG_SYNTHETIC as _flag
            row["meta"] = json.dumps({_flag: True}, ensure_ascii=False)
        store.ConversationsStore.append_message(row)
    return {"conv_id": conv_id, "conv": conv, "question": question,
            "last_user_msg_id": last_user_msg_id}


async def _chat_route(data: dict, gate: dict, send: SendFn):
    """管线阶段② 收件人路由(行为等价抽取自 handle_chat)。

    transfer(收件人既定回复)/语境摘要审计回执 → 已处理(True);
    /指令与文字确认确定性直通(cv-152: 指令不落回模型) → 已处理(True);
    其余返回 (False, decision)——assign 契约随 decision 交给上下文段。
    """
    from ..arch_routes import store
    from ..arch_routes.common import _ts

    conv_id = gate["conv_id"]
    question = gate["question"]
    attach_to = str(data.get("attachTo") or "").strip()
    agent_pick = str(data.get("agent") or "").strip()
    digest = str(data.get("digest") or "").strip()[:2000]   # 语境摘要(用户选史生成)
    from ..arch_routes import exec_bridge as _eb
    decision = _route_decide(conv_id, question, attach_to, agent_pick, store, _eb,
                             digest=digest)
    final_b = decision.reply or None
    if final_b is not None:
        assistant_msg_id_b = store.next_id("m")
        store.ConversationsStore.append_message({
            "id": assistant_msg_id_b, "conversationId": conv_id,
            "role": "assistant", "time": _ts(), "content": final_b,
        })
        # 语境摘要审计回执: 折叠卡(meta.kind=digest_sent), 留"给执行器发过什么"的感知
        if decision.action == "transfer" and digest:
            store.ConversationsStore.append_message({
                "id": store.next_id("m"), "conversationId": conv_id,
                "role": "assistant", "time": _ts(), "content": digest,
                "meta": json.dumps({"kind": "digest_sent", "chars": len(digest)},
                                    ensure_ascii=False),
            })
        try:
            store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
        except Exception:  # noqa: BLE001
            pass
        await send({"type": "chat_start", "conversationId": conv_id,
                                   "requestId": "", "userMessageId": gate["last_user_msg_id"]})
        for i in range(0, len(final_b), 96):
            await send({"type": "chunk", "requestId": "",
                                       "delta": final_b[i:i + 96]})
            await asyncio.sleep(0.01)
        await send({"type": "done", "conversationId": conv_id,
                                   "content": final_b, "messageId": assistant_msg_id_b})
        return True, decision

    # ── 会话指令直通(批戊收编): 意图原语 × 焦点栈就近消解, 单一分派点。
    #    词表定意图(match_imperative)/焦点定指代(build_focus)/实体定状态。
    #    仅 chat 路由生效——转达/指派消息里的 /文本 是发给 subagent 的内容, 不拦。 ──
    if decision.action == "chat":
        from .governance.focus import build_focus, resolve_intent
        from .perception.commands import match_imperative
        imp = match_imperative(question)
        if imp:
            conv = gate["conv"]
            focus = await asyncio.to_thread(
                build_focus, conv_id, None,
                cached_phase=str(conv.get("flowState") or ""))
            res = resolve_intent(imp["intent"], focus)
            act = res.get("action")
            if act == "extract":
                await _run_direct_command("提取需求", conv, send, store,
                                          gate["last_user_msg_id"])
                return True, decision
            if act == "execute":
                # cv-199: 提案卡「运行」按钮的合成 /执行 跳过 LLM 拆步——
                # 点按钮期望即时建卡; 手打 /执行 保留计划编排(带相位反馈)
                await _run_direct_command("执行", conv, send, store,
                                          gate["last_user_msg_id"],
                                          executor=imp.get("executor") or "",
                                          skip_plan=bool(data.get("synthetic")))
                return True, decision
            if act == "confirm_task":
                frame = res.get("frame") or {}
                await _confirm_focus_task(conv, send, store,
                                          gate["last_user_msg_id"],
                                          str(frame.get("taskId") or ""),
                                          executor=imp.get("executor") or "",
                                          label=str(frame.get("label") or ""))
                return True, decision
            if act == "retry_failed":
                frame = res.get("frame") or {}
                await _retry_focus_task(conv, send, store,
                                        gate["last_user_msg_id"],
                                        str(frame.get("taskId") or ""))
                return True, decision
            # relay_hint / none: 焦点态提示(直通回执, 零 LLM)
            note = str(res.get("note") or "")
            if note:
                from ..arch_routes.common import _ts as _tsn
                msg_id = store.next_id("m")
                await send({"type": "chat_start",
                            "conversationId": conv_id, "requestId": "",
                            "userMessageId": gate["last_user_msg_id"]})
                await send({"type": "done", "conversationId": conv_id,
                            "content": note, "messageId": msg_id})
                return True, decision
            # fallthrough: 焦点无指代(如确认语无待确认卡) → 落 GU 对话链
    return False, decision
