"""CodexServerExecutor — codex app-server 会话模式执行器（JSON-RPC over stdio）。

协议（codex-cli 0.147 实测）：
  initialize {clientInfo} → {userAgent, codexHome, ...}
  thread/start {} → {thread:{id, ...}}
  turn/start {threadId, input:[{type:"text",text}], cwd?, approvalPolicy?, sandbox?}
            → {turn:{id, status:"inProgress"}}，随后事件流：
    thread/started / thread/status/changed / turn/started / turn/completed / item/* 等
  turn/interrupt {threadId} / turn/steer —— 中止/追加
  model/list

输入变体：text|image|localImage|audio|localAudio|skill|mention。
鉴权：~/.codex/auth.json（codex login）；未登录时 turn 快速失败并透出错误。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from typing import Optional

from topocode_agent.core.events import AgentEvent
from topocode_agent.subagent.protocol import SubAgentResult

logger = logging.getLogger(__name__)

_EVENT_DONE_HINTS = ("turn/completed", "turn/failed", "turn/cancelled")


class _AppServerProcess:
    """常驻 codex app-server 子进程（行分隔 JSON-RPC）。"""

    def __init__(self, codex_bin: str, cwd: str, codex_home: str = ""):
        self._bin = codex_bin
        self._cwd = cwd
        self._codex_home = os.path.expanduser(codex_home) if codex_home else ""
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._pending: dict[int, asyncio.Future] = {}
        self.events: list[dict] = []  # 最近事件（ring）
        self._waiters: list[tuple[str, asyncio.Event]] = []
        # 通道状态(看门狗/适配层探测): read loop 退出即断流
        self.dead: bool = False
        self.dead_reason: str = ""

    async def _start_locked(self) -> None:
        if self._proc and self._proc.returncode is None:
            return
        env = dict(os.environ)
        if self._codex_home:
            os.makedirs(self._codex_home, exist_ok=True)
            env["CODEX_HOME"] = self._codex_home  # 多实例隔离（各自 config.toml 指向不同模型）
        run_dir = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(run_dir, exist_ok=True)
        self._proc = await asyncio.create_subprocess_exec(
            self._bin, "app-server",
            cwd=self._cwd, env=env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=open(os.path.join(run_dir, "codex-appserver.log"), "ab"),  # noqa: SIM115
            limit=16 * 1024 * 1024,
        )
        self._reader = asyncio.create_task(self._read_loop())
        try:
            await asyncio.wait_for(self._send_and_wait("initialize", {
                "clientInfo": {"name": "topoone-runner", "title": "TopoOne Runner",
                               "version": "0.1.0"}}), timeout=30.0)
        except Exception as e:  # noqa: BLE001
            await self.kill()
            raise RuntimeError(f"codex app-server 启动失败: {e}") from e
        logger.info("[codex] app-server started pid=%s", self._proc.pid)

    async def _send_and_wait(self, method: str, params: dict | None = None,
                             timeout: float = 3600.0):
        if not self._proc or self._proc.returncode is not None or not self._proc.stdin:
            raise RuntimeError("codex app-server not running")
        self._req_id += 1
        rid = self._req_id
        fut: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[rid] = fut
        payload = {"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}
        self._proc.stdin.write((json.dumps(payload) + "\n").encode())
        await self._proc.stdin.drain()
        return await asyncio.wait_for(fut, timeout=timeout)

    async def call(self, method: str, params: dict | None = None,
                   timeout: float = 3600.0):
        async with self._lock:
            await self._start_locked()
        return await self._send_and_wait(method, params, timeout=timeout)

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
                if msg.get("id") is not None and ("result" in msg or "error" in msg):
                    fut = self._pending.pop(msg["id"], None)
                    if fut and not fut.done():
                        if "error" in msg:
                            fut.set_exception(RuntimeError(
                                str((msg["error"] or {}).get("message") or msg["error"])))
                        else:
                            fut.set_result(msg.get("result"))
                elif msg.get("method"):
                    ev = {"method": msg["method"], "params": msg.get("params") or {}}
                    self.events.append(ev)
                    if len(self.events) > 4000:
                        del self.events[:2000]
                    for m, w in self._waiters:
                        if m == ev["method"]:
                            w.set()
        except asyncio.CancelledError:
            self.dead = True
            self.dead_reason = "read loop cancelled"
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning("[codex] read loop died: %s", e)
            self.dead = True
            self.dead_reason = str(e)[:300] or "read loop died"
        else:
            # while 正常退出(stdout EOF/进程结束) → 通道断流
            self.dead = True
            self.dead_reason = "app-server stdout EOF"
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("codex app-server exited"))
        self._pending.clear()

    def wait_event(self, method: str, start_idx: int) -> asyncio.Event:
        """注册等待某事件（从 start_idx 之后的新事件）。"""
        ev = asyncio.Event()
        self._waiters.append((method, ev))
        return ev

    def events_since(self, idx: int) -> list[dict]:
        return self.events[idx:]

    async def kill(self) -> None:
        proc, self._proc = self._proc, None
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(RuntimeError("codex app-server restarting"))
        self._pending.clear()
        if proc and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass


class CodexServerExecutor:
    """codex app-server 会话执行器（mode=serve）。"""

    mode = "serve"

    def __init__(self, id: str = "codex", codex_bin: str = "codex",
                 timeout: float = 3600.0, prompt_builder: Optional[object] = None,
                 approval_policy: str = "never", sandbox_mode: str = "workspace-write",
                 model: str = "", codex_home: str = ""):
        self.id = id
        binpath = shutil.which(codex_bin) or codex_bin
        self._bin = binpath
        self._cwd = os.path.abspath(
            os.environ.get("RUNNER_PROJECT_ROOT", "") or os.getcwd())
        self._timeout = timeout
        self._prompt_builder = prompt_builder
        self._approval_policy = approval_policy
        self._sandbox_mode = sandbox_mode
        self._model = model
        self._codex_home_cfg = codex_home
        self._server: Optional[_AppServerProcess] = None
        self._active: dict[str, str] = {}  # sessionKey → threadId

    def _get_server(self) -> _AppServerProcess:
        if self._server is None:
            self._server = _AppServerProcess(self._bin, self._cwd,
                                             codex_home=self._codex_home_cfg)
        return self._server

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
                               or self._cwd)
        server = self._server or self._get_server()
        session_key = f"{self.id}:{task.id}"

        def _collect_text(events: list[dict]) -> str:
            """从 agentMessage/assistant 类 item 收集输出文本（排除回显的 userMessage）。"""
            texts: list[str] = []
            for ev in events:
                p = ev.get("params") or {}
                item = p.get("item") or {}
                itype = item.get("type") or ""
                if "agent" not in itype and "assistant" not in itype:
                    continue
                for c in item.get("content") or []:
                    if isinstance(c, dict) and isinstance(c.get("text"), str):
                        texts.append(c["text"])
            return "".join(texts)[-8000:]

        try:
            th = await server.call("thread/start", {}, timeout=60.0)
            thread_id = ((th or {}).get("thread") or {}).get("id") or ""
            if not thread_id:
                return SubAgentResult(success=False, error="codex thread 创建失败")
            self._active[session_key] = thread_id

            idx0 = len(server.events)
            params: dict = {
                "threadId": thread_id,
                "input": [{"type": "text", "text": self._prompt(task, context)}],
                "cwd": root,
                "approvalPolicy": self._approval_policy,
                "sandbox": {"mode": self._sandbox_mode},
            }
            if self._model:
                params["model"] = self._model
            turn_resp = await server.call("turn/start", params, timeout=60.0)
            turn_id = ((turn_resp or {}).get("turn") or {}).get("id") or ""

            # 等待 turn 终态：turn/completed=唯一成功终态；error 事件累计(鉴权/断连)即失败
            deadline = asyncio.get_event_loop().time() + self._timeout
            final: Optional[dict] = None
            err_msg = ""
            err_count = 0
            while asyncio.get_event_loop().time() < deadline:
                await asyncio.sleep(1.5)
                for ev in server.events_since(idx0):
                    m = ev["method"]
                    p = ev.get("params") or {}
                    if m in _EVENT_DONE_HINTS:
                        final = ev
                        break
                    if m == "error":
                        err_count += 1
                        e = p.get("error") or {}
                        err_msg = str(e.get("message") or json.dumps(e, ensure_ascii=False))
                        if not p.get("willRetry", True) or err_count >= 3:
                            final = ev  # 不可重试/反复失败 → 终止
                            break
                if final:
                    break
            events = server.events_since(idx0)
            output = _collect_text(events)
            success, error = False, ""
            if final and final["method"] == "turn/completed":
                t = (final.get("params") or {}).get("turn") or {}
                success = (t.get("status") or "completed") == "completed"
                error = str(t.get("error") or "")[:500]
            elif final and final["method"] == "error":
                error = f"codex 执行失败: {err_msg}（检查 codex login / 网络）"
            else:
                error = err_msg or f"codex turn 未在 {self._timeout}s 内完成"
            changed = await _git_changed(root)
            return SubAgentResult(
                success=success, output=output, changed_files=changed, error=error,
                metadata={"codexThreadId": thread_id, "codexTurnId": turn_id})
        except Exception as e:  # noqa: BLE001
            logger.warning("[codex] execute %s failed: %s", task.id, e)
            await server.kill()
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
            server = self._get_server()
            await server.call("model/list", {}, timeout=40.0)
            return True
        except Exception:  # noqa: BLE001
            return False

    def env_check(self) -> dict:
        home = (os.path.expanduser(self._codex_home_cfg) if self._codex_home_cfg
                else os.path.expanduser("~/.codex"))
        return {"mode": "serve", "type": "codex-server", "bin": self._bin,
                "codexHome": self._codex_home_cfg or "~/.codex",
                "authFile": os.path.isfile(os.path.join(home, "auth.json")),
                "note": "本地自定义 provider 无需登录（requires_openai_auth=false）"}

    async def inject(self, session_key: str, message: str) -> dict:
        thread_id = self._active.get(session_key)
        if not thread_id:
            return {"ok": False, "error": "session not active"}
        try:
            server = self._get_server()
            await server.call("turn/steer", {
                "threadId": thread_id, "input": [{"type": "text", "text": message}]},
                timeout=30.0)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}

    async def abort(self, session_key: str) -> dict:
        thread_id = self._active.get(session_key)
        if not thread_id:
            return {"ok": False, "error": "session not active"}
        try:
            server = self._get_server()
            await server.call("turn/interrupt", {"threadId": thread_id}, timeout=15.0)
            return {"ok": True}
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "error": str(e)}


async def _git_changed(root: str) -> list[str]:
    import subprocess
    try:
        p = await asyncio.create_subprocess_exec(
            "git", "status", "--porcelain", "-uall", cwd=root,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
        out, _ = await p.communicate()
        files = []
        for line in out.decode().splitlines():
            path = line[3:]
            if " -> " in path:
                path = path.split(" -> ")[-1].strip()
            if path.strip():
                files.append(path.strip())
        return files
    except Exception:  # noqa: BLE001
        return []
