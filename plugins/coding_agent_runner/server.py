"""Coding Agent Runner — independent process (port 3458).

Manages third-party coding agent subprocesses (opencode, codex, claude-code).
Receives execution tasks via HTTP, streams agent session state via WebSocket.
"""

import logging
import os

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("CODING_AGENT_RUNNER_PORT", "3458"))
app = FastAPI(title="Coding Agent Runner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "coding-agent-runner", "port": PORT}


@app.post("/tasks")
async def submit_task(request: Request):
    """Receive an execution task from the main backend."""
    body = await request.json()
    logger.info(f"Received task: {body.get('id', 'unknown')}")
    return {"ok": True, "taskId": body.get("id")}


@app.websocket("/ws/agent")
async def agent_ws(websocket: WebSocket):
    """Stream agent session state to the frontend."""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            await websocket.send_json({"type": "ack", "msg": f"received: {data.get('type', '')}"})
    except WebSocketDisconnect:
        logger.info("Agent WebSocket disconnected")


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info(f"Starting Coding Agent Runner on port {PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
