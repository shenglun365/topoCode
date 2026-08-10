"""WebSocket routes for KB analysis agent, coding agent and unit-test execution."""
import asyncio
import logging
from typing import Dict, List, Optional
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .common import _ts, _id
from . import store
from . import agent_server
from . import agent_adapters
from . import arch_git

logger = logging.getLogger(__name__)
router = APIRouter()

_MAX_TOOL_ROUNDS = 4


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
    kind = data.get("kind") or "requirement"
    title = data.get("title") or f"{kind} 对话"

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
        if not conv:
            await websocket.send_json({"type": "error", "message": "conversation not found"})
            return
    user_msgs = [m for m in history if m.get("role") == "user" and (m.get("content") or "").strip()]
    last_user_msg_id = ""
    for m in user_msgs[-1:]:
        last_user_msg_id = store.next_id("m")
        store.ConversationsStore.append_message({
            "id": last_user_msg_id, "conversationId": conv_id,
            "role": "user", "time": now, "content": m.get("content", ""),
        })

    # ---- 上下文: 能力文档 + 历史(带软拒绝范围) ----
    msgs = _build_chat_messages(root, project, history)

    # ---- 连续多轮流式: 工具调用循环(architect 自持，最多 MAX_TOOL_ROUNDS 轮) ----
    request_id = None
    assistant_text = ""
    tool_round = 0
    loop_fell_back = False
    while tool_round <= _MAX_TOOL_ROUNDS:
        rid = _req_chat_stream(msgs, model_id or req_agent.get_model_preference())
        if not rid:
            # 流式通道中断：带工具结果的累积上下文改走 llm.sync 收尾
            loop_fell_back = True
            assistant_text = await _sync_with_tools(msgs, root, project, model_id)
            break
        request_id = rid
        await websocket.send_json({"type": "chat_start", "conversationId": conv_id,
                                   "requestId": rid, "userMessageId": last_user_msg_id})
        round_text = ""
        round_ok = True
        async for event_type, payload in _iter_llm_events(rid):
            if event_type == "chunk":
                round_text += payload.get("text") or ""
            elif event_type == "done":
                round_text = payload.get("content") or round_text
                break
            elif event_type == "error":
                round_ok = False
                await websocket.send_json({"type": "error", "requestId": rid,
                                           "message": payload.get("message", "")})
                break
        if not round_ok:
            # 该轮流式出错但已带工具上下文：降级到 llm.sync 收尾，避免无结果
            loop_fell_back = True
            assistant_text = await _sync_with_tools(msgs, root, project, model_id)
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
                    result = await asyncio.to_thread(
                        req_agent.run_arch_tool, name, args, root, project
                    )
                    results.append({"name": name,
                                    "text": req_agent.tool_result_text(name, result)})
                if results:
                    tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                    msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                    msgs.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
                loop_fell_back = True
                assistant_text = await _sync_with_tools(msgs, root, project, model_id)
                break
            tool_round += 1
            results: List[Dict[str, str]] = []
            for c in calls:
                name = c.get("tool", "")
                args = c.get("arguments", {})
                result = await asyncio.to_thread(
                    req_agent.run_arch_tool, name, args, root, project
                )
                logger.info("[req_agent] kb chat tool round=%s call=%s result_keys=%s",
                            tool_round, name, list(result.keys()) if isinstance(result, dict) else ())
                results.append({"name": name,
                                "text": req_agent.tool_result_text(name, result)})
            if results:
                tool_feed = "\n".join(f"[{r['name']}] {r['text']}" for r in results)
                msgs.append({"role": "assistant", "content": req_agent.strip_tool_blocks(round_text) or "(调用知识库检索)"})
                msgs.append({"role": "user", "content": f"以下是知识库工具返回结果，请基于结果直接回答，不再输出工具调用块：\n{tool_feed}"})
            continue

        # 无工具调用 → 本轮即最终答案
        assistant_text = req_agent.strip_tool_blocks(round_text)
        break

    # 最终答案按小块逐字转发，保持流式观感
    if assistant_text:
        CHUNK_SIZE = 24
        for i in range(0, len(assistant_text), CHUNK_SIZE):
            await websocket.send_json({"type": "chunk", "requestId": request_id,
                                       "delta": assistant_text[i:i + CHUNK_SIZE]})
    elif request_id is None and not loop_fell_back:
        # ---- 降级: llm.sync 一次性(同样支持工具调用循环，避免输出裸 [TOOL_CALL] 块) ----
        assistant_text = await _sync_with_tools(msgs, root, project, model_id)
        if not assistant_text:
            await websocket.send_json({"type": "chat_fallback", "conversationId": conv_id})
    else:
        await websocket.send_json({"type": "error", "requestId": request_id, "message": "LLM 未返回内容"})
    if assistant_text:
        assistant_msg_id = store.next_id("m")
        store.ConversationsStore.append_message({
            "id": assistant_msg_id, "conversationId": conv_id,
            "role": "assistant", "time": _ts(), "content": assistant_text,
        })
        await websocket.send_json({"type": "done", "conversationId": conv_id,
                                   "content": assistant_text, "messageId": assistant_msg_id})


