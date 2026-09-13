"""WebSocket routes for KB analysis agent, coding agent and unit-test execution."""
import asyncio
import json
import logging
import os
import re
import urllib.request
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .common import _ts, _id
from . import store
from . import exec_bridge

# ── 会话指令符号表(确定性动作分发, 无自然语言语义判断) ──
# 触达=确切符号「/指令」(杜绝语义模糊); 引导=消息流指令 chip 点击填入对话框。
# 模型不代发指令、不响应指令语义; 每个符号绑定一个确定性后端动作。
SESSION_CMDS: Dict[str, str] = {
    "执行": "预览执行方案(按当前规约版本)",
    "确认执行": "按预览启动执行作业",
    "定稿": "确认当前规约版本(结构门禁校验后 ready)",
    "继续": "把补充信息转达给等待中的作业",
    "diff": "查看最近作业改动差异",
    "调整": "进入需求修订模式(req.amend)",
}
_CMD_RE = re.compile(r"^/([A-Za-z][A-Za-z0-9]*|[\u4e00-\u9fff]{1,4})\s*[!！。.？?]*\s*$")


def parse_session_cmd(question: str) -> str:
    """解析会话指令符号, 返回指令名(未匹配返回空串)。纯函数, 供单测。"""
    m = _CMD_RE.match((question or "").strip())
    return m.group(1) if m else ""


def _cmd_help_text() -> str:
    lines = [f"未知指令。可用指令符号："]
    lines += [f"- `/{name}` — {desc}" for name, desc in SESSION_CMDS.items()]
    lines.append("点击消息中的指令标签可直接填入输入框。")
    return "\n".join(lines)


async def _deliver_coding_turn(conv: dict, text: str) -> str:
    """coding 收件人: 定向投递到活跃作业(等待中→立即转达; 回合中→排队续跑)。"""
    from . import exec_bridge
    conv_id = (conv or {}).get("id") or ""
    # 子会话(作业账本在主会话): 沿父链找 active 且 sub=本会话 的作业
    cid = conv_id
    if (conv.get("kind") or "") == "coding":
        pj = exec_bridge.active_job(str(conv.get("parentConvId") or ""))
        if pj and pj.get("subSessionId") == conv_id:
            cid = str(conv.get("parentConvId") or "")
    res = await asyncio.to_thread(exec_bridge.deliver_to_coding, cid, text)
    if res.get("ok"):
        j = exec_bridge.active_job(cid) or {}
        queued = bool(res.get("queued"))
        ex = j.get("executorId") or "opencode"
        if queued:
            return (f"📥 已排队转达 `{ex}`（当前回合执行中，回合结束自动续跑）。"
                    "architect 方向的讨论不受影响。")
        return (f"➡️ 已转达 `{ex}`（作业继续）。"
                "回合期间可继续以 architect 身份讨论，或等待 agent 下一次提问。")
    err = str(res.get("error") or "")
    if err == "no-active-job":
        return ("没有活跃的 coding 作业。发送 `/执行` 预览并 `/确认执行` 启动作业后，"
                "再把补充内容发给 coding 角色。")
    return f"❌ 转达失败：{err or 'runner 不可达'}。可稍后重试。"


def _guard_cmd_hints(conv_id: str) -> list:
    """守卫卡指令符号建议: 按绑定需求状态给 /定稿(draft) 或 /执行(ready)。"""
    try:
        conv = store.ConversationsStore.get(conv_id) or {}
        rid = conv.get("reqId") or ""
        if not rid:
            return []
        row = store.RequirementsStore.get(rid) or {}
        if (row.get("doneMark") or 0) == 1:
            return []
        active = store.RequirementsStore.spec_active(rid)
        if not active:
            return []
        return ["/执行" if active.get("state") == "confirmed" else "/定稿"]
    except Exception:  # noqa: BLE001
        return []


