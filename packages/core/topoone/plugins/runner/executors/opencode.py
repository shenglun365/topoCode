"""OpenCodeSessionExecutor — opencode serve 会话化执行器。

对齐 opencode 1.18 真实 HTTP API（/session, /session/:id/message, /session/:id/abort,
/session/:id/diff, /session/:id/permissions/:permissionID, /global/health, SSE /event）。

与 tAgent ServeExecutor（一次性 /run，非 opencode 真实端点）的差异：
- 每任务一个 opencode session（会话可追问，clarify 复用）；
- 权限请求经 SSE /event 捕获并按策略自动应答（auto/ask→bus，S1 默认 auto）；
- 变更文件来自 /session/:id/diff（而非依赖 worktree 脏 diff）；
- opencode serve 按项目根目录懒拉起（每项目一个 serve 进程，端口从 base 起探活分配）。
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import subprocess
import time
from typing import Optional

import httpx

from topocode_agent.core.events import AgentEvent
from topocode_agent.subagent.protocol import SubAgentResult

logger = logging.getLogger(__name__)

HEALTH_PATH = "/global/health"


class ServeProc:
    """按项目根托管的 opencode serve 进程。"""

    def __init__(self, root: str, url: str, port: int):
        self.root = os.path.abspath(root)
        self.url = url
        self.port = port
        self.proc: Optional[subprocess.Popen] = None  # None = 外部已起的 serve
        self.created_at = time.time()


class OpenCodeServeManager:
    """项目根 → serve 实例注册表（进程内单例，端口探活分配）。"""

    def __init__(self, opencode_bin: str = "", base_port: int = 3478, auto_start: bool = True):
        self._bin = opencode_bin or shutil.which("opencode") or "opencode"
        self._base_port = base_port
        self._auto_start = auto_start
        self._by_root: dict[str, ServeProc] = {}

    def _log_path(self, port: int) -> str:
        d = os.path.join(os.path.expanduser("~"), ".topocode", "runner")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"opencode-serve-{port}.log")

    async def _healthy(self, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3.0) as c:
                r = await c.get(f"{url}{HEALTH_PATH}")
                return r.status_code == 200
        except Exception:  # noqa: BLE001
            return False

    async def _find_port(self) -> int:
        for off in range(0, 24):
            port = self._base_port + off
            if await self._healthy(f"http://127.0.0.1:{port}"):
                continue  # 已被占用（可能是别的项目的 serve）
            return port
        return self._base_port

    async def ensure(self, root: str) -> ServeProc:
        root = os.path.abspath(root or os.getcwd())
        sp = self._by_root.get(root)
        if sp and await self._healthy(sp.url):
            return sp
        if sp and sp.proc is not None and sp.proc.poll() is None:
            # 进程在但健康检查未过：给一次等待
            for _ in range(10):
                if await self._healthy(sp.url):
                    return sp
                await asyncio.sleep(1.0)
        # 拉起（或复用已健康的外部 serve）；候选端口被占/启动失败自动换下一个
        port = await self._find_port()
        url = f"http://127.0.0.1:{port}"
        if not await self._healthy(url) and self._auto_start:
            last_err = ""
            for off in range(0, 24):
                port = self._base_port + off
                url = f"http://127.0.0.1:{port}"
                if await self._healthy(url):
                    continue  # 已被占用（可能是别的项目的 serve）
                try:
                    return await self._spawn(root, port, url)
                except Exception as e:  # noqa: BLE001
                    last_err = f"port {port}: {e}"
            raise RuntimeError(f"opencode serve 启动失败 root={root}: {last_err}")
        if not await self._healthy(url):
            raise RuntimeError(f"opencode serve 不可达 {url} 且未启用自动拉起")
        # 外部 serve 可能属于别的项目根——复用会串工作区。注册表未命中(或旧条目
        # 进程已死)时一律不复用未知 serve, 走自动拉起换端口
        if (sp is None or (sp.proc is not None and sp.proc.poll() is not None)) \
                and self._auto_start:
            for off in range(0, 24):
                port2 = self._base_port + off
                url2 = f"http://127.0.0.1:{port2}"
                if await self._healthy(url2):
                    continue
                return await self._spawn(root, port2, url2)
            raise RuntimeError(f"opencode serve 无可用端口 root={root}")
        sp = sp or ServeProc(root, url, port)
        self._by_root[root] = sp
        return sp

    async def _spawn(self, root: str, port: int, url: str) -> ServeProc:
        log = open(self._log_path(port), "ab")  # noqa: SIM115
        proc = subprocess.Popen(
            [self._bin, "serve", "--port", str(port), "--hostname", "127.0.0.1"],
            cwd=root, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        sp = ServeProc(root, url, port)
        sp.proc = proc
        for _ in range(30):
            if await self._healthy(url):
                self._by_root[root] = sp
                logger.info("[opencode] serve started pid=%s port=%s root=%s",
                            proc.pid, port, root)
                return sp
            if proc.poll() is not None:
                break
            await asyncio.sleep(1.0)
        try:
            proc.kill()
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"opencode serve 启动失败 port={port} root={root}（见 {self._log_path(port)}）")

    def dispose_root(self, root: str) -> None:
        """释放该根的 serve 实例(probe worktree 用完即清，防实例堆积)。"""
        sp = self._by_root.pop(root, None)
        if sp is None:
            return
        proc = getattr(sp, "proc", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        logger.info("[opencode] serve disposed root=%s", root)


_MANAGER: Optional[OpenCodeServeManager] = None


def get_manager(**kwargs) -> OpenCodeServeManager:
    global _MANAGER
    if _MANAGER is None:
        _MANAGER = OpenCodeServeManager(**kwargs)
    return _MANAGER


class OpenCodeSessionExecutor:
    """opencode serve 会话化执行器（mode=serve）。"""

    mode = "serve"

    def __init__(self, id: str = "opencode", base_url: str = "", api_key: str = "",
                 timeout: float = 1800.0, prompt_builder: Optional[object] = None,
                 auto_start: bool = True, base_port: int = 3478,
                 permission: str = "auto", model: str = "", opencode_bin: str = ""):
        self.id = id
        self._base_url = base_url.rstrip("/") if base_url else ""
        self._api_key = api_key
        self._timeout = timeout
        self._prompt_builder = prompt_builder
        self._permission = permission  # auto: 自动应答权限请求
        self._model = model
        self._mgr = get_manager(opencode_bin=opencode_bin, base_port=base_port,
                                auto_start=auto_start)
        # 活跃会话注册表（供 inject/abort）：sessionKey → {url, session_id}
        self._sessions: dict[str, dict] = {}

    # ── 基础 ──

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        return h

    def _prompt(self, task, context: dict) -> str:
        if self._prompt_builder:
            return self._prompt_builder(task, context)  # type: ignore[misc]
        parts = [task.title]
        parts.extend(task.context or [])
        if task.files:
            parts.append("Files:\n" + "\n".join(task.files))
        return "\n\n".join(p for p in parts if p)

    def _project_root(self, context: dict) -> str:
        return os.path.abspath(context.get("root") or context.get("projectRoot")
                               or os.environ.get("RUNNER_PROJECT_ROOT", "") or os.getcwd())

    # ── 权限自动应答（SSE 监听） ──

    async def _permission_responder(self, client: httpx.AsyncClient, url: str,
                                    session_id: str, stop: asyncio.Event) -> None:
        """监听全局 SSE /event，对本 session 的 permission.asked 事件自动应答。"""
        try:
            async with client.stream("GET", f"{url}/event",
                                     headers={"Accept": "text/event-stream"},
                                     timeout=httpx.Timeout(10.0, read=None)) as resp:
                async for line in resp.aiter_lines():
                    if stop.is_set():
                        return
                    if not line.startswith("data:"):
                        continue
                    import json as _json
                    try:
                        ev = _json.loads(line[5:].strip())
                    except Exception:  # noqa: BLE001
                        continue
                    props = ev.get("properties") or {}
                    sid = props.get("sessionID") or props.get("sessionId") or ""
                    ptype = ev.get("type") or ""
                    if session_id and sid and sid != session_id:
                        continue
                    if "permission" not in ptype:
                        continue
                    pid = (props.get("permissionID") or props.get("id")
                           or props.get("permissionId") or "")
                    if not pid:
                        continue
                    body = {"response": {"outcome": "accept"}}
                    try:
                        r = await client.post(
                            f"{url}/session/{session_id}/permissions/{pid}", json=body)
                        if r.status_code >= 400:
                            # 兼容第二种应答形状
                            await client.post(
                                f"{url}/session/{session_id}/permissions/{pid}",
                                json={"response": "accept"})
                        logger.info("[opencode] permission auto-accepted %s (%s)",
                                    pid, ptype)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("[opencode] permission respond failed: %s", e)
        except Exception as e:  # noqa: BLE001
            logger.debug("[opencode] sse listener end: %s", e)

    # ── 执行 ──

    async def execute(self, task, context: dict) -> SubAgentResult:
        import json as _json
        root = self._project_root(context)
        session_key = f"{self.id}:{task.id}"
        try:
            sp = await self._mgr.ensure(root)
        except Exception as e:  # noqa: BLE001
            return SubAgentResult(success=False, error=f"opencode serve 不可用: {e}")
        url = sp.url
        prompt = self._prompt(task, context)

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            session_id = ""
            stop = asyncio.Event()
            sse_task: Optional[asyncio.Task] = None
            try:
                r = await client.post(f"{url}/session", json={"title": task.id})
                r.raise_for_status()
                session_id = (r.json() or {}).get("id") or ""
                if not session_id:
                    return SubAgentResult(success=False, error="opencode session 创建失败")
                self._sessions[session_key] = {"url": url, "session_id": session_id}

                if self._permission == "auto":
                    sse_task = asyncio.create_task(
                        self._permission_responder(client, url, session_id, stop))

                body: dict = {"parts": [{"type": "text", "text": prompt}]}
                if self._model:
                    # opencode API 的 model 是 {providerID, modelID} 对象；
                    # 配置里写 "provider/model" 字符串（provider 段可省略）
                    if "/" in self._model:
                        pid, mid = self._model.split("/", 1)
                        body["model"] = {"providerID": pid, "modelID": mid}
                    else:
                        body["model"] = {"modelID": self._model}
                r = await client.post(f"{url}/session/{session_id}/message", json=body)
                r.raise_for_status()
                data = r.json() or {}

                # 输出：回复 parts 中的文本
                output = ""
                try:
                    for part in (data.get("parts") or [])[::-1]:
                        if part.get("type") == "text" and part.get("text"):
                            output = part["text"]
                            break
                except Exception:  # noqa: BLE001
                    output = ""

                # 变更文件：会话 diff
                changed: list[str] = []
                try:
                    d = await client.get(f"{url}/session/{session_id}/diff")
                    if d.status_code == 200:
                        for f in (d.json() or []):
                            p = f.get("path") or f.get("file") or ""
                            if p:
                                changed.append(p)
                except Exception:  # noqa: BLE001
                    pass

                # 会话状态（error → 失败）
                success = True
                err = ""
                try:
                    st = await client.get(f"{url}/session/status")
                    if st.status_code == 200:
                        info = ((st.json() or {}).get(session_id)) or {}
                        if info.get("status") == "error":
                            success = False
                            err = str(info.get("message") or "session error")
                except Exception:  # noqa: BLE001
                    pass

                return SubAgentResult(
                    success=success, output=output, changed_files=changed,
                    error=err, metadata={"opencodeSessionId": session_id, "serveUrl": url})
            except Exception as e:  # noqa: BLE001
                logger.warning("[opencode] execute %s failed: %s", task.id, e)
                return SubAgentResult(success=False, error=str(e))
            finally:
                stop.set()
                if sse_task:
                    sse_task.cancel()
                self._sessions.pop(session_key, None)

    async def execute_stream(self, task, context: dict):
        yield AgentEvent.status("working", task.id)
        r = await self.execute(task, context)
        yield AgentEvent.status("testing", task.id)
        yield AgentEvent.done(success=r.success, task_id=task.id)

    async def health_check(self) -> bool:
        url = self._base_url or f"http://127.0.0.1:{self._mgr._base_port}"
        return await self._mgr._healthy(url)

    def env_check(self) -> dict:
        return {"mode": "serve", "type": "opencode-session",
                "auto_start": self._mgr._auto_start,
                "base_port": self._mgr._base_port}

    # ── 会话交互（bus inject / abort） ──

    async def inject(self, session_key: str, message: str) -> dict:
        """向（仍在进行的）会话追加消息——opencode 会话内消息串行处理。"""
        s = self._sessions.get(session_key)
        if not s:
            return {"ok": False, "error": "session not active"}
        async with httpx.AsyncClient(timeout=120.0, headers=self._headers()) as client:
            r = await client.post(
                f"{s['url']}/session/{s['session_id']}/message",
                json={"parts": [{"type": "text", "text": message}]})
            return {"ok": r.status_code < 400, "status": r.status_code}

    async def abort(self, session_key: str) -> dict:
        s = self._sessions.get(session_key)
        if not s:
            return {"ok": False, "error": "session not active"}
        async with httpx.AsyncClient(timeout=10.0, headers=self._headers()) as client:
            r = await client.post(f"{s['url']}/session/{s['session_id']}/abort")
            return {"ok": r.status_code < 400}
