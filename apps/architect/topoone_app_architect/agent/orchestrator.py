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


async def _run_direct_confirm(conv: dict, send: SendFn, store,
                              user_msg_id: str, executor: str = "") -> None:
    """文字确认直通(P2): 确认语 → confirm_task(零 LLM), 与卡片按钮同门禁链。"""
    from .perception import commands as _cmds
    from ..arch_routes.common import _ts
    conv_id = conv["id"]
    res = await asyncio.to_thread(_cmds.run_confirm, conv, executor)
    if res.get("noPending"):
        # 无待确认卡: 回落普通对话(此处不该发生——调用方已查过, 竞态兜底)
        return
    if res.get("ok"):
        t = res.get("task") or {}
        content = (f"🚀 已确认任务「{t.get('title')}」（执行器 `{t.get('executorType')}`）"
                   "——开始执行，进展将在本会话同步。")
    else:
        content = f"⚠️ {res.get('receipt') or '确认失败'}"
    msg_id = store.next_id("m")
    await send({"type": "chat_start", "conversationId": conv_id,
                "requestId": "", "userMessageId": user_msg_id})
    await send({"type": "done", "conversationId": conv_id,
                "content": content, "messageId": msg_id})


async def _run_direct_command(cmd: str, conv: dict, send: SendFn, store,
                              user_msg_id: str, executor: str = "") -> None:
    """会话指令直通(v2): /提取需求 → 历史提取需求卡; /执行 → ready 规约建任务卡。
    @执行器 前缀显式指定执行器; 回执落库+done 事件与常规回合同形;
    specReady meta 供前端渲染[一键建卡]动作。"""
    from .perception import commands as _cmds
    from ..arch_routes.common import _ts
    conv_id = conv["id"]
    # cv-197: 直通链可含 LLM 拆步(最长 LLM_SYNC_TIMEOUT=300s)——零反馈即
    # 「卡死」观感; 状态事件 + 首尾日志补齐可观测性。
    logger.info("[direct-cmd] %s conv=%s 开始", cmd, conv_id)
    try:
        await send({"type": "status", "phase": "direct_cmd", "cmd": cmd})
    except Exception:  # noqa: BLE001
        pass
    meta = None
    if cmd == "提取需求":
        res = _cmds.run_extract_req(conv)
        logger.info("[direct-cmd] 提取需求 conv=%s 完成 ok=%s", conv_id, res.get("ok"))
        if not res.get("ok"):
            content = f"⚠️ {res.get('receipt') or res.get('error') or '提取失败'}"
        else:
            content = res.get("receipt") or "需求卡已提取。"
    elif cmd == "执行":
        res = _cmds.run_execute(conv, executor_id=executor)
        logger.info("[direct-cmd] 执行 conv=%s 完成 ok=%s", conv_id, res.get("ok"))
        if not res.get("ok"):
            content = f"⚠️ {res.get('receipt') or '建卡失败'}"
        else:
            t = res.get("task") or {}
            etag = f"（执行器 `{t.get('executorType')}`{('·' + executor) if executor else ''}）"
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

    # ---- ② 路由: transfer 收尾 / 直通指令 / 文字确认(命中即收束) ----
    handled, decision = await _chat_route(data, gate, send)
    if handled:
        return
    assign_contract = decision.contract or None

    # ---- ③ 上下文: 角色模型路由 + 懒探测 + 挡位 + 消息装配 ----
    eff_model, msgs, gear = _chat_context(data, gate, skill_scenarios, history,
                                          model_id, assign_contract)

    # ---- ④ 执行: 连续多轮流式(A 管线: 抽至 _run_llm_tool_loop) ----
    io = _TurnIO(send, conv_id, gate["last_user_msg_id"])
    tools_used: set = set()
    tool_errors: dict = {}
    loop = await _run_llm_tool_loop(io, conv_id, msgs, root, project,
                                    eff_model, model_id, tools_used, tool_errors,
                                    max_tool_rounds=gear.tool_rounds)

    # ---- ⑤⑥ 落库 + 终态事件(正常 done / 错误 turnError) ----
    await _chat_land(io, msgs, gate, conv, loop, eff_model, model_id,
                     root, project, tools_used, tool_errors)


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

    # ── 会话指令直通(v2): /定稿 /执行 确定性执行不经 LLM(cv-152 教训: 指令落回
    #    模型会引用 v1 旧契约(coding.task.execute)死胡同)。仅 chat 路由生效——
    #    转达/指派消息里的 /文本 是发给 subagent 的内容, 不拦。 ──
    if decision.action == "chat":
        from .perception.commands import match_command as _cmd_match
        _cmd = _cmd_match(question)
        if _cmd:
            await _run_direct_command(_cmd["cmd"], gate["conv"], send, store,
                                      gate["last_user_msg_id"],
                                      executor=_cmd.get("executor") or "")
            return True, decision
        # 文字确认(卡片确认同义路径): 有待确认卡才拦——否则「确认」是普通对话
        from .perception.commands import match_confirm as _confirm_match, \
            has_pending_task as _cmds_has_pending
        _conf = _confirm_match(question)
        if _conf and _cmds_has_pending(conv_id):
            await _run_direct_confirm(gate["conv"], send, store,
                                      gate["last_user_msg_id"],
                                      executor=_conf.get("executor") or "")
            return True, decision
    return False, decision
