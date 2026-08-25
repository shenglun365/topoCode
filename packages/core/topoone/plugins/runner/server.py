"""Coding Agent Runner — tAgent 任务树调度宿主（独立进程 :3458）。

只做接线（INTEGRATION.md §2）：端点直接映射 TaskTreeScheduler 同名方法，无业务逻辑。
- 启动即创建 ExecutorPool + TaskTreeScheduler；
- 树状态持久化 runner.db（独立 SQLite，与主库隔离）→ 进程重启断点续跑；
- WS 事件流：on_event=(tree_id, ev) → 按 tree 订阅推送 ev.to_dict()。

执行器（env 配置）：
  RUNNER_DEFAULT_EXECUTOR  默认执行器 id（opencode/codex/claude-code，默认 opencode）
  OPENCODE_SERVE_URL       opencode serve 地址（默认 http://127.0.0.1:3478）
  OPENCODE_API_KEY         opencode serve api key
  CODEX_CMD / CLAUDE_CMD   CLI 兜底执行器命令模板（{prompt} 占位）
  RUNNER_MAX_PARALLEL      最大并行节点数（默认 2）
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from topocode_agent.orchestration import CodingTaskTree
from topocode_agent.orchestration.scheduler import TaskTreeScheduler
from topocode_agent.subagent import CliExecutor, ExecutorPool, ServeExecutor

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("CODING_AGENT_RUNNER_PORT", "3458"))
DATA_DIR = os.environ.get("TOPOCODE_DB_DIR") or os.path.join(
    os.path.expanduser("~"), ".topocode")
RUNNER_DIR = os.path.join(DATA_DIR, "runner")
RUNNER_DB = os.path.join(RUNNER_DIR, "runner.db")
STATE_DIR = os.path.join(RUNNER_DIR, "state")

os.makedirs(RUNNER_DIR, exist_ok=True)
os.makedirs(STATE_DIR, exist_ok=True)

app = FastAPI(title="Coding Agent Runner")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── runner.db（独立 SQLite，树状态持久化） ──

class RunnerDB:
    def __init__(self, path: str):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS task_trees ("
            "id TEXT PRIMARY KEY, tree_json TEXT NOT NULL, status TEXT NOT NULL, "
            "project_root TEXT, context_json TEXT, created_at TEXT, updated_at TEXT)")
        self._conn.commit()

    def upsert(self, tree_id: str, tree: CodingTaskTree, context: dict,
               project_root: str = "") -> None:
        import datetime
        now = datetime.datetime.now().isoformat()
        status = getattr(tree, "status", "") or ""
        self._conn.execute(
            "INSERT INTO task_trees (id, tree_json, status, project_root, context_json, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET tree_json=excluded.tree_json, "
            "status=excluded.status, updated_at=excluded.updated_at",
            (tree_id, json.dumps(tree.to_dict(), ensure_ascii=False), status,
             project_root, json.dumps(context or {}, ensure_ascii=False), now, now))
        self._conn.commit()

    def all_pending(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM task_trees WHERE status NOT IN ('done','cancelled') "
            "ORDER BY updated_at").fetchall()
        return [dict(r) for r in rows]


# ── WS 事件订阅（按 tree_id） ──

class EventHub:
    def __init__(self):
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

    def subscribe(self, tree_id: str) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(tree_id, set()).add(q)
        return q

    def unsubscribe(self, tree_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(tree_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(tree_id, None)

    def publish(self, tree_id: str, payload: dict) -> None:
        for q in list(self._subscribers.get(tree_id, ())):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                logger.warning("[runner] event queue full for %s, dropping", tree_id)


# ── 宿主状态 ──

class RunnerState:
    db: RunnerDB
    pool: ExecutorPool
    scheduler: TaskTreeScheduler
    hub: EventHub


def build_pool() -> ExecutorPool:
    default_id = os.environ.get("RUNNER_DEFAULT_EXECUTOR", "opencode")
    executors: list = []
    default = None

    if default_id == "opencode":
        base_url = os.environ.get("OPENCODE_SERVE_URL", "http://127.0.0.1:3478")
        default = ServeExecutor(
            id="opencode", base_url=base_url,
            api_key=os.environ.get("OPENCODE_API_KEY", ""),
            timeout=float(os.environ.get("OPENCODE_TIMEOUT", "300")),
        )
    codex_cmd = os.environ.get("CODEX_CMD", "")
    if codex_cmd:
        ex = CliExecutor(id="codex", command=codex_cmd, timeout=600)
        executors.append(ex)
        if default is None:
            default = ex
    claude_cmd = os.environ.get("CLAUDE_CMD", "")
    if claude_cmd:
        ex = CliExecutor(id="claude-code", command=claude_cmd, timeout=600)
        executors.append(ex)
        if default is None:
            default = ex
    if default is None:
        raise RuntimeError(
            "runner: no default executor configured (set OPENCODE_SERVE_URL / CODEX_CMD / CLAUDE_CMD)")
    return ExecutorPool(
        default_executor=default,
        executors=executors,
        max_parallel=int(os.environ.get("RUNNER_MAX_PARALLEL", "2")),
    )


state: RunnerState


def init_runner() -> None:
    global state
    db = RunnerDB(RUNNER_DB)
    pool = build_pool()
    hub = EventHub()
    scheduler = TaskTreeScheduler(
        pool,
        on_event=lambda tree_id, ev: hub.publish(tree_id, ev.to_dict()),
        project_root="",
        state_dir=STATE_DIR,
    )
    state = RunnerState()
    state.db, state.pool, state.scheduler, state.hub = db, pool, scheduler, hub

    # 重启恢复：未终态树重新 submit（保留原 id 与 status，未 done 节点自动续跑）
    for row in db.all_pending():
        try:
            tree = CodingTaskTree.from_dict(json.loads(row["tree_json"]))
            tree_id = row["id"]
            scheduler.submit(
                tree, context=json.loads(row["context_json"] or "{}"), tree_id=tree_id)
            logger.info("[runner] restored tree %s (status=%s)", tree_id, row["status"])
        except Exception as e:  # noqa: BLE001
            logger.warning("[runner] restore tree %s failed: %s", row["id"], e)


def persist(tree_id: str) -> None:
    tree = state.scheduler.get_tree(tree_id)
    if tree is None:
        return
    state.db.upsert(tree_id, tree, state.scheduler.get_context(tree_id),
                    project_root=os.environ.get("RUNNER_PROJECT_ROOT", ""))


# ── 端点（INTEGRATION.md §2.2） ──

@app.get("/health")
async def health():
    return {"status": "ok", "service": "coding-agent-runner", "port": PORT,
            "executors": await state.pool.health()}


@app.get("/healthz")
async def healthz():
    return {"ok": True, "executors": await state.pool.health()}


@app.post("/api/trees")
async def submit_tree(request: Request):
    body = await request.json()
    tree = CodingTaskTree.from_dict(body["tree"])
    tree_id = state.scheduler.submit(tree, context=body.get("context") or {})
    persist(tree_id)
    logger.info("[runner] tree submitted: %s nodes=%d", tree_id, len(tree.roots))
    return {"tree_id": tree_id}


@app.get("/api/trees/{tree_id}")
async def get_tree(tree_id: str):
    tree = state.scheduler.get_tree(tree_id)
    if tree is None:
        return {"error": "tree not found"}
    return {"tree": tree.to_dict(), "progress": state.scheduler.progress(tree_id)}


@app.websocket("/api/trees/{tree_id}/events")
async def tree_events(websocket: WebSocket, tree_id: str):
    await websocket.accept()
    q = state.hub.subscribe(tree_id)
    try:
        while True:
            payload = await q.get()
            await websocket.send_json(payload)
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.unsubscribe(tree_id, q)


@app.post("/api/trees/{tree_id}/pause")
async def pause(tree_id: str):
    return {"ok": state.scheduler.pause(tree_id)}


@app.post("/api/trees/{tree_id}/resume")
async def resume(tree_id: str):
    return {"ok": state.scheduler.resume(tree_id)}


@app.post("/api/trees/{tree_id}/cancel")
async def cancel(tree_id: str):
    ok = state.scheduler.cancel(tree_id)
    persist(tree_id)
    return {"ok": ok}


@app.post("/api/trees/{tree_id}/retry")
async def retry(tree_id: str, request: Request):
    body = await request.json()
    ok = state.scheduler.retry(tree_id, body["task_id"])
    persist(tree_id)
    return {"ok": ok}


@app.post("/api/trees/{tree_id}/skip")
async def skip(tree_id: str, request: Request):
    body = await request.json()
    ok = state.scheduler.skip(tree_id, body["task_id"])
    persist(tree_id)
    return {"ok": ok}


@app.put("/api/trees/{tree_id}")
async def update_tree(tree_id: str, request: Request):
    body = await request.json()
    state.scheduler.update_tree(tree_id, CodingTaskTree.from_dict(body["tree"]))
    persist(tree_id)
    return {"ok": True}


@app.post("/api/trees/{tree_id}/rejudge")
async def rejudge(tree_id: str, request: Request):
    body = await request.json()
    state.scheduler.rejudge(tree_id, body.get("task_ids") or [])
    persist(tree_id)
    return {"ok": True}


@app.post("/api/trees/{tree_id}/run")
async def run_tree(tree_id: str):
    # 非阻塞：内部 run_async
    state.scheduler.run_async(tree_id)
    return {"progress": state.scheduler.progress(tree_id)}


def main():
    logging.basicConfig(level=logging.INFO)
    from topoone.http_logging import install_heartbeat_filter
    install_heartbeat_filter()
    init_runner()
    logger.info("[runner] starting on port %s (executors=%s)", PORT, state.pool.available())
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
