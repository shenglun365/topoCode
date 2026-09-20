"""阶段④⑤⑥ 执行/落库 — chat 形态(M1 自 orchestrator 机械搬迁, 行为等价)。

LLM 工具循环(流式/降级/工具轮/预算门禁) + 回合落库与终态事件 +
LLM chunk 实时转发过滤器。设计 §4 ChatTurn 的执行半边。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re as _re
from typing import Awaitable, Callable, Dict, List, Optional

from .base import (_MAX_TOOL_ROUNDS, _MIN_CHAT_MAX_TOKENS, _STREAM_IDLE_TIMEOUT_S,
                   _TURN_BUDGET_S, SendFn, _TurnIO)

from ..cognition.prompt import TOOL_FEED_PREFIX as _TOOL_FEED_PREFIX
logger = logging.getLogger(__name__)


# 弱模型模仿上下文占位符把"(已调用工具)"当正文输出(cv-189 实证)——
# 纯占位正文不进历史: 有工具轨迹落紧凑回执, 无轨迹跳过。
_PLACEHOLDER_ONLY_RE = _re.compile(
    r"^[（(]\s*(?:已调用工具|调用知识库检索|调用工具|工具已调用)\s*[)）][。.!！]?\s*$")

# cv-196 收尾短路: 落卡工具的产物已由回执/卡片承载——整回合无可见正文且本轮
# 全为落卡工具时, 跳过模型叙述轮, 用回执合成收尾(消灭车轱辘话 + 省一轮 LLM)。
_CARD_LANDING_TOOLS = frozenset({"req.propose", "req.amend", "task.propose"})
_CARD_CLOSINGS = {
    "req.propose": "📝 需求卡已创建(ready)——点「开始执行」启动。",
    "req.amend": "✏️ 规约已修订(ready)。",
    "task.propose": "📋 任务卡已保存——点「开始执行」启动。",
}


def _card_round_closing(results: List[Dict[str, str]]) -> str:
    """落卡轮的确定性收尾(按本轮工具去重合成; 空串=不适用)。"""
    seen: List[str] = []
    for r in results:
        c = _CARD_CLOSINGS.get(r.get("name", ""))
        if c and c not in seen:
            seen.append(c)
    return "\n".join(seen)


def _propose_dup_text() -> str:
    """cv-174: 同回合重复提案回执(三处工具执行分支共用)。"""
    return ("重复的 req.propose 已忽略——本回合已创建规约(以首个为准)；"
            "如需修改请用 req.amend")


# ── LLM chunk 实时转发过滤器 ─────────────────────────────────────────────
# 旧实现整轮缓冲 round_text、结束后才 24 字符假流式重发——LLM 生成期间(可长达
# 数十秒)前端零反馈，用户感知为「处理完成后还要等很久才有消息」。
# 现改为边生成边转发，但必须剔除 [TOOL_CALL] 块(不可展示)：命中疑似标记后
# 停止本轮实时转发(余量在回合结束时按 strip 后文本对齐补发)。
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
    from ...arch_routes import req_agent
    pref = req_agent.get_max_tokens_preference()
    if pref and pref > 0:
        return max(pref, _MIN_CHAT_MAX_TOKENS)
    return None


def _model_health_hint(model_id: str) -> str:
    """模型探测档案 → 切换建议(cv-156/162 实证: 不及格模型大提示词空返回)。

    数据源 CollabConfigStore `llm.modelProfiles`; 无档案/成绩尚可 → 空串。"""
    try:
        from ...arch_routes import store
        raw = store.CollabConfigStore.get("llm.modelProfiles", "")
        profiles = json.loads(raw) if raw else {}
        row = profiles.get(model_id or "") or {}
        caps = row.get("caps") or {}
        score = float(caps.get("probeScore") or 0)
        if score and score >= 0.5:
            return ""
        name = row.get("modelName") or model_id
        return (f"⚠️ 当前模型「{name}」能力探测不及格"
                f"(指令跟随 {int(float(caps.get('instructionScore') or 0) * 100)}%"
                f"/工具协议 {int(float(caps.get('toolCallRate') or 0) * 100)}%)"
                "——建议在会话头部切换模型后重试")
    except Exception:  # noqa: BLE001
        return ""


async def _chat_land(io: "_TurnIO", msgs: list, gate: dict, conv: dict,
                     loop: dict, eff_model: Optional[str], model_id: str,
                     root: str, project: str, tools_used: set,
                     tool_errors: dict) -> None:
    """管线阶段⑤⑥ 回合落库 + 终态事件(行为等价抽取自 handle_chat)。

    正常: 确定性围栏代落(_post_turn_land) → assistant 单流落库 → done 事件;
    空返回: turnError 折叠卡 + error 事件(错误必须完整可见且可刷新)。
    """
    from ...arch_routes import req_agent
    from ...arch_routes import store
    from ...arch_routes.common import _ts

    conv_id = gate["conv_id"]
    request_id = loop["request_id"]
    assistant_text = loop["assistant_text"]
    visible = loop["visible"]
    tool_round = loop["tool_round"]
    loop_fell_back = loop["loop_fell_back"]
    final_content = visible or assistant_text

    # ---- 回合后落库通道(仅确定性围栏, 缓解守卫已按用户裁决拆除 cv-175) ----
    final_content, conv, tools_used, tool_errors = await _post_turn_land(
        io, conv_id, msgs, root, project, eff_model, model_id, conv,
        tools_used, tool_errors, final_content, request_id)

    tool_round_meta = None
    if final_content and _PLACEHOLDER_ONLY_RE.match(final_content.strip()):
        # cv-189: 占位正文折叠——有工具轨迹落紧凑回执(调用清单可追溯), 无则跳过
        final_content = ("🔧 已调用工具: " + "、".join(sorted(tools_used))
                         if tools_used else "")
        tool_round_meta = {"kind": "tool_round", "tools": sorted(tools_used)}
    if final_content:
        assistant_msg_id = store.next_id("m")
        msg_row = {"id": assistant_msg_id, "conversationId": conv_id,
                   "role": "assistant", "time": _ts(), "content": final_content}
        if tool_round_meta:
            msg_row["meta"] = tool_round_meta
        store.ConversationsStore.append_message(msg_row)
        try:  # PR1 双维度: 助手回合落库 → 正常未读(前端打开会话时回 read)
            store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
        except Exception:  # noqa: BLE001
            pass
        done_ev = {"type": "done", "conversationId": conv_id,
                   "content": final_content, "messageId": assistant_msg_id}
        await io.send_ev(done_ev)
        try:
            from ...arch_routes import llm_dataset as _lds
            _lds.record("llm_stream_done", ok=True,
                        chars=len(final_content),
                        latencyMs=int((__import__("time").time() - io.t0) * 1000),
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
        elapsed = int(__import__("time").time() - io.t0)
        detail += f"；回合耗时 {elapsed}s（总预算 {int(_TURN_BUDGET_S)}s）"
        hint = _model_health_hint(eff_model or req_agent.get_model_preference())
        if hint:
            detail += "。" + hint
        try:
            from ..collab import cards as _cards
            _cards.land(conv_id, f"❌ {detail}", kind=_cards.KIND_TURN_ERROR,
                        review_state="error")
            from ..memory.units import record_turn_error
            record_turn_error(conv_id, detail)
        except Exception:  # noqa: BLE001
            logger.warning("[kb-chat] turnError 落库失败 conv=%s", conv_id)
        await io.send_ev({"type": "error", "requestId": request_id, "message": detail})


async def _run_llm_tool_loop(io: "_TurnIO", conv_id: str, msgs: list,
                             root: str, project: str, eff_model: Optional[str],
                             model_id: str, tools_used: set, tool_errors: dict,
                             max_tool_rounds: int = _MAX_TOOL_ROUNDS) -> dict:
    """管线阶段④ LLM 工具循环: 流式/降级/工具轮/预算门禁(行为等价抽取)。

    max_tool_rounds: 工具轮次上限按挡下发(M4-B, gear.tool_rounds);
    返回 {request_id, assistant_text, visible, tool_round, loop_fell_back};
    msgs/tools_used/tool_errors 原地变更(守卫与遥测依赖)。"""
    from ...arch_routes import req_agent
    max_rounds = max(1, int(max_tool_rounds or _MAX_TOOL_ROUNDS))
    structured_on = True    # M4-A: 受限生成通道开关(逐轮按支持位判定+失败降级)
    request_id = None
    assistant_text = ""
    visible = ""
    tool_round = 0
    loop_fell_back = False
    while tool_round <= max_rounds:
        # 回合总预算: 超时终止(不再续流式轮/降级/nudge), 详因落 turnError
        if io.budget_left() <= 0:
            logger.warning("[kb-chat] 回合总预算耗尽 conv=%s elapsed=%.0fs",
                           conv_id, __import__("time").time() - io.t0)
            break
        # ── M4-A 两段式: 受限生成工具轮(非流式约束解码) + 文本终稿轮(流式) ──
        # 支持位模型才走本通道(支持位未配置 = 全程文本协议, 现行为不变);
        # structured 失败显式 nudge 后本回合降级文本协议(不静默)。
        _model_key = eff_model or req_agent.get_model_preference()
        if structured_on and req_agent.structured_model_enabled(_model_key):
            sres = await asyncio.to_thread(req_agent.structured_tool_round,
                                           msgs, _model_key)
            tool_round += 1
            if sres["error"]:
                logger.info("[kb-chat] structured 轮失败 → 降级文本协议 conv=%s: %s",
                            conv_id, sres["error"][:120])
                msgs.append({"role": "user", "content":
                             f"结构化工具调用未成功({sres['error'][:160]})。"
                             "请直接基于已有信息作答，或改用文本协议输出工具调用块。"})
                structured_on = False
                continue
            if not sres["calls"]:
                structured_on = False     # 模型示意无更多工具 → 转终稿流式轮
                continue
            await io.ensure_chat_start()
            results: List[Dict[str, str]] = []
            for c in sres["calls"]:
                # cv-174 守卫(structured 轮同样适用——受限生成通道弱模型连发提案
                # 曾一回合落 4 张重复需求卡, cv-185 实证)
                if c.get("tool") == "req.propose" and "req.propose" in tools_used:
                    results.append({"name": "req.propose",
                                    "text": _propose_dup_text()})
                    continue
                if c.get("tool"):
                    tools_used.add(c.get("tool"))   # cv-174 守卫依赖(回写与流式分支同规)
                tr = await _run_tool_with_progress(
                    io.send, "", c.get("tool", ""), c.get("arguments", {}),
                    root, project, model_id=eff_model)
                results.append(tr)
                if not tr.get("ok"):
                    tool_errors[c.get("tool", "")] = tr.get("text", "")[:200]
            if results:
                tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                msgs.append({"role": "assistant", "content": "(已调用工具)"})
                msgs.append({"role": "user", "content": f"{_TOOL_FEED_PREFIX}{tool_feed}"})
                if not visible.strip():
                    _closing = _card_round_closing(results)
                    if _closing:
                        assistant_text = _closing
                        break
            continue
        rid = _req_chat_stream(msgs, eff_model or req_agent.get_model_preference())
        if not rid:
            # 流式通道中断：带工具结果的累积上下文改走 llm.sync 收尾
            loop_fell_back = True
            await io.ensure_chat_start()
            assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds)
            break
        request_id = rid
        await io.send_ev({"type": "chat_start", "conversationId": conv_id,
                                   "requestId": rid, "userMessageId": io.last_user_msg_id})
        io.chat_start_sent = True
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
                    await io.send_ev({"type": "chunk", "requestId": rid, "delta": out})
            elif event_type == "reasoning":
                # 推理内容单独转发(不混入正文)；前端可折叠展示思考过程
                text = payload.get("text") or ""
                if text:
                    await io.send_ev({"type": "reasoning", "conversationId": conv_id,
                                               "delta": text})
            elif event_type == "done":
                round_text = payload.get("content") or round_text
                break
            elif event_type == "error":
                round_ok = False
                await io.send_ev({"type": "error", "requestId": rid,
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
                await io.send_ev({"type": "chunk", "requestId": rid, "delta": rem})
        if not round_ok:
            # 该轮流式出错但已带工具上下文：降级到 llm.sync 收尾，避免无结果
            loop_fell_back = True
            if io.budget_left() > 0:
                await io.ensure_chat_start()
                assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds)
            break

        # 本轮工具调用解析并在 architect 侧执行
        calls = req_agent.extract_tool_calls(round_text)
        req_agent.record_tool_parse_audit(round_text, calls, surface="chat")
        if calls:
            # 达到最大工具轮次时也要执行本轮工具后用 llm.sync 收尾，避免空答案
            if tool_round >= max_rounds:
                results: List[Dict[str, str]] = []
                for c in calls:
                    name = c.get("tool", "")
                    args = c.get("arguments", {})
                    if name == "req.propose" and "req.propose" in tools_used:
                        # cv-174 守卫(满轮收尾分支同样适用)
                        results.append({"name": name, "text": _propose_dup_text()})
                        continue
                    tr = await _run_tool_with_progress(
                        io.send, rid, name, args, root, project, model_id=eff_model)
                    results.append(tr)
                    if not tr.get("ok"):
                        tool_errors[name] = tr.get("text", "")[:200]
                if results:
                    tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                    msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                    msgs.append({"role": "user", "content": f"{_TOOL_FEED_PREFIX}{tool_feed}"})
                loop_fell_back = True
                if io.budget_left() > 0:
                    await io.ensure_chat_start()
                    assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds)
                break
            tool_round += 1
            results: List[Dict[str, str]] = []
            for c in calls:
                name = c.get("tool", "")
                args = c.get("arguments", {})
                if name == "req.propose" and "req.propose" in tools_used:
                    # cv-174: 同回合重复提案 → 不再落库, 防止一回合多个需求
                    results.append({"name": name, "text": _propose_dup_text()})
                    continue
                if name:
                    tools_used.add(name)
                logger.info("[req_agent] kb chat tool round=%s call=%s",
                            tool_round, name)
                tr = await _run_tool_with_progress(
                    io.send, rid, name, args, root, project, model_id=eff_model)
                results.append(tr)
                if not tr.get("ok"):
                    tool_errors[name] = tr.get("text", "")[:200]
            if results:
                tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                msgs.append({"role": "user", "content": f"{_TOOL_FEED_PREFIX}{tool_feed}"})
                # cv-196 收尾短路: 整回合无可见正文且本轮全为落卡工具 → 不再要
                # 一轮叙述(车轱辘话源头), 用回执合成收尾直接结束。
                _closing = _card_round_closing(results)
                if not visible.strip() and _closing:
                    assistant_text = _closing
                    break
            # 工具结果回喂后的再生成无任何信号会让前端进度条「卡死」观感——显式报相
            await io.send_ev({"type": "status", "phase": "llm_round",
                                       "round": tool_round + 1})
            continue

        # 无工具调用 → 本轮即最终答案
        assistant_text = req_agent.strip_tool_blocks(round_text)
        break

    # 流式通道空响应(如思考型模型推理阶段耗尽 token 仅产出 reasoning_content)：
    # 带工具结果/上下文的累积上下文改走 llm.sync 收尾，避免「LLM 未返回内容」硬失败。
    if (not loop_fell_back and not assistant_text and not visible
            and io.budget_left() > 0):
        await io.ensure_chat_start()
        assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds)

    # 降级通道(llm.sync / 断流收尾)无逐字流 → 假流式补发；实时转发路径
    # visible 已含全部内容，跳过避免重复。断流后收尾的极端场景 partial
    # 可见 + 完整收尾文本 → 追加(轻微重复优于丢内容)。
    if assistant_text and (loop_fell_back or not visible):
        CHUNK_SIZE = 24
        for i in range(0, len(assistant_text), CHUNK_SIZE):
            d = assistant_text[i:i + CHUNK_SIZE]
            visible += d
            await io.send_ev({"type": "chunk", "requestId": request_id,
                                       "delta": d})

    return {"request_id": request_id, "assistant_text": assistant_text,
            "visible": visible, "tool_round": tool_round,
            "loop_fell_back": loop_fell_back}


async def _post_turn_land(io: "_TurnIO", conv_id: str, msgs: list,
                          root: str, project: str, eff_model: Optional[str],
                          model_id: str, conv: dict,
                          tools_used: set, tool_errors: dict,
                          final_content: str, request_id: Optional[str]):
    """管线阶段⑤ 回合后确定性落库通道(仅围栏, 缓解守卫已拆除 cv-175)。

    模型愿发工具块则工具直落; 直接写 JSON 围栏也接受——服务端代执行,
    产物即需求卡/任务卡。不做任何"纠正模型"的启发式判断。
    返回 (final_content, conv, tools_used, tool_errors)。"""
    from ...arch_routes import req_agent
    # ── proposal 围栏 → req.propose 代落(需求卡) ──
    fence_args = req_agent.extract_proposal_fence(final_content)
    if fence_args and "req.propose" not in tools_used:
        logger.info("[kb-chat] proposal 围栏命中, 服务端代落库 conv=%s", conv_id)
        try:
            res = await _run_tool_with_progress(
                io.send, request_id, "req.propose", fence_args, root, project,
                model_id=eff_model)
            tools_used.add("req.propose")
            if res.get("ok"):
                final_content = req_agent.strip_proposal_fence(final_content)
            else:
                tool_errors["req.propose"] = str(res.get("text", ""))[:200]
            notice = (f"\n\n✅ 已从提案围栏自动落库：{str(res.get('text', ''))[:140]}"
                      if res.get("ok") else
                      f"\n\n⚠️ 提案围栏落库失败：{str(res.get('text', ''))[:140]}")
            final_content += notice
            await io.send_ev({"type": "chunk", "requestId": request_id, "delta": notice})
        except Exception as e:  # noqa: BLE001
            logger.warning("[kb-chat] 围栏代落库失败: %s", e)

    # ── 任务载荷围栏 → task.propose 代落(执行卡) ──
    task_fence = req_agent.extract_task_fence(final_content)
    if task_fence and "task.propose" not in tools_used:
        logger.info("[kb-chat] 任务载荷围栏命中, 服务端代落卡 conv=%s", conv_id)
        try:
            res = await _run_tool_with_progress(
                io.send, request_id, "task.propose", task_fence, root, project,
                model_id=eff_model)
            tools_used.add("task.propose")
            if not res.get("ok"):
                tool_errors["task.propose"] = str(res.get("text", ""))[:200]
            notice = (f"\n\n📋 已从上文载荷自动创建**任务卡**（待确认）：{str(res.get('text', ''))[:160]}"
                      if res.get("ok") else
                      f"\n\n⚠️ 任务卡自动创建失败：{str(res.get('text', ''))[:160]}")
            final_content += notice
            await io.send_ev({"type": "chunk", "requestId": request_id, "delta": notice})
        except Exception as e:  # noqa: BLE001
            logger.warning("[kb-chat] 任务围栏代落失败: %s", e)

    return final_content, conv, tools_used, tool_errors

async def _sync_with_tools(send: SendFn, msgs, root, project, model_id, max_rounds: int = 4,
                           tools_used: Optional[set] = None) -> str:
    """llm.sync 降级通道：走统一工具调用循环(req_agent.run_tools_loop)，
    避免「LLM 输出 [TOOL_CALL] 后无结果」。返回最终纯文本。

    ⚠️ 降级通道原本全程零事件(用户数分钟零反馈)；现先发 status:sync 声明相变，
    再经 on_progress 把循环内 llm/tool 进度 marshal 回事件循环推送
    (run_tools_loop 在工作线程同步执行，send 回调非线程安全，
    必须 run_coroutine_threadsafe；连接已断时 send 抛异常需吞掉)。
    """
    from ...arch_routes import req_agent
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
    content = res.get("content", "") if isinstance(res, dict) else ""
    # cv-196 收尾短路(降级通道同规): 模型零可见正文且本回合并发的全是落卡
    # 工具 → 用回执合成收尾(消灭车轱辘话)。流式主路径在轮内短路(省一轮)。
    if not content.strip() and tools_used and tools_used <= _CARD_LANDING_TOOLS:
        closing = "\n".join(_CARD_CLOSINGS[t] for t in sorted(tools_used)
                            if t in _CARD_CLOSINGS)
        if closing:
            return closing
    return content


async def _run_tool_with_progress(send: SendFn, request_id: str, name: str, args: dict,
                                  root: str, project: str,
                                  model_id: Optional[str] = None) -> Dict[str, str]:
    """执行单个 architect 工具，并向前端推送 tool_call/tool_result 进度事件。

    工具轮次(可能跨多轮 LLM 重算)期间前端零反馈是「检索中…」久挂的主因；
    这里在工具执行前后各推一条状态，前端据此显示实时进度而非静态等待。
    参数自动修复已按 cv-175 裁决拆除——错误如实返回(明确报错优于静默纠偏)。
    """
    from ...arch_routes import context_registry, req_agent
    await send({"type": "tool_call", "requestId": request_id, "tool": name})
    result = await asyncio.to_thread(
        req_agent.execute_tool_with_repair, name, args, root, project,
        model_id or "")
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
    await send(event)
    # P2 上下文注册表: 工具轨迹/产物 → 单元(会话级溯源)
    from ...arch_routes import ctx as _ctx
    try:
        context_registry.record_tool_call(_ctx.get_conv() or "", name, args, ok, summary)
    except Exception:
        pass
    return {"name": name, "text": summary, "ok": ok}


async def _iter_llm_events(request_id: str, idle_timeout: Optional[float] = None):
    """architect 进程内 ZMQ SUB 订阅主后端 llm.* 流(按 requestId 过滤)。"""
    from ...arch_routes.zmq_stream import iter_llm_events
    async for e in iter_llm_events(request_id, idle_timeout=idle_timeout):
        yield e


def _req_chat_stream(msgs, model_id):
    """发起流式 llm.chat; 返回 requestId 或 None(降级)。

    cv-156 实证: 函数体在早前重构中丢失(隐式 return None)——流式通道自
    9-13 起从未发起, 所有回合静默走同步降级(大提示词下小模型易空返回)。"""
    from ...arch_routes.req_agent import llm_chat_start
    return llm_chat_start(msgs, model_id=model_id or None,
                          session_id="arch-req-chat",
                          max_tokens=_chat_max_tokens())
