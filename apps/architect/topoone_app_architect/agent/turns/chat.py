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
# 全为落卡工具时, 跳过模型叙述轮(省一轮 LLM)。cv-203 裁决: 卡片是独立消息,
# 合成收尾文案 = 与卡片重复的第二条文本 → 不再落, 以 card_closed 标记收尾。
_CARD_LANDING_TOOLS = frozenset({"req.propose", "req.amend", "task.propose"})


def _card_round_closing(results: List[Dict[str, str]]) -> bool:
    """落卡轮判定(原合成收尾, cv-203 起只判不落): 本轮全为落卡工具 → True。

    卡片(specReady/task_card)已由工具执行落流——独立成卡, 不再追加收尾文本。
    refused 条目(GU 执法拒绝回喂, 批丁)未实际落卡, 不参与判定。"""
    from ..compensation.providers.builtin import card_closing_text
    for r in results:
        if r.get("refused"):
            continue
        if card_closing_text(r.get("name", "")):
            return True
    return False


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
                     tool_errors: dict, allowed_tools: Optional[set] = None,
                     gu_action: str = "") -> None:
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

    # ---- 回合账目(上下文用量观测): 装配体估算 + 可用预算 → conv.meta(fail-soft) ----
    try:
        from ..cognition.ctx_usage import record_turn
        record_turn(conv_id, msgs, eff_model or model_id)
    except Exception:  # noqa: BLE001
        pass

    # ---- 回合后落库通道(仅确定性围栏, 缓解守卫已按用户裁决拆除 cv-175) ----
    final_content, conv, tools_used, tool_errors = await _post_turn_land(
        io, conv_id, msgs, root, project, eff_model, model_id, conv,
        tools_used, tool_errors, final_content, request_id,
        allowed_tools=allowed_tools, gu_action=gu_action)

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
        meta_row = dict(tool_round_meta) if tool_round_meta else {}
        if gu_action:
            # 回合产物元数据(cv-246): GU 动作入 meta——焦点栈澄清在飞帧源
            meta_row["guAction"] = gu_action
        if meta_row:
            msg_row["meta"] = meta_row
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
        # 误路由遥测(#5 先行半, 恒开): 回复推诿 ∧ 问题正则未命中 → 记样本
        # (只观测不改行为; 数据供 LLM 意图兜底的启用决策, 采纳文档 P1)
        try:
            from .intent_llm import misroute_telemetry
            misroute_telemetry(str((gate or {}).get("question") or ""),
                               final_content)
        except Exception:  # noqa: BLE001
            pass
    else:
        # cv-203: 落卡工具产卡后的有意空收尾 → 卡片即回合产物, 不落消息也不报
        # turnError——只发 done 事件收口前端 busy 态。
        if loop.get("card_closed") and not tool_errors:
            await io.send_ev({"type": "done", "conversationId": conv_id,
                              "content": "", "cardClosed": True})
            return
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


def _gu_structured_schema(allowed_tools: Optional[set]):
    """GU 限面 → structured 轮 schema 注入 tool enum(约束解码层面收敛, 批丁)。

    标准约束(cv-225 API 日志实证): enum 必须包含协议声明的空值 ""——
    TOOL_CALL_SCHEMA 声明「空串=本轮不调用工具」, 约束域若不含它, 想遵从
    「先澄清后落卡」的模型没有任何合法方式表达"直接提问", 只能在枚举里
    挑最无害工具打转或退化成占位调用。约束域 ⊇ 协议域, 是单源纪律的
    组成部分(解析层已实现空串→无调用→转终稿轮, 两层语义同源)。"""
    if not allowed_tools:
        return None
    import copy as _copy
    from ..tools.protocol import TOOL_CALL_SCHEMA
    schema = _copy.deepcopy(TOOL_CALL_SCHEMA)
    schema.setdefault("properties", {}).setdefault("tool", {})["enum"] = \
        sorted(allowed_tools) + [""]
    return schema


def _call_key(name: str, args) -> tuple:
    """回合内重复调用判别键(单源委托 req_agent; async 面薄壳)。"""
    from ...arch_routes import req_agent as _ra
    return _ra._call_key(name, args)


def _dup_call_text() -> str:
    from ...arch_routes import req_agent as _ra
    return _ra._DUP_CALL_TEXT


def _allowed_refusal_text(name: str) -> str:
    return (f"工具 {name} 不在本回合可用清单(当前路线限定)——请改用允许的工具，"
            "直接基于已有信息作答，或按回合指引向用户提出澄清问题。")