async def _sync_with_tools(msgs, root, project, model_id, max_rounds: int = 4) -> str:
    """llm.sync 降级通道：走统一工具调用循环(req_agent.run_tools_loop)，
    避免「LLM 输出 [TOOL_CALL] 后无结果」。返回最终纯文本。
    """
    from . import req_agent
    res = await asyncio.to_thread(
        req_agent.run_tools_loop, msgs,
        root=root, project=project, model_id=model_id,
        mode="chat", max_tokens=2000, max_rounds=max_rounds,
    )
    return res.get("content", "") if isinstance(res, dict) else ""


def _build_chat_messages(root, project, history, cap=20):
    """组装 prompt: 能力文档(system) + 最近 N 条历史。"""
    from .req_agent import chat_system_prompt
    msgs = [{"role": "system", "content": chat_system_prompt(root, project)}]
    for m in history[-cap:]:
        if isinstance(m, dict) and m.get("role") in ("user", "assistant") and (m.get("content") or "").strip():
            msgs.append({"role": m["role"], "content": m["content"]})
    return msgs


async def _iter_llm_events(request_id: str):
    """architect 进程内 ZMQ SUB 订阅主后端 llm.* 流(按 requestId 过滤)。"""
    from .zmq_stream import iter_llm_events
    async for e in iter_llm_events(request_id):
        yield e


def _req_chat_stream(msgs, model_id):
    """发起流式 llm.chat; 返回 requestId 或 None(降级)。"""
    from .req_agent import llm_chat_start
    return llm_chat_start(msgs, model_id=model_id, session_id="arch-req-chat", max_tokens=2000)


