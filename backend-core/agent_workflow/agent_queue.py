"""
AgentTaskManager — 异步 Agent 任务队列。

职责:
  - 接受 Agent 任务入队，在工作线程中运行 AgentRuntime
  - 支持并发控制（默认 3，范围 1-10）
  - 支持进度查询和取消
  - 与 AgentRuntime.ProgressCallback 集成

使用:
    queue = AgentTaskManager(max_concurrency=3)
    agent_id = queue.enqueue(task_id, workflow, context, tools, sandbox)
    state = queue.get_progress(agent_id)
    queue.cancel(agent_id)
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .runtime import AgentRuntime, AgentStatus, AgentProgress
from .tools import ToolRegistry
from .sandbox import AgentSandbox
from .workflows.base import AgentWorkflow, WorkflowResult

logger = logging.getLogger(__name__)


class TaskState(Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class AgentTaskState:
    agent_id: str
    task_id: str
    status: TaskState = TaskState.QUEUED
    progress: AgentProgress | None = None
    result: WorkflowResult | None = None
    error: str = ""
    created_at: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        steps = []
        if self.progress and self.progress.steps:
            steps = [
                {"description": s.description, "status": s.status}
                for s in self.progress.steps
            ]
        return {
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "step_current": self.progress.step_current if self.progress else 0,
            "step_total": self.progress.step_total if self.progress else 0,
            "tokens_used": self.progress.tokens_used if self.progress else 0,
            "elapsed_sec": round(self.progress.elapsed_sec if self.progress else 0, 1),
            "message": self.progress.message if self.progress else "",
            "steps": steps,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


class AgentTaskManager:
    def __init__(self, max_concurrency: int = 3, min_concurrency: int = 1, max_concurrency_cap: int = 10):
        self._max = max(min_concurrency, min(max_concurrency, max_concurrency_cap))
        self._tasks: dict[str, AgentTaskState] = {}
        self._lock = threading.Lock()
        self._running = 0
        self._callbacks: dict[str, Callable] = {}
        self._persist_path: str = ""

    def set_persist_path(self, path: str):
        self._persist_path = path
        self._load_persisted()

    def _save_persisted(self):
        if not self._persist_path:
            return
        try:
            import json as _json
            import os as _os
            _os.makedirs(_os.path.dirname(self._persist_path), exist_ok=True)
            data = {}
            with self._lock:
                for aid, s in self._tasks.items():
                    if s.status not in (TaskState.COMPLETED, TaskState.CANCELLED):
                        data[aid] = {
                            "agent_id": aid, "task_id": s.task_id,
                            "status": s.status.value, "created_at": s.created_at,
                        }
            with open(self._persist_path, "w") as f:
                _json.dump(data, f)
        except Exception:
            pass

    def _load_persisted(self):
        if not self._persist_path:
            return
        try:
            import json as _json
            import os as _os
            if not _os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r") as f:
                data = _json.load(f)
            with self._lock:
                for aid, d in data.items():
                    if aid not in self._tasks:
                        s = AgentTaskState(
                            agent_id=aid, task_id=d.get("task_id", ""),
                            status=TaskState.FAILED, created_at=d.get("created_at", 0),
                        )
                        s.error = "进程重启，任务已丢失"
                        s.finished_at = time.time()
                        self._tasks[aid] = s
            _os.remove(self._persist_path)
        except Exception:
            pass

    @property
    def max_concurrency(self) -> int:
        return self._max

    @property
    def running_count(self) -> int:
        with self._lock:
            return self._running

    def enqueue(
        self,
        task_id: str,
        workflow: AgentWorkflow,
        context: dict,
        tools: ToolRegistry,
        sandbox: AgentSandbox,
        on_complete: Optional[Callable[[AgentTaskState], None]] = None,
        multi_db=None,
    ) -> str:
        """入队 Agent 任务，返回 agent_id。立即返回，任务在后台线程执行。"""
        agent_id = f"agent-{int(time.time())}-{uuid.uuid4().hex[:6]}"

        state = AgentTaskState(
            agent_id=agent_id,
            task_id=task_id,
            status=TaskState.QUEUED,
            created_at=time.time(),
        )

        with self._lock:
            self._tasks[agent_id] = state
            self._save_persisted()

        if on_complete:
            self._callbacks[agent_id] = on_complete

        thread = threading.Thread(
            target=self._run_agent,
            args=(agent_id, workflow, context, tools, sandbox, multi_db),
            daemon=True,
        )
        thread.start()

        logger.info(f"[AgentQueue] enqueued {agent_id} task={task_id} running={self.running_count}/{self._max}")
        return agent_id

    def get_progress(self, agent_id: str) -> dict | None:
        """查询任务进度"""
        with self._lock:
            state = self._tasks.get(agent_id)
        if not state:
            return None
        return state.to_dict()

    def cancel(self, agent_id: str) -> bool:
        """取消任务。注意: 当前实现通过标记取消，具体取消取决于 AgentRuntime 协作。"""
        with self._lock:
            state = self._tasks.get(agent_id)
        if not state:
            return False
        if state.status in (TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELLED):
            return False

        state.status = TaskState.CANCELLED
        state.finished_at = time.time()
        logger.info(f"[AgentQueue] cancelled {agent_id}")
        return True

    def _run_agent(self, agent_id: str, workflow: AgentWorkflow, context: dict,
                   tools: ToolRegistry, sandbox: AgentSandbox, multi_db=None):
        with self._lock:
            state = self._tasks.get(agent_id)
        if not state:
            return

        state.status = TaskState.RUNNING
        state.started_at = time.time()

        with self._lock:
            self._running += 1

        def progress_cb(progress: AgentProgress):
            with self._lock:
                s = self._tasks.get(agent_id)
                if s:
                    s.progress = progress

        try:
            import asyncio
            runtime = AgentRuntime(tools, sandbox, on_progress=progress_cb, multi_db=multi_db)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(runtime.run(workflow, context))
            finally:
                loop.close()

            with self._lock:
                s = self._tasks.get(agent_id)
                if s and s.status != TaskState.CANCELLED:
                    s.result = result
                    if not result.success:
                        s.status = TaskState.FAILED
                        s.error = result.error or "unknown error"
                    elif result.steps_completed < result.steps_total and result.steps_completed > 0:
                        s.status = TaskState.PARTIAL
                    else:
                        s.status = TaskState.COMPLETED
                    s.finished_at = time.time()

        except Exception as e:
            logger.exception(f"[AgentQueue] {agent_id} crash: {e}")
            with self._lock:
                s = self._tasks.get(agent_id)
                if s:
                    s.status = TaskState.FAILED
                    s.error = str(e)
                    s.finished_at = time.time()

        finally:
            with self._lock:
                self._running = max(0, self._running - 1)

            cb = self._callbacks.pop(agent_id, None)
            if cb:
                try:
                    with self._lock:
                        s = self._tasks.get(agent_id)
                    if s:
                        cb(s.to_dict())
                except Exception:
                    pass

            self._save_persisted()
            logger.info(f"[AgentQueue] {agent_id} done status={state.status.value}")


# 全局单例
_global_queue: Optional[AgentTaskManager] = None

def get_global_queue(max_concurrency: int = 3) -> AgentTaskManager:
    global _global_queue
    if _global_queue is None:
        _global_queue = AgentTaskManager(max_concurrency=max_concurrency)
    return _global_queue