async def _cmd_finalize_turn(conv: dict) -> str:
    """/定稿: 系统直通规约确认——reqId 由会话绑定注入, 模型不参与。

    门禁不过(常见 designMd 空)时先做确定性补救: 扫最近 assistant 消息提取
    规约载荷(```proposal/```json 围栏)——提取到 → apply 落新 draft 版本后再
    定稿(模型已产出过完整规约但 propose 参数不全的场景); 仍不过 → 给出
    可操作下一步(/调整 补方案), 不再是干巴巴的拒绝。
    """
    from .req_agent import tool_req_finalize
    conv_id = (conv or {}).get("id") or ""
    res = await asyncio.to_thread(tool_req_finalize, "", None, None)
    if res.get("ok"):
        if res.get("already"):   # 重复定稿(当前版本已 confirmed)
            return f"✅ {res.get('hint')}"
        return (f"✅ **规约已确认**：`{res.get('reqId')}` v{res.get('ver')}"
                f"（ready，可执行）\n下一步：发送 `/执行` 预览执行方案。")
    err = str(res.get("error") or "未知原因")
    if "designMd" in err or "结构不完整" in err:
        # 确定性补救: 最近 assistant 消息里的规约载荷 → amend 后重试定稿
        try:
            from .req_agent import extract_spec_payload, apply_spec_payload
            msgs = store.ConversationsStore.messages(conv_id, limit=30)
            for m in reversed(msgs):
                if m.get("role") != "assistant":
                    continue
                payload = extract_spec_payload(m.get("content") or "")
                if payload:
                    r2 = apply_spec_payload(
                        payload, req_id=str(conv.get("reqId") or ""),
                        project=str(conv.get("projectId") or ""), root="")
                    if r2.get("ok"):
                        res2 = await asyncio.to_thread(
                            tool_req_finalize, "", None, None)
                        if res2.get("ok"):
                            return (f"✅ **规约已确认**：`{res2.get('reqId')}` "
                                    f"v{res2.get('ver')}`（已从消息中的规约载荷补全并确认，"
                                    "ready，可执行）\n下一步：发送 `/执行` 预览执行方案。")
                    break
        except Exception:  # noqa: BLE001
            pass
        return ("❌ 定稿未通过：方案(designMd)为空——规约只有需求目标、缺少实施方案。\n\n"
                "**补全方式**：发送 `/调整` 进入修订模式，直接描述方案要点"
                "（如：技术选型、脚本结构、监控判活方式、指数退避参数、重试上限逻辑），"
                "我会整理成完整方案落为新版本；完成后再次 `/定稿` 即可。")
    return f"❌ 定稿未通过：{err}"

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
    # 生命周期重构: 角色是能力声明(roles 数组)——无白名单/锁定; architect 恒为对话主体
    # ---- 收件人路由(S2 双收件人) ----
    # 指令符号优先(系统级确定性通道, 不受收件人影响);
    # targetRole=coding → 活跃作业定向投递(等待中立即转达/回合中排队续跑);
    # 其余(含缺省) → architect 自由对话。running 不再锁定输入。
    target_role = str(data.get("targetRole") or "").strip()
    # ---- 会话指令符号分发(确定性, 无语义判断) ----
    #   /执行 → 执行预览; /确认执行 → 建作业; /定稿 → 规约确认(系统直通)
    #   /继续 → 增量回合; /diff → 作业差异; /调整 → req.amend 契约 + 主流程
    #   停止作业: 仅 UI 按钮(REST 确定操作), 无对话通道
    question = (user_msgs[-1].get("content", "") if user_msgs else "").strip()
    cmd = parse_session_cmd(question)
    final_b = None
    amend_contract = None
    if cmd in ("执行", "确认执行") and (conv.get("kind") or "") == "coding":
        # 子会话(coding)禁止再嵌套建子会话——作业由主会话统一管理
        final_b = ("当前是 coding 子会话（由主会话的作业管理）。\n"
                   "- 补充执行工程师的提问：直接发送（coding 收件人）或 `/继续`\n"
                   "- 启动/重开作业：请到主会话操作 `/执行`")
    elif cmd == "确认执行":
        from . import exec_bridge as _eb
        _wj = _eb.waiting_job(conv_id)
        if _wj:
            # 秩序: 待输入作业未处置(转达/停止)前不再叠新作业
            final_b = (f"存在等待输入的作业 `{(_wj.get('jobId') or '')[:14]}…`——\n"
                       "- 转达补充：回复内容后发 `/继续`\n"
                       "- 或从会话信息面板**停止**该作业后再启动新作业")
        else:
            final_b = await _executor_implement(conv, None, confirmed=True)
    elif cmd == "执行":
        final_b = await _executor_implement(conv, None, confirmed=False)
    elif cmd == "定稿":
        final_b = await _cmd_finalize_turn(conv)
    elif cmd == "继续":
        final_b = await _exec_resume_turn(conv)
    elif cmd == "diff":
        final_b = exec_bridge.diff_text(conv_id)
    elif cmd == "调整":
        amend_contract = (
            "【需求修订模式】本会话绑定需求 "
            f"{(conv.get('reqId') or '')}。用户要求补充/完善/调整需求或方案——"
            "与用户对话收敛修订内容，并用 req.amend 工具落为该需求的新 draft 版本"
            "(append-only 修订；不要调用 req.finalize，确认由用户 /定稿 指令发起)。"
            "修订完成后向用户复述变更点，并说明 `/执行` 将按新版本执行。")
    elif cmd:
        final_b = _cmd_help_text()
    elif target_role == "coding":
        final_b = await _deliver_coding_turn(conv, question)
    if final_b is not None:
        assistant_msg_id_b = store.next_id("m")
        store.ConversationsStore.append_message({
            "id": assistant_msg_id_b, "conversationId": conv_id,
            "role": "assistant", "time": _ts(), "content": final_b,
        })
        try:
            store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
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

    # tAgent 角色模型路由(§9/B1)：按场景角色取模型；explicit 会话选择优先，
    # 无角色命中时 eff_model=None → 回退全局偏好(既有链不变)。护栏 R3：per-call 参数。
    from . import agent_roles as _roles
    eff_model = _roles.resolve_role_model(_roles.scenario_role(skill_scenarios), model_id)

    # 模型能力档案懒探测(后台执行不阻塞): 无档案模型首轮触发, 探测落档后
    # 后续回合 system 按 tier 分级(小模型收紧预算, 大模型放开)
    try:
        from . import model_profile as _mp
        _mp.get_profile_or_lazy(eff_model or model_id or "")
    except Exception:  # noqa: BLE001
        pass

    msgs = _build_chat_messages(root, project, history, diagram_skill=diagram_skill,
                                skill_scenarios=[str(s) for s in skill_scenarios],
                                model_id=eff_model or model_id or "")
    if amend_contract:
        msgs.insert(1, {"role": "system", "content": amend_contract})
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
    # 范式(守卫卡片化): 检出 → 消息 meta.guard 落库(不进 LLM 上下文) → 前端卡片
    # 给出可点击修复指令与 /指令 chips; 点击 → guard-repair REST 外循环/填入对话框。
    claim, need = req_agent.fabricated_claim(final_content, tools_used)
    guard_meta = None
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
            "cmds": _guard_cmd_hints(conv_id),
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


