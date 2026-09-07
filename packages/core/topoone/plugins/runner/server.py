"""Coding Agent Runner — tAgent 任务树调度宿主（独立进程 :3458）。

只做接线（INTEGRATION.md §2）：端点直接映射 TaskTreeScheduler 同名方法，无业务逻辑。
- 启动经 AgentGateway 组装 ExecutorPool（architect 注册表 > env 兼容 > 内置默认）；
- 树状态持久化 runner.db（独立 SQLite，与主库隔离）→ 进程重启断点续跑；
- WS 事件流：on_event=(tree_id, ev) → 按 tree 订阅推送 ev.to_dict()；
- 会话执行器（opencode 会话化 / cline sidecar / codex app-server）支持
  /api/executors/refresh 热刷新与 /api/agent-sessions/{inject,abort}。

执行器配置：architect 系统管理（arch_collab_config["agent.executors"]）；
旧 env（RUNNER_DEFAULT_EXECUTOR/OPENCODE_SERVE_URL/CODEX_CMD/CLAUDE_CMD）仍兼容。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import subprocess
import time
import uuid
from typing import Optional

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from topocode_agent.orchestration import CodingTaskTree
from topocode_agent.orchestration.scheduler import TaskTreeScheduler

from .gateway import AgentGateway

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
    gateway: AgentGateway


state: RunnerState


def init_runner() -> None:
    global state
    db = RunnerDB(RUNNER_DB)
    gateway = AgentGateway()
    pool, _entries = asyncio.run(gateway.build_pool(boot=True))
    hub = EventHub()
    scheduler = TaskTreeScheduler(
        pool,
        on_event=lambda tree_id, ev: hub.publish(tree_id, ev.to_dict()),
        project_root="",
        state_dir=STATE_DIR,
    )
    state = RunnerState()
    state.db, state.pool, state.scheduler, state.hub = db, pool, scheduler, hub
    state.gateway = gateway

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


@app.post("/api/executors/refresh")
async def refresh_executors():
    """architect 配置保存后触发：重建执行器并原子换池。"""
    entries = await state.gateway.apply_to(state.scheduler)
    state.pool = state.scheduler._pool  # noqa: SLF001
    return {"ok": True, "executors": state.pool.available(), "entries": entries}


@app.get("/api/executors")
async def list_executors():
    return {"executors": state.pool.available(),
            "health": await state.pool.health()}


@app.post("/api/agent-sessions/inject")
async def agent_session_inject(request: Request):
    body = await request.json()
    return await state.gateway.inject(body.get("sessionKey", ""),
                                      body.get("message", ""))


@app.post("/api/agent-sessions/abort")
async def agent_session_abort(request: Request):
    body = await request.json()
    return await state.gateway.abort_session(body.get("sessionKey", ""))


@app.post("/api/trees/{tree_id}/run")
async def run_tree(tree_id: str):
    # 非阻塞：内部 run_async
    state.scheduler.run_async(tree_id)
    return {"progress": state.scheduler.progress(tree_id)}


# ── P3 probe 模式(worktree 方案A)：方案草图——只读分析+伪diff，不建分支不落地 ──

_PROBE_HARNESS = (
    "【probe 方案草图模式】\n"
    "- 你在 git worktree 快照中工作，改动不影响主工作区\n"
    "- 禁止 git commit / branch / push / checkout 等仓库操作；只编辑文件表达方案\n"
    "- 禁止运行构建/测试/安装依赖(worktree 无构建产物，属正常)\n"
    "- 先读相关代码理解现状，再用最小文件改动表达方案(伪 diff)\n"
    "- 结束时用 3-5 行总结改动思路与影响面\n"
)


def _git(args: list, cwd: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True, check=check)


@app.post("/api/probe")
async def run_probe(request: Request):
    """probe: worktree 快照上执行 coding agent 产出方案草图 + diff。

    body: {root, baseCommit?, instruction, files?, executorId?, timeoutS?}
    返回 {ok, status, changedFiles, diff, summary, worktree}。结束即清理 worktree。
    """
    body = await request.json()
    root = os.path.abspath(body.get("root") or "")
    instruction = (body.get("instruction") or "").strip()
    if not root or not os.path.isdir(root):
        return {"ok": False, "error": "root 无效"}
    if not instruction:
        return {"ok": False, "error": "instruction 为空"}
    base = body.get("baseCommit") or "HEAD"
    executor_id = (body.get("executorId") or "").strip()
    files = [str(f) for f in (body.get("files") or []) if str(f).strip()]
    timeout_s = min(max(int(body.get("timeoutS") or 900), 60), 3600)

    probe_dir = os.path.join(STATE_DIR, "probes")
    os.makedirs(probe_dir, exist_ok=True)
    wt = os.path.join(probe_dir, f"probe-{int(time.time() * 1000)}")

    def _cleanup_worktree() -> None:
        _git(["worktree", "remove", "--force", wt], cwd=root, check=False)
        _git(["worktree", "prune"], cwd=root, check=False)

    r = _git(["worktree", "add", "--detach", wt, base], cwd=root, check=False)
    if r.returncode != 0:
        return {"ok": False, "error": f"worktree 创建失败: {r.stderr.strip()[:300]}"}

    tree = CodingTaskTree.from_dict({"roots": [{
        "id": "PROBE", "title": instruction[:120] or "方案草图",
        "kind": "task", "files": files, "executor_id": executor_id,
        "context": [_PROBE_HARNESS, instruction],
    }]})
    tree_id = state.scheduler.submit(tree, context={
        "root": wt, "requirement": "probe: 方案草图", "branch": "", "baseCommit": base,
    })
    persist(tree_id)
    state.scheduler.run_async(tree_id)

    deadline = time.time() + timeout_s
    progress: dict = {}
    try:
        while time.time() < deadline:
            await asyncio.sleep(3.0)
            progress = state.scheduler.progress(tree_id)
            if progress.get("terminal"):
                break
        # diff 提取(未跟踪文件 intent-to-add 纳入)
        _git(["add", "-A", "-N"], cwd=wt, check=False)
        d = _git(["diff"], cwd=wt, check=False)
        st = _git(["status", "--porcelain"], cwd=wt, check=False)
        changed = [line[3:].strip() for line in st.stdout.splitlines() if line.strip()]
        node = (progress.get("nodes") or [{}])[0]
        add = del_ = 0
        for line in d.stdout.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                add += 1
            elif line.startswith("-") and not line.startswith("---"):
                del_ += 1
        summary = (f"probe {'完成' if node.get('status') == 'done' else node.get('status')}; "
                   f"{len(changed)} 个文件变更(+{add}/-{del_} 行)")
        return {
            "ok": node.get("status") == "done",
            "status": node.get("status") or "unknown",
            "treeId": tree_id,
            "changedFiles": changed,
            "diff": d.stdout[:200_000],
            "summary": summary,
            "worktree": wt,
        }
    finally:
        _cleanup_worktree()
        # opencode serve 按根托管 → worktree 专用实例即用即弃
        try:
            from .executors.opencode import manager
            m = manager()
            if m is not None:
                m.dispose_root(wt)
        except Exception:  # noqa: BLE001
            pass


def main():
    logging.basicConfig(level=logging.INFO)
    from topoone.http_logging import install_heartbeat_filter
    install_heartbeat_filter()
    init_runner()
    logger.info("[runner] starting on port %s (executors=%s)", PORT, state.pool.available())
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
