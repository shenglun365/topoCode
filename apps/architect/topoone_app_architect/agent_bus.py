"""agent_bus — 独立 broker 进程(P3)：agent 间持久化消息总线。

职责：
- 持久化消息队列(`arch_bus_messages`，全局主库表；broker 单表轮询，无需项目路由)；
- `POST /api/agent-bus/publish` 入队 → 即时经 WS 推送给订阅者(监控页 / agent)；
- `GET /api/agent-bus/messages` 查询；
- `WS /ws/agent-bus` 订阅(新消息实时推送)；
- asyncio 分发循环：轮询 pending → 按 to/topic 路由 → 标记 delivered/failed。

P3.1 分发 = 标记已分发(持久化 + 已推送)；P3.2 按 `to` 路由到 runner/plan 执行。
消息类型(topic)：execution.handoff / interaction.clarify / interaction.answer /
  plan.revise / execution.progress / execution.result / execution.amend。

入口：`python -m topoone_app_architect.agent_bus --data-dir <dir> --port 3486`
(经 apps/agent-bus/manifest.toml 由 supervisor 拉起，独立进程，共享 architect.db。)
"""
import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

# broker 进程内单例状态(单进程)：WS 订阅者集合。
_subscribers: set = set()


async def _broadcast(payload: dict) -> None:
    """推送给所有 WS 订阅者(尽力而为，失败即踢除)。"""
    dead = []
    for ws in list(_subscribers):
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _subscribers.discard(ws)


def _route_and_mark(msg: dict) -> dict:
    """单条消息分发(P3.1：标记已分发；P3.2 按 to 路由到 runner/plan/外部)。同步执行。"""
    from topoone_app_architect.arch_routes import store
    # P3.2 将在此按 to 路由：runner → 触发执行；plan → 触发 plan agent；
    # 其余(monitor/user/*)仅持久化 + 已推送(监控事件)。
    store.AgentBusStore.mark(msg["id"], status="delivered")
    return store.AgentBusStore.get(msg["id"])


async def _dispatch_loop(stop_event: asyncio.Event, poll_interval: float = 1.0) -> None:
    """轮询 pending 消息 → 分发 → 标记。stop_event 置位后退出。"""
    from topoone_app_architect.arch_routes import store
    while not stop_event.is_set():
        try:
            for msg in store.AgentBusStore.pending(limit=20):
                try:
                    _route_and_mark(msg)
                except Exception as e:
                    logger.warning("[agent-bus] dispatch failed msg=%s: %s", msg.get("id"), e)
                    store.AgentBusStore.mark(msg["id"], status="failed", error=str(e))
        except Exception as e:
            logger.warning("[agent-bus] dispatch loop error: %s", e)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
        except asyncio.TimeoutError:
            pass


def build_app(data_dir: str = None, poll_interval: float = 1.0):
    """装配 agent-bus FastAPI 应用。data_dir 经 ctx.setup 注入共享 architect.db。"""
    from fastapi import FastAPI, Request, WebSocket
    from fastapi.middleware.cors import CORSMiddleware
    from topoone_app_architect.arch_routes import ctx, store
    from topoone_app_architect.arch_routes.common import ok, err, _ts

    ctx.setup(data_dir=data_dir)

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()
        task = asyncio.create_task(_dispatch_loop(stop, poll_interval))
        logger.info("[agent-bus] dispatch loop started (poll=%.1fs)", poll_interval)
        try:
            yield
        finally:
            stop.set()
            try:
                await asyncio.wait_for(task, timeout=5)
            except Exception:
                task.cancel()

    app = FastAPI(title="TopoOne Agent Bus", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/health", include_in_schema=False)
    async def health():
        return {"status": "ok", "service": "agent-bus"}

    @app.post("/api/agent-bus/publish")
    async def publish(request: Request):
        body = await request.json()
        topic = (body.get("topic") or "").strip()
        if not topic:
            return err(400, "topic required")
        msg_id = store.next_id("bus")
        now = _ts()
        store.AgentBusStore.create({
            "id": msg_id, "src": body.get("from") or body.get("src") or "",
            "dst": body.get("to") or body.get("dst") or "",
            "topic": topic, "payload": body.get("payload") or {},
            "status": "pending", "createdAt": now, "updatedAt": now,
        })
        row = store.AgentBusStore.get(msg_id)
        await _broadcast({"type": "message", "message": row})
        return ok({"id": msg_id, "status": "pending"})

    @app.get("/api/agent-bus/messages")
    async def messages(dst: str = "", topic: str = "", status: str = "", limit: int = 100):
        rows = store.AgentBusStore.list(dst=dst or None, topic=topic or None,
                                        status=status or None, limit=limit)
        return ok(rows)

    @app.websocket("/ws/agent-bus")
    async def bus_ws(websocket: WebSocket):
        await websocket.accept()
        _subscribers.add(websocket)
        try:
            while True:
                data = await websocket.receive_json()
                if (data or {}).get("type") == "ping":
                    await websocket.send_json({"type": "pong"})
        except Exception:
            pass
        finally:
            _subscribers.discard(websocket)

    return app


def main():
    parser = argparse.ArgumentParser(description="TopoOne Agent Bus Broker")
    parser.add_argument("--port", type=int, default=3486, help="HTTP port")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="HTTP host")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Data directory (shared architect.db)")
    parser.add_argument("--poll-interval", type=float, default=1.0,
                        help="Dispatch poll interval (s)")
    args = parser.parse_args()

    _log_level = os.environ.get("ARCH_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, _log_level, logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    import uvicorn
    app = build_app(data_dir=args.data_dir, poll_interval=args.poll_interval)
    logger.info("Agent Bus broker starting on http://%s:%s", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
