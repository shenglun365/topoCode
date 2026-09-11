"""WebSocket routes for KB analysis agent, coding agent and unit-test execution."""
import asyncio
import json
import logging
import contextvars
import os
import re
import urllib.request
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .common import _ts, _id
from . import store
from . import exec_bridge

# executor 会话指令意图判定(分层, 见 PR-B 分流注释):
#   显式触发词(任意位置) > 短消息动词×宾语共现兜底 > 疑问/迟疑语气排除 > 答疑
_IMPL_EXPLICIT_RE = re.compile(
    r"执行方案|开始执行|继续执行|重新执行|执行本任务|执行任务|执行计划|"
    r"开始实施|继续实施|动手实现|提交执行|启动执行|跑起来|go ahead", re.I)
_IMPL_COOCUR_RE = re.compile(
    r"(执行|实施|启动|开跑|跑|运行|落地)[^?？!！。.]{0,8}"
    r"(方案|任务|计划|rqa?-\d+|coding)", re.I)
_INTENT_EXCLUDE_RE = re.compile(
    r"如何|怎么|怎样|为什么|是否|能否|可以不|还是|要不|或者|先[^?？!！。.]{0,6}(确认|检查|评估|讨论)"
    r"|吗[?？]|\?$", re.I)
_IMPL_BARE_RE = re.compile(r"(执行|实施|开始|继续|动手|开始吧|跑起来|go ahead)[!！。.]?", re.I)
_QA_TONE_RE = re.compile(r"[?？]|吗|如何|怎么|怎样|为什么|是否|能否|什么")


def _is_impl_intent(question: str) -> bool:
    """executor 会话消息是否为实施意图(纯函数, 供单测)。

    分层: ① 显式触发词(任意位置, 仍受疑问语气否决——「执行方案吗」是提问)
          ② 短消息(≤40字)动词×宾语共现兜底(「执行本任务」「跑一下方案」)
    否决: 疑问语气(如何/怎么/吗?…)/迟疑前置句(执行方案前先确认…)。
    """
    q = (question or "").strip()
    if not q:
        return False
    # 否决优先: 疑问/迟疑语气(对显式词同样生效——「执行方案吗」「执行方案前先确认…」)
    if _QA_TONE_RE.search(q) or _INTENT_EXCLUDE_RE.search(q):
        return False
    if _IMPL_EXPLICIT_RE.search(q):
        return True
    if len(q) <= 6 and _IMPL_BARE_RE.fullmatch(q):
        return True
    # 短消息动词×宾语共现兜底(「执行本任务」「跑一下方案」); 长消息不兜底
    if len(q) <= 40 and _IMPL_COOCUR_RE.search(q):
        return True
    return False


_AMEND_TRIG_RE = re.compile(
    r"调整(方案|需求|规约)|(方案|需求|规约)调整|修改(方案|需求|规约)")
_CONFIRM_TRIG_RE = re.compile(r"(确认执行|确认启动|确认，执行|确认。执行)[!！。.]?")
_STOP_TRIG_RE = re.compile(r"(停止执行|中止执行|终止执行)[!！。.]?")
_DIFF_TRIG_RE = re.compile(r"(查看差异|看下差异|查看 diff|看 diff)[?？!！。.]?", re.I)

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_TOOL_ROUNDS = 4

# 自由对话 LLM 调用 token 预算：思考型模型(reasoning_content)会先消耗大量 token 再输出正文，
# 预算过小会在推理阶段耗尽(finish_reason=length、content 为空)。
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
    from . import req_agent
    pref = req_agent.get_max_tokens_preference()
    if pref and pref > 0:
        return max(pref, _MIN_CHAT_MAX_TOKENS)
    return None


# P2/P3: 会话 agent 的 ctx.* + probe.run 工具注册(幂等)
from . import context_registry as _context_registry  # noqa: E402
_context_registry.register_chat_tools()
_context_registry.register_probe_tool()
_context_registry.register_coding_task_tools()
from . import evaluator as _evaluator  # noqa: E402
_evaluator.register_evaluator_tools()
from . import capability_mining as _cap_mining  # noqa: E402
_cap_mining.register_mining_tools()


