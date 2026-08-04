"""WebSocket routes for KB analysis agent and coding agent."""
import asyncio
import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from .common import _ts, _id

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
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "")
            if msg_type == "create_session":
                await websocket.send_json({
                    "type": "session_created",
                    "sessionId": _id("sess"),
                    "adapter": data.get("adapter", "opencode"),
                })
            elif msg_type == "send_message":
                await websocket.send_json({
                    "type": "message", "role": "assistant",
                    "content": f"正在处理: {data.get('message', '')[:50]}...",
                    "time": _ts(),
                })
                await asyncio.sleep(0.5)
                await websocket.send_json({
                    "type": "tool_call",
                    "tool": {"type": "run-command", "label": "代码检查", "detail": "go vet ./...", "ok": True},
                })
                await asyncio.sleep(0.3)
                await websocket.send_json({
                    "type": "status", "status": "done", "sessionId": data.get("sessionId", ""),
                })
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("Coding agent WebSocket disconnected")
