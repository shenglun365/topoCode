"""
Agent Worker — 独立进程运行 Agent 工作流

管理 AgentRuntime 的生命周期（dispatch/progress/cancel/pause/resume），
通过 ZMQ 接收主进程的请求，在自身的线程池和 Event Loop 中执行。

启动方式:
    python -m agent_worker --data-dir <path>

主进程 ↔ Agent Worker 协议 (ZMQ ROUTER/DEALER):
  Request:  [identity, request_id, action, params_json]
  Response: [identity, request_id, result_json]
  Progress: PUB on AGENT_WORKER_PUB_PORT
    frames: [b"agent.progress", agent_id_bytes, data_json_bytes]
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
import uuid

import zmq
import zmq.asyncio

from config import AGENT_WORKER_PORT, AGENT_WORKER_PUB_PORT, TOPO_MODE
from logging_config import setup_logging

setup_logging()
logger = logging.getLogger("agent_worker")


class AgentWorker:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self._ctx: zmq.asyncio.Context | None = None
        self._router: zmq.asyncio.Socket | None = None
        self._pub: zmq.asyncio.Socket | None = None
        self._running = False
        self._agent_task_manager = None
        self._multi_db = None

    async def start(self):
        from sqlite_ctx import MultiDBManager
        from agent_workflow.agent_queue import get_global_queue

        self._multi_db = MultiDBManager(self.data_dir)
        self._agent_task_manager = get_global_queue()

        self._ctx = zmq.asyncio.Context()
        self._router = self._ctx.socket(zmq.ROUTER)
        self._router.bind(f"tcp://127.0.0.1:{AGENT_WORKER_PORT}")
        self._pub = self._ctx.socket(zmq.PUB)
        self._pub.bind(f"tcp://127.0.0.1:{AGENT_WORKER_PUB_PORT}")

        self._running = True
        logger.info(f"[AgentWorker] listening on port {AGENT_WORKER_PORT}")

        while self._running:
            try:
                frames = await self._router.recv_multipart()
                asyncio.ensure_future(self._handle(frames))
            except asyncio.CancelledError:
                break
            except Exception as e:
                if self._running:
                    logger.warning(f"[AgentWorker] recv error: {e}")

        await self._shutdown()

    def stop(self):
        self._running = False

    async def _shutdown(self):
        if self._router:
            self._router.close(linger=0)
        if self._pub:
            self._pub.close(linger=0)
        if self._ctx:
            self._ctx.term()
        if self._multi_db:
            self._multi_db.close_all()
        logger.info("[AgentWorker] shutdown complete")

    def _publish_progress(self, agent_id: str, data: dict):
        try:
            self._pub.send_multipart([
                b"agent.progress",
                agent_id.encode("utf-8"),
                json.dumps(data, default=str).encode("utf-8"),
            ], flags=zmq.NOBLOCK)
        except Exception:
            pass

    async def _handle(self, frames):
        if len(frames) < 4:
            return
        identity = frames[0]
        request_id = frames[1].decode("utf-8")
        # 协议: 5帧带 trace_id, 4帧兼容
        if len(frames) >= 5:
            trace_id = frames[2].decode("utf-8")
            action = frames[3].decode("utf-8")
            params = json.loads(frames[4]) if len(frames) > 4 else {}
        else:
            trace_id = ""
            action = frames[2].decode("utf-8")
            params = json.loads(frames[3]) if len(frames) > 3 else {}
        _lp = f"[{trace_id[:8]}]" if trace_id else ""

        try:
            result = await self._dispatch_action(action, params)
        except Exception as e:
            logger.error(f"{_lp} [AgentWorker] action error: {action}: {e}")
            result = {"error": str(e)}

        try:
            await self._router.send_multipart([
                identity,
                request_id.encode("utf-8"),
                json.dumps(result, default=str).encode("utf-8"),
            ])
        except Exception:
            pass

    async def _dispatch_action(self, action: str, params: dict) -> dict:
        if action == "dispatch":
            return await self._action_dispatch(params)
        elif action == "get_progress":
            return await self._action_get_progress(params)
        elif action == "cancel":
            return await self._action_cancel(params)
        elif action == "pause":
            return await self._action_pause(params)
        elif action == "resume":
            return await self._action_resume(params)
        elif action == "get_history":
            return await self._action_get_history(params)
        elif action == "clear_history":
            return await self._action_clear_history(params)
        elif action == "presummary_chain":
            return await self._action_presummary_chain(params)
        elif action == "list_running":
            return self._action_list_running()
        elif action == "get_config":
            return self._action_get_config(params)
        else:
            return {"error": f"Unknown action: {action}"}

    # ── 动作实现 ──────────────────────────────────────────────────

    async def _action_dispatch(self, params: dict) -> dict:
        """接收主进程的 agent 任务分派"""
        from agent_workflow.router import create_default_router, RouterHarness, RouteEntry
        from agent_workflow.tool_factory import build_pipeline_tools
        from agent_workflow.workflows.pipeline import PipelineWorkflow
        from agent_workflow.sandbox import AgentSandbox

        route = params["route"]
        task_id = params["task_id"]
        context = params.get("context", {})
        project_id = params.get("project_id", "")
        project_root = params.get("project_root", "")
        project_summary = params.get("project_summary", "")

        pid = project_id
        tid = task_id
        project_db = self._multi_db.get_project_db(pid) if pid else None

        def _make_save_fn(comp_edge_lv: dict | None = None):
            """创建 _save_fn — analyze_components 需要 comp_edge_lv 映射"""
            from ingest import write_ingest

            def _save_fn(result):
                try:
                    comp_id = result.get("component_id", "")
                    et, lv = comp_edge_lv.get(comp_id, ("", "L0")) if comp_edge_lv else ("", "L0")
                    data = {
                        "project_id": pid,
                        "task_id": result.get("task_id", tid),
                        "edge_type": et,
                        "comm_lv": lv,
                        "comm_id": comp_id,
                        "name": result.get("analyzed_name") or result.get("name", ""),
                        "summary": result.get("functional_summary") or result.get("summary", ""),
                        "model_id": result.get("model_id", ""),
                        "template_id": result.get("template_id", ""),
                        "component_type": "community",
                        "status": "completed",
                    }
                    write_ingest(project_root, "community_result", data)
                except Exception as e:
                    logger.warning(f"[AgentWorker] _save_fn failed: {e}")
            return _save_fn

        def _on_complete(state_dict):
            """保存 agent 历史到 DB"""
            try:
                from store.task_store import TaskStore
                ts = TaskStore(self._multi_db.main_db)
                ts.execute(
                    "INSERT OR REPLACE INTO agent_task_history "
                    "(project_id, task_id, agent_id, action, status, steps, message, error, created_at, finished_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                    (pid, tid, state_dict.get("agent_id", ""), route,
                     state_dict.get("status", ""), json.dumps(state_dict.get("steps", [])),
                     state_dict.get("message", ""), state_dict.get("error", "")),
                )
            except Exception as e:
                logger.warning(f"[AgentWorker] history save failed: {e}")

        if route == "pipeline":
            tools = build_pipeline_tools(
                self._multi_db, project_db, project_root, tid, pid, project_summary
            )
            router = RouterHarness(project_root=project_root, multi_db=self._multi_db)
            router.register("pipeline", RouteEntry(
                workflow_class=PipelineWorkflow,
                tool_builder=lambda ctx: tools,
                description="pipeline",
                sandbox_builder=lambda root: AgentSandbox(root, max_tokens=0, timeout_seconds=0),
            ))
            agent_id = router.dispatch(route, tid, context, on_complete=_on_complete)
        elif route == "analyze_components":
            comp_edge_lv = params.get("comp_edge_lv", {})
            context["_save_fn"] = _make_save_fn(comp_edge_lv)
            context.setdefault("max_turns", 30)
            router = create_default_router(
                project_root=project_root, project_db=project_db,
                multi_db=self._multi_db, task_id=tid,
                project_summary=project_summary,
            )
            agent_id = router.dispatch(route, tid, context, on_complete=_on_complete)
        else:
            # overview / presummary_files
            context.setdefault("_save_fn", _make_save_fn())
            router = create_default_router(
                project_root=project_root, project_db=project_db,
                multi_db=self._multi_db, task_id=tid,
                project_summary=project_summary,
            )
            agent_id = router.dispatch(route, tid, context, on_complete=_on_complete)

        return {"agent_id": agent_id}

    async def _action_presummary_chain(self, params: dict) -> dict:
        """链式预摘要：P0→P1→P2 顺序执行，Agent Worker 内部回调"""
        tid = params.get("task_id", "")
        pid = params.get("project_id", "")
        batches = params.get("batches", ["P0", "P1", "P2"])
        limit = params.get("limit", 0)
        subagent_concurrency = params.get("subagent_concurrency", 1)
        project_root = params.get("project_root", "")
        project_summary = params.get("project_summary", "")

        project_db = self._multi_db.get_project_db(pid) if pid else None
        if not project_db:
            return {"error": "project_db not found"}

        from agent_workflow.router import create_default_router
        from agent_workflow.agent_queue import get_global_queue as _gq

        first_agent_id = [""]

        def _dispatch_batch(batch_idx: int) -> str | None:
            if batch_idx >= len(batches):
                return None
            batch = batches[batch_idx]
            from analysis_utils import get_l0_comps as _get_l0_comps
            from task_manager import _compute_file_ranks
            comps = _get_l0_comps(project_db, tid)
            rank_data = _compute_file_ranks(tid, project_db, comps, project_root)
            batch_files = [f["file_path"] for f in rank_data["files"]
                           if f["batch"] == batch]
            if limit > 0:
                batch_files = batch_files[:limit]
            if not batch_files:
                logger.info(f"[presummary_chain] {batch}: 0 files, skip")
                _dispatch_batch(batch_idx + 1)
                return

            cached_paths = set()
            try:
                ph = ",".join("?" for _ in batch_files)
                rows = project_db.execute(
                    f"SELECT file_path FROM file_summaries WHERE project_id=? AND file_path IN ({ph})",
                    (pid, *batch_files)
                ).fetchall()
                cached_paths = {r[0] for r in rows}
            except Exception:
                pass

            if len(cached_paths) == len(batch_files):
                logger.info(f"[presummary_chain] {batch}: all {len(batch_files)} cached, skip")
                _dispatch_batch(batch_idx + 1)
                return
            uncached = [fp for fp in batch_files if fp not in cached_paths]

            context = {
                "task_id": tid, "project_id": pid,
                "files": uncached, "cached_paths": cached_paths,
                "subagent_concurrency": subagent_concurrency,
            }

            def _on_batch_complete(state_dict):
                fc = state_dict.get("failed_count", 0)
                if fc:
                    from store.task_store import TaskStore
                    ts = TaskStore(self._multi_db.main_db)
                    ts._db.execute(
                        "UPDATE analysis_tasks SET error=error||', presummary_failures='||? WHERE id=?",
                        (str(fc), tid)
                    )
                    try:
                        ts._db.commit()
                    except Exception:
                        pass
                st = state_dict.get("status", "")
                if st in ("cancelled", "failed"):
                    return
                _dispatch_batch(batch_idx + 1)

            router = create_default_router(
                project_root=project_root, project_db=project_db,
                multi_db=self._multi_db, task_id=tid,
                project_summary=project_summary,
            )
            aid = router.dispatch("presummary_files", tid, context, on_complete=_on_batch_complete)
            if not first_agent_id[0]:
                first_agent_id[0] = aid

        _dispatch_batch(0)
        return {"success": True, "batches": batches, "agentTaskId": first_agent_id[0]}

    async def _action_get_progress(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        if self._agent_task_manager:
            return self._agent_task_manager.get_progress(agent_id)
        return {"error": "no agent_task_manager"}

    async def _action_cancel(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        if self._agent_task_manager:
            ok = self._agent_task_manager.cancel(agent_id)
            return {"cancelled": ok}
        return {"cancelled": False}

    async def _action_pause(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        if self._agent_task_manager:
            ok = self._agent_task_manager.pause(agent_id)
            return {"paused": ok}
        return {"paused": False}

    async def _action_resume(self, params: dict) -> dict:
        agent_id = params.get("agent_id", "")
        if self._agent_task_manager:
            ok = self._agent_task_manager.resume(agent_id)
            return {"resumed": ok}
        return {"resumed": False}

    def _action_list_running(self) -> dict:
        """返回 Agent Worker 中正在运行的任务列表"""
        tasks = []
        if self._agent_task_manager:
            try:
                for aid, state in list(self._agent_task_manager._tasks.items()):
                    if state.status.name in ('RUNNING', 'QUEUED'):
                        tasks.append({
                            "id": aid,
                            "name": f"[Agent] {state.task_id}",
                            "project_id": "",
                        })
            except Exception as e:
                logger.warning(f"[AgentWorker] list_running error: {e}")
        return {"tasks": tasks}

    async def _action_get_history(self, params: dict) -> dict:
        task_id = params.get("task_id", "")
        offset = params.get("offset", 0)
        limit = params.get("limit", 10)
        from store.task_store import TaskStore
        ts = TaskStore(self._multi_db.main_db)
        history = ts.fetchall(
            "SELECT * FROM agent_task_history WHERE task_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (task_id, limit, offset),
        )
        return {"history": history}

    async def _action_clear_history(self, params: dict) -> dict:
        project_id = params.get("project_id", "")
        task_id = params.get("task_id", "")
        from store.task_store import TaskStore
        ts = TaskStore(self._multi_db.main_db)
        ts.execute("DELETE FROM agent_task_history WHERE project_id=? AND task_id=?",
                    (project_id, task_id))
        return {"success": True}

    def _action_get_config(self, params: dict) -> dict:
        return {
            "routes": [
                {"action": "overview", "workflow": "OverviewWorkflow"},
                {"action": "analyze_components", "workflow": "AgenticComponentAnalystWorkflow"},
                {"action": "presummary_files", "workflow": "PreSummaryWorkflow"},
                {"action": "pipeline", "workflow": "PipelineWorkflow"},
            ],
        }


# ═══════════════════════════════════════════════════════════════
# 入口
# ═══════════════════════════════════════════════════════════════

def main():
    data_dir = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--data-dir" and i < len(sys.argv):
            data_dir = sys.argv[i + 1]
        elif arg == "--help":
            print("Usage: python -m agent_worker --data-dir <path>")
            return

    if not data_dir:
        data_dir = os.environ.get("TOPOCODE_DB_DIR",
                                  os.path.join(os.path.expanduser("~"), ".topocode"))

    logger.info(f"[AgentWorker] starting (data_dir={data_dir})")
    worker = AgentWorker(data_dir)

    from messaging.worker_signal import signal_ready, start_heartbeat_thread
    signal_ready()
    start_heartbeat_thread()

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, worker.stop)
            except (NotImplementedError, ValueError):
                pass
        loop.run_until_complete(worker.start())
    finally:
        loop.close()


if __name__ == "__main__":
    main()