@router.websocket("/ws/coding-agent")
async def coding_agent_ws(websocket: WebSocket):
    """coding-agent 会话流(阶段 2 服务端模拟 + 落库；真实 opencode 对接优先)。

    契约见 docs/architect/api-execution.md §5。客户端消息:
      session.create  { exec, planTitle, keepContext?, root? }   → session_created { session }
      session.message { sessionId, content }                      → message
      task.run       { sessionId, task }                          → 流式 message/tool_call/status/tree.change + done|failed|stopped
      session.stop   { sessionId }                                → status stopped
      ping                                                        → pong

    session.create 携带 root(工程实现目录)时走真实 opencode(经 AgentInstancePool)；
    无 root / 实例不可达 / 探测失败 → 回退服务端模拟(与 api-execution.md §5.4 一致)。
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

                # 真实 opencode 对接: 需要 root 或 project + 该 adapter 的连接配置。
                inst = None
                if root or project_id:
                    inst = await _ensure_opencode_session(root, project_id, exec_data, session_id)
                if inst:
                    store.AgentSessionsStore.update(session_id, {
                        "instanceId": inst["id"], "status": "idle", "updatedAt": _ts(),
                    })
                    session["instanceId"] = inst["id"]
                await websocket.send_json({"type": "session_created", "session": session})

            elif msg_type == "session.message":
                session_id = data.get("sessionId")
                content = data.get("content", "")
                session = store.AgentSessionsStore.get(session_id)
                if not session:
                    await websocket.send_json({"type": "error", "message": "Session not found"})
                    continue
                user_msg = {
                    "id": store.next_id("m"), "role": "user", "time": _ts(), "content": content,
                }
                store.AgentSessionsStore.append_message({**user_msg, "sessionId": session_id})
                store.AgentSessionsStore.update(session_id, {"updatedAt": _ts()})
                if session.get("opencodeSessionId"):
                    reply = await _opencode_message(session, content)
                    if reply:
                        m = {"id": store.next_id("m"), "role": "assistant", "time": _ts(), "content": reply}
                        store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
                        await websocket.send_json({"type": "message", **m})
                await websocket.send_json({"type": "message", **user_msg})

            elif msg_type == "task.run":
                session_id = data.get("sessionId")
                task = data.get("task", {})
                if session_id in _RUNNING:
                    await websocket.send_json({"type": "error", "message": "Session already running"})
                    continue
                _RUNNING.add(session_id)
                asyncio.create_task(_run_coding_agent_task(websocket, session_id, task))

            elif msg_type == "session.stop":
                session_id = data.get("sessionId")
                _CANCELLED.add(session_id)
                session = store.AgentSessionsStore.get(session_id)
                if session and session.get("opencodeSessionId"):
                    await _opencode_abort(session)
                if session_id not in _RUNNING:
                    await websocket.send_json({"type": "stopped", "sessionId": session_id, "status": "stopped"})

    except WebSocketDisconnect:
        logger.info("Coding agent WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Coding agent WS error: {e}")


# ── 真实 opencode 对接辅助 ─────────────────────────────────────

def _config_for_adapter(adapter: str):
    for c in store.AgentConfigsStore.all():
        if (c.get("adapter") or "").lower() == (adapter or "opencode").lower():
            return c
    return None


def _project_for_root(root: str):
    from .project import _resolve_project
    return _resolve_project(root, None)


def _task_prompt(task: dict, root: Optional[str] = None) -> str:
    """任务上下文包 + 语义数据资产锚点展开(锁定「改哪里」)。"""
    context = task.get("context") or []
    text = (
        f"任务「{task.get('title', '')}」。\n"
        f"上下文: {' / '.join(context) if context else '无'}\n"
    )
    try:
        from . import semantic_assets as S
        block = S.context_block_for(root, None, context)
        if block:
            text += block + "\n"
    except Exception:
        pass
    text += "请按架构规约实现, 完成后提交到当前分支并保持测试通过。"
    return text


def _project_for(root: Optional[str], project_id: Optional[str]):
    from .project import _resolve_project
    return _resolve_project(root, project_id)


async def _ensure_opencode_session(root: str, project_id: Optional[str], exec_data: dict, session_id: str) -> Optional[dict]:
    """确保项目实例就绪 + 创建 agent 会话。失败返回 None(调用方回退模拟)。"""
    try:
        project = _project_for(root or None, project_id)
        if not project or not project.get("id"):
            return None
        adapter = (exec_data.get("adapter") or "opencode").lower()
        agent = agent_adapters.get_agent(adapter)
        if agent is None:
            return None
        cfg = _config_for_adapter(adapter)
        if not cfg:
            return None
        pool = agent_server.get_pool()
        inst = await pool.ensure(project, cfg)
        if not inst or inst.get("state") not in ("ready", "busy", "idle"):
            return None
        client = agent_server.agent_client_for(inst, cfg, agent.id)
        title = f"architect/{session_id} · {exec_data.get('id', '')}"
        oc = client.create_session(title=title)
        oc_id = oc.get("id") or oc.get("_id")
        if not oc_id or oc.get("_error"):
            logger.warning(f"[coding-agent] opencode 会话创建失败: {oc.get('_error', 'no id')}")
            return None
        store.AgentSessionsStore.update(session_id, {"opencodeSessionId": oc_id, "updatedAt": _ts()})
        # 任务树由 exec 提供; 建 task 分支并记录到实例。
        task_branch = exec_data.get("taskBranch") or f"arch/{exec_data.get('id', session_id)}"
        store.AgentInstancesStore.update(inst["id"], {
            "taskBranch": task_branch, "updatedAt": _ts(),
        })
        return inst
    except Exception as e:
        logger.warning(f"[coding-agent] 真实 opencode 会话创建失败, 回退模拟: {e}")
        return None


async def _opencode_message(session: dict, content: str) -> str:
    """向 agent 会话发消息(同步取回复文本)。失败返回空串。阻塞调用放线程。"""
    try:
        inst = store.AgentInstancesStore.get(session.get("instanceId") or "")
        cfg = _config_for_adapter(session.get("adapter") or "opencode")
        if not inst or not cfg:
            return ""
        adapter = agent_adapters.get_agent(session.get("adapter") or "opencode")
        if adapter is None:
            return ""
        client = agent_server.agent_client_for(inst, cfg, adapter.id)
        res = await asyncio.to_thread(client.send_message, session.get("opencodeSessionId", ""), content)
        if res.get("_error"):
            return ""
        info = res.get("info") or {}
        parts = res.get("parts") or []
        texts = [p.get("text", "") for p in parts if p.get("type") == "text" and p.get("text")]
        return "\n".join(texts) or (info.get("id") or "")
    except Exception as e:
        logger.warning(f"[coding-agent] agent 消息失败: {e}")
        return ""


async def _opencode_abort(session: dict) -> None:
    try:
        inst = store.AgentInstancesStore.get(session.get("instanceId") or "")
        cfg = _config_for_adapter(session.get("adapter") or "opencode")
        if not inst or not cfg:
            return
        adapter = agent_adapters.get_agent(session.get("adapter") or "opencode")
        if adapter is None:
            return
        client = agent_server.agent_client_for(inst, cfg, adapter.id)
        await asyncio.to_thread(client.abort, session.get("opencodeSessionId", ""))
    except Exception:
        pass


_CANCELLED: set[str] = set()
_RUNNING: set[str] = set()

_ASSISTANT_REPLIES = [
    "计划: 1) 建立任务入口与领域对象  2) 实现核心逻辑并接入唯一约束  3) 补齐单测与集成用例。待你确认后开始。",
    "正在实现核心逻辑…已完成主体，正在进行自测与用例补充。",
    "已按规约完成编码并提交(Conventional Commits)。",
]

_TOOL_SEQUENCE = [
    {"type": "write-file", "label": "app/domain.go", "detail": "领域对象与不变量 96 行", "ok": True, "delay": 0.42},
    {"type": "write-file", "label": "app/service.go", "detail": "核心业务逻辑 + 幂等查重 214 行", "ok": True, "delay": 0.36},
    {"type": "run-command", "label": "go test ./app/...", "detail": "单测 14 个，通过 14", "ok": True, "delay": 0.30},
    {"type": "run-test", "label": "tests/integration_test.go", "detail": "集成用例 3 个，通过 3", "ok": True, "delay": 0.38},
]


def _agent_bump_stats(session: dict, bytes_: int) -> None:
    stats = session.get("stats") or {"requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0}
    stats["requests"] += 1
    stats["bytesIn"] += bytes_
    stats["bytesOut"] += round(bytes_ * 0.4)
    stats["tokensIn"] += round(bytes_ / 4)
    stats["tokensOut"] += round(bytes_ / 10)
    session["stats"] = stats


async def _run_coding_agent_task(websocket: WebSocket, session_id: str, task: dict) -> None:
    """coding-agent 任务执行流(真实 opencode 优先；无 opencode 会话则服务端模拟)。

    isCancelled 语义: 收到 session.stop 后置 _CANCELLED；任务流内各步检查。
    """
    session = store.AgentSessionsStore.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        _RUNNING.discard(session_id)
        return
    _CANCELLED.discard(session_id)

    oc_id = session.get("opencodeSessionId") or ""
    inst = store.AgentInstancesStore.get(session.get("instanceId") or "") if oc_id else None

    # 真实执行路径: 有 opencode 会话 → 发任务上下文包, 同步取最终回复。
    if oc_id and inst:
        try:
            await _run_opencode_task(websocket, session, inst, task)
            return
        except Exception as e:
            logger.warning(f"[coding-agent] opencode 执行失败, 回退模拟: {e}")
        finally:
            _RUNNING.discard(session_id)

    def cancelled() -> bool:
        return session_id in _CANCELLED

    async def set_status(status: str) -> None:
        store.AgentSessionsStore.update(session_id, {"status": status, "updatedAt": _ts()})
        await websocket.send_json({"type": "status", "sessionId": session_id, "status": status})

    async def finish(status: str) -> None:
        """终止事件(类型 = 最终状态),同时落库并携带最终 stats/artifacts。"""
        _RUNNING.discard(session_id)
        cur = store.AgentSessionsStore.get(session_id) or {}
        store.AgentSessionsStore.update(session_id, {"status": status, "updatedAt": _ts()})
        await websocket.send_json({
            "type": status,
            "sessionId": session_id,
            "status": status,
            "stats": cur.get("stats"),
            "artifacts": cur.get("artifacts"),
            "testResult": cur.get("testResult"),
        })

    def push(role: str, content: str, tool=None) -> dict:
        msg = {
            "id": store.next_id("m"), "role": role, "time": _ts(), "content": content,
        }
        if tool:
            msg["tool"] = tool
        store.AgentSessionsStore.append_message({**msg, "sessionId": session_id})
        return msg

    await set_status("planning")
    _agent_bump_stats(session, 3200)
    await asyncio.sleep(0.4)
    if cancelled():
        return await finish("stopped")
    m = push("assistant", f"收到任务「{task.get('title', '')}」，已加载上下文包: {' / '.join(task.get('context', []) or [])}。")
    await websocket.send_json({"type": "message", **m})
    await asyncio.sleep(0.3)
    if cancelled():
        return await finish("stopped")
    m = push("assistant", _ASSISTANT_REPLIES[0])
    await websocket.send_json({"type": "message", **m})

    await set_status("working")
    for i, step in enumerate(_TOOL_SEQUENCE):
        await asyncio.sleep(step["delay"])
        if cancelled():
            return await finish("stopped")
        _agent_bump_stats(session, 2400 + i * 800)
        tool = {k: v for k, v in step.items() if k != "delay"}
        m = push("tool", "", tool)
        await websocket.send_json({"type": "tool_call", "tool": tool, "id": m["id"], "time": m["time"]})
        if i == 1:
            await websocket.send_json({"type": "tree.change", "sessionId": session_id,
                                       "reason": "执行中发现拆分粒度不合理，整体重建任务树(旧树缩略保存)"})

    if cancelled():
        return await finish("stopped")
    await set_status("testing")
    await asyncio.sleep(0.35)
    if cancelled():
        return await finish("stopped")
    ok = task.get("_ok") is not False
    done_msg = push(
        "assistant",
        "任务完成：单测与集成用例全部通过，符合编码规约。已生成变更摘要待验收。"
        if ok else "存在未通过用例，已标记风险项，等待你的决策或降级方案。",
    )
    store.AgentSessionsStore.update(session_id, {"stats": session.get("stats"), "updatedAt": _ts()})
    await websocket.send_json({"type": "message", **done_msg})
    await finish("done" if ok else "failed")


async def _run_opencode_task(websocket: WebSocket, session: dict, inst: dict, task: dict) -> None:
    """真实执行: 组装上下文包 → 下发 → 流式消费(fallback 同步取回复) → 更新 git 引用。

    流式: adapter 支持流式时, 订阅 /event → 归一化前端 WS 事件(message/tool_call/status);
    同时阻塞调用经 `asyncio.to_thread`, 避免卡住事件循环。不支持流式的 adapter 走同步回退。
    """
    session_id = session["id"]
    oc_id = session.get("opencodeSessionId", "")
    cfg = _config_for_adapter(session.get("adapter") or "opencode")
    if not cfg:
        raise RuntimeError("无 agent 连接配置")
    adapter = agent_adapters.get_agent(session.get("adapter") or "opencode")
    if adapter is None:
        raise RuntimeError(f"未知 adapter: {session.get('adapter')}")
    client = agent_server.agent_client_for(inst, cfg, adapter.id)

    await websocket.send_json({"type": "status", "sessionId": session_id, "status": "planning"})
    store.AgentSessionsStore.update(session_id, {"status": "planning", "updatedAt": _ts()})

    # 任务上下文包(方案/任务/上下文文件 + 语义数据资产锚点展开)。
    context = task.get("context") or []
    ctx_text = _task_prompt(task, inst.get("workDir"))
    model = session.get("model") or ""

    def _forward(ev: dict) -> None:
        kind = ev.get("type")
        if kind == "message":
            m = {"id": store.next_id("m"), "role": "assistant", "time": _ts(),
                 "content": ev.get("content", "")}
            store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
            asyncio.create_task(websocket.send_json({"type": "message", **m}))
        elif kind == "tool_call":
            m = {"id": store.next_id("m"), "role": "tool", "time": _ts(),
                 "content": "", "tool": ev.get("tool", {})}
            store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
            asyncio.create_task(websocket.send_json({"type": "tool_call", "id": m["id"],
                                                     "time": m["time"], "tool": m["tool"]}))
        elif kind == "status":
            asyncio.create_task(websocket.send_json({"type": "status",
                                                     "sessionId": session_id,
                                                     "status": ev.get("status")}))

    async def _finish() -> None:
        """任务收尾: 更新状态 → 同步 git 分析副本 → 终态事件。"""
        await websocket.send_json({"type": "status", "sessionId": session_id, "status": "done"})
        store.AgentSessionsStore.update(session_id, {"status": "done", "updatedAt": _ts()})
        project = _project_for_root(inst.get("workDir") or "")
        task_branch = inst.get("taskBranch") or ""
        if project and task_branch:
            copy = arch_git.pull_task_branch(project, task_branch)
            if copy.get("ok"):
                await websocket.send_json({
                    "type": "tree.change", "sessionId": session_id,
                    "reason": f"agent 已提交到 {task_branch}({copy.get('commit', '')[:8]}), 分析副本已同步",
                })
        await websocket.send_json({
            "type": "done", "sessionId": session_id, "status": "done",
            "stats": session.get("stats"), "artifacts": session.get("artifacts"),
            "testResult": session.get("testResult"),
        })

    # cli 型(进程执行): 一次性子进程流式消费; 复用 _finish 收尾。
    if getattr(adapter, "mode", "server") == "cli":
        workdir = inst.get("workDir") or (client.cfg or {}).get("workdir") or ""
        context = task.get("context") or []
        ctx_text = _task_prompt(task, workdir)

        async def _forward_cli(ev: dict) -> None:
            kind = ev.get("type")
            if kind == "message":
                m = {"id": store.next_id("m"), "role": "assistant", "time": _ts(),
                     "content": ev.get("content", "")}
                store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
                asyncio.create_task(websocket.send_json({"type": "message", **m}))
            elif kind == "tool_call":
                m = {"id": store.next_id("m"), "role": "tool", "time": _ts(),
                     "content": "", "tool": ev.get("tool", {})}
                store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
                asyncio.create_task(websocket.send_json({"type": "tool_call", "id": m["id"],
                                                         "time": m["time"], "tool": m["tool"]}))
            elif kind == "error":
                _agent_bump_stats(session, 400)
                await websocket.send_json({"type": "message", "sessionId": session_id,
                                           "content": ev.get("content", "")})
            elif kind == "status":
                asyncio.create_task(websocket.send_json({"type": "status",
                                                         "sessionId": session_id,
                                                         "status": ev.get("status")}))

        try:
            async for ev in adapter.process_events(client, ctx_text, session.get("model") or "",
                                                   resume="", workdir=workdir):
                if session_id in _CANCELLED:
                    break
                await _forward_cli(ev)
            await _run_cancel(websocket, session_id, _finish())
        finally:
            _RUNNING.discard(session_id)
        return

    try:
        # 先注入上下文(no_reply: 只注入不等待 AI 回复)。
        await asyncio.to_thread(client.send_message, oc_id, ctx_text, "", True)

        if not adapter.supports_stream:
            # 非流式回退: 同步取最终回复文本。
            res = await asyncio.to_thread(client.send_message, oc_id, ctx_text, model)
            if res.get("_error"):
                raise RuntimeError(res["_error"])
            for t in [p.get("text", "") for p in (res.get("parts") or [])
                      if p.get("type") == "text" and p.get("text")]:
                m = {"id": store.next_id("m"), "role": "assistant", "time": _ts(), "content": t}
                store.AgentSessionsStore.append_message({**m, "sessionId": session_id})
                await websocket.send_json({"type": "message", **m})
            await _run_cancel(websocket, session_id, _finish())
            return

        # 流式: 后台下发任务 + 前台消费 /event 归一化事件, 直至下发完成。
        send_fut = asyncio.create_task(asyncio.to_thread(client.send_message, oc_id, ctx_text, model))
        iterator = adapter.iter_events(client, oc_id)

        async def _drain() -> None:
            async for ev in iterator:
                if send_fut.done() or session_id in _CANCELLED:
                    break
                _forward(ev)

        drain_fut = asyncio.create_task(_drain())
        try:
            if session_id in _CANCELLED:
                # 已取消: 不等下发完成, abort 由 stop 处理器负责。
                await asyncio.wait_for(asyncio.shield(drain_fut), timeout=1.0)
            else:
                res = await asyncio.wait_for(asyncio.shield(send_fut), timeout=None)
                # send 完成后短暂收尾 SSE 尾部事件, 再关闭。
                await asyncio.wait_for(asyncio.shield(drain_fut), timeout=1.0)
                if isinstance(res, dict) and res.get("_error"):
                    raise RuntimeError(res["_error"])
        except asyncio.TimeoutError:
            pass
        finally:
            drain_fut.cancel()
            await asyncio.gather(drain_fut, return_exceptions=True)
            await iterator.aclose()
        await _run_cancel(websocket, session_id, _finish())
    finally:
        _RUNNING.discard(session_id)


async def _run_cancel(websocket: WebSocket, session_id: str, coro) -> None:
    """在取消检查通过后执行收尾; 已取消则发 stopped。"""
    if session_id in _CANCELLED:
        await websocket.send_json({"type": "stopped", "sessionId": session_id, "status": "stopped"})
        return
    await coro


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
                    script = test["scriptPath"] or name
                    # 开始 tool 消息
                    tool_start = {"type": "run-test", "label": script, "detail": f"开始执行「{name}」", "ok": True}
                    start_msg = _push_session_message(session_id, "tool", "", tool_start)
                    await websocket.send_json({"type": "tool_call", "tool": tool_start, "id": start_msg["id"], "time": start_msg["time"]})
                    await asyncio.sleep(0.5)
                    # 服务端模拟判定: ut-3 失败
                    fail = (test_id == "ut-3")
                    if fail:
                        last_result = {"passed": 5, "failed": 2, "error": "TestRelayRetry: 重试退避断言失败",
                                       "note": f"go test {script}", "at": _ts()}
                        status = "failed"
                        detail = f"失败: {last_result['error']}"
                    else:
                        last_result = {"passed": 12, "failed": 0, "note": "全部通过", "at": _ts()}
                        status = "passed"
                        detail = f"通过: {last_result['passed']} 用例"
                    store.UnitTestsStore.update(test_id, {"status": status, "lastResult": last_result, "updatedAt": _ts()})
                    store.UnitTestSessionsStore.update(session_id, {"updatedAt": _ts()})
                    await websocket.send_json({"type": "result", "testId": test_id, "status": status, "lastResult": last_result})
                    tool_end = {"type": "run-test", "label": script, "detail": detail, "ok": not fail}
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