async def _run_llm_tool_loop(io: "_TurnIO", conv_id: str, msgs: list,
                             root: str, project: str, eff_model: Optional[str],
                             model_id: str, tools_used: set, tool_errors: dict,
                             max_tool_rounds: int = _MAX_TOOL_ROUNDS,
                             allowed_tools: Optional[set] = None) -> dict:
    """管线阶段④ LLM 工具循环: 流式/降级/工具轮/预算门禁(行为等价抽取)。

    max_tool_rounds: 工具轮次上限按挡下发(M4-B, gear.tool_rounds);
    allowed_tools: GU 路线工具限定(批丁)——提示面(能力文档子集+schema enum)
    与执行面(名单外拒绝回喂)双重收敛。
    返回 {request_id, assistant_text, visible, tool_round, loop_fell_back,
    card_closed}; msgs/tools_used/tool_errors 原地变更(守卫与遥测依赖)。"""
    from ...arch_routes import req_agent
    max_rounds = max(1, int(max_tool_rounds or _MAX_TOOL_ROUNDS))
    structured_on = True    # M4-A: 受限生成通道开关(逐轮按支持位判定+失败降级)
    request_id = None
    assistant_text = ""
    visible = ""
    tool_round = 0
    loop_fell_back = False
    card_closed = False     # cv-203: 落卡工具已产卡, 空文本收尾(≠空返回错误)
    seen_calls: set = set()  # 回合内幂等重复抑制(标准环守卫, cv-225 实证)
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
            sres = await asyncio.to_thread(
                req_agent.structured_tool_round,
                msgs, _model_key,
                schema=_gu_structured_schema(allowed_tools))
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
                # 批丁 GU 执法: 名单外工具拒绝回喂(提示面已收敛, 此为执行面兜底)
                if allowed_tools and c.get("tool") \
                        and c.get("tool") not in allowed_tools:
                    results.append({"name": c.get("tool", ""),
                                    "text": _allowed_refusal_text(c.get("tool")),
                                    "refused": True})
                    continue
                # 幂等重复抑制: 同回合 (tool, args) 全同的再调用 → 拒绝回喂
                _ck = _call_key(c.get("tool", ""), c.get("arguments", {}))
                if _ck in seen_calls:
                    results.append({"name": c.get("tool", ""),
                                    "text": _dup_call_text(), "refused": True})
                    continue
                seen_calls.add(_ck)
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
                    if _card_round_closing(results):
                        card_closed = True   # 卡片已落流, 空文本收尾(非错误)
                        break
            continue
        rid = _req_chat_stream(msgs, eff_model or req_agent.get_model_preference())
        if not rid:
            # 流式通道中断：带工具结果的累积上下文改走 llm.sync 收尾
            loop_fell_back = True
            await io.ensure_chat_start()
            assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds, allowed_tools=allowed_tools)
            if not assistant_text and tools_used and tools_used <= _CARD_LANDING_TOOLS:
                card_closed = True   # cv-203: 落卡工具已产卡, 空文本≠空返回错误
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
                assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds, allowed_tools=allowed_tools)
            break

        # 本轮工具调用解析并在 architect 侧执行
        calls = req_agent._normalize_tool_calls(req_agent.extract_tool_calls(round_text))
        req_agent.record_tool_parse_audit(round_text, calls, surface="chat")
        if calls:
            # 达到最大工具轮次时也要执行本轮工具后用 llm.sync 收尾，避免空答案
            if tool_round >= max_rounds:
                results: List[Dict[str, str]] = []
                for c in calls:
                    name = c.get("tool", "")
                    args = c.get("arguments", {})
                    if allowed_tools and name and name not in allowed_tools:
                        # 批丁 GU 执法(满轮收尾分支同规)
                        results.append({"name": name,
                                        "text": _allowed_refusal_text(name),
                                        "refused": True})
                        continue
                    _ck = _call_key(name, args)
                    if _ck in seen_calls:
                        results.append({"name": name, "text": _dup_call_text(),
                                        "refused": True})
                        continue
                    seen_calls.add(_ck)
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
                    assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds, allowed_tools=allowed_tools)
                break
            tool_round += 1
            results: List[Dict[str, str]] = []
            for c in calls:
                name = c.get("tool", "")
                args = c.get("arguments", {})
                if allowed_tools and name and name not in allowed_tools:
                    # 批丁 GU 执法: 名单外工具拒绝回喂
                    results.append({"name": name,
                                    "text": _allowed_refusal_text(name),
                                    "refused": True})
                    continue
                _ck = _call_key(name, args)
                if _ck in seen_calls:
                    results.append({"name": name, "text": _dup_call_text(),
                                    "refused": True})
                    continue
                seen_calls.add(_ck)
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
                # cv-196 收尾短路 + cv-203 卡片独立: 整回合无可见正文且本轮全为
                # 落卡工具 → 不再要一轮叙述(车轱辘话源头), 也不落合成收尾文本
                # (与卡片重复)——卡片即本回合产物, 空文本收尾。
                if not visible.strip() and _card_round_closing(results):
                    card_closed = True
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
    if (not loop_fell_back and not card_closed and not assistant_text
            and not visible and io.budget_left() > 0):
        await io.ensure_chat_start()
        assistant_text = await _sync_with_tools(io.send, msgs, root, project, eff_model, tools_used=tools_used, max_rounds=max_rounds, allowed_tools=allowed_tools)
        if not assistant_text and tools_used and tools_used <= _CARD_LANDING_TOOLS:
            card_closed = True   # 降级通道同样以卡收尾(空文本≠错误)

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
            "loop_fell_back": loop_fell_back, "card_closed": card_closed}