@router.websocket("/ws/kb-analysis")
async def kb_analysis_ws(websocket: WebSocket):
    """需求分析 <=> KB agent 会话流(阶段A 自由对话流式 + 阶段D 统一会话持久化)。

    客户端消息:
      chat   { conversationId?, kind?, projectId?, reqId?, title?, messages:[{role,content}], modelId? }
             → streaming: chunk {requestId,text} ... done {requestId,conversationId,content} | error
      ping   → pong

    LLM 通道: 主后端 `llm.chat`(流式,经 ZMQ PUB 推送 chunk,按 requestId 过滤)优先;
    不可达/未配置 → 降级 `llm.sync`(一次性完整回复)。
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "chat":
                await _handle_kb_chat(websocket, data)

    except WebSocketDisconnect:
        logger.info("KB analysis WebSocket disconnected")
    except Exception as e:
        logger.exception(f"KB analysis WS error: {e}")


async def _handle_kb_chat(websocket: WebSocket, data: dict) -> None:
    """自由对话回合：持久化历史 → 发起 llm.chat 流式 → 逐字转发。"""
    from . import req_agent

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
    from . import ctx as _ctx
    from .project import _resolve_project as _rp
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
    # ---- 会话落库(阶段D 统一表) ----
    now = _ts()
    conv_id = data.get("conversationId") or ""
    if not conv_id:
        conv = store.ConversationsStore.create({
            "kind": kind, "projectId": project, "reqId": data.get("reqId") or "",
            "title": title, "status": "active", "meta": {"title": title},
        })
        conv_id = conv["id"]
    else:
        conv = store.ConversationsStore.get(conv_id)
        if conv and (conv.get("status") or "active") == "archived":
            # PR1: 归档会话只读——拒绝继续对话(读取/复制/提炼经 REST 与只读工具仍开放)
            await websocket.send_json({"type": "error", "requestId": request_id,
                                       "message": "会话已归档(只读)：不可继续对话。可复制到新会话或提炼引用。"})
            return
        # 会话↔需求绑定回填：提案卡产生后前端 send 会带 reqId——补写进会话记录,
        # 刷新/重开会话后 openConversation 携带 meta.reqId, 自然语言确认仍可用
        if conv and (data.get("reqId") or "") and not (conv.get("reqId") or ""):
            try:
                conv = store.ConversationsStore.update(conv_id, {"reqId": data["reqId"]})
            except Exception as e:  # noqa: BLE001
                logger.warning("[kb-chat] 回填 reqId 失败 conv=%s: %s", conv_id, e)
        if not conv:
            # 自愈降级（勿改回直接报 "conversation not found" 后 return）：
            # 浏览器 tab 内存里保留的 chatConvId 可能指向已不存在的会话
            # （服务重启/数据目录迁移/多实例并存导致库漂移）；若在此报错返回，
            # 前端不清 convId，该 tab 之后每条消息都会永远失败。
            # 历史消息全量在 payload.messages，新建会话零丢失；chat_start 会把
            # 新 conv_id 回传，前端 chatConvId 自动跟进。
            logger.warning("[kb-chat] conversation %s not found → fallback to fresh conversation", conv_id)
            conv = store.ConversationsStore.create({
                "kind": kind, "projectId": project, "reqId": data.get("reqId") or "",
                "title": title, "status": "active", "meta": {"title": title},
            })
            conv_id = conv["id"]
    # 请求级会话上下文(供 contract.propose 工具回填 origin.convId 证据链)
    try:
        _ctx.set_conv(conv_id)
    except Exception:
        pass
    # 需求绑定兜底: 载荷未带 reqId 时回退会话记录的既有绑定——
    # 刷新/重开会话后前端 activeReqId 丢失, NL「确认定稿」仍可凭记录绑定走通
    try:
        if not (data.get("reqId") or "") and conv and (conv.get("reqId") or ""):
            _ctx.set_req(conv["reqId"])
    except Exception:
        pass
    user_msgs = [m for m in history if m.get("role") == "user" and (m.get("content") or "").strip()]
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
    # PR-A 角色能力 enforcement: executor 角色会话 → 技能场景以角色配置为准、
    # 工具白名单收紧(空=全量); architect 角色不受限。
    _role = None
    try:
        _role = store.SessionRolesStore.get(
            (conv.get("roleId") or "architect")) if conv else None
        if _role and (_role.get("kind") or "") == "executor":
            role_skills = [str(x) for x in (_role.get("skills") or []) if x]
            if role_skills:
                skill_scenarios = role_skills
            _TOOL_WHITELIST.set([str(x) for x in (_role.get("tools") or []) if x] or None)
        else:
            _TOOL_WHITELIST.set(None)
    except Exception:  # noqa: BLE001
        _TOOL_WHITELIST.set(None)
    # PR-B executor 会话路由: 指令分级分流——
    #   ① 实施触发词(执行方案/开始执行/继续执行/执行/实施…) → runner 实施作业(桥接泵)
    #   ② 停止执行/查看差异 → 作业控制
    #   ③ 作业运行中的其他消息 → 提示经泵上行转达(等待输入场景)
    #   ④ 方案调整(调整方案/方案调整/调整需求…) → 回 architect 流程修订本会话绑定
    #      规约(req.amend, 不新建规约)——不走 executor 早退, 落到下方主流程
    #   ⑤ 其余 → tAgent 执行工程师答疑(tAgent 代码问答, agentic_loop + KB/代码工具)
    if _role and (_role.get("kind") or "") == "executor":
        question = (user_msgs[-1].get("content", "") if user_msgs else "").strip()
        impl_hit = _is_impl_intent(question)
        amend_hit = bool(_AMEND_TRIG_RE.search(question))
        stop_hit = bool(_STOP_TRIG_RE.fullmatch(question))
        diff_hit = bool(_DIFF_TRIG_RE.fullmatch(question))
        job_live = exec_bridge.is_running(conv_id)
        confirm_hit = bool(_CONFIRM_TRIG_RE.fullmatch(question))
        if stop_hit:
            final_b = exec_bridge.stop(conv_id)
        elif diff_hit:
            final_b = _exec_diff_text(conv)
        elif job_live:
            final_b = ("实施作业运行中——执行工程师的提问会直接出现在本会话，"
                       "直接发送消息即可转达（作业等待输入时自动送达）。"
                       "发送「停止执行」可中止，「查看差异」看当前改动。")
        elif confirm_hit or (impl_hit and not job_live):
            final_b = await _executor_implement(conv, _role, confirmed=confirm_hit)
        elif amend_hit:
            final_b = None  # 落到下方 architect 主流程(带 req.amend 收敛)
        else:
            exec_bridge.resume_if_job(conv_id, project_id=(conv.get("projectId") or ""))
            final_b = await _executor_chat_reply(conv, question, _role)
            if final_b and not exec_bridge.is_running(conv_id):
                # 答疑兜底引导(闭环): 消灭「想做实施却滑入答疑」的死循环——
                # 无论模型怎么答, 回复尾部都有通往实施的明确路径
                try:
                    from . import llm_dataset as _lds
                    _lds.record("exec_intent_miss", question=question[:200],
                                role=(_role or {}).get("id") or "")
                except Exception:  # noqa: BLE001
                    pass
                final_b += ("\n\n> ℹ️ 发送「**执行方案**」启动实施作业（开发+单元测试+整体编译验收）；"
                            "「方案调整」可修订本会话规约；「停止执行」「查看差异」控制作业。")
        if final_b is not None:
            assistant_msg_id_b = store.next_id("m")
            store.ConversationsStore.append_message({
                "id": assistant_msg_id_b, "conversationId": conv_id,
                "role": "assistant", "time": _ts(), "content": final_b,
            })
            try:
                # 会话状态流转: 执行会话获得 coding agent 首个回复 → 执行中(会话即流程)
                patch = {"reviewState": "unread"}
                if (conv.get("status") or "active") == "active":
                    patch["status"] = "running"
                store.ConversationsStore.update(conv_id, patch)
            except Exception:  # noqa: BLE001
                pass
            await websocket.send_json({"type": "chat_start", "conversationId": conv_id,
                                       "requestId": "", "userMessageId": last_user_msg_id})
            for i in range(0, len(final_b), 96):
                await websocket.send_json({"type": "chunk", "requestId": "",
                                           "delta": final_b[i:i + 96]})
                await asyncio.sleep(0.01)
            await websocket.send_json({"type": "done", "conversationId": conv_id,
                                       "content": final_b, "messageId": assistant_msg_id_b})
            return
        # 方案调整: 注入修订契约后走 architect 主流程(工具含 req.amend, 守卫照常)
        amend_contract = (
            "【方案调整模式】本会话为执行会话，绑定需求 "
            f"{(conv.get('reqId') or '')}。用户要求调整方案/规约——你现在是架构师："
            "与用户对话收敛调整内容，并用 req.amend 工具把调整落回该需求的方案字段"
            "(只更新既有规约，严禁调用 req.propose / req.finalize 新建规约)。"
            "调整完成后向用户复述变更点。")

    msgs = _build_chat_messages(root, project, history, diagram_skill=diagram_skill,
                                skill_scenarios=[str(s) for s in skill_scenarios])
    if _role and (_role.get("kind") or "") == "executor" and amend_hit:
        msgs.insert(1, {"role": "system", "content": amend_contract})

    # tAgent 角色模型路由(§9/B1)：按场景角色取模型；explicit 会话选择优先，
    # 无角色命中时 eff_model=None → 回退全局偏好(既有链不变)。护栏 R3：per-call 参数。
    from . import agent_roles as _roles
    eff_model = _roles.resolve_role_model(_roles.scenario_role(skill_scenarios), model_id)

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
        await websocket.send_json({"type": "chat_start", "conversationId": conv_id,
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
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001
            client_gone = True

    while tool_round <= _MAX_TOOL_ROUNDS:
        rid = _req_chat_stream(msgs, eff_model or req_agent.get_model_preference())
        if not rid:
            # 流式通道中断：带工具结果的累积上下文改走 llm.sync 收尾
            loop_fell_back = True
            await _ensure_chat_start()
            assistant_text = await _sync_with_tools(websocket, msgs, root, project, eff_model, tools_used=tools_used)
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
            assistant_text = await _sync_with_tools(websocket, msgs, root, project, eff_model, tools_used=tools_used)
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
                        websocket, rid, name, args, root, project, model_id=eff_model)
                    results.append(tr)
                    if not tr.get("ok"):
                        tool_errors[name] = tr.get("text", "")[:200]
                if results:
                    tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                    msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                    msgs.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
                loop_fell_back = True
                await _ensure_chat_start()
                assistant_text = await _sync_with_tools(websocket, msgs, root, project, eff_model, tools_used=tools_used)
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
                    websocket, rid, name, args, root, project, model_id=eff_model)
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
        assistant_text = await _sync_with_tools(websocket, msgs, root, project, eff_model, tools_used=tools_used)

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
                websocket, request_id, "req.propose", fence_args, root, project,
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
            corr = await _sync_with_tools(websocket, msgs, root, project, eff_model,
                                          max_rounds=3, tools_used=tools_used)
            corr = req_agent.strip_tool_blocks(corr or "")
            if corr:
                for i in range(0, len(corr), 24):
                    d = corr[i:i + 24]
                    visible += d
                    await send_ev({"type": "chunk", "requestId": request_id, "delta": d})
                final_content = visible

    # ── 防编造守卫: 声称的落库/执行动作必须有本回合真实工具调用佐证 ──
    claim, need = req_agent.fabricated_claim(final_content, tools_used)
    if claim:
        logger.warning("[kb-chat] 防编造守卫触发 conv=%s claim=%s need=%s", conv_id, claim, need)
        primary_need = need.split("|")[0] if need else ""
        failed_try = bool(primary_need) and primary_need in tool_errors
        try:
            from . import llm_dataset as _lds
            _lds.record("guard_hit", kind="fabricated", claim=claim, need=need,
                        toolFailed=failed_try,
                        toolError=tool_errors.get(primary_need, ""))
        except Exception:  # noqa: BLE001
            pass
        fail_line = (f"注意：{primary_need} 本回合已尝试执行但失败"
                     f"（{tool_errors.get(primary_need, '')[:160]}）——"
                     "请修正参数后重新调用，不要重复同样的参数形状。"
                     if failed_try else "")
        msgs.append({"role": "assistant", "content": final_content})
        msgs.append({"role": "user", "content": (
            f"[系统守卫] 你上述回复声称「{claim}」，但本回合并未实际调用 {need} "
            "（或引用了不存在的需求编号）——该表述不成立。" + fail_line +
            "现在二选一补救："
            f"① 确需产出 → 立即输出 [TOOL_CALL] 调用 {need.split('|')[0]} 完成真实落库；"
            "② 不应/无法产出 → 如实更正，说明该动作尚未发生。禁止再声称任何未执行的结果。")})
        corr = await _sync_with_tools(websocket, msgs, root, project, eff_model,
                                      max_rounds=2, tools_used=tools_used)
        corr = req_agent.strip_tool_blocks(corr or "")
        claim2, _ = req_agent.fabricated_claim(corr, tools_used)
        if corr and not claim2:
            for i in range(0, len(corr), 24):
                d = corr[i:i + 24]
                visible += d
                await send_ev({"type": "chunk", "requestId": request_id, "delta": d})
            final_content = visible
        else:
            # 修复2: 基于 final_content(含围栏失败通知等)追加, 不用 visible 重建——
            # 否则真实失败原因被丢弃, 用户只见误导性守卫文案(cv-71 案例)
            notice = req_agent.guard_notice(claim, need, tools_used, tool_errors)
            final_content = final_content + notice
            await send_ev({"type": "chunk", "requestId": request_id, "delta": notice})

    if final_content:
        assistant_msg_id = store.next_id("m")
        store.ConversationsStore.append_message({
            "id": assistant_msg_id, "conversationId": conv_id,
            "role": "assistant", "time": _ts(), "content": final_content,
        })
        try:  # PR1 双维度: 助手回合落库 → 正常未读(前端打开会话时回 read)
            store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
        except Exception:  # noqa: BLE001
            pass
        await send_ev({"type": "done", "conversationId": conv_id,
                                   "content": final_content, "messageId": assistant_msg_id})
        try:
            from . import llm_dataset as _lds
            _lds.record("llm_stream_done", ok=True,
                        chars=len(final_content),
                        latencyMs=int((__import__("time").time() - _turn_t0) * 1000),
                        toolRounds=tool_round, model=eff_model or "",
                        degraded=loop_fell_back)
        except Exception:  # noqa: BLE001
            pass
    else:
        try:
            store.ConversationsStore.update(conv_id, {"reviewState": "error"})
        except Exception:  # noqa: BLE001
            pass
        await send_ev({"type": "error", "requestId": request_id, "message": "LLM 未返回内容"})


async def _sync_with_tools(websocket, msgs, root, project, model_id, max_rounds: int = 4,
                           tools_used: Optional[set] = None) -> str:
    """llm.sync 降级通道：走统一工具调用循环(req_agent.run_tools_loop)，
    避免「LLM 输出 [TOOL_CALL] 后无结果」。返回最终纯文本。

    ⚠️ 降级通道原本全程零事件(用户数分钟零反馈)；现先发 status:sync 声明相变，
    再经 on_progress 把循环内 llm/tool 进度 marshal 回事件循环推送
    (run_tools_loop 在工作线程同步执行，websocket.send_json 非线程安全，
    必须 run_coroutine_threadsafe；连接已断时 send 抛异常需吞掉)。
    """
    from . import req_agent
    loop = asyncio.get_running_loop()

    def on_progress(event: str, detail: dict) -> None:
        if event == "tool" and detail.get("tool") and tools_used is not None:
            tools_used.add(detail["tool"])
        payload = {"type": "status", "phase": f"sync_{event}"}
        payload.update(detail or {})
        try:
            asyncio.run_coroutine_threadsafe(websocket.send_json(payload), loop)
        except Exception:
            pass

    try:
        await websocket.send_json({"type": "status", "phase": "sync"})
    except Exception:
        pass
    res = await asyncio.to_thread(
        req_agent.run_tools_loop, msgs,
        root=root, project=project, model_id=model_id,
        mode="chat", max_tokens=_chat_max_tokens(), max_rounds=max_rounds,
        on_progress=on_progress,
    )
    return res.get("content", "") if isinstance(res, dict) else ""


# PR-A 角色工具白名单(请求级 contextvar: executor 角色会话限制可调工具集)
_TOOL_WHITELIST = contextvars.ContextVar("arch_tool_whitelist", default=None)


def _check_tool_whitelist(name: str) -> Optional[str]:
    wl = _TOOL_WHITELIST.get()
    if not wl or name in wl:
        return None
    return f"角色工具白名单拒绝: {name} 不在本会话角色允许的工具集内"


async def _ws_send(websocket, payload: dict) -> None:
    """尽力发送: 连接断开时吞异常(工具进度不因断连炸出回合)。"""
    try:
        await websocket.send_json(payload)
    except Exception:  # noqa: BLE001
        pass


async def _run_tool_with_progress(websocket, request_id: str, name: str, args: dict,
                                  root: str, project: str,
                                  model_id: Optional[str] = None) -> Dict[str, str]:
    """执行单个 architect 工具，并向前端推送 tool_call/tool_result 进度事件。

    工具轮次(可能跨多轮 LLM 重算)期间前端零反馈是「检索中…」久挂的主因；
    这里在工具执行前后各推一条状态，前端据此显示实时进度而非静态等待。
    格式/参数类失败 → 聚焦修复外循环(req_agent.repair_tool_args)：
    极简上下文单独请求一次修正 arguments，成功则带修复参数重执行一次。
    """
    from . import context_registry, req_agent
    await _ws_send(websocket, {"type": "tool_call", "requestId": request_id, "tool": name})
    denied = _check_tool_whitelist(name)
    if denied:
        await _ws_send(websocket, {"type": "tool_result", "requestId": request_id,
                                   "tool": name, "ok": False, "summary": denied[:160]})
        return {"name": name, "text": denied, "ok": False}
    result = await asyncio.to_thread(req_agent.run_arch_tool, name, args, root, project)
    summary = req_agent.tool_result_text(name, result)
    ok = not (isinstance(result, dict) and result.get("error"))
    if not ok and req_agent._is_repairable_error(str(result.get("error"))):
        await _ws_send(websocket, {"type": "status", "phase": "arg_repair", "tool": name})
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
    await _ws_send(websocket, event)
    # P2 上下文注册表: 工具轨迹/产物 → 单元(会话级溯源)
    from . import ctx as _ctx
    try:
        context_registry.record_tool_call(_ctx.get_conv() or "", name, args, ok, summary)
    except Exception:
        pass
    return {"name": name, "text": summary, "ok": ok}


def _build_chat_messages(root, project, history, cap=20, diagram_skill: bool = False,
                         skill_scenarios: Optional[List[str]] = None):
    """组装 prompt: 能力文档(system) + 最近 N 条历史。diagram_skill 开启绘图增强(IR→代码)。

    skill_scenarios 非空 → 按场景注入语义资产 skill 文档（资产管理对话='extract'）。
    """
    from .req_agent import chat_system_prompt
    msgs = [{"role": "system", "content": chat_system_prompt(
        root, project, diagram_skill=diagram_skill, skill_scenarios=skill_scenarios)}]
    for m in history[-cap:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and (m.get("content") or "").strip():
            msgs.append({"role": m["role"], "content": m["content"]})
    return msgs


async def _iter_llm_events(request_id: str, idle_timeout: Optional[float] = None):
    """architect 进程内 ZMQ SUB 订阅主后端 llm.* 流(按 requestId 过滤)。"""
    from .zmq_stream import iter_llm_events
    async for e in iter_llm_events(request_id, idle_timeout=idle_timeout):
        yield e


def _req_chat_stream(msgs, model_id):
    """发起流式 llm.chat; 返回 requestId 或 None(降级)。"""
    from .req_agent import llm_chat_start
    return llm_chat_start(msgs, model_id=model_id, session_id="arch-req-chat", max_tokens=_chat_max_tokens())


# ── A7: tAgent 代码问答辅助(会话驱动: 会话→工程上下文→代码问答) ────────

async def _agent_chat_reply(conv: dict, content: str,
                            extra_context: str = "",
                            role: Optional[dict] = None) -> Optional[str]:
    """executor 会话对话直达 coding agent(tAgent 代码问答, agentic_loop + KB/代码工具)。

    会话绑定需求/项目 → root/project → chat_reply。KB 不可达/异常 → None
    (调用方仅落库回显用户消息)。阻塞调用放线程。
    """
    from . import tagent_chat
    from .execution import conv_root_project
    root, project = conv_root_project(conv or {})
    req_title = ""
    rid = (conv or {}).get("reqId") or ""
    if rid:
        r = store.RequirementsStore.get(rid)
        req_title = (r or {}).get("title", "")
    task_context = ""
    if rid:
        task_context = (f"执行会话绑定需求: {rid}"
                        + (f"「{req_title}」" if req_title else "")
                        + "\n说明: 用户正在执行会话中对话, 问题通常涉及该需求要实现的代码。")
    if extra_context:
        task_context = (task_context + "\n" + extra_context) if task_context else extra_context
    try:
        return await asyncio.to_thread(
            tagent_chat.chat_reply,
            question=content, root=root, project=project, task_context=task_context,
            model_id=(role or {}).get("modelId") or "")
    except Exception as e:
        logger.warning(f"[executor-chat] tAgent 聊天失败: {e}")
        return None


def _build_impl_instruction(rid: str) -> str:
    """绑定需求 → coding agent 实施指令(目标/方案/边界/验收/交付定义)。"""
    r = store.RequirementsStore.get(rid) or {}
    a = r.get("analysis") or {}
    parts = [f"# 实施任务：{r.get('title') or rid}（{rid}）"]
    if a.get("functionalScope"):
        parts.append("## 需求目标\n" + "\n".join(f"- {x}" for x in a["functionalScope"]))
    if a.get("designMd") or a.get("implementationPath"):
        parts.append("## 实现方案(遵循执行)\n"
                     + str(a.get("designMd") or a.get("implementationPath")))
    if a.get("allowedScope"):
        parts.append("## 允许增删改\n" + "\n".join(f"- {x}" for x in a["allowedScope"]))
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


def _executor_hint(role: Optional[dict]) -> Optional[dict]:
    """角色绑定的执行器配置 → runner 作业提示(model/端口等)。"""
    eid = (role or {}).get("executorId") or ""
    if not eid:
        return None
    try:
        from .agent_executors import load_executors
        for e in load_executors():
            if (e.get("id") or "") == eid:
                cfg = e.get("config") or {}
                models = e.get("models") or []
                return {"model": (models[0] if models else "") or cfg.get("model") or "",
                        "basePort": cfg.get("base_port"), "autoStart": cfg.get("auto_start"),
                        "baseUrl": cfg.get("base_url") or cfg.get("serve_url") or ""}
    except Exception:  # noqa: BLE001
        pass
    return None


_EXEC_PENDING_TTL_MS = 30 * 60 * 1000   # 执行预览有效期(超时重建)


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


def _executor_preview_card(conv: dict, instruction: str, pending: dict) -> str:
    """执行预览卡: 即将按哪版规约实施(方案摘要/边界/验收/分支), 待确认。"""
    rid = (conv or {}).get("reqId") or ""
    r = store.RequirementsStore.get(rid) or {}
    a = r.get("analysis") or {}
    import datetime as _dt
    upd = _dt.datetime.fromtimestamp((pending.get("specUpdatedAt") or 0) / 1000).strftime("%m-%d %H:%M") \
        if pending.get("specUpdatedAt") else "未知"
    design = str(a.get("designMd") or a.get("implementationPath") or "")[:400]
    parts = [
        "📋 **执行预览**（回复「**确认执行**」启动作业；「方案调整」可先修订规约）",
        f"- 需求：{r.get('title') or rid}（{rid}）",
        f"- 规约版本：{upd}" + ("（最新）" if not pending.get("stale") else "（⚠️ 预览后规约已变更，本卡已按最新规约刷新）"),
        f"- 分支：`{pending.get('branchName') or ''}`",
        f"- 允许改动 {len(a.get('allowedScope') or [])} 项 / 禁止改动 {len(a.get('forbiddenScope') or [])} 项 / 验收标准 {len(a.get('acceptance') or [])} 条",
        "- 交付：开发 + 单元测试 + 整体编译验收；过程中需确认/澄清会直接在本会话提问",
    ]
    if design:
        parts.append(f"\n**方案摘要**：{design}…")
    prev_jobs = (_meta_get(conv).get("execJobCount") or 0)
    if prev_jobs:
        parts.append(f"\n> ⚠️ 本会话已有 {prev_jobs} 次实施记录，本次将创建**新分支**重新实施。")
    return "\n".join(parts)


async def _executor_implement(conv: dict, role: Optional[dict], confirmed: bool = False) -> str:
    """实施触发词 → 两段式: 首次=执行预览(不建作业); 「确认执行」→ 真正建作业。

    防"污染/更新过的会话"误执行: 每次执行前都展示将依据的规约版本与摘要;
    预览后规约再变更(方案调整)则自动按最新规约刷新预览。
    """
    import time as _time
    from . import exec_bridge
    conv_id = (conv or {}).get("id") or ""
    rid = (conv or {}).get("reqId") or ""
    if not rid:
        return "本会话未绑定需求，无法启动实施（请通过需求定稿生成待执行会话）。"
    meta = _meta_get(store.ConversationsStore.get(conv_id) or conv)   # 现读 DB(传入行可能滞后)
    pending = meta.get("execPending") or {}
    spec_now = _spec_updated_at(rid)

    if confirmed and not pending:
        confirmed = False   # 无预览的「确认执行」→ 按实施触发处理(生成预览)
    if confirmed:
        if _time.time() * 1000 - (pending.get("createdAt") or 0) > _EXEC_PENDING_TTL_MS:
            pending = {}
        if pending and pending.get("specUpdatedAt") != spec_now:
            pending = {}   # 预览后规约已变(方案调整) → 需重新预览
        if not pending:
            instruction = _build_impl_instruction(rid)
            branch = f"exec/{rid.replace('RQ-', 'rq').lower()}-{_ts() % 100000}"
            pending = {"instruction": instruction, "branchName": branch,
                       "specUpdatedAt": spec_now, "createdAt": int(_time.time() * 1000)}
            meta["execPending"] = pending
            _meta_set(conv_id, meta)
            return _executor_preview_card(conv, instruction, pending) + \
                "\n\n(上一份预览已因规约变更/超时失效，已按最新规约刷新)"
        meta.pop("execPending", None)
        _meta_set(conv_id, meta)
        info = exec_bridge.start_implement(conv, pending["instruction"],
                                           executor_hint=_executor_hint(role),
                                           branch_name=pending.get("branchName") or "")
        try:
            m2 = _meta_get(conv)
            m2["execJobCount"] = (m2.get("execJobCount") or 0) + 1
            _meta_set(conv_id, m2)
        except Exception:  # noqa: BLE001
            pass
        return info

    # 非确认触发(执行方案/执行本任务…) → 生成/刷新预览
    instruction = _build_impl_instruction(rid)
    stale = bool(pending) and pending.get("specUpdatedAt") != spec_now
    branch = (pending.get("branchName") if pending and not stale else "") or \
        f"exec/{rid.replace('RQ-', 'rq').lower()}-{_ts() % 100000}"
    pending = {"instruction": instruction, "branchName": branch,
               "specUpdatedAt": spec_now, "createdAt": int(_time.time() * 1000),
               "stale": stale}
    meta["execPending"] = pending
    _meta_set(conv_id, meta)
    return _executor_preview_card(conv, instruction, pending)


def _exec_diff_text(conv: dict) -> str:
    """「查看差异」→ 当前作业相对基线的 diff 摘要。"""
    from . import exec_bridge
    info = exec_bridge.job_info(conv) or {}
    if not info.get("jobId"):
        return "暂无实施作业。发送「执行方案」开始实施。"
    d = exec_bridge._runner(f"/api/implement/{info['jobId']}/diff", timeout=30.0) or {}
    if not d.get("ok"):
        return "无法获取差异(作业不存在或 runner 不可达)。"
    files = "\n".join(f"- `{f}`" for f in (d.get("changedFiles") or [])[:30]) or "- (无)"
    return (f"**分支 `{info.get('branch', '')}` 相对基线的差异**"
            f"(+{d.get('addLines', 0)}/-{d.get('delLines', 0)} 行)\n{files}")


async def _executor_chat_reply(conv: dict, question: str, role: Optional[dict]) -> str:
    """执行工程师答疑(tAgent 代码问答) + 不可达兜底文案。"""
    reply = await _agent_chat_reply(conv, question, role=role)
    return reply or ("(执行工程师暂不可达: runner/LLM 网关无响应——稍后重试，"
                     "或在系统管理页检查执行器与模型连通性)")


def _push_session_message(session_id: str, role: str, content: str, tool=None):
    """写入单测会话消息并落库。"""
    msg = {
        "id": store.next_id("m"),
        "role": role,
        "time": _ts(),
        "content": content,
    }
    if tool:
        msg["tool"] = tool
    store.UnitTestSessionsStore.append_message({**msg, "sessionId": session_id})
    return msg


@router.websocket("/ws/unit-test")
async def unit_test_ws(websocket: WebSocket):
    """单测执行流(阶段 1 服务端模拟)。契约见 docs/architect/api-unit-test.md §4。"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "message":
                session_id = data.get("sessionId")
                content = data.get("content", "")
                session = store.UnitTestSessionsStore.get(session_id)
                if not session:
                    await websocket.send_json({"type": "error", "message": "Session not found"})
                    continue
                _push_session_message(session_id, "user", content)
                session = store.UnitTestSessionsStore.get(session_id)
                channel = session.get("channel", "cli")
                reply = (
                    "已接收指令。请回到左栏选择失败用例重新执行，或补充修复提示。"
                    if channel == "cli"
                    else f"收到，将基于报错「{content[:24]}」分析并修复，修复后可重新触发关联单测。"
                )
                msg = _push_session_message(session_id, "assistant", reply)
                store.UnitTestSessionsStore.update(session_id, {"updatedAt": _ts()})
                await websocket.send_json({"type": "message", "role": "assistant", "content": reply,
                                           "id": msg["id"], "time": msg["time"]})

            elif msg_type == "run":
                session_id = data.get("sessionId")
                test_ids = data.get("testIds", [])
                root = data.get("root") or ""
                session = store.UnitTestSessionsStore.get(session_id)
                if not session:
                    await websocket.send_json({"type": "error", "message": "Session not found"})
                    continue
                store.UnitTestSessionsStore.update(session_id, {"status": "running", "updatedAt": _ts()})
                await websocket.send_json({"type": "status", "sessionId": session_id, "status": "running"})

                stopped = False
                for test_id in test_ids:
                    test = store.UnitTestsStore.get(test_id)
                    if not test:
                        await websocket.send_json({
                            "type": "result", "testId": test_id, "status": "error",
                            "lastResult": {"passed": 0, "failed": 0, "error": "test not found", "note": "", "at": _ts()},
                        })
                        continue
                    name = test["name"] or test_id
                    script = test["scriptPath"] or ""
                    # 开始 tool 消息
                    tool_start = {"type": "run-test", "label": script or name, "detail": f"开始执行「{name}」", "ok": True}
                    start_msg = _push_session_message(session_id, "tool", "", tool_start)
                    await websocket.send_json({"type": "tool_call", "tool": tool_start, "id": start_msg["id"], "time": start_msg["time"]})
                    # 真实 subprocess 执行（自主路径·确定性），替代服务端模拟判定
                    from .test_runner import run_test_script
                    raw = await asyncio.to_thread(run_test_script, script, root)
                    last_result = {**raw, "at": _ts()}
                    status = "passed" if raw.get("failed", 0) == 0 and raw.get("passed", 0) > 0 else "failed"
                    detail = (f"失败: {raw['error']}" if status == "failed"
                              else f"通过: {raw.get('passed', 0)} 用例")
                    store.UnitTestsStore.update(test_id, {"status": status, "lastResult": last_result, "updatedAt": _ts()})
                    store.UnitTestSessionsStore.update(session_id, {"updatedAt": _ts()})
                    await websocket.send_json({"type": "result", "testId": test_id, "status": status, "lastResult": last_result})
                    tool_end = {"type": "run-test", "label": script or name, "detail": detail, "ok": status == "passed"}
                    end_msg = _push_session_message(session_id, "tool", "", tool_end)
                    await websocket.send_json({"type": "tool_call", "tool": tool_end, "id": end_msg["id"], "time": end_msg["time"]})

                # 汇总
                session = store.UnitTestSessionsStore.get(session_id)
                failed = ok_count = 0
                for tid in test_ids:
                    t = store.UnitTestsStore.get(tid)
                    if not t:
                        continue
                    if t["status"] == "failed":
                        failed += 1
                    elif t["status"] == "passed":
                        ok_count += 1
                summary = (f"本轮执行完成：{ok_count} 通过 / {failed} 失败，"
                           "可在对话中要求 agent 修复后重试。") if failed else f"本轮执行全部通过({ok_count})。"
                msg = _push_session_message(session_id, "assistant", summary)
                terminate_status = "done" if not stopped else "stopped"
                store.UnitTestSessionsStore.update(session_id, {"status": terminate_status, "updatedAt": _ts()})
                await websocket.send_json({"type": "message", "role": "assistant", "content": summary,
                                           "id": msg["id"], "time": msg["time"]})
                await websocket.send_json({"type": "status", "sessionId": session_id, "status": terminate_status})

            elif msg_type == "stop":
                session_id = data.get("sessionId")
                store.UnitTestSessionsStore.update(session_id, {"status": "stopped", "updatedAt": _ts()})
                await websocket.send_json({"type": "status", "sessionId": session_id, "status": "stopped"})

    except WebSocketDisconnect:
        logger.info("Unit-test WebSocket disconnected")