async def _guard_autoland(conv: dict, final_content: str) -> Optional[dict]:
    """guard 确定性纠错: 编造「已创建需求」+ 正文含可提取规约 → 系统代为落库。

    落库成功返回 {notice, summary}(调用方补记佐证/更新卡片); 失败返回 None
    (仍走卡片人工修复)。model 已被误导, 不宜再让用户多点一步。
    """
    from .req_agent import extract_spec_payload, apply_spec_payload
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
    try:
        from .adaptation import strategies_for_model
        from .req_agent import extract_spec_payload
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
                    from . import llm_dataset as _lds
                    _lds.record("draft_card", ok=True, convId=conv_id, model=model_id or "")
                except Exception:  # noqa: BLE001
                    pass
                return {"kind": "specDraft", "payload": payload}
    except Exception as e:  # noqa: BLE001
        logger.warning("[kb-chat] 草稿卡提取失败 conv=%s: %s", conv_id, e)
    return None


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
                         skill_scenarios: Optional[List[str]] = None,
                         model_id: str = ""):
    """组装 prompt: 能力文档(system, 按模型档案 tier 分级+预算裁剪) + 最近 N 条历史。

    skill_scenarios 非空 → 按场景注入语义资产 skill 文档（资产管理对话='extract'）。
    model_id 非空 → 查模型能力档案(小模型收紧预算/大模型放开)。
    """
    from .req_agent import chat_system_prompt
    msgs = [{"role": "system", "content": chat_system_prompt(
        root, project, diagram_skill=diagram_skill, skill_scenarios=skill_scenarios,
        model_id=model_id)}]
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


def _build_impl_instruction(rid: str, prior_brief: str = "") -> str:
    """绑定需求 active 规约版本 → coding agent 实施指令(方案/边界/验收/DoD)。

    prior_brief: 前情简报(重试时注入——上次非完成作业的失败原因/改动/结论)。
    """
    r = store.RequirementsStore.get(rid) or {}
    active = store.RequirementsStore.spec_active(rid) or {}
    a = (active.get("snapshot") or {})
    if not a:
        a = r.get("analysis") or {}
    parts = [f"# 实施任务：{r.get('title') or rid}（{rid} · 规约 v{active.get('ver') or '?'}）"]
    if prior_brief:
        parts.append("## 前情简报(上次作业)\n" + prior_brief)
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


def _executor_hint(conv: Optional[dict]) -> Optional[dict]:
    """会话绑定的执行器(executor_id) → 执行器配置提示(model/端口等)。

    绑定模型 v3: conv.executor_id 直连 arch_collab_config 执行器注册表
    (一次绑定, 换=克隆); 无绑定 → None(实施走缺省 opencode)。
    """
    eid = ((conv or {}).get("executorId") or "").strip()
    if not eid:
        return None
    conv_model = ((conv or {}).get("executorModel") or "").strip()
    try:
        from .agent_executors import load_executors, _default_sidecar_path
        for e in load_executors():
            if (e.get("id") or "") == eid:
                cfg = e.get("config") or {}
                # 模型白名单真源: config.models[{name}](顶层 e.models 恒空——历史 bug 修正)
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
    """执行预览卡: 即将按哪个规约版本执行(方案摘要/边界/验收/分支), 待确认。"""
    rid = (conv or {}).get("reqId") or ""
    r = store.RequirementsStore.get(rid) or {}
    active = store.RequirementsStore.spec_active(rid) or {}
    snap = active.get("snapshot") or {}
    import datetime as _dt
    parts = [
        "📋 **执行预览**（回复 `/确认执行` 启动作业；`/调整` 可先修订规约）",
        f"- 需求：{r.get('title') or rid}（{rid}）",
        f"- 规约版本：v{active.get('ver') or pending.get('specVer') or '?'}"
        + ("（预览后规约已修订，本卡已按最新版本刷新）" if pending.get("stale") else "（最新）"),
        f"- 分支：`{pending.get('branchName') or ''}`",
        f"- 允许改动 {len(snap.get('allowedScope') or [])} 项 / "
        f"禁止改动 {len(snap.get('forbiddenScope') or [])} 项 / "
        f"验收标准 {len(snap.get('acceptance') or [])} 条",
        "- 交付：开发 + 单元测试 + 整体编译验收；对话不锁定(收件人可切换 architect/coding)，"
        "agent 提问/完成/报错时自动恢复对话",
    ]
    design = str(snap.get("designMd") or "")[:400]
    if design:
        parts.append(f"\n**方案摘要**：{design}…")
    jobs = _meta_get(conv).get("jobs") or []
    if jobs:
        parts.append(f"\n> ℹ️ 本会话已有 {len(jobs)} 次作业记录(账本可追溯)；本次为独立新作业。")
    return "\n".join(parts)


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