async def _post_turn_land(io: "_TurnIO", conv_id: str, msgs: list,
                          root: str, project: str, eff_model: Optional[str],
                          model_id: str, conv: dict,
                          tools_used: set, tool_errors: dict,
                          final_content: str, request_id: Optional[str],
                          allowed_tools: Optional[set] = None,
                          gu_action: str = ""):
    """管线阶段⑤ 回合后确定性落库通道(仅围栏, 缓解守卫已拆除 cv-175)。

    写卡执法点统一(cv-246 架构裁决「回合权力单源授予, 回合产物统一执法」):
    围栏代落**不是独立通道**——它只是模型输出的一种调用形态, 与工具轮
    tool_calls 走同一验权关卡(allowed_tools=GU 本回合授权面): 纯读面
    (面不含写工具)不代落, 载荷按模型原文诚实保留+rejected 遥测。
    载荷归属由内容 schema 单源判别(规约字段→req.propose; 任务形态→
    task.propose), 不由围栏标记/正则竞争决定。
    代落成功=卡即回执(cv-203): 剥载荷正文, 不合成任何通知文本;
    失败保留诚实错误(cv-175 纪律)。
    返回 (final_content, conv, tools_used, tool_errors)。"""
    from ...arch_routes import req_agent

    # ── 结构化问询卡(choices 交互卡, cv-247): 非实体写卡——不落
    # Requirements/Tasks, 故不经 GU 写权验权(执法点管「写实体权力」);
    # 每回合最多 1 张; 坏载荷不落卡, 正文原样保留(信息不丢)。
    # ```json 兜底(cv-252): GU 判 clarify-first(意图佐证)而模型漂移到
    # ```json 标记——schema 同尺校验后落卡, 裸 JSON 不再漏到前端。
    choices_payload = req_agent.extract_choices_fence(final_content)
    json_fallback = False
    if not choices_payload and str(gu_action or "") == "clarify-first":
        choices_payload = req_agent.extract_choices_json_fence(final_content)
        json_fallback = choices_payload is not None
    if choices_payload and "choices" not in tools_used:
        from ..collab import cards as _cards
        landed = await asyncio.to_thread(
            _cards.land_choices, conv_id, choices_payload)
        if landed:
            final_content = (_cards.strip_choices_json_fence(final_content)
                             if json_fallback
                             else _cards.strip_choices_fence(final_content))

    async def _fence_land(tool: str, args: dict, strip_fn) -> bool:
        nonlocal final_content
        if allowed_tools is not None and tool not in allowed_tools:
            # 执法点: 名单外不代落(与工具轮三分支拒绝同规; 载荷原文保留)
            try:
                from ...arch_routes import llm_dataset as _lds
                _lds.record("fence_rejected", tool=tool, convId=conv_id)
            except Exception:  # noqa: BLE001
                pass
            return False
        if tool in tools_used:
            return False
        logger.info("[kb-chat] 载荷围栏命中(%s), 服务端代落 conv=%s", tool, conv_id)
        try:
            res = await _run_tool_with_progress(
                io.send, request_id, tool, args, root, project,
                model_id=eff_model)
            tools_used.add(tool)
            if res.get("ok"):
                final_content = strip_fn(final_content)  # 卡即回执(cv-203)
                return True
            tool_errors[tool] = str(res.get("text", ""))[:200]
            notice = f"\n\n⚠️ {tool} 落库失败：{str(res.get('text', ''))[:140]}"
            final_content += notice
            await io.send_ev({"type": "chunk", "requestId": request_id, "delta": notice})
        except Exception as e:  # noqa: BLE001
            logger.warning("[kb-chat] 围栏代落失败 %s: %s", tool, e)
        return False

    # 归属判别: 规约 schema 载荷(req 域认领, 不限围栏形态) 优先;
    # 任务形态载荷归 task 域(规约形态已被其认领谓词排斥)
    fence_args = req_agent.extract_proposal_fence(final_content)
    if fence_args:
        await _fence_land("req.propose", fence_args,
                          req_agent.strip_proposal_fence)
    else:
        task_fence = req_agent.extract_task_fence(final_content)
        if task_fence:
            await _fence_land("task.propose", task_fence,
                              req_agent.strip_task_fence)

    return final_content, conv, tools_used, tool_errors

async def _sync_with_tools(send: SendFn, msgs, root, project, model_id, max_rounds: int = 4,
                           tools_used: Optional[set] = None,
                           allowed_tools: Optional[set] = None) -> str:
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
        on_progress=on_progress, allowed=allowed_tools,
    )
    content = res.get("content", "") if isinstance(res, dict) else ""
    # cv-196 收尾短路(降级通道同规) + cv-203 卡片独立: 模型零可见正文且本回合
    # 全为落卡工具 → 空文本返回(卡片已落流即本回合产物; 调用方以 card_closed
    # 区分"有意空收尾"与"空返回错误")。
    if not content.strip() and tools_used and tools_used <= _CARD_LANDING_TOOLS:
        return ""
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