# ── Runner 任务树进度事件代理（A2：同源转发，前端免直连 :3458）──────

def _bus_ws_url() -> str:
    base = (os.environ.get("BROKER_BASE_URL") or "http://127.0.0.1:3486").rstrip("/")
    return base.replace("https://", "wss://").replace("http://", "ws://") + "/ws/agent-bus"


@router.websocket("/ws/agent-bus")
async def agent_bus_ws(websocket: WebSocket):
    """代理 agent-bus broker WS 到前端(同源 + 鉴权；监控页总线事件流)。

    - broker → 前端：`{type: "message", message}`(新消息，原样转发)；
    - 前端 → broker：`{type: "ping"}`(keepalive，broker 回 pong)；
    - 连接时：先发 `{type: "state", messages: [最近20条]}` 对齐(消除订阅竞态)。
    broker 不可达 → 推一条 error 后关闭。
    """
    await websocket.accept()
    try:
        import websockets
    except Exception as e:  # noqa: BLE001
        await websocket.send_json({"type": "error", "message": f"websockets 不可用: {e}"})
        await websocket.close()
        return

    url = _bus_ws_url()
    try:
        bus_ws = await asyncio.wait_for(websockets.connect(url), timeout=5)
    except Exception as e:  # noqa: BLE001
        logger.warning("[agent-bus] broker WS 不可达(%s): %s", url, e)
        await websocket.send_json({"type": "error", "message": "agent-bus broker 不可达"})
        await websocket.close()
        return

    # 初始同步：最近 20 条消息(监控页立即可见历史)
    try:
        base = (os.environ.get("BROKER_BASE_URL") or "http://127.0.0.1:3486").rstrip("/")
        with urllib.request.urlopen(f"{base}/api/agent-bus/messages?limit=20", timeout=3) as resp:
            body = json.loads(resp.read().decode())
        await websocket.send_json({"type": "state",
                                   "messages": (body or {}).get("data") or []})
    except Exception:  # noqa: BLE001
        pass

    async def _relay_broker_to_client() -> None:
        try:
            async for raw in bus_ws:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode()
                await websocket.send_text(raw)  # 原样转发 {type: "message", message}
        except Exception:  # noqa: BLE001
            pass

    async def _relay_client_to_broker() -> None:
        try:
            while True:
                data = await websocket.receive_json()
                if (data or {}).get("type") == "ping":
                    await bus_ws.send(json.dumps({"type": "ping"}))
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass

    relay_out = asyncio.create_task(_relay_broker_to_client())
    relay_in = asyncio.create_task(_relay_client_to_broker())
    try:
        await asyncio.wait({relay_out, relay_in}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (relay_out, relay_in):
            t.cancel()
        try:
            await bus_ws.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass
