"""回合编排器(agent 内核) — KB 对话回合全管道。

P2 自 websocket._handle_kb_chat 机械迁入(逐字节保真, 仅接缝替换):
  gate(会话闸门, agent.perception.gate) → route(收件人路由, agent.perception.router)
  → cognition(消息装配/流式循环/降级) → fence(提案/任务围栏代落)
  → reflection(路由纠偏/意图追问/防编造守卫) → persist(单流落库 + done)。

websocket.py 仅保留 WS 适配器(事件形状契约冻结, CONV-04)。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Callable, Awaitable, Dict, List, Optional

from .perception.gate import bind_session
from .perception.intent import GENERIC_EXEC_RE as _GENERIC_EXEC_RE
from .perception.router import decide as _route_decide

logger = logging.getLogger(__name__)

SendFn = Callable[[dict], Awaitable[None]]

_MAX_TOOL_ROUNDS = 4


# 默认传 None 由主后端按 model_configs.max_tokens(设置中可配，如 32000)；也可经 KB 侧 `llm.maxTokens` 覆盖。
_MIN_CHAT_MAX_TOKENS = 8192

# 自由对话流式(ZMQ SUB)空闲超时：连续这么久收不到本 requestId 的任何事件(chunk/done/error)
# 即判定流中断(主后端/llm 服务重启、任务取消、瞬时断连)，降级 llm.sync 一次性收尾，
# 避免前端「知识库检索中…」永久挂起、内容始终不返回。
_STREAM_IDLE_TIMEOUT_S = 60.0

# ── LLM chunk 实时转发过滤器 ─────────────────────────────────────────────
# 旧实现整轮缓冲 round_text、结束后才 24 字符假流式重发——LLM 生成期间(可长达
# 数十秒)前端零反馈，用户感知为「处理完成后还要等很久才有消息」。
# 现改为边生成边转发，但必须剔除 [TOOL_CALL] 块(不可展示)：命中疑似标记后
# 停止本轮实时转发(余量在回合结束时按 strip 后文本对齐补发)。
import re as _re
_LIVE_SUSPECT = _re.compile(r'(?:^|\n)[ \t]*```|\[?\s*TOOL_CALL(?![\w])')
_LIVE_TOOL_HINT = _re.compile(r'\[?\s*TOOL_CALL(?![\w])')
_LIVE_HOLD_BACK = 24
_LIVE_FENCE_PROBE = 32   # 围栏后需积累的判定字符数(区分代码块与工具块围栏前缀)


class _LiveForward:
    """单轮 LLM 输出的实时转发状态机：
    - 普通文本 → 放行(留尾部 holdback 防标记被截断)；
    - markdown 代码围栏 → 积累 _LIVE_FENCE_PROBE 字符判定：其后出现 TOOL_CALL
      → 从围栏起静默(工具块不可展示)；否则是普通代码块 → 放行继续；
    - 直接命中 TOOL_CALL 标记 → 自标记起静默至本轮结束。"""

    def __init__(self):
        self.buf = ""          # 待判定缓冲(含末尾 holdback)
        self.blocked = False   # 命中工具块 → 本轮停止实时转发
        self.emitted = ""      # 本轮已实时发出的文本

    def _emit(self, out: list, text: str) -> None:
        out.append(text)
        self.emitted += text

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self.buf += delta
        out: list = []
        while not self.blocked:
            m = _LIVE_SUSPECT.search(self.buf)
            if not m:
                break
            is_fence = m.group(0).lstrip().startswith("`")
            if is_fence:
                after = self.buf[m.end():]
                if len(after) < _LIVE_FENCE_PROBE:
                    break              # 判定字符不足 → 等下一段输入
                if _LIVE_TOOL_HINT.search(after[:_LIVE_FENCE_PROBE]):
                    self._emit(out, self.buf[:m.start()])
                    self.buf = self.buf[m.start():]
                    self.blocked = True
                    break
                # 普通代码块 → 放行围栏本身，继续扫描其后内容
                self._emit(out, self.buf[:m.end()])
                self.buf = self.buf[m.end():]
                continue
            # 直接 TOOL_CALL 标记(可能带 [ 前缀) → 自标记起静默
            self._emit(out, self.buf[:m.start()])
            self.buf = self.buf[m.start():]
            self.blocked = True
            break
        if not self.blocked and len(self.buf) > _LIVE_HOLD_BACK:
            cut = len(self.buf) - _LIVE_HOLD_BACK
            self._emit(out, self.buf[:cut])
            self.buf = self.buf[cut:]
        return "".join(out)

    def flush(self, stripped_final: str) -> str:
        """回合结束：按 strip_tool_blocks 后的最终文本对齐补发余量。"""
        core = self.emitted.strip()
        rem = stripped_final
        if core and stripped_final.startswith(core):
            rem = stripped_final[len(core):]
        elif core and core in stripped_final:
            rem = stripped_final.split(core, 1)[-1]
        self.emitted += rem
        return rem


def _chat_max_tokens() -> Optional[int]:
    """读 KB 侧 `llm.maxTokens` 偏好(与 llm.modelId 同源)；未配置返回 None → 主后端用模型配置。
    覆盖值做过小保护，避免思考型模型在推理阶段耗尽 token 产出空正文。"""
    from ..arch_routes import req_agent
    pref = req_agent.get_max_tokens_preference()
    if pref and pref > 0:
        return max(pref, _MIN_CHAT_MAX_TOKENS)
    return None


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
    """会话指令直通(v2): /定稿 → finalize(门禁+幂等); /执行 → ready 规约建任务卡。
    @执行器 前缀显式指定执行器; 回执落库+done 事件与常规回合同形;
    specReady meta 供前端渲染[一键建卡]动作。"""
    from .perception import commands as _cmds
    from ..arch_routes.common import _ts
    conv_id = conv["id"]
    meta = None
    if cmd == "定稿":
        res = _cmds.run_finalize(conv)
        if not res.get("ok"):
            content = f"⚠️ {res.get('error') or '定稿失败'}"
        else:
            content = (f"✅ **规约已确认**：`{res['reqId']}` v{res.get('ver')}（ready，可执行）"
                       "——发送 `/执行` 建任务卡。")
            meta = {"kind": "specReady", "requirementId": res.get("reqId"),
                    "ver": res.get("ver")}
    elif cmd == "执行":
        res = _cmds.run_execute(conv, executor_id=executor)
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
    """自由对话回合：持久化历史 → 发起 llm.chat 流式 → 逐字转发。"""
    from ..arch_routes import req_agent
    from ..arch_routes import store
    from ..arch_routes.common import _ts

    now = _ts()

    _register_session_tools()
    history = data.get("messages") or []
    if not history and data.get("content"):
        history = [{"role": "user", "content": data.get("content", "")}]
    model_id = data.get("modelId") or data.get("model") or ""
    project = (data.get("project") or "").strip()
    root = (data.get("root") or "").strip()
    kind = data.get("kind") or "chat"
    title = data.get("title") or ""
    diagram_skill = bool(data.get("diagramSkill") or data.get("diagram_skill"))

    # 请求级项目上下文(项目库路由；WS 无 HTTP 查询串，按消息载荷设置)
    from ..arch_routes import ctx as _ctx
    from ..arch_routes.project import _resolve_project as _rp
    try:
        _proj = _rp(root, project)
        if _proj and _proj.get("id"):
            _ctx.set_project(_proj["id"])
    except Exception:
        pass
    # 请求级需求上下文(供 plan agent「定稿」工具定位当前会话需求)
    try:
        _ctx.set_req(data.get("reqId") or "")
    except Exception:
        pass
    # ---- 会话闸门(感知层): 绑定/归档闸/自愈/需求回填 ----
    binding = bind_session(data, store, _ctx, store.next_id)
    if binding.error_event is not None:
        await send(binding.error_event)
        return
    conv_id = binding.conv_id
    conv = binding.conv
    # P1 泵恢复(惰性): 服务重启丢内存泵/runner 作业 → 打开会话时核对收尾,
    # 终态任务补回执落库(否则互斥锁死会话且无结果; cv-153 实证)
    try:
        if any((t.get("status") or "") in ("running", "waiting_input")
               for t in store.TasksStore.of_conv(conv_id)):
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
        store.ConversationsStore.append_message({
            "id": last_user_msg_id, "conversationId": conv_id,
            "role": "user", "time": now, "content": m.get("content", ""),
        })

    # ---- 上下文: 能力文档 + 历史(带软拒绝范围) + 按场景 skill 文档 ----
    skill_scenarios = data.get("skillScenarios") or []
    if not isinstance(skill_scenarios, list):
        skill_scenarios = []
    # ---- v2 subagent 路由(感知层): transfer 提前收尾 / assign 注入契约 / chat ----
    from ..arch_routes import exec_bridge as _eb
    attach_to = str(data.get("attachTo") or "").strip()
    agent_pick = str(data.get("agent") or "").strip()
    digest = str(data.get("digest") or "").strip()[:2000]   # 语境摘要(用户选史生成)
    decision = _route_decide(conv_id, question, attach_to, agent_pick, store, _eb,
                             digest=digest)
    final_b = decision.reply or None
    assign_contract = decision.contract or None
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
                                   "requestId": "", "userMessageId": last_user_msg_id})
        for i in range(0, len(final_b), 96):
            await send({"type": "chunk", "requestId": "",
                                       "delta": final_b[i:i + 96]})
            await asyncio.sleep(0.01)
        await send({"type": "done", "conversationId": conv_id,
                                   "content": final_b, "messageId": assistant_msg_id_b})
        return

    # ── 会话指令直通(v2): /定稿 /执行 确定性执行不经 LLM(cv-152 教训: 指令落回
    #    模型会引用 v1 旧契约(coding.task.execute)死胡同)。仅 chat 路由生效——
    #    转达/指派消息里的 /文本 是发给 subagent 的内容, 不拦。 ──
    if decision.action == "chat":
        from .perception.commands import match_command as _cmd_match
        _cmd = _cmd_match(question)
        if _cmd:
            await _run_direct_command(_cmd["cmd"], conv, send, store, last_user_msg_id,
                                      executor=_cmd.get("executor") or "")
            return
        # 文字确认(卡片确认同义路径): 有待确认卡才拦——否则「确认」是普通对话
        from .perception.commands import match_confirm as _confirm_match, \
            has_pending_task as _cmds_has_pending
        _conf = _confirm_match(question)
        if _conf and _cmds_has_pending(conv_id):
            await _run_direct_confirm(conv, send, store, last_user_msg_id,
                                      executor=_conf.get("executor") or "")
            return

    # tAgent 角色模型路由(§9/B1)：按场景角色取模型；explicit 会话选择优先，
    # 无角色命中时 eff_model=None → 回退全局偏好(既有链不变)。护栏 R3：per-call 参数。
    from ..arch_routes import agent_roles as _roles
    eff_model = _roles.resolve_role_model(_roles.scenario_role(skill_scenarios), model_id)

    # 模型能力档案懒探测(后台执行不阻塞): 无档案模型首轮触发, 探测落档后
    # 后续回合 system 按 tier 分级(小模型收紧预算, 大模型放开)
    try:
        from ..arch_routes import model_profile as _mp
        _mp.get_profile_or_lazy(eff_model or model_id or "")
    except Exception:  # noqa: BLE001
        pass

    # ── 分析挡位(会话级 analysisMode): strict=需求分析→规约→任务 | quick=轻整理直出任务卡 ──
    try:
        _mode = str((conv or {}).get("analysisMode") or "strict").strip() or "strict"
    except Exception:  # noqa: BLE001
        _mode = "strict"
    msgs = _build_chat_messages(root, project, history, diagram_skill=diagram_skill,
                                skill_scenarios=[str(s) for s in skill_scenarios],
                                model_id=eff_model or model_id or "")
    # v2 统一会话编排契约: 通用 agent 模式——能力分界 + 路由
    _spec_note = (
        "不要调用 req.propose/req.finalize/req.amend(快捷挡已退役)。"
        if _mode == "quick" else
        "严格挡: 先 req.propose 产规约并 /定稿, 再 task.propose 建卡(req.* 规约工具本挡可用)。")
    msgs.insert(1, {"role": "system", "content":
        "【工作模式(通用 agent 路由)】你是 architect 外循环(编排者)。可调度资源: "
        "A. 你自己(知识/分析面): KB 架构资产检索、需求澄清与方案设计、数据资产、"
        "图/命名/契约/验收等结构化分析。 "
        "B. coding subagent(cline/opencode/codex, 通用执行 agent): 完整的 shell/文件/"
        "读写代码/编译运行能力——代码实现、环境检测、编译构建、文件统计/批量处理、"
        "跑命令、写脚本、任何需要直接对源码或环境动手的通用任务, 一律交给他, "
        "调用 task.propose 创建任务卡(title + instruction 写实质内容: 目标/方案要点/"
        "边界/验收; 工作环境与 DoD 系统注入不必重复), 用户确认后执行。 "
        "路由原则: 用户的问题不需要本项目知识库就能动手的(如「检测编译环境」"
        "「统计文件数」「跑个脚本」)→ task.propose, 不要用 KB 检索话术推给用户; "
        "需要项目上下文/架构语义的 → 你自己分析。 "
        "执行期间 subagent 的提问/进展/完成会以消息进入本会话, 用户直接回复即转达。"
        + _spec_note})
    if assign_contract:
        msgs.insert(1, {"role": "system", "content": assign_contract})
    # 挡位指引注入独立 system 消息(最后插入 → 恒在 msgs[1]; 不进块注册表, 等价模式不变)
    try:
        from .cognition.prompt import gear_guidance
        msgs.insert(1, {"role": "system", "content": gear_guidance(_mode)})
    except Exception:  # noqa: BLE001
        pass
    # ── 规约草稿延续: 会话有未落库草稿(上轮草稿卡提取) → 注入下轮上下文,
    #    用户「继续调整」时模型基于草稿合并完善, 而非从零重写 ──
    try:
        _draft = ((conv.get("meta") or {}).get("specDraft")
                  if isinstance(conv.get("meta"), dict) else None)
        if isinstance(_draft, dict) and _draft and not str(conv.get("reqId") or ""):
            import json as _json
            msgs.insert(1, {"role": "system", "content": (
                "系统从上轮对话提取了规约草稿(尚未落库):\n```json\n"
                + _json.dumps(_draft, ensure_ascii=False)[:2000] + "\n```\n"
                "用户补充/调整意见时，请**合并该草稿**产出完整规约并调用 req.propose 落库"
                "(title/requirementMd/designMd/acceptanceMd)；不要丢弃草稿中已有的内容。")})
    except Exception:  # noqa: BLE001
        pass

    # ---- 连续多轮流式: 工具调用循环(architect 自持，最多 MAX_TOOL_ROUNDS 轮) ----
    request_id = None
    assistant_text = ""
    _turn_t0 = __import__("time").time()  # 回合时延采集(llm_stream_done)
    visible = ""            # 本次回合实际发出的 chunk 总量(实时转发+补发；done/落库以此为准)
    tool_round = 0
    loop_fell_back = False
    chat_start_sent = False

    async def _ensure_chat_start() -> None:
        """chat_start 幂等补发：流式路径正常发；降级路径(llm.sync)原样不发会让
        前端整段等待拿不到 conversationId/userMessageId——补发保证会话早绑定。"""
        nonlocal chat_start_sent
        if chat_start_sent:
            return
        await send({"type": "chat_start", "conversationId": conv_id,
                                   "requestId": request_id or "", "userMessageId": last_user_msg_id})
        chat_start_sent = True

    tools_used: set = set()  # 本回合实际执行的工具(防编造守卫佐证)
    tool_errors: dict = {}  # 工具名 → 失败摘要(守卫区分「编造」与「执行失败」)
    # 安全发送: 客户端断连后吞掉发送异常, 服务端继续消费流/守卫/落库——
    # 避免回合中断且历史整段丢失(实测断连即丢整回合)
    client_gone = False

    async def send_ev(payload: dict) -> None:
        nonlocal client_gone
        if client_gone:
            return
        try:
            await send(payload)
        except Exception:  # noqa: BLE001
            client_gone = True

    while tool_round <= _MAX_TOOL_ROUNDS:
        rid = _req_chat_stream(msgs, eff_model or req_agent.get_model_preference())
        if not rid:
            # 流式通道中断：带工具结果的累积上下文改走 llm.sync 收尾
            loop_fell_back = True
            await _ensure_chat_start()
            assistant_text = await _sync_with_tools(send, msgs, root, project, eff_model, tools_used=tools_used)
            break
        request_id = rid
        await send_ev({"type": "chat_start", "conversationId": conv_id,
                                   "requestId": rid, "userMessageId": last_user_msg_id})
        chat_start_sent = True
        round_text = ""
        round_ok = True
        live = _LiveForward()   # 本轮实时转发状态(工具块抑制)
        async for event_type, payload in _iter_llm_events(rid, idle_timeout=_STREAM_IDLE_TIMEOUT_S):
            if event_type == "chunk":
                text = payload.get("text") or ""
                round_text += text
                # 实时转发(剔除工具块)：LLM 生成即逐字可见，不再整轮沉默
                out = live.feed(text)
                if out:
                    visible += out
                    await send_ev({"type": "chunk", "requestId": rid, "delta": out})
            elif event_type == "reasoning":
                # 推理内容单独转发(不混入正文)；前端可折叠展示思考过程
                text = payload.get("text") or ""
                if text:
                    await send_ev({"type": "reasoning", "conversationId": conv_id,
                                               "delta": text})
            elif event_type == "done":
                round_text = payload.get("content") or round_text
                break
            elif event_type == "error":
                round_ok = False
                await send_ev({"type": "error", "requestId": rid,
                                           "message": payload.get("message", "")})
                break
        else:
            # 流自然结束(idle 超时)却未收到 done/error → ZMQ 流中断，标记降级 llm.sync 收尾
            round_ok = False
            logger.warning("[kb-chat] stream idle timeout rid=%s partial_chars=%s → llm.sync 收尾",
                           rid, len(round_text))
        # 本轮结束：补发 strip 工具块后的余量(holdback 尾巴/被静默段的合法文本)
        if round_ok:
            rem = live.flush(req_agent.strip_tool_blocks(round_text))
            if rem:
                visible += rem
                await send_ev({"type": "chunk", "requestId": rid, "delta": rem})
        if not round_ok:
            # 该轮流式出错但已带工具上下文：降级到 llm.sync 收尾，避免无结果
            loop_fell_back = True
            await _ensure_chat_start()
            assistant_text = await _sync_with_tools(send, msgs, root, project, eff_model, tools_used=tools_used)
            break

        # 本轮工具调用解析并在 architect 侧执行
        calls = req_agent.extract_tool_calls(round_text)
        if calls:
            # 达到最大工具轮次时也要执行本轮工具后用 llm.sync 收尾，避免空答案
            if tool_round >= _MAX_TOOL_ROUNDS:
                results: List[Dict[str, str]] = []
                for c in calls:
                    name = c.get("tool", "")
                    args = c.get("arguments", {})
                    tr = await _run_tool_with_progress(
                        send, rid, name, args, root, project, model_id=eff_model)
                    results.append(tr)
                    if not tr.get("ok"):
                        tool_errors[name] = tr.get("text", "")[:200]
                if results:
                    tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                    msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                    msgs.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
                loop_fell_back = True
                await _ensure_chat_start()
                assistant_text = await _sync_with_tools(send, msgs, root, project, eff_model, tools_used=tools_used)
                break
            tool_round += 1
            results: List[Dict[str, str]] = []
            for c in calls:
                name = c.get("tool", "")
                args = c.get("arguments", {})
                if name:
                    tools_used.add(name)
                logger.info("[req_agent] kb chat tool round=%s call=%s",
                            tool_round, name)
                tr = await _run_tool_with_progress(
                    send, rid, name, args, root, project, model_id=eff_model)
                results.append(tr)
                if not tr.get("ok"):
                    tool_errors[name] = tr.get("text", "")[:200]
            if results:
                tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                msgs.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
            # 工具结果回喂后的再生成无任何信号会让前端进度条「卡死」观感——显式报相
            await send_ev({"type": "status", "phase": "llm_round",
                                       "round": tool_round + 1})
            continue

        # 无工具调用 → 本轮即最终答案
        assistant_text = req_agent.strip_tool_blocks(round_text)
        break

    # 流式通道空响应(如思考型模型推理阶段耗尽 token 仅产出 reasoning_content)：
    # 带工具结果/上下文的累积上下文改走 llm.sync 收尾，避免「LLM 未返回内容」硬失败。
    if not loop_fell_back and not assistant_text and not visible:
        await _ensure_chat_start()
        assistant_text = await _sync_with_tools(send, msgs, root, project, eff_model, tools_used=tools_used)

    # 降级通道(llm.sync / 断流收尾)无逐字流 → 假流式补发；实时转发路径
    # visible 已含全部内容，跳过避免重复。断流后收尾的极端场景 partial
    # 可见 + 完整收尾文本 → 追加(轻微重复优于丢内容)。
    if assistant_text and (loop_fell_back or not visible):
        CHUNK_SIZE = 24
        for i in range(0, len(assistant_text), CHUNK_SIZE):
            d = assistant_text[i:i + CHUNK_SIZE]
            visible += d
            await send_ev({"type": "chunk", "requestId": request_id,
                                       "delta": d})

    # done/落库以「本次回合实际可见文本」为准(含工具轮前的说明文字，
    # 与前端逐字累积的内容严格一致，避免 done 覆盖造成跳变)。
    final_content = visible or assistant_text

    # ── proposal 围栏自动落库: 模型直接输出 ```proposal JSON → 服务端代执行 ──
    fence_args = req_agent.extract_proposal_fence(final_content)
    if fence_args and "req.propose" not in tools_used:
        logger.info("[kb-chat] proposal 围栏命中, 服务端代落库 conv=%s", conv_id)
        try:
            res = await _run_tool_with_progress(
                send, request_id, "req.propose", fence_args, root, project,
                model_id=eff_model)
            tools_used.add("req.propose")
            ok = bool(res.get("ok"))
            if not ok:
                tool_errors["req.propose"] = str(res.get("text", ""))[:200]
            notice = (f"\n\n✅ 已从提案草稿围栏自动落库：{str(res.get('text', ''))[:140]}"
                      if ok else
                      f"\n\n⚠️ 提案围栏落库失败：{str(res.get('text', ''))[:140]}")
            final_content += notice
            await send_ev({"type": "chunk", "requestId": request_id, "delta": notice})
        except Exception as e:  # noqa: BLE001
            logger.warning("[kb-chat] 围栏代落库失败: %s", e)

    # ── v2 任务载荷围栏代落: 模型把 task.propose 载荷写成 ```json 围栏(不发
    #    工具块, cv-150 实证) → 服务端解析代为落卡(轻门禁, 用户确认后执行)。
    #    与防编造守卫协同: 代落后 claim 的佐证工具成立 → 不出拦截卡。 ──
    task_fence = req_agent.extract_task_fence(final_content)
    if task_fence and "task.propose" not in tools_used:
        logger.info("[kb-chat] 任务载荷围栏命中, 服务端代落卡 conv=%s", conv_id)
        try:
            res = await _run_tool_with_progress(
                send, request_id, "task.propose", task_fence, root, project,
                model_id=eff_model)
            tools_used.add("task.propose")
            ok = bool(res.get("ok"))
            if not ok:
                tool_errors["task.propose"] = str(res.get("text", ""))[:200]
            notice = (f"\n\n📋 已从上文载荷自动创建**任务卡**（待确认）：{str(res.get('text', ''))[:160]}"
                      if ok else
                      f"\n\n⚠️ 任务卡自动创建失败：{str(res.get('text', ''))[:160]}")
            final_content += notice
            await send_ev({"type": "chunk", "requestId": request_id, "delta": notice})
        except Exception as e:  # noqa: BLE001
            logger.warning("[kb-chat] 任务围栏代落失败: %s", e)

    # ── v2 通用任务路由守卫: 用户指令是通用执行类 + architect 答复是「无法直接/
    #    需检索」推诿话术且未发起任务 → 纠偏一轮(交 coding subagent) ──
    try:
        _generic_user = _GENERIC_EXEC_RE.search(question or "")
        _deflect = bool(_generic_user) and not tools_used and (
            re.search(r"无法直接|无法凭|不能直接|无法给出|需要先(调用|检索|查询)",
                      final_content or ""))
        if _deflect and "task.propose" not in tools_used:
            logger.info("[kb-chat] 通用任务路由守卫触发 conv=%s q=%.60s", conv_id, question)
            msgs.append({"role": "assistant", "content": (final_content or "")[:2000]})
            msgs.append({"role": "user", "content": (
                "[系统路由] 用户的问题是可直接执行的通用任务(如环境检测/文件统计/编译/"
                "脚本), 不需要本项目知识库。你没有 shell 与文件能力, 但 coding subagent 有——"
                "请立即输出 task.propose 工具调用块把该任务交给 subagent, "
                '格式: [TOOL_CALL]{"tool":"task.propose","arguments":'
                '{"title":"…","instruction":"…"}}[/TOOL_CALL]; '
                "除工具块外只输出一句转述。不要再用「需要检索/无法直接」回答通用任务。")})
            corr = await _sync_with_tools(send, msgs, root, project, eff_model,
                                          max_rounds=3, tools_used=tools_used)
            corr = req_agent.strip_tool_blocks(corr or "")
            if corr:
                for i in range(0, len(corr), 24):
                    d = corr[i:i + 24]
                    visible += d
                    await send_ev({"type": "chunk", "requestId": request_id, "delta": d})
                final_content = visible
    except Exception as _ge:  # noqa: BLE001
        logger.warning("[kb-chat] 通用路由守卫异常: %s", _ge)

    # ── 意图未执行守卫: 宣布要调工具却收尾悬置 → 追问一轮 ──
    # 零工具回合: 任意意图短语即追问; 有工具回合: 最终答案段(assistant_text,
    # 即结束循环的无工具轮)宣布工具而未执行也追问——此前轮次的宣布已被
    # 真实工具调用兑现, 查全文会误报, 故只查末段
    pending_wait = "请等待" in final_content
    intent = ""
    if pending_wait:
        intent = "请等待"
    elif not tools_used:
        intent = req_agent.announced_tool_intent(final_content)
    elif assistant_text:
        intent = req_agent.announced_tool_intent(assistant_text)
    if intent:
            logger.warning("[kb-chat] 意图未执行守卫触发 conv=%s intent=%s", conv_id, intent)
            msgs.append({"role": "assistant", "content": final_content})
            msgs.append({"role": "user", "content": (
                "[系统守卫] 你宣布要调用工具，但本回合没有输出任何 [TOOL_CALL] 块就结束了回合"
                "——不会有任何\"等待\"发生，动作也没有发生。二选一："
                "① 立即输出你要执行的第一批工具调用块，"
                '格式: [TOOL_CALL]{"tool":"工具名","arguments":{…}}[/TOOL_CALL]，'
                "一次一个；除工具块外不要输出任何说明文字。"
                "② 若该动作确实不能现在执行（需要用户确认/信息不足），用一句话明确说明缺什么，"
                "不要宣布将要执行。")})
            corr = await _sync_with_tools(send, msgs, root, project, eff_model,
                                          max_rounds=3, tools_used=tools_used)
            corr = req_agent.strip_tool_blocks(corr or "")
            if corr:
                for i in range(0, len(corr), 24):
                    d = corr[i:i + 24]
                    visible += d
                    await send_ev({"type": "chunk", "requestId": request_id, "delta": d})
                final_content = visible

    # ── 防编造守卫(⑦ 反思组件, 策略矩阵驱动): 声称的落库/执行动作必须有本回合真实工具调用佐证 ──
    # 范式(守卫卡片化): 检出 → 消息 meta.guard 落库(不进 LLM 上下文) → 前端卡片
    # 给出可点击修复指令与 /指令 chips; 点击 → guard-repair REST 外循环/填入对话框。
    # 策略开关 guard 当前全档启用(t0-t4), 接线预留降级通道; intent_followup
    # 分档接线留 P6(现网默认路径行为锁定)。
    from .cognition.strategy import strategies_for_model
    _guard_on = strategies_for_model(eff_model or model_id or "").get("guard", True)
    claim, need = (req_agent.fabricated_claim(final_content, tools_used)
                   if _guard_on else (None, None))
    guard_meta = None
    if claim:
        # 成功路径的编号笔误更正: 本回合已真实 propose 落库, 但正文残留假编号
        # (cv-98 实证: 真实 RQ-47 / 正文 RQ-001) → 轻量更正回执替代拦截卡
        if claim.startswith("引用不存在的需求编号") and "req.propose" in tools_used:
            _fresh = store.ConversationsStore.get(conv_id) or {}
            real_rid = str(_fresh.get("reqId") or "")
            if real_rid:
                corr_note = (f"\n\n> ℹ️ 系统更正：正文中的需求编号为模型笔误，"
                             f"本回合真实落库编号为 `{real_rid}`(以系统回执为准)。")
                final_content += corr_note
                await send_ev({"type": "chunk", "requestId": request_id, "delta": corr_note})
                claim = ""    # 已真实落库, 不再出拦截卡
        if claim:
            logger.warning("[kb-chat] 防编造守卫触发 conv=%s claim=%s need=%s", conv_id, claim, need)
        primary_need = need.split("|")[0] if need else ""
        failed_try = bool(primary_need) and primary_need in tool_errors
        try:
            from ..arch_routes import llm_dataset as _lds
            _lds.record("guard_hit", kind="fabricated", claim=claim, need=need,
                        toolFailed=failed_try,
                        toolError=tool_errors.get(primary_need, ""))
        except Exception:  # noqa: BLE001
            pass
        guard_meta = {
            "kind": "guard",
            "claim": claim,
            "need": need or "",
            "failedTry": failed_try,
            "toolError": tool_errors.get(primary_need, "")[:200],
            "hasSpecJson": req_agent.extract_spec_payload(final_content) is not None,
            "suggestions": req_agent.guard_suggestions(
                claim, need, failed_try,
                has_spec_json=req_agent.extract_spec_payload(final_content) is not None),
            # 指令符号建议(与需求态相关): 绑定需求 draft → /定稿; ready → /执行
            "cmds": [],
        }
        if (guard_meta.get("hasSpecJson") and not failed_try
                and "req.propose" in (need or "") and "req.propose" not in tools_used):
            fixed = await _guard_autoland(conv, final_content)
            if fixed:
                tools_used.add("req.propose")
                final_content += fixed["notice"]
                await send_ev({"type": "chunk", "requestId": request_id,
                               "delta": fixed["notice"]})
                guard_meta["resolved"] = True
                guard_meta["resolvedSummary"] = fixed["summary"][:200]
                guard_meta["suggestions"] = []
                conv = store.ConversationsStore.get(conv_id) or conv

    draft_meta = _maybe_draft_card(conv, final_content, tools_used,
                                   eff_model or model_id or "", conv_id)

    if final_content:
        assistant_msg_id = store.next_id("m")
        msg_row = {"id": assistant_msg_id, "conversationId": conv_id,
                   "role": "assistant", "time": _ts(), "content": final_content}
        meta = guard_meta or draft_meta
        if meta:
            msg_row["meta"] = meta   # 守卫/草稿卡元数据: 落库可重建卡片, 不进 LLM 上下文
        store.ConversationsStore.append_message(msg_row)
        try:  # PR1 双维度: 助手回合落库 → 正常未读(前端打开会话时回 read)
            store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
        except Exception:  # noqa: BLE001
            pass
        done_ev = {"type": "done", "conversationId": conv_id,
                   "content": final_content, "messageId": assistant_msg_id}
        if guard_meta or draft_meta:
            done_ev["meta"] = guard_meta or draft_meta
        await send_ev(done_ev)
        try:
            from ..arch_routes import llm_dataset as _lds
            _lds.record("llm_stream_done", ok=True,
                        chars=len(final_content),
                        latencyMs=int((__import__("time").time() - _turn_t0) * 1000),
                        toolRounds=tool_round, model=eff_model or "",
                        degraded=loop_fell_back)
        except Exception:  # noqa: BLE001
            pass
    else:
        # 空返回: 带上失败上下文落库(turnError)+回传——错误必须完整可见且可刷新
        detail = "LLM 未返回内容"
        if tool_errors:
            detail += "；工具失败: " + "; ".join(
                f"{k}: {str(v)[:160]}" for k, v in list(tool_errors.items())[:3])
        if loop_fell_back:
            detail += "（流式通道中断，已走同步降级通道仍未产出）"
        try:
            store.ConversationsStore.append_message({
                "id": store.next_id("m"), "conversationId": conv_id,
                "role": "assistant", "time": _ts(), "content": f"❌ {detail}",
                "meta": json.dumps({"kind": "turnError"}, ensure_ascii=False)})
        except Exception:  # noqa: BLE001
            logger.warning("[kb-chat] turnError 落库失败 conv=%s", conv_id)
        try:
            store.ConversationsStore.update(conv_id, {"reviewState": "error"})
        except Exception:  # noqa: BLE001
            pass
        await send_ev({"type": "error", "requestId": request_id, "message": detail})


async def _guard_autoland(conv: dict, final_content: str) -> Optional[dict]:
    """guard 确定性纠错: 编造「已创建需求」+ 正文含可提取规约 → 系统代为落库。

    落库成功返回 {notice, summary}(调用方补记佐证/更新卡片); 失败返回 None
    (仍走卡片人工修复)。model 已被误导, 不宜再让用户多点一步。
    """
    from ..arch_routes.req_agent import extract_spec_payload, apply_spec_payload
    try:
        payload = extract_spec_payload(final_content or "")
        if not payload:
            return None
        res = await asyncio.to_thread(
            apply_spec_payload, payload,
            req_id=str((conv or {}).get("reqId") or ""),
            project=str((conv or {}).get("projectId") or ""), root="")
        if res.get("ok"):
            summary = str(res.get("summary") or "")
            notice = (f"\n\n{summary}（系统检测到上文声明了创建动作，"
                      "已从正文规约代为落库——以本回执编号为准）")
            return {"notice": notice, "summary": summary}
    except Exception as e:  # noqa: BLE001
        logger.warning("[kb-chat] guard 代落库失败 conv=%s: %s", (conv or {}).get("id"), e)
    return None


def _maybe_draft_card(conv: dict, final_content: str, tools_used: set,
                      model_id: str, conv_id: str) -> Optional[dict]:
    """草稿卡确定性收敛(分级适配 t2+): 规约 JSON 在正文而未调工具 → 暂存草稿卡。

    条件全满足才提取: 策略开启 / 本回合无 req.propose / 会话无绑定需求 /
    正文含规约围栏载荷。返回 draft_meta(payload 供前端卡片)或 None;
    同时落 conv.meta.specDraft(「继续调整」时注入下轮上下文合并完善)。
    """
    from ..arch_routes import store
    try:
        from ..arch_routes.adaptation import strategies_for_model
        from ..arch_routes.req_agent import extract_spec_payload
        if (strategies_for_model(model_id or "").get("draft_card")
                and "req.propose" not in tools_used
                and not str((conv or {}).get("reqId") or "")):
            payload = extract_spec_payload(final_content or "")
            if payload:
                cm = conv.get("meta") if isinstance(conv.get("meta"), dict) else {}
                cm = dict(cm or {})
                cm["specDraft"] = payload
                store.ConversationsStore.update(conv_id, {"meta": cm})
                try:
                    from ..arch_routes import llm_dataset as _lds
                    _lds.record("draft_card", ok=True, convId=conv_id, model=model_id or "")
                except Exception:  # noqa: BLE001
                    pass
                return {"kind": "specDraft", "payload": payload}
    except Exception as e:  # noqa: BLE001
        logger.warning("[kb-chat] 草稿卡提取失败 conv=%s: %s", conv_id, e)
    return None


async def _sync_with_tools(send: SendFn, msgs, root, project, model_id, max_rounds: int = 4,
                           tools_used: Optional[set] = None) -> str:
    """llm.sync 降级通道：走统一工具调用循环(req_agent.run_tools_loop)，
    避免「LLM 输出 [TOOL_CALL] 后无结果」。返回最终纯文本。

    ⚠️ 降级通道原本全程零事件(用户数分钟零反馈)；现先发 status:sync 声明相变，
    再经 on_progress 把循环内 llm/tool 进度 marshal 回事件循环推送
    (run_tools_loop 在工作线程同步执行，send 回调非线程安全，
    必须 run_coroutine_threadsafe；连接已断时 send 抛异常需吞掉)。
    """
    from ..arch_routes import req_agent
    loop = asyncio.get_running_loop()

    def on_progress(event: str, detail: dict) -> None:
        if event == "tool" and detail.get("tool") and tools_used is not None:
            tools_used.add(detail["tool"])
        payload = {"type": "status", "phase": f"sync_{event}"}
        payload.update(detail or {})
        try:
            asyncio.run_coroutine_threadsafe(send(payload), loop)
        except Exception:
            pass

    try:
        await send({"type": "status", "phase": "sync"})
    except Exception:
        pass
    res = await asyncio.to_thread(
        req_agent.run_tools_loop, msgs,
        root=root, project=project, model_id=model_id,
        mode="chat", max_tokens=_chat_max_tokens(), max_rounds=max_rounds,
        on_progress=on_progress,
    )
    return res.get("content", "") if isinstance(res, dict) else ""


async def _run_tool_with_progress(send: SendFn, request_id: str, name: str, args: dict,
                                  root: str, project: str,
                                  model_id: Optional[str] = None) -> Dict[str, str]:
    """执行单个 architect 工具，并向前端推送 tool_call/tool_result 进度事件。

    工具轮次(可能跨多轮 LLM 重算)期间前端零反馈是「检索中…」久挂的主因；
    这里在工具执行前后各推一条状态，前端据此显示实时进度而非静态等待。
    格式/参数类失败 → 聚焦修复外循环(req_agent.repair_tool_args)：
    极简上下文单独请求一次修正 arguments，成功则带修复参数重执行一次。
    """
    from ..arch_routes import context_registry, req_agent
    await send({"type": "tool_call", "requestId": request_id, "tool": name})
    result = await asyncio.to_thread(req_agent.run_arch_tool, name, args, root, project)
    summary = req_agent.tool_result_text(name, result)
    ok = not (isinstance(result, dict) and result.get("error"))
    if not ok and req_agent._is_repairable_error(str(result.get("error"))):
        await send({"type": "status", "phase": "arg_repair", "tool": name})
        fixed = await asyncio.to_thread(
            req_agent.repair_tool_args, name, args, str(result.get("error")),
            model_id=model_id)
        if isinstance(fixed, dict):
            args = fixed
            result = await asyncio.to_thread(req_agent.run_arch_tool, name, args, root, project)
            summary = req_agent.tool_result_text(name, result)
            ok = not (isinstance(result, dict) and result.get("error"))
            if ok:
                summary = f"(参数已自动修复) {summary}"
    event = {
        "type": "tool_result", "requestId": request_id, "tool": name,
        "ok": ok,
        "summary": summary[:160],
    }
    # 资产卡透传(评估报告等带资产引用的工具): 前端渲染可联动资产地图的卡片
    if isinstance(result, dict) and isinstance(result.get("assets"), list) and result["assets"]:
        event["assets"] = result["assets"][:12]
    await send(event)
    # P2 上下文注册表: 工具轨迹/产物 → 单元(会话级溯源)
    from ..arch_routes import ctx as _ctx
    try:
        context_registry.record_tool_call(_ctx.get_conv() or "", name, args, ok, summary)
    except Exception:
        pass
    return {"name": name, "text": summary, "ok": ok}


def _build_chat_messages(root, project, history, cap=20, diagram_skill: bool = False,
                         skill_scenarios: Optional[List[str]] = None,
                         model_id: str = ""):
    """组装 prompt(P4 委托 memory.working, 原文保真)。"""
    from .memory.working import build_chat_messages
    return build_chat_messages(root, project, history, cap=cap,
                               diagram_skill=diagram_skill,
                               skill_scenarios=skill_scenarios, model_id=model_id)


async def _iter_llm_events(request_id: str, idle_timeout: Optional[float] = None):
    """architect 进程内 ZMQ SUB 订阅主后端 llm.* 流(按 requestId 过滤)。"""
    from ..arch_routes.zmq_stream import iter_llm_events
    async for e in iter_llm_events(request_id, idle_timeout=idle_timeout):
        yield e


def _req_chat_stream(msgs, model_id):
    """发起流式 llm.chat; 返回 requestId 或 None(降级)。

    cv-156 实证: 函数体在早前重构中丢失(隐式 return None)——流式通道自
    9-13 起从未发起, 所有回合静默走同步降级(大提示词下小模型易空返回)。"""
    from ..arch_routes.req_agent import llm_chat_start
    return llm_chat_start(msgs, model_id=model_id or None,
                          session_id="arch-req-chat",
                          max_tokens=_chat_max_tokens())
