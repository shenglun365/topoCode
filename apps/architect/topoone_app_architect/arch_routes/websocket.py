"""WS 适配层 — KB 分析流 + 单测执行流。

P2 重构: KB 对话回合管道已迁至 agent.orchestrator(九层内核);
本模块仅保留 WS 协议适配(接收/事件形状契约冻结, CONV-04)与
unit-test 域(独立通道, 后续同法迁出)。
"""
import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from . import store
from .common import _ts

logger = logging.getLogger(__name__)
router = APIRouter()

# 兼容 re-export(P0 特征测试引用): 通用执行意图正则已迁至 agent.perception.intent
from ..agent.perception.intent import GENERIC_EXEC_RE as _GENERIC_EXEC_RE  # noqa: F401,E402

@router.websocket("/ws/kb-analysis")
async def kb_analysis_ws(websocket: WebSocket):
    """需求分析 <=> KB agent 会话流(事件形状契约见 docs/architect/api-unit-test.md 同级约定)。

    客户端消息:
      chat   { conversationId?, kind?, projectId?, reqId?, title?, messages:[{role,content}], modelId?,
               attachTo?, agent? }
             → streaming: chat_start → chunk/reasoning/status/tool_call/tool_result* → done | error
      ping   → pong

    回合管道: agent.orchestrator.handle_chat(九层内核)。
    """
    await websocket.accept()
    from ..agent import orchestrator

    async def _send(payload: dict) -> None:
        # 安全发送: 客户端断连后吞掉发送异常, 服务端继续消费流/守卫/落库——
        # 避免回合中断且历史整段丢失(实测断连即丢整回合)
        try:
            await websocket.send_json(payload)
        except Exception:  # noqa: BLE001
            pass

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")

            if msg_type == "ping":
                await websocket.send_json({"type": "pong"})

            elif msg_type == "chat":
                try:
                    await orchestrator.handle_chat(data, _send)
                except Exception as e:  # noqa: BLE001
                    # 回合级异常兜底: 完整错误落库(turnError)+回传——
                    # 不再静默吞掉(cv-154 实证: 异常后 UI 零反馈且刷新即失)
                    logger.exception("[kb-chat] 回合异常 conv=%s",
                                     (data or {}).get("conversationId"))
                    detail = f"{type(e).__name__}: {e}"
                    conv_id = str((data or {}).get("conversationId") or "")
                    if conv_id:
                        try:
                            from ..agent.collab import cards as _cards
                            _cards.land(conv_id, f"❌ 回合失败：{detail}",
                                        kind=_cards.KIND_TURN_ERROR)
                        except Exception:  # noqa: BLE001
                            logger.exception("[kb-chat] turnError 落库失败 conv=%s",
                                             conv_id)
                    await _send({"type": "error",
                                 "requestId": str((data or {}).get("requestId") or ""),
                                 "message": f"回合失败：{detail}"})

    except WebSocketDisconnect:
        logger.info("KB analysis WebSocket disconnected")
    except Exception as e:
        logger.exception(f"KB analysis WS error: {e}")


# ── A7: tAgent 代码问答辅助(会话驱动: 会话→工程上下文→代码问答) ────────


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
