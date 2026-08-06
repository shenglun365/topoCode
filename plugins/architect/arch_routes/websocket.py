"""WebSocket routes for KB analysis agent, coding agent and unit-test execution."""
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .common import _ts, _id
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()


@router.websocket("/ws/kb-analysis")
async def kb_analysis_ws(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "clarify":
                await websocket.send_json({
                    "type": "clarify",
                    "questions": [
                        {"key": "scope", "label": "需求影响范围", "type": "text", "hint": "描述该需求涉及的模块"},
                        {"key": "priority", "label": "优先级", "type": "select", "options": ["P0", "P1", "P2"]},
                    ],
                    "turnId": _id("turn"),
                })
            elif msg_type == "answer":
                await websocket.send_json({
                    "type": "collect", "status": "analyzing", "message": "正在分析知识库…",
                })
                await asyncio.sleep(1)
                await websocket.send_json({
                    "type": "collect", "status": "done",
                    "report": {
                        "functionalScope": ["订单创建", "库存预扣"],
                        "entityBoundary": ["Order", "Inventory"],
                        "feasibility": {"ok": True, "reason": "影响范围可控", "estMin": 120},
                        "assetScope": [
                            {"assetId": "c-order", "assetType": "component", "role": "core", "source": "auto"},
                        ],
                    },
                })
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("KB analysis WebSocket disconnected")


@router.websocket("/ws/coding-agent")
async def coding_agent_ws(websocket: WebSocket):
    """coding-agent 会话流(阶段 2 服务端模拟 + 落库)。

    契约见 docs/architect/api-execution.md §5。客户端消息:
      session.create  { exec, planTitle, keepContext? }   → session_created { session }
      session.message { sessionId, content }              → message
      task.run       { sessionId, task }                  → 流式 message/tool_call/status/tree.change + done|failed|stopped
      session.stop   { sessionId }                        → status stopped
      ping                                                → pong
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
                if session_id not in _RUNNING:
                    await websocket.send_json({"type": "stopped", "sessionId": session_id, "status": "stopped"})

    except WebSocketDisconnect:
        logger.info("Coding agent WebSocket disconnected")
    except Exception as e:
        logger.exception(f"Coding agent WS error: {e}")


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
    """coding-agent 任务执行流(服务端模拟，对齐 mock agent-engine，边流边落库)。

    isCancelled 语义: 收到 session.stop 后置 _CANCELLED；任务流内各步检查。
    """
    session = store.AgentSessionsStore.get(session_id)
    if not session:
        await websocket.send_json({"type": "error", "message": "Session not found"})
        _RUNNING.discard(session_id)
        return
    _CANCELLED.discard(session_id)

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
