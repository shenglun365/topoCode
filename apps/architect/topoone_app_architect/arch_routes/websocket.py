"""WebSocket routes for KB analysis agent, coding agent and unit-test execution."""
import asyncio
import json
import logging
import os
import urllib.request
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .common import _ts, _id
from . import store

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
    msgs = _build_chat_messages(root, project, history, diagram_skill=diagram_skill,
                                skill_scenarios=[str(s) for s in skill_scenarios])

    # tAgent 角色模型路由(§9/B1)：按场景角色取模型；explicit 会话选择优先，
    # 无角色命中时 eff_model=None → 回退全局偏好(既有链不变)。护栏 R3：per-call 参数。
    from . import agent_roles as _roles
    eff_model = _roles.resolve_role_model(_roles.scenario_role(skill_scenarios), model_id)

    # ---- 连续多轮流式: 工具调用循环(architect 自持，最多 MAX_TOOL_ROUNDS 轮) ----
    request_id = None
    assistant_text = ""
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
    while tool_round <= _MAX_TOOL_ROUNDS:
        rid = _req_chat_stream(msgs, eff_model or req_agent.get_model_preference())
        if not rid:
            # 流式通道中断：带工具结果的累积上下文改走 llm.sync 收尾
            loop_fell_back = True
            await _ensure_chat_start()
            assistant_text = await _sync_with_tools(websocket, msgs, root, project, eff_model, tools_used=tools_used)
            break
        request_id = rid
        await websocket.send_json({"type": "chat_start", "conversationId": conv_id,
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
                    await websocket.send_json({"type": "chunk", "requestId": rid, "delta": out})
            elif event_type == "reasoning":
                # 推理内容单独转发(不混入正文)；前端可折叠展示思考过程
                text = payload.get("text") or ""
                if text:
                    await websocket.send_json({"type": "reasoning", "conversationId": conv_id,
                                               "delta": text})
            elif event_type == "done":
                round_text = payload.get("content") or round_text
                break
            elif event_type == "error":
                round_ok = False
                await websocket.send_json({"type": "error", "requestId": rid,
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
                await websocket.send_json({"type": "chunk", "requestId": rid, "delta": rem})
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
                    results.append(await _run_tool_with_progress(
                        websocket, rid, name, args, root, project))
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
                results.append(await _run_tool_with_progress(
                    websocket, rid, name, args, root, project))
            if results:
                tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                msgs.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
            # 工具结果回喂后的再生成无任何信号会让前端进度条「卡死」观感——显式报相
            await websocket.send_json({"type": "status", "phase": "llm_round",
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
            await websocket.send_json({"type": "chunk", "requestId": request_id,
                                       "delta": d})

    # done/落库以「本次回合实际可见文本」为准(含工具轮前的说明文字，
    # 与前端逐字累积的内容严格一致，避免 done 覆盖造成跳变)。
    final_content = visible or assistant_text

    # ── 防编造守卫: 声称的落库/执行动作必须有本回合真实工具调用佐证 ──
    claim, need = req_agent.fabricated_claim(final_content, tools_used)
    if claim:
        logger.warning("[kb-chat] 防编造守卫触发 conv=%s claim=%s need=%s", conv_id, claim, need)
        msgs.append({"role": "assistant", "content": final_content})
        msgs.append({"role": "user", "content": (
            f"[系统守卫] 你上述回复声称「{claim}」，但本回合并未实际调用 {need} "
            "（或引用了不存在的需求编号）——该表述为编造，不成立。现在二选一补救："
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
                await websocket.send_json({"type": "chunk", "requestId": request_id, "delta": d})
            final_content = visible
        else:
            notice = (f"\n\n> ⚠️ 系统守卫：上述回复中「{claim}」的表述未经实际工具调用，不成立。"
                      "请重试，或改用界面操作（方案生成按钮/任务执行页）。")
            final_content = visible + notice
            await websocket.send_json({"type": "chunk", "requestId": request_id, "delta": notice})

    if final_content:
        assistant_msg_id = store.next_id("m")
        store.ConversationsStore.append_message({
            "id": assistant_msg_id, "conversationId": conv_id,
            "role": "assistant", "time": _ts(), "content": final_content,
        })
        await websocket.send_json({"type": "done", "conversationId": conv_id,
                                   "content": final_content, "messageId": assistant_msg_id})
    else:
        await websocket.send_json({"type": "error", "requestId": request_id, "message": "LLM 未返回内容"})


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


async def _run_tool_with_progress(websocket, request_id: str, name: str, args: dict,
                                  root: str, project: str) -> Dict[str, str]:
    """执行单个 architect 工具，并向前端推送 tool_call/tool_result 进度事件。

    工具轮次(可能跨多轮 LLM 重算)期间前端零反馈是「检索中…」久挂的主因；
    这里在工具执行前后各推一条状态，前端据此显示实时进度而非静态等待。
    """
    from . import context_registry, req_agent
    await websocket.send_json({"type": "tool_call", "requestId": request_id, "tool": name})
    result = await asyncio.to_thread(req_agent.run_arch_tool, name, args, root, project)
    summary = req_agent.tool_result_text(name, result)
    ok = not (isinstance(result, dict) and result.get("error"))
    event = {
        "type": "tool_result", "requestId": request_id, "tool": name,
        "ok": ok,
        "summary": summary[:160],
    }
    # 资产卡透传(评估报告等带资产引用的工具): 前端渲染可联动资产地图的卡片
    if isinstance(result, dict) and isinstance(result.get("assets"), list) and result["assets"]:
        event["assets"] = result["assets"][:12]
    await websocket.send_json(event)
    # P2 上下文注册表: 工具轨迹/产物 → 单元(会话级溯源)
    from . import ctx as _ctx
    try:
        context_registry.record_tool_call(_ctx.get_conv() or "", name, args, ok, summary)
    except Exception:
        pass
    return {"name": name, "text": summary}


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


@router.websocket("/ws/coding-agent")
async def coding_agent_ws(websocket: WebSocket):
    """coding-agent 会话流(代码问答聊天 + 落库；A7 起经 tAgent，不再对接 opencode)。

    注：
    - 任务执行(task.run)已迁移到 runner 流(POST /exec/{id}/run + WS /ws/trees/{id}/events)；
    - 对话(session.message)经 tAgent 代码问答(agentic_loop + KB/代码工具，见 tagent_chat.py)，
      按会话关联的执行任务解析 root/project 作为上下文。
    本 WS 仅保留会话创建/对话/停止。客户端消息:
      session.create  { exec, planTitle, keepContext?, root?, project? } → session_created { session }
      session.message { sessionId, content }                              → (assistant message) + message
      session.stop   { sessionId }                                       → status stopped
      ping                                                        → pong

    KB/LLM 不可达 → 无 assistant 回复，仅落库回显用户消息(降级)。
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "session.create":
                exec_data = data.get("exec", {})
                plan_title = data.get("planTitle", "")
                keep_context = bool(data.get("keepContext", True))
                root = (data.get("root") or data.get("execRoot") or "").strip()
                project_id = (data.get("project") or "").strip() or None
                # 请求级项目上下文(本连接后续消息/task.run 子任务继承)
                from . import ctx as _ctx
                from .project import _resolve_project as _rp
                try:
                    _proj = _rp(root, project_id)
                    if _proj and _proj.get("id"):
                        _ctx.set_project(_proj["id"])
                except Exception:
                    pass
                session_id = store.next_id("sess")
                now = _ts()
                session = {
                    "id": session_id,
                    "taskId": exec_data.get("id", ""),
                    "adapter": exec_data.get("adapter", "opencode"),
                    "status": "idle",
                    "keepContext": keep_context,
                    "artifacts": [],
                    "testResult": None,
                    "stats": {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0},
                    "createdAt": now,
                    "updatedAt": now,
                }
                store.AgentSessionsStore.create(session)
                init_msg = {
                    "id": store.next_id("m"),
                    "role": "user",
                    "time": now,
                    "content": f"创建会话 · 执行方案「{plan_title}」(任务 {exec_data.get('id', '')}, 第 {exec_data.get('runCount', 1)} 次)",
                }
                store.AgentSessionsStore.append_message({**init_msg, "sessionId": session_id})
                session["messages"] = [init_msg]
                # A7：会话仅落库；对话经 tAgent 代码问答(见 session.message)，不再对接 opencode。
                await websocket.send_json({"type": "session_created", "session": session})

            elif msg_type == "session.message":
                session_id = data.get("sessionId")
                content = (data.get("content") or "").strip()
                session = store.AgentSessionsStore.get(session_id)
                if not session:
                    await websocket.send_json({"type": "error", "message": "Session not found"})
                    continue
                user_msg = {
                    "id": store.next_id("m"), "role": "user", "time": _ts(), "content": content,
                }
                store.AgentSessionsStore.append_message({**user_msg, "sessionId": session_id})
                store.AgentSessionsStore.update(session_id, {"updatedAt": _ts()})
                # A7：tAgent 代码问答(替换 opencode 直连)。KB/LLM 不可达 → reply=None，仅落库回显用户消息。
                if content:
                    # tAgent 问答是同步长调用(工具循环多轮)，先声明相变避免前端零反馈
                    try:
                        await websocket.send_json({"type": "status", "sessionId": session_id,
                                                   "phase": "chat"})
                    except Exception:
                        pass
                    reply = await _agent_chat_reply(session, content)
                    try:
                        await websocket.send_json({"type": "status", "sessionId": session_id,
                                                   "phase": "idle"})
                    except Exception:
                        pass
                    if reply:
                        m = {"id": store.next_id("m"), "role": "assistant", "time": _ts(), "content": reply}
                        store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
                        await websocket.send_json({"type": "message", **m})
                await websocket.send_json({"type": "message", **user_msg})

            elif msg_type == "session.stop":
                session_id = data.get("sessionId")
                # A7：无 opencode 会话，停止仅置状态。
                store.AgentSessionsStore.update(session_id, {"status": "stopped", "updatedAt": _ts()})
                await websocket.send_json({"type": "stopped", "sessionId": session_id, "status": "stopped"})

    except WebSocketDisconnect:
        logger.info("Coding agent WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Coding agent WS error: {e}")


# ── A7: tAgent 代码问答辅助 ─────────────────────────────────────

async def _agent_chat_reply(session: dict, content: str) -> Optional[str]:
    """A7: tAgent 代码问答(替换 opencode 直连)。

    解析会话关联的执行任务 → root/project → chat_reply(agentic_loop + KB/代码工具) → 回答。
    无任务 / KB 不可达 / 异常 → None(调用方仅落库回显用户消息)。阻塞调用放线程。
    """
    from . import tagent_chat
    task_id = (session.get("taskId") or "").strip()
    task = store.ExecutionTasksStore.get(task_id) if task_id else None
    root, project, task_context = "", "", ""
    if task:
        from .execution import _resolve_root_project
        reqs = [store.RequirementsStore.get(i) for i in task.get("reqIds") or []]
        reqs = [r for r in reqs if r]
        root, project = _resolve_root_project(reqs, {})
        root = root or ""
        titles = [r.get("title", "") for r in reqs if r.get("title")]
        task_context = (
            f"执行任务: {task.get('id', '')}\n"
            f"需求: {'; '.join(titles) if titles else '无'}\n"
            "说明: 用户正在与该任务的实现会话对话，问题可能涉及该任务要实现的代码。"
        )
    try:
        return await asyncio.to_thread(
            tagent_chat.chat_reply,
            question=content, root=root, project=project, task_context=task_context)
    except Exception as e:
        logger.warning(f"[coding-agent] tAgent 聊天失败: {e}")
        return None


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

def _runner_ws_url(tree_id: str) -> str:
    """由 RunnerGateway.base_url(http://) 推导 runner WS 地址(ws://)。"""
    from .runner_gateway import get_runner
    base = get_runner().base_url
    ws_base = base.replace("http://", "ws://").replace("https://", "wss://")
    return f"{ws_base}/api/trees/{tree_id}/events"


@router.websocket("/ws/trees/{tree_id}/events")
async def tree_events_ws(websocket: WebSocket, tree_id: str):
    """代理 runner 任务树进度事件到前端。

    - runner → 前端：原样转发 `AgentEvent.to_dict()`(`{type, data:{stage,...}, ts}`)；
      前端据 `data.stage` + `data.message`(节点 id / 树级原因) 更新任务树进度。
    - 前端 → runner：控制消息 `{cmd: run/pause/resume/cancel/skip/retry, taskId?}`
      → RunnerGateway HTTP(经 to_thread，避免阻塞事件循环)。
    runner 不可达 → 推一条 error 事件后关闭。
    """
    await websocket.accept()
    try:
        import websockets
    except Exception as e:  # noqa: BLE001
        await websocket.send_json({"type": "error",
                                   "data": {"stage": "proxy_error", "message": f"websockets 不可用: {e}"}})
        await websocket.close()
        return

    url = _runner_ws_url(tree_id)
    try:
        runner_ws = await asyncio.wait_for(websockets.connect(url), timeout=5)
    except Exception as e:  # noqa: BLE001
        logger.warning("[tree-events] runner WS 不可达(%s): %s", url, e)
        await websocket.send_json({"type": "error",
                                   "data": {"stage": "proxy_error", "message": "runner 不可达"}})
        await websocket.close()
        return

    # 初始状态同步：下发当前 tree + progress，前端据此对齐(消除"run 先于订阅"的早期事件竞态)
    from .runner_gateway import get_runner
    try:
        cur = await asyncio.to_thread(get_runner().get_tree, tree_id)
        if cur:
            await websocket.send_json({"type": "state", "data": cur})
    except Exception:  # noqa: BLE001
        pass

    async def _relay_runner_to_client() -> None:
        try:
            async for raw in runner_ws:
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode()
                await websocket.send_text(raw)  # 原样转发 AgentEvent JSON
        except Exception:  # noqa: BLE001
            pass

    async def _relay_client_to_runner() -> None:
        from .runner_gateway import get_runner
        r = get_runner()
        try:
            while True:
                data = await websocket.receive_json()
                cmd = data.get("cmd")
                if cmd == "run":
                    await asyncio.to_thread(r.run, tree_id)
                elif cmd == "pause":
                    await asyncio.to_thread(r.pause, tree_id)
                elif cmd == "resume":
                    await asyncio.to_thread(r.resume, tree_id)
                elif cmd == "cancel":
                    await asyncio.to_thread(r.cancel, tree_id)
                elif cmd == "skip" and data.get("taskId"):
                    await asyncio.to_thread(r.skip, tree_id, data["taskId"])
                elif cmd == "retry" and data.get("taskId"):
                    await asyncio.to_thread(r.retry, tree_id, data["taskId"])
        except WebSocketDisconnect:
            pass
        except Exception:  # noqa: BLE001
            pass

    relay_out = asyncio.create_task(_relay_runner_to_client())
    relay_in = asyncio.create_task(_relay_client_to_runner())
    try:
        # 任一侧结束(前端断开 / runner 关闭) → 取消另一侧
        await asyncio.wait({relay_out, relay_in}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in (relay_out, relay_in):
            t.cancel()
        try:
            await runner_ws.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


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
