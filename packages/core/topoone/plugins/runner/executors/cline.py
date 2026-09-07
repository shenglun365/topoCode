"""ClineSdkExecutor — architect 自主模式执行器（@topocode/cline-sidecar 常驻进程）。

sidecar（packages/agent-sidecar, @cline/sdk）经 stdio 行分隔 JSON-RPC 通信：
  ping / run / stop / dispose + event 通知（status/text-delta/tool/done）。

架构资产能力：run 时携带 archUrl/archToken/projectId，sidecar 将
topocode_asset_map 工具注入 cline Agent（编码时直接查资产地图）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

from topocode_agent.core.events import AgentEvent
from topocode_agent.subagent.protocol import SubAgentResult

logger = logging.getLogger(__name__)


def _default_token() -> str:
    for p in (os.environ.get("TOPOCODE_TOKEN_FILE"),
              os.path.join(os.path.expanduser("~"), ".topocode", "token")):
        if p and os.path.isfile(p):
            try:
                return open(p).read().strip()
            except Exception:  # noqa: BLE001
                pass
    return ""


class _SidecarProcess:
    """单例 sidecar 进程：懒拉起、崩溃自动重启、请求-响应关联。"""

    def __init__(self, node_bin: str, script: str):
        self._node = node_bin or "node"
        self._script = script
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self._reader_task: Optional[asyncio.Task] = None
        self._event_handler = None  # callable(params)

    def set_event_handler(self, handler) -> None:
        self._event_handler = handler

    async def _start_locked(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        run_dir = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(run_dir, exist_ok=True)
        self._proc = await asyncio.create_subprocess_exec(
            self._node, self._script,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(run_dir, "cline-sidecar.log"), "ab"),  # noqa: SIM115
            limit=16 * 1024 * 1024,
        )
        self._reader_task = asyncio.create_task(self._read_loop())
        # 等 ready 事件（直接内发，避免与 ensure 的锁重入死锁）
        try:
            await asyncio.wait_for(self._send_and_wait("ping"), timeout=30.0)
        except Exception as e:  # noqa: BLE001
            await self.kill()
            raise RuntimeError(f"cline sidecar 启动失败: {e}") from e
        logger.info("[cline] sidecar started pid=%s", self._proc.pid)

    async def _send_and_wait(self, method: str, params: dict | None = None,
                             timeout: float = 3600.0):
        """假定进程已就绪的裸请求（不经过 ensure/锁）。"""
        if not self._proc or self._proc.returncode is not None or not self._proc.stdin:
            raise RuntimeError("sidecar not running")
        self._req_id += 1
        rid = self._req_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        payload = {"id": rid, "method": method, "params": params or {}}
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    async def ensure(self) -> None:
        async with self._lock:
            await self._start_locked()

    async def kill(self) -> None:
        proc, self._proc = self._proc, None
        if self._reader_task:
            self._reader_task.cancel()
            self._reader_task = None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("sidecar restarting"))
        self._pending.clear()
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    async def _read_loop(self) -> None:
        proc = self._proc
        try:
            while proc and proc.returncode is None:
                line = await proc.stdout.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if "id" in msg and (msg.get("result") is not None or msg.get("error") is not None):
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if msg.get("error"):
                            fut.set_exception(RuntimeError(msg["error"].get("message", "error")))
                        else:
                            fut.set_result(msg.get("result"))
                elif msg.get("method") == "event" and self._event_handler:
                    try:
                        self._event_handler(msg.get("params") or {})
                    except Exception:  # noqa: BLE001
                        pass
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline] sidecar read loop died: %s", e)
        # 进程退出：使所有挂起请求失败，触发上层重启
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("cline sidecar exited"))
        self._pending.clear()

    async def call(self, method: str, params: dict | None = None, timeout: float = 3600.0):
        async with self._lock:
            await self._start_locked()
        return await self._send_and_wait(method, params, timeout=timeout)


class ClineSdkExecutor:
    """cline SDK sidecar 执行器（mode=embedded，architect 自主模式）。"""

    mode = "embedded"

    def __init__(self, id: str = "cline", node_bin: str = "node",
                 sidecar_script: str = "", provider_id: str = "", model_id: str = "",
                 api_key: str = "", base_url: str = "", max_iterations: int = 40,
                 arch_url: str = "", arch_token: str = "", timeout: float = 3600.0,
                 prompt_builder: Optional[object] = None):
        self.id = id
        self._node = node_bin or "node"
        default_script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))))))),  # executors→packages/
            "agent-sidecar", "dist", "index.js")
        self._script = sidecar_script or default_script
        self._provider_id = provider_id
        self._model_id = model_id
        self._api_key = api_key
        self._base_url = base_url
        self._max_iterations = max_iterations
        self._arch_url = arch_url or os.environ.get("ARCH_BASE_URL", "http://127.0.0.1:3470")
        self._arch_token = arch_token or _default_token()
        self._timeout = timeout
        self._prompt_builder = prompt_builder
        self._sidecar: Optional[_SidecarProcess] = None
        self._active: dict[str, str] = {}  # sessionKey → taskId（inject/abort 用）

    def _get_sidecar(self) -> _SidecarProcess:
        if self._sidecar is None:
            self._sidecar = _SidecarProcess(self._node, self._script)
        return self._sidecar

    def _prompt(self, task, context: dict) -> str:
        if self._prompt_builder:
            return self._prompt_builder(task, context)  # type: ignore[misc]
        parts = [task.title]
        parts.extend(task.context or [])
        if task.files:
            parts.append("Files:\n" + "\n".join(task.files))
        return "\n\n".join(p for p in parts if p)

    async def execute(self, task, context: dict) -> SubAgentResult:
        root = os.path.abspath(context.get("root") or context.get("projectRoot")
                               or os.environ.get("RUNNER_PROJECT_ROOT", "") or os.getcwd())
        sc = self._get_sidecar()
        session_key = f"{self.id}:{task.id}"
        self._active[session_key] = task.id

        def on_event(params: dict) -> None:
            # 事件直接落入 runner 日志（S1：调度器 WS 事件由 scheduler 自身产生）
            t = params.get("type") or ""
            if t in ("status", "done", "tool"):
                logger.info("[cline] %s %s %s", task.id, t, params.get("stage", ""))

        sc.set_event_handler(on_event)
        params = {
            "taskId": task.id,
            "prompt": self._prompt(task, context),
            "cwd": root,
            "maxIterations": self._max_iterations,
            "archUrl": self._arch_url,
            "archToken": self._arch_token,
            "projectId": context.get("project") or context.get("projectId") or "",
        }
        if self._provider_id:
            params["providerId"] = self._provider_id
        if self._model_id:
            params["modelId"] = self._model_id
        if self._api_key:
            params["apiKey"] = self._api_key
        if self._base_url:
            params["baseUrl"] = self._base_url

        try:
            result = await sc.call("run", params, timeout=self._timeout)
            return SubAgentResult(
                success=bool(result.get("success")),
                output=result.get("output", ""),
                changed_files=list(result.get("changedFiles") or []),
                error=result.get("error", ""),
                metadata={"executor": self.id, "iterations": result.get("iterations", 0)})
        except Exception as e:  # noqa: BLE001
            logger.warning("[cline] execute %s failed: %s", task.id, e)
            await sc.kill()  # 崩溃重启语义
            return SubAgentResult(success=False, error=str(e))
        finally:
            self._active.pop(session_key, None)

    async def execute_stream(self, task, context: dict):
        yield AgentEvent.status("working", task.id)
        r = await self.execute(task, context)
        yield AgentEvent.status("testing", task.id)
        yield AgentEvent.done(success=r.success, task_id=task.id)

    async def health_check(self) -> bool:
        try:
            sc = self._get_sidecar()
            await sc.call("ping", timeout=40.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def env_check(self) -> dict:
        return {"mode": "embedded", "type": "cline-sdk", "node": self._node,
                "sidecar": self._script,
                "sidecarExists": os.path.isfile(self._script),
                "providerId": self._provider_id or "cline(env)",
                "baseUrl": self._base_url or "(provider 默认)"}

    async def inject(self, session_key: str, message: str) -> dict:
        """追加消息到进行中的 cline 会话（S5 clarify 用；S1 仅注册表打通）。"""
        task_id = self._active.get(session_key)
        if not task_id:
            return {"ok": False, "error": "session not active"}
        return {"ok": True, "note": "cline sidecar inject 在 S5 启用"}

    async def abort(self, session_key: str) -> dict:
        task_id = self._active.get(session_key)
        if not task_id:
            return {"ok": False, "error": "session not active"}
        try:
            sc = self._get_sidecar()
            await sc.call("stop", {"taskId": task_id}, timeout=15.0)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}