async def _executor_implement(conv: dict, role: Optional[dict], confirmed: bool = False) -> str:
    """执行指令 → 两段式: `/执行`=预览(不建作业); `/确认执行` → 真正建作业。

    版本绑定: 预览/确认均锚定 active 规约版本(specVer); 预览后规约修订
    (版本号变化) → 旧预览自动失效, 确认时按最新版本刷新预览。
    """
    import time as _time
    from . import exec_bridge
    conv_id = (conv or {}).get("id") or ""
    rid = (conv or {}).get("reqId") or ""
    if not rid:
        return ("本会话未绑定需求规约，无法执行。请先在对话中形成需求"
                "（模型会调用 req.propose），或从需求登记选择既有需求。")
    row = store.RequirementsStore.get(rid)
    if not row:
        return f"需求 {rid} 不存在。"
    if (row.get("doneMark") or 0) == 1:
        return (f"{rid} 已完结(用户判定)。继续迭代请新建需求"
                "（对话提出新需求即可，可引用本需求上下文）。")
    active = store.RequirementsStore.spec_active(rid)
    if not active:
        return "该需求无生效规约版本。"
    if active.get("state") != "confirmed":
        return ("当前规约版本 v%s 尚未确认(draft)。请先说「确认方案」或经需求登记确认"
                "（`/定稿` 指令经结构门禁校验后进入 ready），再 `/执行`。"
                % active.get("ver"))
    meta = _meta_get(store.ConversationsStore.get(conv_id) or conv)   # 现读 DB(传入行可能滞后)
    pending = meta.get("execPending") or {}
    spec_ver_now = int(active.get("ver") or 0)

    if confirmed and not pending:
        confirmed = False   # 无预览的「/确认执行」→ 按预览流程处理(生成预览)
    if confirmed:
        if _time.time() * 1000 - (pending.get("createdAt") or 0) > _EXEC_PENDING_TTL_MS:
            pending = {}
        if pending and pending.get("specVer") != spec_ver_now:
            pending = {}   # 预览后规约修订 → 需重新预览
        if not pending:
            instruction = _build_impl_instruction(rid, prior_brief=_prior_job_brief(conv))
            branch = f"exec/{rid.replace('RQ-', 'rq').lower()}-{_ts() % 100000}"
            pending = {"instruction": instruction, "branchName": branch,
                       "specVer": spec_ver_now, "createdAt": int(_time.time() * 1000)}
            meta["execPending"] = pending
            _meta_set(conv_id, meta)
            return _executor_preview_card(conv, instruction, pending) + \
                "\n\n(上一份预览已因规约修订/超时失效，已按最新版本刷新)"
        meta.pop("execPending", None)
        _meta_set(conv_id, meta)
        return exec_bridge.start_implement(
            conv, pending["instruction"], executor_hint=_executor_hint(conv),
            branch_name=pending.get("branchName") or "",
            spec_ver=spec_ver_now)

    # /执行 → 生成/刷新预览
    instruction = _build_impl_instruction(rid, prior_brief=_prior_job_brief(conv))
    stale = bool(pending) and pending.get("specVer") != spec_ver_now
    branch = (pending.get("branchName") if pending and not stale else "") or \
        f"exec/{rid.replace('RQ-', 'rq').lower()}-{_ts() % 100000}"
    pending = {"instruction": instruction, "branchName": branch,
               "specVer": spec_ver_now, "createdAt": int(_time.time() * 1000),
               "stale": stale}
    meta["execPending"] = pending
    _meta_set(conv_id, meta)
    return _executor_preview_card(conv, instruction, pending)


async def _exec_resume_turn(conv: dict) -> str:
    """`/继续`: 把上次回合结束后的用户补充打包交回等待中的作业(增量回合)。

    依赖 coding agent 会话保持能力(opencode session 多轮, 已确认); 作业终态
    (done/failed/lost)时不可续——引导走 `/执行` 新作业(自动带前情简报)。
    """
    from . import exec_bridge
    conv_id = (conv or {}).get("id") or ""
    ledger_conv = conv_id   # 作业账本所有者(默认本会话; 跨会话续跑时=父会话)
    job = exec_bridge.waiting_job(conv_id)
    if not job and (conv or {}).get("kind") == "coding":
        # 子会话: job_input 提示落在子会话, 作业账本在主会话——
        # 沿父链找 waiting 且 sub=当前会话 的作业(用户正是在此收到提示)
        pid = str((conv or {}).get("parentConvId") or "")
        pjob = exec_bridge.waiting_job(pid)
        if pjob and pjob.get("subSessionId") == conv_id:
            job = pjob
            ledger_conv = pid   # 账本所有者: job_input 状态回写目标
    if not job:
        if exec_bridge.is_running(conv_id):
            return ("作业正在执行回合中——补充内容可直接以 coding 收件人发送(自动排队续跑)，"
                    "或等待回合结束(多为等待回复)后再发 `/继续`。")
        return ("没有等待输入的作业。发送 `/执行` 按当前规约版本启动新作业"
                "（会自动附带上次作业的前情简报）。")
    # 增量上下文: 上次 agent 事件消息之后的所有用户消息
    msgs = store.ConversationsStore.messages(conv_id, limit=30)
    cut_ts = job.get("lastAgentTs") or 0
    inc = [m.get("content", "").strip() for m in msgs
           if m.get("role") == "user" and (m.get("time") or 0) > cut_ts
           and (m.get("content") or "").strip()]
    if not inc:
        return ("没有新补充的信息。请先回复执行工程师的问题，再发送 `/继续`。")
    payload = ("用户补充/回复(/继续)：\n\n" + "\n\n---\n\n".join(inc[:10]))
    res = await asyncio.to_thread(
        exec_bridge.job_input,
        ledger_conv,
        job.get("jobId", ""), payload)
    if res.get("ok"):
        return (f"➡️ 已转达执行工程师（{len(inc)} 条补充），作业继续。"
                "回合期间可继续以 architect 身份讨论；agent 提问/完成/报错时恢复对话。")
    return f"转达失败：{res.get('error') or 'runner 不可达'}。可稍后重试或 `/执行` 新作业。"





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
